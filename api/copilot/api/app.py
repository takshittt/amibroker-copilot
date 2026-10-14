"""The FastAPI application: every route in ARCHITECTURE.md section 8.

Every request must carry the shared BFF key, or it is refused before any
other code runs. Every route but sign-up, login and health also needs a
valid session token.
"""

import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal

import redis
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, Field

from copilot.api import security
from copilot.api.answers import (
    ANSWERED,
    finding_from_dict,
    fix_answer,
    review_answer,
    write_answer,
)
from copilot.api.limits import Limits
from copilot.api.store import Store
from copilot.api.streaming import Job, run_as_stream
from copilot.checker import Context
from copilot.config import ConfigError, Settings
from copilot.embeddings import Embedder
from copilot.kb import Catalog
from copilot.pipeline.fix_error import FixErrorRequest, run_fix_error
from copilot.pipeline.llm import LLM
from copilot.pipeline.orchestrator import Deps, WriteRequest, run_write
from copilot.pipeline.review import ReviewRequest, run_review
from copilot.pipeline.rewrite import ApplyRequest, run_apply_fixes

log = logging.getLogger("copilot.api")

KEY_HEADER = "X-Internal-Key"
CLIENT_IP_HEADER = "X-Client-IP"  # set by the BFF; trusted only with the right key
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL = 254
MAX_NAME = 100


@dataclass
class Services:
    """Everything the routes use. Tests build one with a scripted model."""

    settings: Settings
    pool: ConnectionPool
    redis: redis.Redis
    catalog: Catalog
    llm: LLM
    embedder: Embedder


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


# Request bodies. Unknown fields are refused.


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignupIn(_Body):
    email: str = Field(max_length=MAX_EMAIL)
    password: str = Field(max_length=security.MAX_PASSWORD * 4)
    name: str = Field(max_length=MAX_NAME)


class LoginIn(_Body):
    email: str = Field(max_length=MAX_EMAIL)
    password: str = Field(max_length=security.MAX_PASSWORD * 4)


class ConversationIn(_Body):
    mode: Literal["write", "review", "fix"]
    market_id: str = Field(max_length=40)
    timeframe: str = Field(max_length=20)


class MessageIn(_Body):
    text: str = ""
    code: str | None = None
    error_text: str | None = None


class FeedbackIn(_Body):
    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=2000)


