"""Conversations and the three modes through the API, with a scripted model."""

import pytest

from copilot.pipeline.llm import LLMError

from .conftest import new_conversation, sign_up, stream

BRIEF = {
    "kind": "strategy",
    "goal": "Moving-average crossover.",
    "direction": "long",
    "entry": "Buy when the 20-day average crosses above the 50-day one.",
    "exit": "Sell when it crosses back below.",
    "stops": [],
    "sizing": "",
    "time_rules": [],
    "other_requirements": [],
}
CODE = (
    'FastLen = Param("Fast", 20, 5, 100, 1);\n'
    "SetTradeDelays(1, 1, 1, 1);\n"
    "Buy = Cross(MA(Close, FastLen), MA(Close, 50));\n"
    "Sell = Cross(MA(Close, 50), MA(Close, FastLen));\n"
)


def generation(code=CODE):
    return {
        "code": code,
        "explanation_blocks": [{"start_line": 1, "end_line": 4, "text": "All of it."}],
        "requirements_covered": [
            {"id": "R1", "start_line": 3, "end_line": 3},
            {"id": "R2", "start_line": 3, "end_line": 3},
            {"id": "R3", "start_line": 4, "end_line": 4},
        ],
        "notes": [],
    }


def write_model(generations=None, brief=BRIEF):
    queue = list(generations or [generation()])
    briefs = brief if isinstance(brief, list) else None

    def answer(call):
        if call.schema_name == "brief":
            return briefs.pop(0) if briefs is not None else brief
        if call.schema_name == "rerank":
            return {"scores": []}
        return queue.pop(0)

    return answer


def usage(client, auth):
    return client.get("/v1/me/usage", headers=auth).json()["used"]


@pytest.fixture
def writing(make_client):
    def _writing(script=None, **changes):
        client, model = make_client(script or write_model(), **changes)
        auth = sign_up(client)
        return client, model, auth, new_conversation(client, auth)

    return _writing


# Conversations


def test_create_list_and_open_a_conversation(client):
    auth = sign_up(client)
    created = client.post(
        "/v1/conversations",
        json={"mode": "review", "market_id": "mcx", "timeframe": "15min"},
        headers=auth,
    ).json()
    assert created["mode"] == "review"
    assert created["title"] == ""
    listed = client.get("/v1/conversations", headers=auth).json()
    assert [c["id"] for c in listed] == [created["id"]]
    opened = client.get(f"/v1/conversations/{created['id']}", headers=auth).json()
    assert opened["messages"] == []


@pytest.mark.parametrize(
    ("body", "words"),
    [
        ({"mode": "chat", "market_id": "nse_eq", "timeframe": "daily"}, "mode"),
        ({"mode": "write", "market_id": "moon", "timeframe": "daily"}, "Unknown market"),
        ({"mode": "write", "market_id": "nse_eq", "timeframe": "5m"}, "timeframe"),
    ],
)
def test_bad_conversation(client, body, words):
    auth = sign_up(client)
    response = client.post("/v1/conversations", json=body, headers=auth)
    assert response.status_code == 422
    assert words in response.json()["error"]["message"]


def test_markets_come_from_the_market_table(client):
    auth = sign_up(client)
    markets = {m["id"]: m for m in client.get("/v1/markets", headers=auth).json()}
    assert set(markets) == {"nse_eq", "nse_fo", "bse_eq", "mcx", "nyse", "nasdaq", "lse", "crypto"}
    assert len(markets["mcx"]["dst_rules"]) == 2


# Write


def test_write_streams_progress_then_the_checked_answer(writing):
    client, _, auth, conversation = writing()
    code, events = stream(
        client,
        f"/v1/conversations/{conversation}/messages",
        auth,
        {"text": "Buy when the 20 MA crosses the 50 MA."},
    )
    assert code == 200
    names = [name for name, _ in events]
    assert names[0] == "status"
    assert names[-1] == "result"
    stages = [data["stage"] for name, data in events if name == "status"]
    assert stages[:3] == ["understanding", "searching", "writing"]
    result = events[-1][1]
    assert result["status"] == "checked"
    assert result["code"] == CODE
    assert {c["outcome"] for c in result["checks"]} == {"passed"}
    assert result["message_id"]
    assert usage(client, auth) == 1


