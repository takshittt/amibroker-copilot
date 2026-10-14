"""Warning: a signal triggered inside the bar, with no matching trade price.

`Sell = Low < StopLevel` says the stop was hit during the bar. Unless
SellPrice is set, the backtest fills at its default price and not at the
stop level, which makes results look better or worse than they would be.
"""

from copilot.checker.findings import Finding
from copilot.checker.parser import Binary, Call, Name, Node
from copilot.checker.symbols import PRICE_OF, SIGNAL_LABEL, SIGNALS, Analysis

RULE = "intrabar_stop_price"

# Entries on a buy stop and short covers trigger when High rises to a level;
# short entries and long exits trigger when Low falls to one.
_TRIGGER = {"buy": "high", "cover": "high", "sell": "low", "short": "low"}


def _sides(node: Node) -> tuple[Node, Node] | None:
    """Returns (greater, lesser) for a comparison or a Cross, else None."""
    if isinstance(node, Binary):
        if node.op in (">", ">="):
            return node.left, node.right
        if node.op in ("<", "<="):
            return node.right, node.left
    if isinstance(node, Call) and node.name and node.name.lower() == "cross":
        if len(node.args) == 2:
            return node.args[0], node.args[1]
    return None


def run(analysis: Analysis) -> list[Finding]:
    findings = []
    for signal in SIGNALS:
        price = PRICE_OF[signal]
        if analysis.is_assigned(price):
            continue
        trigger = _TRIGGER[signal]
        for node in analysis.reachable_from(signal):
            sides = _sides(node)
            if sides is None:
                continue
            operand = sides[0] if trigger == "high" else sides[1]
            if not (isinstance(operand, Name) and analysis.canonical(operand.name) == trigger):
                continue
            findings.append(
                Finding(
                    RULE,
                    "warning",
                    node.line,
                    f"{SIGNAL_LABEL[signal]} triggers when {trigger.capitalize()} reaches a "
                    f"level inside the bar, but {price} is not set, so the backtest does not "
                    "fill at that level.",
                    f"Set {price} to the level that was reached.",
                )
            )
            break
    return findings
