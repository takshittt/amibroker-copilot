from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from copilot.config import ConfigError, Settings
from copilot.pipeline.llm import LLMError, OpenAILLM, ScriptedLLM, Usage, UsageMeter, ask

SCHEMA = {"type": "object"}


class Answer(BaseModel):
    value: int


def ask_for_answer(llm, meter=None):
    return ask(
        llm,
        meter or UsageMeter(),
        model="cheap",
        system="system text",
        user="user text",
        schema_name="answer",
        schema=SCHEMA,
        parse=Answer.model_validate,
        max_output_tokens=100,
    )


# The scripted model


def test_scripted_replies_come_in_order_and_calls_are_recorded():
    llm = ScriptedLLM([{"value": 1}, {"value": 2}])
    assert ask_for_answer(llm).value == 1
    assert ask_for_answer(llm).value == 2
    assert [call.schema_name for call in llm.calls] == ["answer", "answer"]
    assert llm.calls[0].system == "system text"
    assert llm.calls[0].model == "cheap"


def test_scripted_function_sees_the_call():
    llm = ScriptedLLM(lambda call: {"value": len(call.user)})
    assert ask_for_answer(llm).value == len("user text")


def test_scripted_model_with_nothing_left_fails_loudly():
    with pytest.raises(AssertionError, match="no reply left"):
        ask_for_answer(ScriptedLLM([]))


# ask: checking and repairing a reply


def test_usage_is_added_up_by_model():
    meter = UsageMeter()
    llm = ScriptedLLM([{"value": 1}, {"value": 2}], usage=Usage(tokens_in=10, tokens_out=4))
    ask_for_answer(llm, meter)
    ask_for_answer(llm, meter)
    assert meter.calls == {"cheap": 2}
    assert meter.tokens_in == {"cheap": 20}
    assert meter.tokens_out == {"cheap": 8}


def test_reply_that_fails_the_check_is_repaired_once():
    meter = UsageMeter()
    llm = ScriptedLLM([{"value": "not a number"}, {"value": 7}])
    assert ask_for_answer(llm, meter).value == 7
    assert len(llm.calls) == 2
    assert "could not be used" in llm.calls[1].user
    assert "user text" in llm.calls[1].user
    assert "could not be used" not in llm.calls[0].user
    # Both calls were paid for.
    assert meter.calls == {"cheap": 2}


def test_reply_that_is_not_json_is_repaired_once():
    llm = ScriptedLLM([LLMError("invalid_output", "the reply was not JSON"), {"value": 3}])
    assert ask_for_answer(llm).value == 3
    assert "not JSON" in llm.calls[1].user


def test_two_unusable_replies_give_invalid_output():
    llm = ScriptedLLM([{"value": "x"}, {"wrong": 1}])
    with pytest.raises(LLMError) as raised:
        ask_for_answer(llm)
    assert raised.value.kind == "invalid_output"
    assert len(llm.calls) == 2


@pytest.mark.parametrize("kind", ["unavailable", "rate_limited", "rejected"])
def test_other_failures_are_not_repaired(kind):
    llm = ScriptedLLM([LLMError(kind, "no luck")])
    with pytest.raises(LLMError) as raised:
        ask_for_answer(llm)
    assert raised.value.kind == kind
    assert len(llm.calls) == 1


# The OpenAI client


class StatusError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


class APITimeoutError(Exception):
    """Named like the SDK's timeout error, which carries no status code."""


def response(content, refusal=None, tokens=(11, 5)):
    message = SimpleNamespace(content=content, refusal=refusal)
    usage = SimpleNamespace(prompt_tokens=tokens[0], completion_tokens=tokens[1])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


class StubClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def call(client, sleeps=None):
    llm = OpenAILLM(client, sleep=(sleeps if sleeps is not None else []).append)
    return llm.complete_json(
        model="strong-model",
        system="rules",
        user="request",
        schema_name="generation",
        schema=SCHEMA,
        max_output_tokens=900,
    )


def test_request_asks_for_strict_json_with_the_schema():
    client = StubClient([response('{"value": 4}')])
    reply = call(client)
    assert reply.data == {"value": 4}
    assert reply.usage == Usage(tokens_in=11, tokens_out=5)
    assert reply.model == "strong-model"
    (request,) = client.requests
    assert request["model"] == "strong-model"
    assert request["messages"] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "request"},
    ]
    assert request["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "generation", "schema": SCHEMA, "strict": True},
    }
    assert request["max_completion_tokens"] == 900


@pytest.mark.parametrize("failure", [StatusError(500), StatusError(503), APITimeoutError("slow")])
def test_server_trouble_is_retried_twice_with_a_growing_wait(failure):
    sleeps = []
    client = StubClient([failure, failure, response('{"value": 1}')])
    assert call(client, sleeps).data == {"value": 1}
    assert len(client.requests) == 3
    assert sleeps == [1.0, 2.0]


def test_server_trouble_three_times_is_unavailable():
    client = StubClient([StatusError(502)] * 3)
    with pytest.raises(LLMError) as raised:
        call(client)
    assert raised.value.kind == "unavailable"
    assert len(client.requests) == 3


def test_rate_limit_backs_off_then_reports_rate_limited():
    sleeps = []
    client = StubClient([StatusError(429)] * 3)
    with pytest.raises(LLMError) as raised:
        call(client, sleeps)
    assert raised.value.kind == "rate_limited"
    assert sleeps == [1.0, 2.0]


def test_rate_limit_that_clears_gives_the_reply():
    client = StubClient([StatusError(429), response('{"value": 2}')])
    assert call(client).data == {"value": 2}


@pytest.mark.parametrize("status", [400, 401, 404])
def test_refused_request_is_not_retried(status):
    client = StubClient([StatusError(status)])
    with pytest.raises(LLMError) as raised:
        call(client)
    assert raised.value.kind == "rejected"
    assert len(client.requests) == 1


@pytest.mark.parametrize("content", ["not json", "", "[1, 2]", '"text"'])
def test_reply_that_is_not_a_json_object(content):
    client = StubClient([response(content)])
    with pytest.raises(LLMError) as raised:
        call(client)
    assert raised.value.kind == "invalid_output"
    assert len(client.requests) == 1


def test_model_declining_is_invalid_output():
    client = StubClient([response(None, refusal="I cannot help with that")])
    with pytest.raises(LLMError) as raised:
        call(client)
    assert raised.value.kind == "invalid_output"
    assert "declined" in str(raised.value)


def test_error_that_is_not_from_the_api_is_not_swallowed():
    client = StubClient([KeyError("a bug in our own code")])
    with pytest.raises(KeyError):
        call(client)


def test_client_needs_a_key():
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        OpenAILLM.from_settings(Settings())
