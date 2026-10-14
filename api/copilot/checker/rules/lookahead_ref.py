"""Critical: `Ref(x, n)` with a positive `n` feeding a trade signal.

A positive period reads future bars, so the backtest trades on prices
it could not have known. A positive Ref that is only plotted is fine.
"""

from copilot.checker.findings import Finding
from copilot.checker.parser import Call
from copilot.checker.symbols import SIGNAL_LABEL, SIGNALS, Analysis

RULE = "lookahead_ref"


def run(analysis: Analysis) -> list[Finding]:
    findings = []
    reported: set[int] = set()
    for signal in SIGNALS:
        for node in analysis.reachable_from(signal):
            if not (isinstance(node, Call) and node.name and node.name.lower() == "ref"):
                continue
            if len(node.args) != 2 or id(node) in reported:
                continue
            period = analysis.const_value(node.args[1])
            if period is None or period <= 0:
                continue
            reported.add(id(node))
            findings.append(
                Finding(
                    RULE,
                    "critical",
                    node.line,
                    f"Ref with a positive period ({period:g}) reads future bars, and "
                    f"{SIGNAL_LABEL[signal]} depends on it. The backtest would use prices "
                    "that were not known yet.",
                    "Use a negative period to read earlier bars, for example Ref(x, -1).",
                )
            )
    return findings
