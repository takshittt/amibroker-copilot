import pytest
import yaml

from copilot.checker.findings import INTRADAY_TIMEFRAMES, OTHER_TIMEFRAMES
from copilot.kb import KBError, Notes, load_notes
from copilot.kb.__main__ import main
from copilot.kb.schema import TIMEFRAMES

MISTAKE = """\
id: look-ahead-ref
title: Reading tomorrow's bar
checker_rule: lookahead_ref
explanation: A positive period reads future bars.
bad_example: |
  Buy = Ref(Close, 1) > Close;
good_example: |
  Buy = Close > Ref(Close, -1);
tags: [look-ahead, ref]
"""

CONCEPT = """\
---
title: Arrays, not loops
tags: [arrays]
---
AFL works on whole arrays at once.

A second paragraph.
"""

EXAMPLE_MD = """\
---
title: Daily moving-average crossover
timeframe: daily
market: nse_eq
tags: [crossover]
---
Buys when the fast average crosses above the slow one.
"""

EXAMPLE_AFL = "SetTradeDelays(1, 1, 1, 1);\nBuy = Cross(MA(Close, 20), MA(Close, 50));\n"

ERROR = """\
id: error-29
code: 29
title: Variable used before it has a value
explanation: The formula reads a variable that was never assigned.
fix: Assign the variable before the line that uses it.
tags: [variables]
"""


@pytest.fixture
def kb(tmp_path):
    for folder in ("mistakes", "concepts", "examples", "errors"):
        (tmp_path / folder).mkdir()
    (tmp_path / "mistakes" / "look-ahead-ref.yaml").write_text(MISTAKE)
    (tmp_path / "concepts" / "arrays-not-loops.md").write_text(CONCEPT)
    (tmp_path / "examples" / "ma-crossover.md").write_text(EXAMPLE_MD)
    (tmp_path / "examples" / "ma-crossover.afl").write_text(EXAMPLE_AFL)
    (tmp_path / "errors" / "error-29.yaml").write_text(ERROR)
    return tmp_path


def problems(kb_dir):
    with pytest.raises(KBError) as raised:
        load_notes(kb_dir)
    return raised.value.problems


def without(text, field):
    data = yaml.safe_load(text)
    del data[field]
    return yaml.safe_dump(data)


# A good tree


def test_good_tree_loads(kb):
    notes = load_notes(kb)
    assert isinstance(notes, Notes)

    mistake = notes.mistakes["look-ahead-ref"]
    assert mistake.checker_rule == "lookahead_ref"
    assert mistake.timeframe == "daily"
    assert mistake.bad_example == "Buy = Ref(Close, 1) > Close;\n"
    assert mistake.tags == ["look-ahead", "ref"]

    concept = notes.concepts["arrays-not-loops"]
    assert concept.title == "Arrays, not loops"
    assert concept.content == "AFL works on whole arrays at once.\n\nA second paragraph."

    example = notes.examples["ma-crossover"]
    assert (example.timeframe, example.market) == ("daily", "nse_eq")
    assert example.code == EXAMPLE_AFL
    assert example.description == "Buys when the fast average crosses above the slow one."

    assert notes.errors["error-29"].code == 29


def test_missing_folders_mean_nothing_of_that_kind(tmp_path):
    notes = load_notes(tmp_path)
    assert (notes.mistakes, notes.concepts, notes.examples, notes.errors) == ({}, {}, {}, {})


def test_mistake_without_a_checker_rule_is_allowed(kb):
    path = kb / "mistakes" / "look-ahead-ref.yaml"
    path.write_text(MISTAKE.replace("checker_rule: lookahead_ref", "checker_rule: null"))
    assert load_notes(kb).mistakes["look-ahead-ref"].checker_rule is None


def test_error_note_without_a_code_is_allowed(kb):
    (kb / "errors" / "error-29.yaml").write_text(ERROR.replace("code: 29", "code: null"))
    assert load_notes(kb).errors["error-29"].code is None


def test_timeframes_match_the_checker():
    assert TIMEFRAMES == INTRADAY_TIMEFRAMES + OTHER_TIMEFRAMES


# Problems


def test_unknown_field_is_reported_with_its_file(kb):
    (kb / "mistakes" / "look-ahead-ref.yaml").write_text(MISTAKE + "severity: high\n")
    found = problems(kb)
    assert len(found) == 1
    assert "mistakes/look-ahead-ref.yaml" in found[0]
    assert "severity" in found[0]


@pytest.mark.parametrize(
    "field", ["id", "title", "checker_rule", "explanation", "bad_example", "good_example"]
)
def test_mistake_missing_field(kb, field):
    (kb / "mistakes" / "look-ahead-ref.yaml").write_text(without(MISTAKE, field))
    found = problems(kb)
    assert len(found) == 1
    assert field in found[0]


@pytest.mark.parametrize("field", ["id", "code", "title", "explanation", "fix"])
def test_error_note_missing_field(kb, field):
    (kb / "errors" / "error-29.yaml").write_text(without(ERROR, field))
    found = problems(kb)
    assert len(found) == 1
    assert field in found[0]


def test_id_must_match_the_file_name(kb):
    (kb / "mistakes" / "look-ahead-ref.yaml").rename(kb / "mistakes" / "lookahead.yaml")
    found = problems(kb)
    assert len(found) == 1
    assert "lookahead.yaml" in found[0]
    assert "look-ahead-ref.yaml" in found[0]


