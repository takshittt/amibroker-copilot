"""Runs the rules over a piece of AFL and reports the result."""

from copilot.checker import rules
from copilot.checker.findings import Check, CheckResult, Context, Finding
from copilot.checker.lexer import LexError, tokenize
from copilot.checker.parser import (
    Call,
    Program,
    SyntaxProblem,
    bracket_problems,
    parse,
    walk,
)
from copilot.checker.symbols import Analysis
from copilot.kb import Catalog

_FAILING = ("critical", "warning")


def check(source: str, catalog: Catalog, context: Context) -> CheckResult:
    """Checks `source` against every rule. Never raises and never executes AFL.

    If the checker itself breaks, the status is `checker_error`, never
    `passed`: code must not be shown as checked when it was not.
    """
    try:
        return _check(source, catalog, context)
    except Exception as error:  # noqa: BLE001 (any failure must become checker_error)
        return CheckResult(
            status="checker_error",
            findings=(),
            checks=(),
            error=f"{type(error).__name__}: {error}",
        )


def _check(source: str, catalog: Catalog, context: Context) -> CheckResult:
    program = Program()
    try:
        tokens = tokenize(source)
    except LexError as error:
        closing = "never closed" in error.message
        hint = "Close it before the end of the file." if closing else "Remove that character."
        problems = [SyntaxProblem(error.message, error.line, hint)]
    else:
        program = parse(tokens)
        # An unbalanced bracket explains whatever the parser then trips over.
        problems = bracket_problems(tokens) or program.problems

    analysis = Analysis(program, catalog, context, problems)
    order = {rule.id: position for position, rule in enumerate(rules.RULES)}
    findings: list[Finding] = []
    checks: list[Check] = []
    for rule in rules.RULES:
        # The other rules would be judging code that was only partly read.
        if problems and rule.id != "syntax":
            checks.append(Check(rule.id, "skipped"))
            continue
        found = rule.run(analysis)
        findings.extend(found)
        checks.append(Check(rule.id, "failed" if found else "passed"))

    findings.sort(key=lambda finding: (finding.line, order.get(finding.rule, 0)))
    failed = any(finding.severity in _FAILING for finding in findings)
    return CheckResult(
        status="failed" if failed else "passed",
        findings=tuple(findings),
        checks=tuple(checks),
    )


def called_functions(source: str) -> list[str]:
    """The names called in `source`, each once, in the order first met.

    Returns an empty list for code that cannot be read. This reads the
    code; it does not judge it.
    """
    try:
        program = parse(tokenize(source))
    except (LexError, RecursionError):
        return []
    names: dict[str, str] = {}  # lower-case name -> the name as first written
    for node in walk(program.body):
        if isinstance(node, Call) and node.name:
            names.setdefault(node.name.lower(), node.name)
    return list(names.values())
