import pytest

from copilot.config import ConfigError, Settings
from copilot.pipeline.generate import ExplanationBlock
from copilot.pipeline.orchestrator import CheckLine, Problem, RunRecord, WriteResult
from copilot.pipeline.setup import connect_deps
from copilot.write import main, render

RUN = RunRecord(
    attempts=2,
    tokens_in={"strong": 900, "cheap": 300},
    tokens_out={"strong": 200, "cheap": 40},
    cost_usd=0.0123,
    latency_ms=15400,
    kb_version=4,
)


def answer(status, **changes):
    fields = {
        "status": status,
        "run": RUN,
        "code": "Buy = 1;\nSell = 0;\n",
        "explanation_blocks": (ExplanationBlock(start_line=1, end_line=2, text="Signals."),),
        "checks": (CheckLine("syntax", "passed"), CheckLine("unknown_function", "failed")),
        "doc_links": (("MA", "https://www.amibroker.com/guide/afl/ma.html"),),
        "notes": ("Check your data's time zone.",),
    }
    fields.update(changes)
    return WriteResult(**fields)


def test_checked_answer_shows_everything():
    text = render(answer("checked"))
    assert text.startswith("CHECKED: this code passed every check.")
    assert "Buy = 1;\nSell = 0;" in text
    assert "Lines 1-2: Signals." in text
    assert "Checks (Verified)" in text
    assert "[pass] syntax" in text
    assert "[FAIL] unknown_function" in text
    assert "Check your data's time zone." in text
    assert "MA: https://www.amibroker.com/guide/afl/ma.html" in text
    assert "2 attempts, 1200 tokens in, 240 out, cost $0.0123, 15.4 s, kb_version 4" in text


def test_code_that_failed_its_checks_is_never_headed_checked():
    problem = Problem("checker", "unknown_function", "TrailStop is not an AFL function.", 3)
    text = render(answer("not_fully_checked", problems=(problem,)))
    assert text.startswith("NOT FULLY CHECKED")
    assert "CHECKED: this code passed" not in text
    assert "  - line 3: TrailStop is not an AFL function." in text
    assert "Buy = 1;" in text


def test_checker_crash_is_labelled_not_checked():
    text = render(answer("not_checked", checks=()))
    assert text.startswith("NOT CHECKED")
    assert "unverified" in text
    assert "Checks (Verified)" not in text


def test_clarify_shows_only_the_questions():
    text = render(WriteResult(status="clarify", run=RUN, questions=("Long or short?",)))
    assert text == "Before writing the code, I need to know:\n  - Long or short?"


def test_error_and_cancelled():
    assert render(WriteResult(status="error", run=RUN, message="Busy.")) == "No answer: Busy."
    assert "Stopped" in render(WriteResult(status="cancelled", run=RUN))


def test_unknown_cost_is_shown_as_unknown():
    run = RunRecord(attempts=1)
    assert "1 attempt, 0 tokens in, 0 out, cost unknown" in render(answer("checked", run=run))


def test_setup_needs_the_model_ids_before_anything_else():
    with pytest.raises(ConfigError, match="STRONG_MODEL and CHEAP_MODEL"):
        connect_deps(Settings(openai_api_key="sk-test", database_url="postgresql:///x"))
    with pytest.raises(ConfigError, match="CHEAP_MODEL must be set"):
        connect_deps(Settings(strong_model="s"))


def test_setup_needs_the_key():
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        connect_deps(Settings(strong_model="s", cheap_model="c"))


def test_command_without_settings_explains_and_exits_two(monkeypatch, capsys):
    for name in ("STRONG_MODEL", "CHEAP_MODEL", "OPENAI_API_KEY", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    assert main(["--market", "nse_fo", "--timeframe", "5min", "anything"]) == 2
    assert "STRONG_MODEL" in capsys.readouterr().err
