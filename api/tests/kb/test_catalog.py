import textwrap

import pytest

from copilot.kb import Catalog, KBError, load_catalog
from copilot.kb.__main__ import main

MA = """\
name: MA
category: indicator
returns: array
params:
  - {name: array, type: array, optional: false}
  - {name: periods, type: any, optional: false}
description: Simple moving average.
doc_url: https://www.amibroker.com/guide/afl/ma.html
"""

TIMENUM = """\
name: TimeNum
category: time
returns: array
params: []
description: Time of each bar as HHMMSS.
doc_url: https://www.amibroker.com/guide/afl/timenum.html
"""

BUILTINS = """\
- name: Close
  kind: variable
  type: array
  description: Closing price of each bar.
  aliases: [C]
- name: Buy
  kind: variable
  type: array
  description: Long entry signal.
- name: "True"
  kind: constant
  type: number
  description: Logical true.
"""

MARKETS = """\
- id: nse_eq
  name: NSE equity
  exchange: NSE
  timezone: Asia/Kolkata
  sessions:
    - {name: regular, open: "09:15", close: "15:30", days: [mon, tue, wed, thu, fri]}
  dst_rules: []
  last_verified: 2026-10-14
"""


@pytest.fixture
def kb(tmp_path):
    """A small valid knowledge base."""
    (tmp_path / "functions").mkdir()
    (tmp_path / "functions" / "ma.yaml").write_text(MA)
    (tmp_path / "functions" / "timenum.yaml").write_text(TIMENUM)
    (tmp_path / "builtins.yaml").write_text(BUILTINS)
    (tmp_path / "markets.yaml").write_text(MARKETS)
    (tmp_path / "VERSION").write_text("3\n")
    return tmp_path


def problems(kb_dir):
    with pytest.raises(KBError) as raised:
        load_catalog(kb_dir)
    return raised.value.problems


# Loading a good tree


def test_good_tree_loads(kb):
    catalog = load_catalog(kb)
    assert isinstance(catalog, Catalog)
    assert sorted(f.name for f in catalog.functions.values()) == ["MA", "TimeNum"]
    assert sorted(b.name for b in catalog.builtins.values()) == ["Buy", "Close", "True"]
    assert list(catalog.markets) == ["nse_eq"]
    assert catalog.kb_version == 3


def test_function_lookup_ignores_case(kb):
    catalog = load_catalog(kb)
    assert catalog.function("ma").name == "MA"
    assert catalog.function("TIMENUM").name == "TimeNum"
    assert catalog.function("TrailStop") is None


def test_builtin_lookup_ignores_case_and_resolves_aliases(kb):
    catalog = load_catalog(kb)
    assert catalog.builtin("close").name == "Close"
    assert catalog.builtin("C").name == "Close"
    assert catalog.builtin("c").name == "Close"
    assert catalog.builtin("Sell") is None


def test_market_lookup(kb):
    catalog = load_catalog(kb)
    assert catalog.market("nse_eq").exchange == "NSE"
    assert catalog.market("moon") is None


def test_functions_and_builtins_do_not_answer_for_each_other(kb):
    catalog = load_catalog(kb)
    assert catalog.function("Close") is None
    assert catalog.builtin("MA") is None


# Problems in single files


def test_unknown_field_is_reported_with_its_file(kb):
    (kb / "functions" / "ma.yaml").write_text(MA + "notes: extra\n")
    found = problems(kb)
    assert len(found) == 1
    assert "functions/ma.yaml" in found[0]
    assert "notes" in found[0]


def test_missing_field_is_reported(kb):
    (kb / "functions" / "ma.yaml").write_text(MA.replace("returns: array\n", ""))
    found = problems(kb)
    assert len(found) == 1
    assert "functions/ma.yaml" in found[0]
    assert "returns" in found[0]


def test_file_name_must_match_function_name(kb):
    (kb / "functions" / "ma.yaml").rename(kb / "functions" / "average.yaml")
    found = problems(kb)
    assert len(found) == 1
    assert "functions/average.yaml" in found[0]
    assert "ma.yaml" in found[0]


def test_duplicate_yaml_key_is_reported(kb):
    (kb / "functions" / "ma.yaml").write_text(MA + "returns: number\n")
    found = problems(kb)
    assert len(found) == 1
    assert "functions/ma.yaml" in found[0]
    assert "duplicate key" in found[0]


def test_yaml_that_does_not_parse_is_reported(kb):
    (kb / "functions" / "ma.yaml").write_text("name: [MA\n")
    found = problems(kb)
    assert len(found) == 1
    assert "functions/ma.yaml" in found[0]


def test_function_file_holding_a_list_is_reported(kb):
    (kb / "functions" / "ma.yaml").write_text("- name: MA\n")
    found = problems(kb)
    assert len(found) == 1
    assert "functions/ma.yaml" in found[0]


def test_bad_builtin_is_reported_with_its_name(kb):
    (kb / "builtins.yaml").write_text(BUILTINS.replace("kind: constant", "kind: function"))
    found = problems(kb)
    assert len(found) == 1
    assert "builtins.yaml" in found[0]
    assert "True" in found[0]


