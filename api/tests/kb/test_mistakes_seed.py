"""The mistake catalogue in /kb agrees with the checker.

Each entry names the rule that catches it. Its wrong example must set
off that rule and nothing else, and its right example must be clean.
"""

from pathlib import Path

import pytest

from copilot.checker import Context, check
from copilot.checker.rules import RULES
from copilot.kb import load_catalog, load_notes

KB_DIR = Path(__file__).resolve().parents[3] / "kb"
NOTES = load_notes(KB_DIR)
RULE_IDS = {rule.id for rule in RULES}


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(KB_DIR)


def test_every_checker_rule_has_a_mistake_entry():
    assert {m.checker_rule for m in NOTES.mistakes.values()} == RULE_IDS


@pytest.mark.parametrize("mistake", NOTES.mistakes.values(), ids=lambda m: m.id)
def test_mistake_names_a_real_rule(mistake):
    assert mistake.checker_rule is None or mistake.checker_rule in RULE_IDS


@pytest.mark.parametrize("mistake", NOTES.mistakes.values(), ids=lambda m: m.id)
def test_wrong_example_sets_off_its_rule_and_no_other(mistake, catalog):
    result = check(mistake.bad_example, catalog, Context(timeframe=mistake.timeframe))
    assert result.status != "checker_error", result.error
    assert {finding.rule for finding in result.findings} == {mistake.checker_rule}


@pytest.mark.parametrize("mistake", NOTES.mistakes.values(), ids=lambda m: m.id)
def test_right_example_is_clean(mistake, catalog):
    result = check(mistake.good_example, catalog, Context(timeframe=mistake.timeframe))
    assert result.status == "passed"
    assert result.findings == ()
