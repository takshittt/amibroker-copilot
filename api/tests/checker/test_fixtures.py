"""Runs the checker over every sample in tests/fixtures/afl.

Each sample says in its header what the checker must report:

    // context: timeframe=5min market=nse_fo
    // expect: lookahead_ref 12        (rule and line; repeat for each finding)
    // expect: none                    (no findings at all)
    // status: passed                  (optional; else failed when anything is expected)
"""

import re
from pathlib import Path

import pytest

from copilot.checker import Context, check
from copilot.checker.rules import RULES

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "afl"
FIXTURES = sorted(FIXTURE_DIR.glob("*.afl"))


def read_header(text):
    context = re.search(r"^// context: timeframe=(\S+) market=(\S+)$", text, re.M)
    assert context, "sample needs a '// context: timeframe=... market=...' line"
    expected = []
    for rule, line in re.findall(r"^// expect: (\w+) (\d+)$", text, re.M):
        expected.append((rule, int(line)))
    says_none = re.search(r"^// expect: none$", text, re.M) is not None
    assert says_none != bool(expected), "sample needs '// expect: none' or expect lines, not both"
    status = re.search(r"^// status: (\w+)$", text, re.M)
    return context.group(1), context.group(2), expected, status.group(1) if status else None


def test_there_are_samples():
    assert len(FIXTURES) >= 15


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_sample_gives_the_expected_findings(path, catalog):
    text = path.read_text()
    timeframe, market_id, expected, status = read_header(text)
    assert catalog.market(market_id) is not None, f"unknown market {market_id}"

    result = check(text, catalog, Context(timeframe=timeframe, market_id=market_id))

    assert result.status != "checker_error", result.error
    assert sorted((f.rule, f.line) for f in result.findings) == sorted(expected)
    assert result.status == (status or ("failed" if expected else "passed"))


def test_good_samples_start_with_good_and_bad_samples_with_bad():
    for path in FIXTURES:
        _, _, expected, _ = read_header(path.read_text())
        assert path.stem.startswith("bad_" if expected else "good_"), path.name


def test_every_rule_has_a_sample_that_triggers_it():
    triggered = set()
    for path in FIXTURES:
        triggered.update(rule for rule, _ in read_header(path.read_text())[2])
    assert triggered == {rule.id for rule in RULES}
