"""Fix-from-error: the user pastes code and the error AmiBroker gave.

The error text is read for its number and position, matched against our
own notes on AmiBroker's errors, and the code is corrected and checked.
We never run AFL, so the fix is checked by the checker but not compiled.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from copilot.checker import check
from copilot.pipeline.brief import wrap_block
from copilot.pipeline.orchestrator import Deps
from copilot.pipeline.retrieve import hit_item
from copilot.pipeline.review import check_input, review_items, verified_findings
from copilot.pipeline.rewrite import FixResult, fix_code
from copilot.pipeline.tracking import Tracker
from copilot.search import error_note

NOT_COMPILED_NOTE = (
    "This fix was checked by our checker but has not been run in AmiBroker. If AmiBroker "
    "reports another error, paste it here."
)
NO_NUMBER_NOTE = (
    "No error number was found in the text you pasted, so the fix is based on the "
    "message as written."
)

_NUMBER = re.compile(r"\b(error|warning)\s*#?\s*(\d{1,4})\b", re.IGNORECASE)
_LINE = re.compile(r"\b(?:ln|line)\b\s*[:#]?\s*(\d+)", re.IGNORECASE)
_COLUMN = re.compile(r"\b(?:col|column)\b\s*[:#]?\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedError:
    number: int | None = None
    is_warning: bool = False
    line: int | None = None
    column: int | None = None


def parse_error(text: str) -> ParsedError:
    """Reads the error number, line and column out of AmiBroker's message,
    in whichever of its layouts the user copied."""
    number = _NUMBER.search(text)
    line = _LINE.search(text)
    column = _COLUMN.search(text)
    return ParsedError(
        number=int(number.group(2)) if number else None,
        is_warning=bool(number) and number.group(1).lower() == "warning",
        line=int(line.group(1)) if line else None,
        column=int(column.group(1)) if column else None,
    )


@dataclass(frozen=True)
class FixErrorRequest:
    code: str
    error_text: str
    market_id: str
    timeframe: str


def run_fix_error(
    request: FixErrorRequest,
    deps: Deps,
    on_progress: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> FixResult:
    tracker = Tracker(deps.settings, deps.catalog, deps.embedder)

    def refuse(message: str) -> FixResult:
        return FixResult(status="error", run=tracker.record(), message=message)

    context = check_input(request.code, request.market_id, request.timeframe, deps)
    if isinstance(context, str):
        return refuse(context)
    error_text = request.error_text.strip()
    if not error_text:
        return refuse("Paste the error message AmiBroker showed.")
    if len(error_text) > deps.settings.max_error_chars:
        return refuse(
            f"That error text is too long ({len(error_text)} characters). "
            f"The limit is {deps.settings.max_error_chars}."
        )

    code = request.code.replace("\r\n", "\n")
    parsed = parse_error(error_text)
    line_count = len(code.rstrip("\n").split("\n"))
    line = parsed.line if parsed.line and parsed.line <= line_count else None

    # What the checker sees in the code often pinpoints the same mistake.
    verified = verified_findings(check(code, deps.catalog, context))
    rules = tuple(dict.fromkeys(finding.rule for finding in verified))
    items = review_items(deps, code, context, rules)

    kind = "warning" if parsed.is_warning else "error"
    where = f" at line {line}" if line else ""
    where += f", column {parsed.column}" if line and parsed.column else ""
    notes = [NOT_COMPILED_NOTE]
    if parsed.number is None:
        described = f"AmiBroker reported a problem{where}. Its message is in the block above."
        notes.append(NO_NUMBER_NOTE)
    else:
        described = f"AmiBroker reported {kind} {parsed.number}{where}."
        note = error_note(deps.conn, parsed.number)
        if note is not None:
            items.insert(0, hit_item(note, pinned=True))
            described += f" What that means and how to fix it: {note.title}. {note.content}"
        else:
            described += " Its message is in the block above."

    problems = [described, *(finding.text for finding in verified)]
    return fix_code(
        deps,
        tracker,
        code,
        context,
        problems,
        items,
        extra=wrap_block("amibroker_error", error_text),
        notes=tuple(notes),
        on_progress=on_progress,
        should_stop=should_stop,
    )
