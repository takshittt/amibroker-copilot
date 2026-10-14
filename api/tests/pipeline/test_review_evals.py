from pathlib import Path

import pytest

from copilot.evals import (
    Planted,
    ReviewSample,
    load_review_samples,
    main,
    render_review,
    run_review_evals,
    score_review,
)
from copilot.kb import KBError
from copilot.pipeline.review import AI_SUGGESTED, VERIFIED, ReviewFinding

REVIEW_DIR = Path(__file__).resolve().parents[3] / "evals" / "review"
KB_DIR = Path(__file__).resolve().parents[3] / "kb"


def finding(label, rule, line, severity="critical"):
    return ReviewFinding(label, severity, line, "message", "fix", rule)


def sample(*planted):
    return ReviewSample("s", "nse_eq", "daily", "x = 1;\n", tuple(planted))


# The real test set, run through the checker. No model is involved.


@pytest.fixture(scope="module")
def samples(catalog):
    return load_review_samples(REVIEW_DIR, catalog)


def test_the_review_test_set_meets_the_size_the_spec_asks_for(samples):
    assert len(samples) >= 30
    assert sum(1 for s in samples if not s.planted) >= 5
    assert sum(1 for s in samples for p in s.planted if p.kind == "ai") >= 10
    assert len({s.market for s in samples}) >= 4


def test_every_checker_rule_is_planted_somewhere(samples):
    from copilot.checker.rules import RULES

    planted = {p.rule for s in samples for p in s.planted if p.kind == "verified"}
    assert planted == {rule.id for rule in RULES}


def test_headers_are_blanked_so_nothing_gives_the_answer_away(samples):
    for item in samples:
        assert "planted" not in item.code
        assert "// context" not in item.code


def test_blanking_the_header_keeps_the_line_numbers(samples):
    original = (REVIEW_DIR / "a01-cross-swapped.afl").read_text()
    blanked = next(s for s in samples if s.id == "a01-cross-swapped")
    assert len(blanked.code.split("\n")) == len(original.split("\n"))
    (planted,) = blanked.planted
    assert "Cross(Slow, Fast)" in blanked.code.split("\n")[planted.line - 1]


def test_checker_finds_every_planted_verified_bug_and_raises_no_false_alarm(samples, catalog):
    report = run_review_evals(samples, catalog)
    missed = {o.id: o.verified_missed for o in report.outcomes if o.verified_missed}
    alarms = {o.id: o.false_alarms for o in report.outcomes if o.false_alarms}
    assert missed == {}
    assert alarms == {}
    assert report.metrics["verified_recall"] == 1.0
    assert report.metrics["clean_samples_with_a_false_alarm"] == 0
    assert not report.with_ai
    assert "ai_recall" not in report.metrics


def test_the_ai_only_bugs_really_are_invisible_to_the_checker(samples, catalog):
    # If the checker starts catching one, it belongs with the verified samples.
    report = run_review_evals([s for s in samples if s.id.startswith("a")], catalog)
    assert report.metrics["verified_false_alarms"] == 0


# Scoring


def test_verified_bug_is_found_when_its_rule_fires():
    outcome = score_review(
        sample(Planted("verified", rule="lookahead_ref"), Planted("verified", rule="exrem")),
        [finding(VERIFIED, "lookahead_ref", 4)],
    )
    assert (outcome.verified_planted, outcome.verified_found) == (2, 1)
    assert outcome.verified_missed == ("exrem",)
    assert outcome.false_alarms == ()


def test_verified_finding_nobody_planted_is_a_false_alarm():
    outcome = score_review(sample(), [finding(VERIFIED, "trade_delays", 3, "warning")])
    assert outcome.clean
    assert outcome.false_alarms == ("trade_delays (line 3, warning)",)


@pytest.mark.parametrize(("line", "found"), [(20, 1), (23, 1), (17, 1), (24, 0), (None, 0)])
def test_ai_bug_is_found_when_an_ai_finding_is_within_three_lines(line, found):
    outcome = score_review(
        sample(Planted("ai", line=20, description="swapped")),
        [finding(AI_SUGGESTED, "ai_review", line)],
    )
    assert outcome.ai_found == found
    assert outcome.ai_other == 1 - found
    assert outcome.ai_missed == (() if found else ("swapped",))


def test_a_verified_finding_does_not_count_as_finding_an_ai_bug():
    outcome = score_review(
        sample(Planted("ai", line=5, description="d")), [finding(VERIFIED, "exrem", 5)]
    )
    assert outcome.ai_found == 0
    assert outcome.false_alarms == ("exrem (line 5, critical)",)


# Loading

SAMPLE = "// context: timeframe=daily market=nse_eq\n// planted: verified exrem\n\nBuy = 1;\n"


def problems(directory, catalog):
    with pytest.raises(KBError) as raised:
        load_review_samples(directory, catalog)
    return raised.value.problems


@pytest.mark.parametrize(
    ("text", "words"),
    [
        (SAMPLE.replace("// context: timeframe=daily market=nse_eq\n", ""), "context"),
        (SAMPLE.replace("// planted: verified exrem\n", ""), "planted"),
        (SAMPLE.replace("nse_eq", "moon"), "unknown market"),
        (SAMPLE.replace("daily", "1d"), "unknown timeframe"),
        (SAMPLE + "// planted: none\n", "cannot stand beside"),
    ],
)
def test_bad_sample_is_reported(tmp_path, catalog, text, words):
    (tmp_path / "s.afl").write_text(text)
    found = problems(tmp_path, catalog)
    assert len(found) == 1
    assert words in found[0]


def test_empty_directory(tmp_path, catalog):
    assert "no samples" in problems(tmp_path, catalog)[0]


# Command line


def test_checker_only_command_needs_no_key_and_no_database(capsys, monkeypatch):
    for name in ("OPENAI_API_KEY", "DATABASE_URL", "STRONG_MODEL", "CHEAP_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert main(["review", str(REVIEW_DIR), "--kb", str(KB_DIR)]) == 0
    out = capsys.readouterr().out
    assert "checker only (the AI review was not run)" in out
    assert "verified_recall" in out
    assert "ai_recall" not in out


def test_command_without_kb_or_ai_explains(capsys):
    assert main(["review", str(REVIEW_DIR)]) == 2
    assert "--kb" in capsys.readouterr().err


def test_report_shows_misses_and_false_alarms(catalog):
    bad = ReviewSample(
        "bad",
        "nse_eq",
        "daily",
        "Buy = Cross(C, MA(C, 5));\nSell = 0;\n",
        (Planted("verified", rule="lookahead_ref"),),
    )
    text = render_review(run_review_evals([bad], catalog))
    assert "MISSED lookahead_ref" in text
    assert "FALSE ALARM trade_delays" in text
