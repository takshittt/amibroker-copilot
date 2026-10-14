"""Critical: a call to a function that is not in the AFL function list.

When the code has an #include, the function may be defined in a file the
checker cannot read, so the finding is a Warning instead.
"""

from difflib import get_close_matches

from copilot.checker.findings import Finding
from copilot.checker.symbols import Analysis

RULE = "unknown_function"


def run(analysis: Analysis) -> list[Finding]:
    known = {key: function.name for key, function in analysis.catalog.functions.items()}
    known.update({key: function.name for key, function in analysis.functions.items()})

    findings = []
    for call in analysis.calls:
        if call.name.lower() in known:
            continue
        if analysis.has_include:
            findings.append(
                Finding(
                    RULE,
                    "warning",
                    call.line,
                    f"{call.name} is not in the AFL function list. It may be defined in an "
                    "#include file, which the checker cannot read.",
                    f"Check that an included file defines {call.name}.",
                )
            )
            continue
        close = get_close_matches(call.name.lower(), list(known), n=1, cutoff=0.75)
        hint = (
            f"Did you mean {known[close[0]]}?"
            if close
            else "Use a function from the AFL function list, or define it with "
            "'function' above this line."
        )
        findings.append(
            Finding(RULE, "critical", call.line, f"{call.name} is not an AFL function.", hint)
        )
    return findings
