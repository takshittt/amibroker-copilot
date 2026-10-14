"""Critical: `if`, `while` or `for` whose condition is an array.

A condition must be one number. It fires only when the type guess is
sure the value is an array; an unknown type is left to the AI review.
"""

from copilot.checker.findings import Finding
from copilot.checker.parser import DoWhile, For, If
from copilot.checker.symbols import Analysis

RULE = "if_on_array"


def run(analysis: Analysis) -> list[Finding]:
    findings = []
    for statement, condition in analysis.conditions:
        if analysis.type_of(condition, analysis.shadow(condition)) != "array":
            continue
        if isinstance(statement, If):
            word = "if"
        elif isinstance(statement, For):
            word = "for"
        else:
            word = "while"
        line = condition.line if isinstance(statement, DoWhile) else statement.line
        findings.append(
            Finding(
                RULE,
                "critical",
                line,
                f"The condition of this '{word}' is an array (one value for each bar), "
                f"but '{word}' needs a single number.",
                "Use IIf to choose bar by bar, or take one bar with LastValue or [i] in a loop.",
            )
        )
    return findings