@pytest.mark.parametrize("name", ["Arrays.md", "arrays_not_loops.md", "arrays--x.md"])
def test_file_name_must_be_lower_case_words_joined_by_hyphens(kb, name):
    (kb / "concepts" / "arrays-not-loops.md").rename(kb / "concepts" / name)
    found = problems(kb)
    assert len(found) == 1
    assert name in found[0]


def test_mistake_with_an_unknown_timeframe(kb):
    (kb / "mistakes" / "look-ahead-ref.yaml").write_text(MISTAKE + "timeframe: 5m\n")
    found = problems(kb)
    assert len(found) == 1
    assert "timeframe" in found[0]


def test_concept_without_front_matter(kb):
    (kb / "concepts" / "arrays-not-loops.md").write_text("Just some text.\n")
    found = problems(kb)
    assert len(found) == 1
    assert "concepts/arrays-not-loops.md" in found[0]
    assert "---" in found[0]


def test_concept_with_an_empty_body(kb):
    (kb / "concepts" / "arrays-not-loops.md").write_text("---\ntitle: T\n---\n\n")
    found = problems(kb)
    assert len(found) == 1
    assert "content" in found[0]


def test_concept_missing_title(kb):
    (kb / "concepts" / "arrays-not-loops.md").write_text("---\ntags: [a]\n---\nText.\n")
    found = problems(kb)
    assert len(found) == 1
    assert "title" in found[0]


def test_example_needs_both_files(kb):
    (kb / "examples" / "ma-crossover.afl").unlink()
    found = problems(kb)
    assert len(found) == 1
    assert "ma-crossover.afl" in found[0]

    (kb / "examples" / "ma-crossover.afl").write_text(EXAMPLE_AFL)
    (kb / "examples" / "ma-crossover.md").unlink()
    found = problems(kb)
    assert len(found) == 1
    assert "ma-crossover.md" in found[0]


def test_example_with_empty_code(kb):
    (kb / "examples" / "ma-crossover.afl").write_text("\n")
    found = problems(kb)
    assert len(found) == 1
    assert "code" in found[0]


@pytest.mark.parametrize("field", ["title", "timeframe", "market"])
def test_example_missing_field(kb, field):
    lines = [line for line in EXAMPLE_MD.splitlines() if not line.startswith(f"{field}:")]
    (kb / "examples" / "ma-crossover.md").write_text("\n".join(lines) + "\n")
    found = problems(kb)
    assert len(found) == 1
    assert field in found[0]


def test_file_of_another_kind_in_a_folder_is_reported(kb):
    (kb / "mistakes" / "notes.txt").write_text("x")
    (kb / "concepts" / "x.yaml").write_text("x: 1")
    found = problems(kb)
    assert len(found) == 2


def test_every_problem_is_reported_in_one_run(kb):
    (kb / "mistakes" / "look-ahead-ref.yaml").write_text(MISTAKE + "severity: high\n")
    (kb / "errors" / "error-29.yaml").write_text(without(ERROR, "fix"))
    (kb / "concepts" / "arrays-not-loops.md").write_text("No front matter.\n")
    assert len(problems(kb)) == 3


# Command line


@pytest.fixture
def full_kb(kb):
    (kb / "functions").mkdir()
    (kb / "functions" / "timenum.yaml").write_text(
        "name: TimeNum\ncategory: time\nreturns: array\nparams: []\n"
        "doc_url: https://www.amibroker.com/guide/afl/timenum.html\n"
    )
    (kb / "builtins.yaml").write_text("[]\n")
    (kb / "markets.yaml").write_text(
        "- id: nse_eq\n  name: NSE equity\n  exchange: NSE\n  timezone: Asia/Kolkata\n"
        "  sessions:\n"
        '    - {name: regular, open: "09:15", close: "15:30", days: [mon, tue, wed, thu, fri]}\n'
        "  dst_rules: []\n  last_verified: null\n"
    )
    (kb / "VERSION").write_text("1\n")
    return kb


def test_command_counts_the_notes(full_kb, capsys):
    assert main([str(full_kb)]) == 0
    out = capsys.readouterr().out
    assert "1 mistakes" in out
    assert "1 concepts" in out
    assert "1 examples" in out
    assert "1 error notes" in out


def test_command_fails_on_a_bad_note(full_kb, capsys):
    (full_kb / "errors" / "error-29.yaml").write_text(without(ERROR, "fix"))
    assert main([str(full_kb)]) == 1
    assert "errors/error-29.yaml" in capsys.readouterr().err


def test_command_reports_catalog_and_note_problems_together(full_kb, capsys):
    (full_kb / "VERSION").unlink()
    (full_kb / "errors" / "error-29.yaml").write_text(without(ERROR, "fix"))
    assert main([str(full_kb)]) == 1
    err = capsys.readouterr().err
    assert "VERSION" in err
    assert "errors/error-29.yaml" in err
    assert "2 problems" in err


def test_command_fails_on_an_example_for_an_unknown_market(full_kb, capsys):
    path = full_kb / "examples" / "ma-crossover.md"
    path.write_text(EXAMPLE_MD.replace("market: nse_eq", "market: moon"))
    assert main([str(full_kb)]) == 1
    assert "unknown market 'moon'" in capsys.readouterr().err