def test_unquoted_true_in_builtins_says_to_quote_it(kb):
    (kb / "builtins.yaml").write_text(BUILTINS.replace('"True"', "True"))
    found = problems(kb)
    assert len(found) == 1
    assert "put quotes around" in found[0]


def test_unquoted_time_in_markets_says_to_quote_it(kb):
    # YAML reads an unquoted 15:30 as the base-60 number 930.
    (kb / "markets.yaml").write_text(MARKETS.replace('"15:30"', "15:30"))
    found = problems(kb)
    assert len(found) == 1
    assert "markets.yaml" in found[0]
    assert "nse_eq" in found[0]
    assert "put quotes around" in found[0]


# Problems across files


def test_duplicate_function_differing_only_in_case(kb):
    # Two files on a case-sensitive disk; one name to AmiBroker.
    (kb / "functions" / "ma.yaml").write_text(MA.replace("name: MA", "name: Timenum"))
    (kb / "functions" / "ma.yaml").rename(kb / "functions" / "timenum2.yaml")
    found = problems(kb)
    assert any("Timenum" in p and "already defined" in p for p in found)


def test_duplicate_builtin_name(kb):
    extra = """\
    - name: close
      kind: variable
      type: array
      description: Again.
    """
    (kb / "builtins.yaml").write_text(BUILTINS + textwrap.dedent(extra))
    found = problems(kb)
    assert len(found) == 1
    assert "close" in found[0]
    assert "already defined" in found[0]


def test_alias_colliding_with_a_function(kb):
    (kb / "builtins.yaml").write_text(BUILTINS.replace("aliases: [C]", "aliases: [MA]"))
    found = problems(kb)
    assert len(found) == 1
    assert "MA" in found[0]
    assert "already defined" in found[0]
    assert "functions/ma.yaml" in found[0]


def test_builtin_colliding_with_a_function(kb):
    (kb / "builtins.yaml").write_text(BUILTINS.replace("name: Buy", "name: TimeNum"))
    found = problems(kb)
    assert len(found) == 1
    assert "already defined" in found[0]


def test_duplicate_market_id(kb):
    (kb / "markets.yaml").write_text(MARKETS + MARKETS)
    found = problems(kb)
    assert len(found) == 1
    assert "nse_eq" in found[0]
    assert "already defined" in found[0]


def test_every_problem_is_reported_in_one_run(kb):
    (kb / "functions" / "ma.yaml").write_text(MA + "notes: extra\n")
    (kb / "functions" / "timenum.yaml").write_text(TIMENUM.replace("returns: array", "returns: x"))
    (kb / "markets.yaml").write_text(MARKETS.replace("Asia/Kolkata", "Asia/Mumbai"))
    found = problems(kb)
    assert len(found) == 3
    assert any("functions/ma.yaml" in p for p in found)
    assert any("functions/timenum.yaml" in p for p in found)
    assert any("markets.yaml" in p for p in found)


# Missing pieces


def test_missing_version_file(kb):
    (kb / "VERSION").unlink()
    found = problems(kb)
    assert len(found) == 1
    assert "VERSION" in found[0]


@pytest.mark.parametrize("text", ["", "one\n", "1.5\n", "0\n", "-2\n"])
def test_version_must_be_a_positive_whole_number(kb, text):
    (kb / "VERSION").write_text(text)
    found = problems(kb)
    assert len(found) == 1
    assert "VERSION" in found[0]


@pytest.mark.parametrize("name", ["builtins.yaml", "markets.yaml"])
def test_missing_list_file(kb, name):
    (kb / name).unlink()
    found = problems(kb)
    assert len(found) == 1
    assert name in found[0]


def test_empty_functions_directory(kb):
    for path in (kb / "functions").iterdir():
        path.unlink()
    found = problems(kb)
    assert len(found) == 1
    assert "functions" in found[0]


def test_directory_that_does_not_exist(tmp_path):
    found = problems(tmp_path / "nowhere")
    assert len(found) == 1
    assert "nowhere" in found[0]


def test_file_in_functions_with_another_extension_is_reported(kb):
    # A .yml file would otherwise be skipped without a word.
    (kb / "functions" / "ema.yml").write_text(MA)
    found = problems(kb)
    assert len(found) == 1
    assert "ema.yml" in found[0]


# Command line


def test_command_exits_zero_on_a_good_tree(kb, capsys):
    assert main([str(kb)]) == 0
    out = capsys.readouterr().out
    assert "2 functions" in out
    assert "3 built-ins" in out
    assert "1 markets" in out
    assert "kb_version 3" in out


def test_command_exits_one_and_lists_problems_on_a_bad_tree(kb, capsys):
    (kb / "functions" / "ma.yaml").write_text(MA + "notes: extra\n")
    assert main([str(kb)]) == 1
    err = capsys.readouterr().err
    assert "functions/ma.yaml" in err
    assert "1 problem" in err


def test_command_names_markets_nobody_has_verified(kb, capsys):
    (kb / "markets.yaml").write_text(MARKETS.replace("2026-10-14", "null"))
    assert main([str(kb)]) == 0
    assert "nse_eq" in capsys.readouterr().out


def test_command_needs_exactly_one_argument(capsys):
    assert main([]) == 2
    assert "usage" in capsys.readouterr().err.lower()
