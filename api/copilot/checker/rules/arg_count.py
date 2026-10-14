"""Critical: a function called with too few or too many arguments."""

from copilot.checker.findings import Finding
from copilot.checker.symbols import Analysis

RULE = "arg_count"


def _describe(low: int, high: int | None) -> str:
    if high is None:
        return f"at least {low} argument{'' if low == 1 else 's'}"
    if high == 0:
        return "no arguments"
    if low == high:
        return f"{low} argument{'' if low == 1 else 's'}"
    return f"{low} to {high} arguments"


def run(analysis: Analysis) -> list[Finding]:
    findings = []
    for call in analysis.calls:
        written = analysis.functions.get(call.name.lower())
        listed = analysis.catalog.function(call.name)
        if written is not None:
            name, low, high = written.name, len(written.params), len(written.params)
        elif listed is not None:
            name, low, high = listed.name, listed.min_args, listed.max_args
        else:
            continue  # unknown_function reports it
        given = len(call.args)
        if given >= low and (high is None or given <= high):
            continue
        findings.append(
            Finding(
                RULE,
                "critical",
                call.line,
                f"{name} takes {_describe(low, high)} but is called with {given}.",
                f"Call {name} with {_describe(low, high)}.",
            )
        )
    return findings
