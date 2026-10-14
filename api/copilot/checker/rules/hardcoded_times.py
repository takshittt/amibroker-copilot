"""Tip: a session time written as a number inside the logic.

`TimeNum() >= 151500` works, but the time is buried. A parameter or a
variable at the top is easier to find and change for another market.
"""

from copilot.checker.findings import Finding
from copilot.checker.parser import Binary, Call, Name, Node, Num
from copilot.checker.symbols import COMPARISONS, Analysis

RULE = "hardcoded_times"


def _is_time_of_day(analysis: Analysis, expr: Node, depth: int = 0) -> bool:
    if isinstance(expr, Call):
        return bool(expr.name) and expr.name.lower() == "timenum"
    if isinstance(expr, Name) and depth < 5:
        return any(
            _is_time_of_day(analysis, value, depth + 1) for value in analysis.values_of(expr.name)
        )
    return False


def run(analysis: Analysis) -> list[Finding]:
    findings = []
    lines: set[int] = set()
    for node in analysis.nodes:
        if isinstance(node, Binary) and node.op in COMPARISONS:
            pair = (node.left, node.right)
        elif isinstance(node, Call) and node.name and node.name.lower() == "cross":
            if len(node.args) != 2:
                continue
            pair = (node.args[0], node.args[1])
        else:
            continue
        for time_side, other in (pair, pair[::-1]):
            if not isinstance(other, Num) or not _is_time_of_day(analysis, time_side):
                continue
            if node.line in lines:
                continue
            lines.add(node.line)
            findings.append(
                Finding(
                    RULE,
                    "tip",
                    node.line,
                    f"The time {other.value:g} is written inside the logic.",
                    "Put it in a parameter or a variable at the top, for example "
                    'ExitTime = ParamTime("Exit time", "15:15");',
                )
            )
    return findings
