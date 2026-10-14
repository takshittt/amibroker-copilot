"""Warning: SetTradeDelays missing, set twice differently, or at odds with prices.

Without SetTradeDelays the backtest uses whatever the Settings window
holds, so the same code gives different results on different machines.
"""

from copilot.checker.findings import Finding
from copilot.checker.parser import Call, Name
from copilot.checker.symbols import PRICE_OF, SIGNAL_LABEL, SIGNALS, Analysis

RULE = "trade_delays"


def _is_lagged(analysis: Analysis, signal: str) -> bool:
    """True when the signal reads earlier bars with Ref, so it is known at the open."""
    for node in analysis.reachable_from(signal):
        if isinstance(node, Call) and node.name and node.name.lower() == "ref":
            if len(node.args) == 2:
                period = analysis.const_value(node.args[1])
                if period is not None and period < 0:
                    return True
    return False


def run(analysis: Analysis) -> list[Finding]:
    assigned = [signal for signal in SIGNALS if analysis.is_assigned(signal)]
    if not assigned:
        return []

    calls = analysis.calls_named("SetTradeDelays")
    if not calls:
        return [
            Finding(
                RULE,
                "warning",
                analysis.first_line(assigned[0]),
                "SetTradeDelays is not called, so the backtest takes its trade delays from "
                "the Settings window and results change from one setup to another.",
                "Add SetTradeDelays at the top, for example SetTradeDelays(1, 1, 1, 1) to "
                "trade on the bar after the signal.",
            )
        ]

    findings = []
    first = [analysis.const_value(arg) for arg in calls[0].args]
    for call in calls[1:]:
        if [analysis.const_value(arg) for arg in call.args] != first:
            findings.append(
                Finding(
                    RULE,
                    "warning",
                    call.line,
                    f"SetTradeDelays is called again with different delays than on line "
                    f"{calls[0].line}. Only the last call takes effect.",
                    "Keep one SetTradeDelays call at the top.",
                )
            )

    # Delay 0 means the trade happens on the signal bar. Filling at that bar's
    # Open uses a price from before the signal could be known.
    delays = [analysis.const_value(arg) for arg in calls[-1].args]
    if len(delays) != 4:
        return findings  # arg_count reports it
    for signal, delay in zip(SIGNALS, delays, strict=True):
        if delay != 0 or not analysis.is_assigned(signal) or _is_lagged(analysis, signal):
            continue
        price = PRICE_OF[signal]
        for assignment in analysis.assignments.get(price.lower(), []):
            value = assignment.node.value
            if isinstance(value, Name) and analysis.canonical(value.name) == "open":
                findings.append(
                    Finding(
                        RULE,
                        "warning",
                        assignment.line,
                        f"{price} is Open while the {SIGNAL_LABEL[signal]} delay is 0, so the "
                        "trade fills at the open of the bar whose data produced the signal.",
                        f"Use a delay of 1 with {price} = Open, or keep the delay at 0 and "
                        f"set {price} = Close.",
                    )
                )
                break
    return findings