def test_answer_and_run_are_saved_and_shown_again(writing, pool):
    client, _, auth, conversation = writing()
    stream(client, f"/v1/conversations/{conversation}/messages", auth, {"text": "MA cross please"})
    opened = client.get(f"/v1/conversations/{conversation}", headers=auth).json()
    assert opened["title"] == "MA cross please"
    user, assistant = opened["messages"]
    assert (user["role"], user["content"]) == ("user", "MA cross please")
    assert (assistant["role"], assistant["status"], assistant["code"]) == (
        "assistant",
        "checked",
        CODE,
    )
    assert assistant["answer"]["checks"]
    with pool.connection() as conn:
        run = conn.execute("select * from runs").fetchone()
    assert run["status"] == "checked"
    assert run["attempts"] == 1
    assert run["tokens_in"] > 0
    assert float(run["cost_usd"]) > 0
    assert run["model_versions"]["strong"] == "strong-model"
    assert run["kb_version"] >= 4


def test_failed_upstream_call_uses_no_quota(writing):
    # The stage 7 proof: an answer that never came costs the user nothing.
    client, _, auth, conversation = writing(lambda call: LLMError("unavailable", "OpenAI is down"))
    code, events = stream(client, f"/v1/conversations/{conversation}/messages", auth, {"text": "x"})
    assert code == 200
    assert events[-1][0] == "error"
    assert "could not be reached" in events[-1][1]["message"]
    assert "OpenAI is down" not in str(events)
    assert usage(client, auth) == 0


def test_a_crash_on_our_side_uses_no_quota_either(writing):
    def broken(call):
        raise RuntimeError("a bug")

    client, _, auth, conversation = writing(broken)
    code, events = stream(client, f"/v1/conversations/{conversation}/messages", auth, {"text": "x"})
    assert events[-1] == (
        "error",
        {"message": "Something went wrong on our side. Please try again."},
    )
    assert usage(client, auth) == 0


def test_answer_that_is_not_fully_checked_does_use_quota(writing):
    bad = generation(CODE + "x = TrailStop(1);\n")
    client, _, auth, conversation = writing(write_model([bad, bad, bad]))
    _, events = stream(client, f"/v1/conversations/{conversation}/messages", auth, {"text": "x"})
    assert events[-1][1]["status"] == "not_fully_checked"
    assert events[-1][1]["problems"][0]["rule"] == "unknown_function"
    assert usage(client, auth) == 1


def test_clarifying_question_is_free_and_the_reply_completes_the_request(writing):
    briefs = [{**BRIEF, "direction": "unknown"}, BRIEF]
    client, model, auth, conversation = writing(write_model(brief=briefs))
    path = f"/v1/conversations/{conversation}/messages"
    _, events = stream(client, path, auth, {"text": "MA crossover on Nifty"})
    assert events[-1][0] == "clarify"
    assert events[-1][1]["questions"] == ["Should it trade long only, short only, or both?"]
    assert usage(client, auth) == 0

    _, events = stream(client, path, auth, {"text": "Long only."})
    assert events[-1][1]["status"] == "checked"
    second_brief = [c.user for c in model.calls if c.schema_name == "brief"][1]
    assert "MA crossover on Nifty\n\nMore details: Long only." in second_brief
    assert usage(client, auth) == 1


def test_follow_up_changes_the_last_code(writing):
    client, model, auth, conversation = writing(write_model([generation(), generation()]))
    path = f"/v1/conversations/{conversation}/messages"
    stream(client, path, auth, {"text": "MA crossover"})
    stream(client, path, auth, {"text": "Make the fast average 10 days."})
    last_prompt = [c.user for c in model.calls if c.schema_name == "generation"][-1]
    assert "keep everything else as it is" in last_prompt
    assert "Buy = Cross(MA(Close, FastLen), MA(Close, 50));" in last_prompt


def test_daily_quota_is_enforced(writing):
    client, _, auth, conversation = writing(write_model([generation()] * 3), daily_quota=2)
    path = f"/v1/conversations/{conversation}/messages"
    assert stream(client, path, auth, {"text": "one"})[0] == 200
    assert stream(client, path, auth, {"text": "two"})[0] == 200
    code, body = stream(client, path, auth, {"text": "three"})
    assert code == 429
    assert body["error"]["code"] == "quota"
    assert usage(client, auth) == 2
    assert client.get("/v1/me/usage", headers=auth).json()["remaining"] == 0