def create_app(services: Services) -> FastAPI:
    settings = services.settings
    security.check_secrets(settings)
    if settings.daily_spend_cap_usd is not None:
        prices = (
            settings.strong_price_in,
            settings.strong_price_out,
            settings.cheap_price_in,
            settings.cheap_price_out,
        )
        if any(price is None for price in prices):
            raise ConfigError(
                "DAILY_SPEND_CAP_USD is set, so all four model prices must be set too: "
                "without them the cost of a run is unknown and cannot be held under the cap."
            )

    store = Store(services.pool)
    limits = Limits(services.redis, settings)
    app = FastAPI(title="AFL Copilot API", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def require_bff_key(request: Request, call_next):
        # First, on every route: without the shared key nothing else runs.
        if not security.key_matches(settings, request.headers.get(KEY_HEADER)):
            return _error(401, "unauthorized", "This API only answers the AFL Copilot website.")
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_body_bytes:
            return _error(413, "too_large", "That request is too large.")
        return await call_next(request)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError):
        return _error(error.status, error.code, error.message)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception):
        log.exception("unexpected error on %s %s", request.method, request.url.path)
        return _error(500, "server_error", "Something went wrong on our side. Please try again.")

    @app.exception_handler(RequestValidationError)
    async def bad_body(request: Request, error: RequestValidationError):
        fields = sorted({".".join(str(p) for p in e["loc"][1:]) for e in error.errors()})
        return _error(422, "invalid", f"Check these fields: {', '.join(fields) or 'body'}.")

    def client_ip(request: Request) -> str:
        # The middleware has already checked the key, so the BFF's header is trusted.
        given = request.headers.get(CLIENT_IP_HEADER, "").strip()
        return given or (request.client.host if request.client else "unknown")

    def current_user(request: Request) -> uuid.UUID:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        user_id = (
            security.user_from_token(settings, token.strip())
            if scheme.lower() == "bearer"
            else None
        )
        if user_id is None or not store.user_exists(user_id):
            raise ApiError(401, "unauthorized", "Please sign in again.")
        return user_id

    User = Annotated[uuid.UUID, Depends(current_user)]

    # Health and markets

    @app.get("/v1/health")
    def health():
        return {"status": "ok", "kb_version": services.catalog.kb_version}

    @app.get("/v1/markets")
    def markets(user_id: User):
        return [market.model_dump(mode="json") for market in services.catalog.markets.values()]

    # Auth

    @app.post("/v1/auth/signup", status_code=201)
    def signup(body: SignupIn, request: Request):
        email = body.email.strip().lower()
        name = " ".join(body.name.split())
        if not _EMAIL.match(email):
            raise ApiError(422, "invalid", "That email address does not look right.")
        if not name:
            raise ApiError(422, "invalid", "Please give your name.")
        problem = security.password_problem(body.password)
        if problem:
            raise ApiError(422, "invalid", problem)
        if not limits.attempt(
            f"signup:ip:{client_ip(request)}", settings.signups_per_ip_per_hour, 3600
        ):
            raise ApiError(429, "too_many", "Too many sign-ups from here. Try again later.")
        user_id = store.create_user(email, name, security.hash_password(body.password))
        if user_id is None:
            raise ApiError(409, "exists", "An account with that email already exists.")
        return {"token": security.issue_token(settings, user_id)}

    @app.post("/v1/auth/login")
    def login(body: LoginIn, request: Request):
        email = body.email.strip().lower()
        window = settings.login_window_seconds
        by_email = limits.attempt(f"login:email:{email}", settings.login_attempts, window)
        by_ip = limits.attempt(f"login:ip:{client_ip(request)}", settings.login_attempts, window)
        if not (by_email and by_ip):
            raise ApiError(429, "too_many", "Too many attempts. Wait a few minutes and try again.")
        user = store.user_by_email(email)
        # The same answer whether the email is unknown or the password wrong.
        if user is None or not security.verify_password(user["password_hash"], body.password):
            raise ApiError(401, "wrong_login", "The email or the password is wrong.")
        if security.needs_rehash(user["password_hash"]):
            store.set_password(user["id"], security.hash_password(body.password))
        limits.clear(f"login:email:{email}")
        return {"token": security.issue_token(settings, user["id"])}

    # Usage

    @app.get("/v1/me/usage")
    def usage(user_id: User):
        used = limits.usage(str(user_id))
        return {
            "used": used.used,
            "limit": used.limit,
            "remaining": used.remaining,
            "resets_at": used.resets_at.isoformat(),
        }

    # Conversations

    @app.post("/v1/conversations", status_code=201)
    def create_conversation(body: ConversationIn, user_id: User):
        if services.catalog.market(body.market_id) is None:
            raise ApiError(422, "invalid", f"Unknown market {body.market_id!r}.")
        try:
            Context(timeframe=body.timeframe)
        except ValueError as error:
            raise ApiError(422, "invalid", str(error)) from None
        return store.create_conversation(user_id, body.mode, body.market_id, body.timeframe)

    @app.get("/v1/conversations")
    def list_conversations(user_id: User):
        return store.conversations(user_id)

    @app.get("/v1/conversations/{conversation_id}")
    def get_conversation(conversation_id: uuid.UUID, user_id: User):
        conversation = store.conversation(user_id, conversation_id)
        if conversation is None:
            raise ApiError(404, "not_found", "No such conversation.")
        messages = []
        for message in store.messages(conversation_id):
            answer = dict(message["answer"] or {})
            answer.pop("reviewed_code", None)
            messages.append({**message, "answer": answer or None})
        return {**conversation, "messages": messages}

    # Running the pipeline

    def run_deps() -> tuple[Deps, Callable[[], None]]:
        conn = services.pool.getconn()
        made = Deps(conn, services.catalog, services.llm, services.embedder, settings)

        def release() -> None:
            conn.rollback()
            services.pool.putconn(conn)

        return made, release

    def reserve(user_id: uuid.UUID) -> None:
        """Takes a unit of quota, before anything is saved or run."""
        if limits.over_spend_cap():
            raise ApiError(
                503, "spend_cap", "We have reached today's limit. Please come back tomorrow."
            )
        if not limits.take(str(user_id)):
            raise ApiError(
                429, "quota", "You have used all your answers for today. They reset at midnight."
            )

    def start(user_id: uuid.UUID, prepare: Callable[[], Job]) -> StreamingResponse:
        """Takes a unit of quota, saves what the user sent (`prepare`), and
        streams the job. The job gives the unit back itself when it ends
        without an answer; a crash, here or in the job, gives it back too."""
        reserve(user_id)
        try:
            job = prepare()
        except Exception:
            limits.give_back(str(user_id))
            raise
        stream = run_as_stream(
            job, settings.keepalive_seconds, on_failure=lambda: limits.give_back(str(user_id))
        )
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def finish(user_id: uuid.UUID, status: str, cost: float | None) -> None:
        if cost:
            limits.add_spend(cost)
        if status not in ANSWERED:
            limits.give_back(str(user_id))

    def check_code(code: str | None) -> str:
        if not code or not code.strip():
            raise ApiError(422, "invalid", "Paste the AFL code.")
        if len(code.encode("utf-8")) > settings.max_code_bytes:
            raise ApiError(
                413, "too_large", f"Code over {settings.max_code_bytes} bytes is not accepted."
            )
        return code

    @app.post("/v1/conversations/{conversation_id}/messages")
    def send_message(conversation_id: uuid.UUID, body: MessageIn, user_id: User):
        conversation = store.conversation(user_id, conversation_id)
        if conversation is None:
            raise ApiError(404, "not_found", "No such conversation.")
        mode, market, timeframe = (
            conversation["mode"],
            conversation["market_id"],
            conversation["timeframe"],
        )
        history = store.messages(conversation_id)
        text = body.text.strip()

        if mode == "write":
            if not text:
                raise ApiError(422, "invalid", "Describe the strategy you want written.")
            if len(text) > settings.max_request_chars:
                raise ApiError(
                    413,
                    "too_large",
                    f"Requests over {settings.max_request_chars} characters are not accepted.",
                )
            request = _write_request(text, market, timeframe, history)

            def job(progress, should_stop):
                made, release = run_deps()
                try:
                    result = run_write(request, made, progress, should_stop)
                finally:
                    release()
                answer = write_answer(result)
                message_id = store.add_message(
                    conversation_id,
                    "assistant",
                    result.message,
                    result.code or None,
                    answer["problems"],
                    result.status,
                    answer,
                )
                store.add_run(message_id, result.status, result.run, answer["checks"])
                finish(user_id, result.status, result.run.cost_usd)
                event = {"clarify": "clarify", "error": "error"}.get(result.status, "result")
                return event, {"message_id": str(message_id), **answer}

            def prepare():
                store.add_message(conversation_id, "user", text)
                store.set_title_if_empty(conversation_id, text)
                return job

            return start(user_id, prepare)

        code = check_code(body.code)
        if mode == "review":

            def job(progress, should_stop):
                made, release = run_deps()
                try:
                    result = run_review(
                        ReviewRequest(code, market, timeframe), made, progress, should_stop
                    )
                finally:
                    release()
                answer = review_answer(result, code)
                message_id = store.add_message(
                    conversation_id,
                    "assistant",
                    result.message,
                    None,
                    answer["findings"],
                    result.status,
                    answer,
                )
                store.add_run(message_id, result.status, result.run, answer["checks"])
                finish(user_id, result.status, result.run.cost_usd)
                public = {k: v for k, v in answer.items() if k != "reviewed_code"}
                event = "error" if result.status == "error" else "result"
                return event, {"message_id": str(message_id), **public}

            def prepare():
                store.add_message(conversation_id, "user", text, code)
                store.set_title_if_empty(conversation_id, text or "Review")
                return job

            return start(user_id, prepare)

        error_text = (body.error_text or "").strip()
        if not error_text:
            raise ApiError(422, "invalid", "Paste the error message AmiBroker showed.")
        if len(error_text) > settings.max_error_chars:
            raise ApiError(
                413,
                "too_large",
                f"Error text over {settings.max_error_chars} characters is not accepted.",
            )

        def job(progress, should_stop):
            made, release = run_deps()
            try:
                result = run_fix_error(
                    FixErrorRequest(code, error_text, market, timeframe),
                    made,
                    progress,
                    should_stop,
                )
            finally:
                release()
            answer = fix_answer(result)
            message_id = store.add_message(
                conversation_id,
                "assistant",
                result.message,
                result.code or None,
                answer["problems"],
                result.status,
                answer,
            )
            store.add_run(message_id, result.status, result.run, answer["checks"])
            finish(user_id, result.status, result.run.cost_usd)
            event = "error" if result.status == "error" else "result"
            return event, {"message_id": str(message_id), **answer}

        def prepare():
            store.add_message(
                conversation_id, "user", text, code, answer={"error_text": error_text}
            )
            store.set_title_if_empty(conversation_id, text or error_text)
            return job

        return start(user_id, prepare)

    @app.post("/v1/messages/{message_id}/apply-fixes")
    def apply_fixes(message_id: uuid.UUID, user_id: User):
        message = store.message_for_user(user_id, message_id)
        if message is None or message["role"] != "assistant" or message["status"] != "reviewed":
            raise ApiError(404, "not_found", "No review with that id.")
        answer = message["answer"] or {}
        findings = tuple(finding_from_dict(f) for f in answer.get("findings", []))
        if not findings:
            raise ApiError(422, "nothing_to_fix", "That review has no findings to fix.")
        code = answer["reviewed_code"]
        market, timeframe = message["market_id"], message["timeframe"]
        conversation_id = message["conversation_id"]

        def job(progress, should_stop):
            made, release = run_deps()
            try:
                result = run_apply_fixes(
                    ApplyRequest(code, market, timeframe, findings), made, progress, should_stop
                )
            finally:
                release()
            answer = fix_answer(result)
            new_id = store.add_message(
                conversation_id,
                "assistant",
                result.message,
                result.code or None,
                answer["problems"],
                result.status,
                answer,
            )
            store.add_run(new_id, result.status, result.run, answer["checks"])
            finish(user_id, result.status, result.run.cost_usd)
            event = "error" if result.status == "error" else "result"
            return event, {"message_id": str(new_id), **answer}

        return start(user_id, lambda: job)

    # Feedback

    @app.post("/v1/messages/{message_id}/feedback", status_code=204)
    def feedback(message_id: uuid.UUID, body: FeedbackIn, user_id: User):
        message = store.message_for_user(user_id, message_id)
        if message is None or message["role"] != "assistant":
            raise ApiError(404, "not_found", "No answer with that id.")
        comment = (body.comment or "").strip() or None
        store.save_feedback(message_id, user_id, body.rating, comment)
        return None

    return app


def _write_request(text: str, market: str, timeframe: str, history: list[dict]) -> WriteRequest:
    """Uses the conversation so far.

    After a clarifying question, the answer is added to the request that
    prompted it. After code was written, the new message is a change to
    that code.
    """
    last_answer = next((m for m in reversed(history) if m["role"] == "assistant"), None)
    if last_answer is not None and last_answer["status"] == "clarify":
        asked = next(
            (
                m
                for m in reversed(history)
                if m["role"] == "user" and m["created_at"] <= last_answer["created_at"]
            ),
            None,
        )
        if asked is not None:
            text = f"{asked['content']}\n\nMore details: {text}"
    previous_code = next(
        (m["code"] for m in reversed(history) if m["role"] == "assistant" and m["code"]), ""
    )
    return WriteRequest(text, market, timeframe, previous_code)
