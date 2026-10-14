import pytest

from copilot.api import offline
from copilot.config import ConfigError


def test_offline_demo_refuses_to_start_without_its_switch(monkeypatch):
    monkeypatch.delenv("OFFLINE_DEMO", raising=False)
    with pytest.raises(ConfigError, match="OFFLINE_DEMO=1"):
        offline.create_offline_app()
    monkeypatch.setenv("OFFLINE_DEMO", "yes")
    with pytest.raises(ConfigError, match="OFFLINE_DEMO=1"):
        offline.create_offline_app()


def test_offline_demo_listens_only_on_this_machine():
    assert offline.HOST == "127.0.0.1"


def test_scripted_code_passes_the_real_checker(catalog):
    from copilot.checker import Context, check

    result = check(offline.WRITE_CODE, catalog, Context(timeframe="daily", market_id="nse_eq"))
    assert result.status == "passed"
    assert result.findings == ()


def test_every_scripted_answer_says_it_is_scripted(make_client, monkeypatch):
    from .conftest import new_conversation, sign_up, stream

    monkeypatch.setattr(offline.time, "sleep", lambda seconds: None)
    client, _ = make_client(offline._answer)
    auth = sign_up(client)
    conversation = new_conversation(client, auth)
    _, events = stream(
        client,
        f"/v1/conversations/{conversation}/messages",
        auth,
        {
            "text": "Long only: buy when the 20 day average crosses above the 50 day one, "
            "sell when it crosses back below. Trade at the next open and show arrows."
        },
    )
    result = events[-1][1]
    assert result["status"] == "checked"
    assert offline.OFFLINE_NOTE in result["notes"]

    review = new_conversation(client, auth, mode="review")
    _, events = stream(
        client, f"/v1/conversations/{review}/messages", auth, {"code": offline.WRITE_CODE}
    )
    reviewed = events[-1][1]
    assert reviewed["summary"] == offline.OFFLINE_NOTE
    assert [f["label"] for f in reviewed["findings"]] == ["AI-suggested"]