def test_spend_cap_stops_new_runs(writing, redis_client):
    client, _, auth, conversation = writing(daily_spend_cap_usd=0.0001)
    path = f"/v1/conversations/{conversation}/messages"
    assert stream(client, path, auth, {"text": "one"})[0] == 200
    code, body = stream(client, path, auth, {"text": "two"})
    assert code == 503
    assert body["error"]["code"] == "spend_cap"
    assert "come back tomorrow" in body["error"]["message"]
    assert usage(client, auth) == 1


@pytest.mark.parametrize(
    ("body", "status", "words"),
    [
        ({"text": "   "}, 422, "Describe"),
        ({"text": "x" * 4001}, 413, "4000"),
        ({"text": "x", "colour": "red"}, 422, "colour"),
    ],
)
def test_bad_write_message_is_refused_before_anything_runs(writing, body, status, words):
    client, model, auth, conversation = writing()
    code, answer = stream(client, f"/v1/conversations/{conversation}/messages", auth, body)
    assert code == status
    assert words in answer["error"]["message"]
    assert model.calls == []
    assert usage(client, auth) == 0


# Review and apply all fixes

PASTED = (
    "SetTradeDelays(1, 1, 1, 1);\nFast = EMA(Close, 9);\nSlow = EMA(Close, 21);\n"
    "Buy = Cross(Fast, Slow) AND Ref(Close, 1) > Close;\nSell = Cross(Fast, Slow);\n"
)
FIXED = (
    "SetTradeDelays(1, 1, 1, 1);\nFast = EMA(Close, 9);\nSlow = EMA(Close, 21);\n"
    "Buy = Cross(Fast, Slow);\nSell = Cross(Slow, Fast);\n"
)
AI_REVIEW = {
    "findings": [
        {
            "severity": "critical",
            "line": 5,
            "problem": "Sell repeats the Buy cross.",
            "fix": "Swap.",
        }
    ],
    "summary": "One more problem.",
}


def test_review_then_apply_all_fixes(make_client):
    replies = {"review": [AI_REVIEW], "rewrite": [{"code": FIXED, "changes": [], "notes": []}]}
    client, model = make_client(lambda call: replies[call.schema_name].pop(0))
    auth = sign_up(client)
    conversation = new_conversation(client, auth, mode="review")

    _, events = stream(client, f"/v1/conversations/{conversation}/messages", auth, {"code": PASTED})
    review = events[-1][1]
    assert review["status"] == "reviewed"
    assert [(f["label"], f["line"]) for f in review["findings"]] == [
        ("Verified", 4),
        ("AI-suggested", 5),
    ]
    assert "reviewed_code" not in review
    assert usage(client, auth) == 1

    _, events = stream(client, f"/v1/messages/{review['message_id']}/apply-fixes", auth)
    fixed = events[-1][1]
    assert fixed["status"] == "checked"
    assert fixed["code"] == FIXED
    assert any("AI-suggested" in note for note in fixed["notes"])
    assert usage(client, auth) == 2
    rewrite_prompt = [c.user for c in model.calls if c.schema_name == "rewrite"][0]
    assert "  4  Buy = Cross(Fast, Slow) AND Ref(Close, 1) > Close;" in rewrite_prompt

    messages = client.get(f"/v1/conversations/{conversation}", headers=auth).json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "assistant"]
    assert "reviewed_code" not in str(messages)


def test_review_needs_code(make_client):
    client, _ = make_client()
    auth = sign_up(client)
    conversation = new_conversation(client, auth, mode="review")
    code, body = stream(client, f"/v1/conversations/{conversation}/messages", auth, {"text": "hi"})
    assert code == 422
    assert "Paste the AFL" in body["error"]["message"]


def test_review_with_the_model_down_still_gives_the_verified_findings(make_client):
    client, _ = make_client(lambda call: LLMError("unavailable", "down"))
    auth = sign_up(client)
    conversation = new_conversation(client, auth, mode="review")
    _, events = stream(client, f"/v1/conversations/{conversation}/messages", auth, {"code": PASTED})
    review = events[-1][1]
    assert review["ai_review"] == "failed"
    assert [f["label"] for f in review["findings"]] == ["Verified"]


