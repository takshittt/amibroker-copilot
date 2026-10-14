"""Warning: an intraday strategy with no end-of-day exit.

On an intraday timeframe every side that is entered needs an exit that
depends on the time of day, or positions are carried overnight. A market
that trades all day, every day, has no close to exit before, so the rule
does not apply there.
"""

from copilot.checker.findings import Finding
from copilot.checker.parser import Call
from copilot.checker.symbols import SIGNAL_LABEL, Analysis

RULE = "eod_exit"
_SIDES = (("buy", "sell", "long"), ("short", "cover", "short"))


def _uses_time_of_day(analysis: Analysis, signal: str) -> bool:
    return any(
        isinstance(node, Call) and node.name and node.name.lower() == "timenum"
        for node in analysis.reachable_from(signal)
    )


def run(analysis: Analysis) -> list[Finding]:
    if not analysis.context.is_intraday:
        return []
    market_id = analysis.context.market_id
    market = analysis.catalog.market(market_id) if market_id else None
    if market is not None and market.never_closes:
        return []
    findings = []
    for entry, exit_, side in _SIDES:
        if not analysis.is_assigned(entry) or _uses_time_of_day(analysis, exit_):
            continue
        findings.append(
            Finding(
                RULE,
                "warning",
                analysis.first_line(entry),
                f"This is an intraday strategy, but {SIGNAL_LABEL[exit_]} never depends on the "
                f"time of day, so {side} positions can be carried overnight.",
                f"Add an end-of-day exit to {SIGNAL_LABEL[exit_]}, for example "
                "'OR TimeNum() >= ExitTime', with ExitTime as a parameter at the top.",
            )
        )
    return findings
