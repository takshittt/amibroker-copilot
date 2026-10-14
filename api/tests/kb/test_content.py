"""The written content in /kb holds up against the checker and the catalog.

Examples must pass the checker with nothing reported. Code shown in a
concept note must have no Critical finding. Notes must only name
functions that exist.
"""

import re
from pathlib import Path

import pytest

from copilot.checker import Context, check
from copilot.kb import load_catalog, load_notes

KB_DIR = Path(__file__).resolve().parents[3] / "kb"
NOTES = load_notes(KB_DIR)
AFL_BLOCK = re.compile(r"```afl\n(.*?)```", re.DOTALL)
SNIPPETS = [
    pytest.param(code, id=f"{concept.id}-{number}")
    for concept in NOTES.concepts.values()
    for number, code in enumerate(AFL_BLOCK.findall(concept.content), start=1)
]


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(KB_DIR)


def describe(result):
    return [(f.rule, f.line, f.message) for f in result.findings]


# Examples


def test_there_are_examples_for_daily_and_intraday_and_several_markets():
    examples = list(NOTES.examples.values())
    assert len(examples) >= 10
    assert {"daily", "5min"} <= {example.timeframe for example in examples}
    assert {"nse_eq", "nse_fo", "mcx"} <= {example.market for example in examples}


@pytest.mark.parametrize("example", NOTES.examples.values(), ids=lambda e: e.id)
def test_example_passes_the_checker_with_nothing_reported(example, catalog):
    assert catalog.market(example.market) is not None
    context = Context(timeframe=example.timeframe, market_id=example.market)
    result = check(example.code, catalog, context)
    assert result.status == "passed", describe(result)
    assert result.findings == (), describe(result)


@pytest.mark.parametrize("example", NOTES.examples.values(), ids=lambda e: e.id)
def test_example_keeps_its_settings_in_parameters(example):
    assert "Param" in example.code


def test_intraday_examples_on_markets_that_close_exit_by_the_time_of_day(catalog):
    for example in NOTES.examples.values():
        market = catalog.market(example.market)
        intraday = Context(timeframe=example.timeframe).is_intraday
        if intraday and not market.never_closes and "Buy" in example.code:
            assert "ExitTime" in example.code, example.id


# Concept notes


def test_the_planned_concepts_are_covered():
    assert len(NOTES.concepts) >= 12
    assert len(SNIPPETS) >= 12


@pytest.mark.parametrize("code", SNIPPETS)
def test_code_in_a_concept_note_has_no_critical_finding(code, catalog):
    result = check(code, catalog, Context(timeframe="daily"))
    assert result.status != "checker_error", result.error
    critical = [f for f in result.findings if f.severity == "critical"]
    assert critical == [], describe(result)


@pytest.mark.parametrize("concept", NOTES.concepts.values(), ids=lambda c: c.id)
def test_every_code_fence_in_a_concept_note_is_marked_afl(concept):
    fences = re.findall(r"^```(.*)$", concept.content, re.MULTILINE)
    assert fences[0::2] == ["afl"] * (len(fences) // 2), "open each code block with ```afl"
    assert len(fences) % 2 == 0


def _named_calls(text):
    """Names written as `Name(` in running text, outside code blocks."""
    prose = AFL_BLOCK.sub("", text)
    return set(re.findall(r"\b([A-Z][A-Za-z0-9_]+)\(", prose))


@pytest.mark.parametrize(
    "note",
    [*NOTES.concepts.values(), *NOTES.errors.values()],
    ids=lambda n: n.id,
)
def test_functions_named_in_a_note_exist(note, catalog):
    text = getattr(note, "content", None) or f"{note.explanation} {note.fix}"
    unknown = {name for name in _named_calls(text) if catalog.function(name) is None}
    assert unknown == set()


# Error notes


def test_error_numbers_are_unique():
    codes = [error.code for error in NOTES.errors.values() if error.code is not None]
    assert len(codes) == len(set(codes))
    assert len(codes) >= 15


@pytest.mark.parametrize("error", NOTES.errors.values(), ids=lambda e: e.id)
def test_error_note_id_carries_its_number(error):
    kind = "warning" if 500 <= error.code < 600 else "error"
    assert error.id == f"{kind}-{error.code}"