def test_apply_fixes_only_on_your_own_review_with_findings(make_client):
    client, _ = make_client(lambda call: {"findings": [], "summary": ""})
    auth = sign_up(client)
    conversation = new_conversation(client, auth, mode="review")
    clean = "SetTradeDelays(1, 1, 1, 1);\nBuy = Cross(C, MA(C, 20));\nSell = Cross(MA(C, 20), C);\n"
    _, events = stream(client, f"/v1/conversations/{conversation}/messages", auth, {"code": clean})
    message_id = events[-1][1]["message_id"]
    code, body = stream(client, f"/v1/messages/{message_id}/apply-fixes", auth)
    assert code == 422
    assert body["error"]["code"] == "nothing_to_fix"

    other = sign_up(client, "other@example.in")
    code, _ = stream(client, f"/v1/messages/{message_id}/apply-fixes", other)
    assert code == 404


# Fix-from-error


def test_fix_from_error(make_client):
    broken = (
        "SetTradeDelays(1, 1, 1, 1);\nFast = EMA(Close, 9)\nBuy = Cross(Fast, Close);\nSell = 0;\n"
    )
    fixed = broken.replace("EMA(Close, 9)\n", "EMA(Close, 9);\n")
    client, model = make_client([{"code": fixed, "changes": [], "notes": []}])
    auth = sign_up(client)
    conversation = new_conversation(client, auth, mode="fix")
    _, events = stream(
        client,
        f"/v1/conversations/{conversation}/messages",
        auth,
        {"code": broken, "error_text": "Ln: 3, Col: 1 : Error 32."},
    )
    result = events[-1][1]
    assert result["status"] == "checked"
    assert result["code"] == fixed
    assert any("not been run in AmiBroker" in note for note in result["notes"])
    assert "A semicolon is missing on the line before" in model.calls[0].user
    messages = client.get(f"/v1/conversations/{conversation}", headers=auth).json()["messages"]
    assert messages[0]["answer"] == {"error_text": "Ln: 3, Col: 1 : Error 32."}


@pytest.mark.parametrize(
    ("body", "status", "words"),
    [
        ({"code": "Buy = 1;", "error_text": ""}, 422, "error message"),
        ({"code": "Buy = 1;", "error_text": "x" * 2001}, 413, "2000"),
        ({"code": "", "error_text": "Error 32."}, 422, "Paste the AFL"),
        ({"code": "x;" * 20000, "error_text": "Error 32."}, 413, "bytes"),
    ],
)
def test_bad_fix_request(make_client, body, status, words):
    client, model = make_client(max_body_bytes=200_000)
    auth = sign_up(client)
    conversation = new_conversation(client, auth, mode="fix")
    code, answer = stream(client, f"/v1/conversations/{conversation}/messages", auth, body)
    assert code == status
    assert words in answer["error"]["message"]
    assert model.calls == []


# Feedback


def test_feedback_on_your_own_answer_can_be_changed(writing, pool):
    client, _, auth, conversation = writing()
    _, events = stream(client, f"/v1/conversations/{conversation}/messages", auth, {"text": "x"})
    message_id = events[-1][1]["message_id"]
    path = f"/v1/messages/{message_id}/feedback"
    assert (
        client.post(path, json={"rating": -1, "comment": "Wrong stop"}, headers=auth).status_code
        == 204
    )
    assert client.post(path, json={"rating": 1}, headers=auth).status_code == 204
    with pool.connection() as conn:
        rows = conn.execute("select rating, comment from feedback").fetchall()
    assert rows == [{"rating": 1, "comment": None}]

    other = sign_up(client, "other@example.in")
    assert client.post(path, json={"rating": 1}, headers=other).status_code == 404
    assert client.post(path, json={"rating": 5}, headers=auth).status_code == 422


def test_a_request_refused_for_quota_leaves_nothing_behind(writing):
    client, _, auth, conversation = writing(write_model([generation()]), daily_quota=1)
    path = f"/v1/conversations/{conversation}/messages"
    stream(client, path, auth, {"text": "one"})
    code, _ = stream(client, path, auth, {"text": "two"})
    assert code == 429
    messages = client.get(f"/v1/conversations/{conversation}", headers=auth).json()["messages"]
    assert [m["content"] for m in messages if m["role"] == "user"] == ["one"]


def test_unexpected_server_error_is_json_and_gives_the_quota_back(writing, monkeypatch):
    from copilot.api.store import Store

    client, _, auth, conversation = writing()

    def broken(self, *args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(Store, "add_message", broken)
    no_raise = client.__class__(
        client.app, headers=dict(client.headers), raise_server_exceptions=False
    )
    response = no_raise.post(
        f"/v1/conversations/{conversation}/messages", json={"text": "x"}, headers=auth
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "server_error"
    assert "database" not in response.text
    assert usage(client, auth) == 0
