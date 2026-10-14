"""Reading and writing users, conversations, messages, runs and feedback."""

import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from copilot.pipeline.tracking import RunRecord

TITLE_CHARS = 80


class Store:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    # Users

    def create_user(self, email: str, name: str, password_hash: str) -> uuid.UUID | None:
        """None when the email is already registered."""
        with self.pool.connection() as conn:
            try:
                row = conn.execute(
                    "insert into users (email, name, password_hash) values (%s, %s, %s) "
                    "returning id",
                    (email, name, password_hash),
                ).fetchone()
            except psycopg.errors.UniqueViolation:
                return None
            return row["id"]

    def user_by_email(self, email: str) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute(
                "select id, email, name, password_hash from users where lower(email) = lower(%s)",
                (email,),
            ).fetchone()

    def user_exists(self, user_id: uuid.UUID) -> bool:
        with self.pool.connection() as conn:
            return bool(conn.execute("select 1 from users where id = %s", (user_id,)).fetchone())

    def set_password(self, user_id: uuid.UUID, password_hash: str) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "update users set password_hash = %s where id = %s", (password_hash, user_id)
            )

    # Conversations

    def create_conversation(
        self, user_id: uuid.UUID, mode: str, market_id: str, timeframe: str
    ) -> dict:
        with self.pool.connection() as conn:
            return conn.execute(
                "insert into conversations (user_id, mode, market_id, timeframe) "
                "values (%s, %s, %s, %s) "
                "returning id, mode, market_id, timeframe, title, created_at",
                (user_id, mode, market_id, timeframe),
            ).fetchone()

    def conversations(self, user_id: uuid.UUID) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute(
                "select id, mode, market_id, timeframe, title, created_at from conversations "
                "where user_id = %s order by created_at desc",
                (user_id,),
            ).fetchall()

    def conversation(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> dict | None:
        """Only the user's own conversation; another user's is the same as none."""
        with self.pool.connection() as conn:
            return conn.execute(
                "select id, mode, market_id, timeframe, title, created_at from conversations "
                "where id = %s and user_id = %s",
                (conversation_id, user_id),
            ).fetchone()

    def set_title_if_empty(self, conversation_id: uuid.UUID, text: str) -> None:
        title = " ".join(text.split())[:TITLE_CHARS]
        with self.pool.connection() as conn:
            conn.execute(
                "update conversations set title = %s where id = %s and title = ''",
                (title, conversation_id),
            )

    # Messages

    def messages(self, conversation_id: uuid.UUID) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute(
                "select id, role, content, code, findings, status, answer, created_at "
                "from messages where conversation_id = %s order by created_at, id",
                (conversation_id,),
            ).fetchall()

    def add_message(
        self,
        conversation_id: uuid.UUID,
        role: str,
        content: str = "",
        code: str | None = None,
        findings: Any = None,
        status: str | None = None,
        answer: Any = None,
    ) -> uuid.UUID:
        with self.pool.connection() as conn:
            row = conn.execute(
                "insert into messages "
                "(conversation_id, role, content, code, findings, status, answer, created_at) "
                "values (%s, %s, %s, %s, %s, %s, %s, clock_timestamp()) returning id",
                (
                    conversation_id,
                    role,
                    content,
                    code,
                    None if findings is None else Jsonb(findings),
                    status,
                    None if answer is None else Jsonb(answer),
                ),
            ).fetchone()
            return row["id"]

    def message_for_user(self, user_id: uuid.UUID, message_id: uuid.UUID) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute(
                "select m.id, m.conversation_id, m.role, m.content, m.code, m.findings, "
                "m.status, m.answer, c.mode, c.market_id, c.timeframe "
                "from messages m join conversations c on c.id = m.conversation_id "
                "where m.id = %s and c.user_id = %s",
                (message_id, user_id),
            ).fetchone()

    # Runs and feedback

    def add_run(self, message_id: uuid.UUID, status: str, run: RunRecord, checks: Any) -> uuid.UUID:
        with self.pool.connection() as conn:
            row = conn.execute(
                "insert into runs (message_id, status, attempts, checks, tokens_in, tokens_out, "
                "cost_usd, latency_ms, model_versions, kb_version) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
                (
                    message_id,
                    status,
                    run.attempts,
                    Jsonb(checks),
                    sum(run.tokens_in.values()),
                    sum(run.tokens_out.values()),
                    run.cost_usd or 0,
                    run.latency_ms,
                    Jsonb(run.model_versions),
                    run.kb_version,
                ),
            ).fetchone()
            return row["id"]

    def save_feedback(
        self, message_id: uuid.UUID, user_id: uuid.UUID, rating: int, comment: str | None
    ) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "insert into feedback (message_id, user_id, rating, comment) "
                "values (%s, %s, %s, %s) on conflict (message_id, user_id) "
                "do update set rating = excluded.rating, comment = excluded.comment, "
                "created_at = now()",
                (message_id, user_id, rating, comment),
            )
