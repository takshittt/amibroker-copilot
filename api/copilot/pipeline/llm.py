"""Talking to the language model.

Every step asks for JSON that follows a schema and then checks the reply
itself. Steps take an LLM, so tests run with the scripted one and never
call OpenAI.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from copilot.config import ConfigError, Settings

_RETRIES = 2  # after a timeout, a server error or a rate limit


@dataclass(frozen=True)
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass(frozen=True)
class Reply:
    data: dict
    usage: Usage
    model: str


class LLMError(Exception):
    """The model could not give a usable answer.

    `kind` is one of:
    - unavailable: timeouts or server errors, after the retries
    - rate_limited: still rate limited after backing off
    - rejected: the request itself was refused (bad model id, bad key)
    - invalid_output: the reply was not usable JSON, even after one repair
    """

    def __init__(self, kind: str, message: str):
        self.kind = kind
        super().__init__(message)


class LLM(Protocol):
    def complete_json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema_name: str,
        schema: dict,
        max_output_tokens: int,
    ) -> Reply:
        """Returns the model's reply parsed as a JSON object, or raises LLMError."""
        ...


@dataclass
class UsageMeter:
    """Adds up the calls and tokens of one run, model by model."""

    calls: dict[str, int] = field(default_factory=dict)
    tokens_in: dict[str, int] = field(default_factory=dict)
    tokens_out: dict[str, int] = field(default_factory=dict)

    def add(self, model: str, usage: Usage) -> None:
        self.calls[model] = self.calls.get(model, 0) + 1
        self.tokens_in[model] = self.tokens_in.get(model, 0) + usage.tokens_in
        self.tokens_out[model] = self.tokens_out.get(model, 0) + usage.tokens_out


def ask[T](
    llm: LLM,
    meter: UsageMeter,
    *,
    model: str,
    system: str,
    user: str,
    schema_name: str,
    schema: dict,
    parse: Callable[[dict], T],
    max_output_tokens: int,
) -> T:
    """Asks the model and turns its reply into a checked value with `parse`.

    If the reply is not JSON or `parse` rejects it, the model is asked once
    more and told what was wrong. A second failure raises LLMError.
    """
    problem = ""
    for attempt in range(2):
        prompt = user
        if attempt:
            prompt += (
                "\n\nYour previous reply could not be used: "
                f"{problem}\nReply again with JSON that follows the schema exactly."
            )
        try:
            reply = llm.complete_json(
                model=model,
                system=system,
                user=prompt,
                schema_name=schema_name,
                schema=schema,
                max_output_tokens=max_output_tokens,
            )
        except LLMError as error:
            if error.kind != "invalid_output":
                raise
            problem = str(error)
            continue
        meter.add(reply.model, reply.usage)
        try:
            return parse(reply.data)
        except (ValidationError, ValueError, KeyError, TypeError) as error:
            problem = " ".join(str(error).split())[:500]
    raise LLMError("invalid_output", f"the model's reply was not usable: {problem}")


@dataclass(frozen=True)
class ScriptedCall:
    model: str
    system: str
    user: str
    schema_name: str


class ScriptedLLM:
    """Gives prepared replies. For tests, and for running the pipeline offline.

    `script` is either a list of replies used in order, or a function that
    takes the call and returns the reply. A reply is a dict, or an
    exception to raise.
    """

    def __init__(self, script: list | Callable[[ScriptedCall], Any], usage: Usage | None = None):
        self._script = script
        self._usage = usage or Usage(tokens_in=100, tokens_out=50)
        self.calls: list[ScriptedCall] = []

    def complete_json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema_name: str,
        schema: dict,
        max_output_tokens: int,
    ) -> Reply:
        call = ScriptedCall(model, system, user, schema_name)
        self.calls.append(call)
        if callable(self._script):
            reply = self._script(call)
        elif self._script:
            reply = self._script.pop(0)
        else:
            raise AssertionError(f"the script has no reply left for a {schema_name} call")
        if isinstance(reply, Exception):
            raise reply
        return Reply(data=reply, usage=self._usage, model=model)


def _failure_kind(error: Exception) -> str | None:
    """Sorts an exception from the OpenAI SDK. None means it is not one we handle."""
    status = getattr(error, "status_code", None)
    if status == 429:
        return "rate_limited"
    if isinstance(status, int) and status >= 500:
        return "unavailable"
    if isinstance(status, int):
        return "rejected"
    if type(error).__name__ in ("APITimeoutError", "APIConnectionError"):
        return "unavailable"
    if isinstance(error, TimeoutError | ConnectionError):
        return "unavailable"
    return None


class OpenAILLM:
    """Replies from the OpenAI API. `client` is an `openai.OpenAI` object."""

    def __init__(self, client: Any, sleep: Callable[[float], None] = time.sleep):
        self.client = client
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings) -> "OpenAILLM":
        if not settings.openai_api_key:
            raise ConfigError("OPENAI_API_KEY is not set")
        from openai import OpenAI  # imported here so nothing else loads the SDK

        client = OpenAI(
            api_key=settings.openai_api_key, timeout=settings.llm_timeout_seconds, max_retries=0
        )
        return cls(client)

    def complete_json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema_name: str,
        schema: dict,
        max_output_tokens: int,
    ) -> Reply:
        response = self._create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": schema, "strict": True},
            },
            max_completion_tokens=max_output_tokens,
        )
        message = response.choices[0].message
        if getattr(message, "refusal", None):
            raise LLMError("invalid_output", f"the model declined: {message.refusal}")
        try:
            data = json.loads(message.content or "")
        except json.JSONDecodeError as error:
            raise LLMError("invalid_output", f"the reply was not JSON ({error})") from None
        if not isinstance(data, dict):
            raise LLMError("invalid_output", "the reply was JSON but not an object")
        usage = Usage(
            tokens_in=getattr(response.usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(response.usage, "completion_tokens", 0) or 0,
        )
        return Reply(data=data, usage=usage, model=model)

    def _create(self, **request: Any) -> Any:
        """One request, retried with a growing wait after a failure that may pass."""
        for attempt in range(_RETRIES + 1):
            try:
                return self.client.chat.completions.create(**request)
            except Exception as error:  # noqa: BLE001 (sorted just below; unknown ones re-raised)
                kind = _failure_kind(error)
                if kind is None:
                    raise
                if kind == "rejected" or attempt == _RETRIES:
                    raise LLMError(kind, " ".join(str(error).split())[:300]) from error
                self._sleep(2.0**attempt)
        raise AssertionError("unreachable")
