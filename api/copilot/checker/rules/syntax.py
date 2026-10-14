"""Critical: brackets, semicolons, and `=` where a comparison is meant."""

from copilot.checker.findings import Finding
from copilot.checker.parser import AssignExpr, Node, walk
from copilot.checker.symbols import Analysis

RULE = "syntax"
_DEFAULT_HINT = "Check this line for a missing or extra symbol."


def _assignment_in(condition: Node) -> AssignExpr | None:
    for node in walk(condition):
        if isinstance(node, AssignExpr) and node.op == "=":
            return node
    return None


def run(analysis: Analysis) -> list[Finding]:
    findings = [
        Finding(RULE, "critical", problem.line, problem.message, problem.fix_hint or _DEFAULT_HINT)
        for problem in analysis.syntax_problems
    ]

    conditions = [(condition, "this condition") for _, condition in analysis.conditions]
    conditions += [
        (call.args[0], "the condition of IIf") for call in analysis.calls_named("IIf") if call.args
    ]
    for condition, where in conditions:
        assignment = _assignment_in(condition)
        if assignment is not None:
            findings.append(
                Finding(
                    RULE,
                    "critical",
                    assignment.line,
                    f"'=' in {where} assigns a value; it does not compare.",
                    "Use == to compare two values.",
                )
            )
    return findings
