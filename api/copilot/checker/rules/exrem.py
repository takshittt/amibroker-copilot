"""Warning: signals shown on a chart or in an exploration without ExRem.

A raw signal stays true on every bar its condition holds. The backtester
copes with that, but arrows and exploration rows repeat on every such bar.
So the rule fires only where a signal is plotted with PlotShapes, listed
with AddColumn, or used in Filter.
"""

from copilot.checker.findings import Finding
from copilot.checker.parser import Name, Node
from copilot.checker.symbols import SIGNAL_LABEL, SIGNALS, Analysis

RULE = "exrem"
_PARTNER = {"buy": "sell", "sell": "buy", "short": "cover", "cover": "short"}


def _is_cleaned(analysis: Analysis, signal: str) -> bool:
    for call in analysis.calls_named("ExRem"):
        if len(call.args) != 2:
            continue
        first, second = call.args
        if isinstance(first, Name) and isinstance(second, Name):
            if (first.name.lower(), second.name.lower()) == (signal, _PARTNER[signal]):
                return True
    return False


def run(analysis: Analysis) -> list[Finding]:
    shown: list[tuple[int, str, Node]] = []
    for call in analysis.calls:
        if call.name.lower() in ("plotshapes", "addcolumn") and call.args:
            shown.append((call.line, call.name, call.args[0]))
    for assignment in analysis.assignments.get("filter", []):
        shown.append((assignment.line, "Filter", assignment.node.value))

    findings = []
    reported: set[str] = set()
    for line, where, expr in sorted(shown, key=lambda item: item[0]):
        for node in analysis.reachable([expr], stop=frozenset(SIGNALS)):
            if not isinstance(node, Name) or node.name.lower() not in SIGNALS:
                continue
            signal = node.name.lower()
            partner = _PARTNER[signal]
            if signal in reported or _is_cleaned(analysis, signal):
                continue
            if not (analysis.is_assigned(signal) and analysis.is_assigned(partner)):
                continue
            reported.add(signal)
            label, other = SIGNAL_LABEL[signal], SIGNAL_LABEL[partner]
            findings.append(
                Finding(
                    RULE,
                    "warning",
                    line,
                    f"{label} is used in {where} without ExRem, so it repeats on every bar "
                    "its condition holds instead of once for each trade.",
                    f"Add {label} = ExRem({label}, {other}); before this line.",
                )
            )
    return findings
