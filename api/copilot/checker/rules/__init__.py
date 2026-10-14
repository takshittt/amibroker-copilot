"""The checker's rules. Each rule is one function in its own file.

A rule takes the Analysis of a piece of code and returns its findings.
The ids are fixed: the mistake catalogue refers to them.
"""

from collections.abc import Callable
from dataclasses import dataclass

from copilot.checker.findings import Finding
from copilot.checker.rules import (
    arg_count,
    eod_exit,
    exrem,
    hardcoded_times,
    if_on_array,
    intrabar_stop_price,
    lookahead_ref,
    syntax,
    trade_delays,
    unknown_function,
)
from copilot.checker.symbols import Analysis


@dataclass(frozen=True)
class Rule:
    id: str
    run: Callable[[Analysis], list[Finding]]


# Critical rules first, then Warnings, then the Tip.
RULES: list[Rule] = [
    Rule("syntax", syntax.run),
    Rule("unknown_function", unknown_function.run),
    Rule("arg_count", arg_count.run),
    Rule("if_on_array", if_on_array.run),
    Rule("lookahead_ref", lookahead_ref.run),
    Rule("eod_exit", eod_exit.run),
    Rule("intrabar_stop_price", intrabar_stop_price.run),
    Rule("trade_delays", trade_delays.run),
    Rule("exrem", exrem.run),
    Rule("hardcoded_times", hardcoded_times.run),
]
