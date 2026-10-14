import ast
import subprocess
import sys
from pathlib import Path

import pytest

from copilot import checker
from copilot.checker import CheckResult, Context, check, rules
from copilot.checker.rules import RULES, Rule

CHECKER_DIR = Path(checker.__file__).parent

GOOD = """\
SetTradeDelays(1, 1, 1, 1);
Fast = EMA(Close, 9);
Slow = EMA(Close, 21);
Buy = Cross(Fast, Slow);
Sell = Cross(Slow, Fast);
BuyPrice = Open;
SellPrice = Open;
"""


def test_good_code_passes_with_every_rule_listed(run):
    result = run(GOOD)
    assert isinstance(result, CheckResult)
    assert result.status == "passed"
    assert result.findings == ()
    assert [c.rule for c in result.checks] == [rule.id for rule in RULES]
    assert {c.outcome for c in result.checks} == {"passed"}
    assert result.error is None


def test_the_ten_rules_are_registered_in_order():
    assert [rule.id for rule in RULES] == [
        "syntax",
        "unknown_function",
        "arg_count",
        "if_on_array",
        "lookahead_ref",
        "eod_exit",
        "intrabar_stop_price",
        "trade_delays",
        "exrem",
        "hardcoded_times",
    ]


def test_critical_finding_fails_the_check(run):
    result = run(GOOD + "x = TrailStop(Close, 2);\n")
    assert result.status == "failed"
    assert [(f.rule, f.severity, f.line) for f in result.findings] == [
        ("unknown_function", "critical", 8)
    ]
    outcomes = {c.rule: c.outcome for c in result.checks}
    assert outcomes["unknown_function"] == "failed"
    assert outcomes["arg_count"] == "passed"


def test_warning_alone_fails_the_check(run):
    result = run(GOOD.replace("SetTradeDelays(1, 1, 1, 1);\n", ""))
    assert {f.severity for f in result.findings} == {"warning"}
    assert result.status == "failed"


def test_tip_alone_passes_the_check(run):
    result = run("x = TimeNum() >= 91500;")
    assert [(f.rule, f.severity) for f in result.findings] == [("hardcoded_times", "tip")]
    assert result.status == "passed"
    assert {c.rule: c.outcome for c in result.checks}["hardcoded_times"] == "failed"


def test_every_finding_has_a_message_and_a_fix_hint(run):
    result = run(
        "if (Close > Open) x = TrailStop(1);\ny = MA(Close);\nBuy = Ref(Close, 1) > Close;\n"
    )
    assert result.findings
    for finding in result.findings:
        assert finding.message
        assert finding.fix_hint
        assert finding.line >= 1


def test_findings_are_ordered_by_line(run):
    result = run("a = Foo(1);\nb = MA(Close);\nc = Bar(2);\n")
    assert [f.line for f in result.findings] == [1, 2, 3]


def test_code_that_does_not_parse_fails_and_skips_the_other_rules(run):
    result = run("Buy = Cross(MA(Close, 5), MA(Close, 20);\nx = TrailStop(1);\n")
    assert result.status == "failed"
    assert {f.rule for f in result.findings} == {"syntax"}
    outcomes = {c.rule: c.outcome for c in result.checks}
    assert outcomes["syntax"] == "failed"
    assert outcomes["unknown_function"] == "skipped"


def test_comment_never_closed_is_a_syntax_finding_not_a_crash(run):
    result = run("Buy = 1;\n/* oops\nSell = 1;\n")
    assert result.status == "failed"
    assert [(f.rule, f.line) for f in result.findings] == [("syntax", 2)]


def test_empty_source_passes(run):
    assert run("").status == "passed"
    assert run("// only a comment\n").status == "passed"


def test_exception_inside_a_rule_gives_checker_error(run, monkeypatch):
    def broken(analysis):
        raise RuntimeError("rule blew up")

    monkeypatch.setattr(rules, "RULES", [Rule("syntax", RULES[0].run), Rule("broken", broken)])
    result = run(GOOD)
    assert result.status == "checker_error"
    assert result.findings == ()
    assert "rule blew up" in result.error


def test_exception_while_parsing_gives_checker_error(run):
    # Nesting deep enough to exhaust Python's recursion limit.
    result = run("x = " + "(" * 20000 + "1" + ")" * 20000 + ";")
    assert result.status == "checker_error"
    assert result.error


def test_checker_error_is_never_passed(catalog, monkeypatch):
    def broken(analysis):
        raise ValueError("boom")

    monkeypatch.setattr(rules, "RULES", [Rule("broken", broken)])
    result = check("", catalog, Context(timeframe="daily"))
    assert result.status == "checker_error"


def test_context_knows_intraday_timeframes():
    assert Context(timeframe="5min").is_intraday
    assert Context(timeframe="hourly").is_intraday
    assert not Context(timeframe="daily").is_intraday
    assert not Context(timeframe="weekly").is_intraday


def test_context_rejects_an_unknown_timeframe():
    with pytest.raises(ValueError, match="timeframe"):
        Context(timeframe="5m")


# No AI and no network

ALLOWED_IMPORTS = {"re", "dataclasses", "difflib", "collections", "typing", "copilot"}


def test_checker_source_imports_only_plain_python():
    imported = set()
    for path in CHECKER_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module.split(".")[0])
    assert imported <= ALLOWED_IMPORTS


def test_importing_the_checker_loads_no_network_or_openai_module():
    code = (
        "import sys, copilot.checker\n"
        "bad = [m for m in ('openai', 'httpx', 'requests', 'aiohttp', 'urllib.request',"
        " 'http.client', 'urllib3') if m in sys.modules]\n"
        "print(bad)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        cwd=CHECKER_DIR.parents[1],
    )
    assert out.stdout.strip() == "[]"
