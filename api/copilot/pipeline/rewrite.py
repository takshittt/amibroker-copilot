"""Correcting existing code: "apply all fixes" in Review, and Fix-from-error.

The model rewrites the code, the checker looks at the result, and what
the checker still finds goes back to the model, up to the attempt limit.
The rewritten code is "checked" only if the checker passes it.
"""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator

from copilot.checker import Context, called_functions, check
from copilot.pipeline import prompts
from copilot.pipeline.brief import wrap_block
from copilot.pipeline.generate import numbered
from copilot.pipeline.llm import LLMError, ask
from copilot.pipeline.orchestrator import (
    ERROR_MESSAGES,
    Cancelled,
    CheckLine,
    Deps,
    Problem,
    checker_problems,
    doc_links_for,
)
from copilot.pipeline.retrieve import Item, allowed_function_names
from copilot.pipeline.review import (
    AI_SUGGESTED,
    ReviewFinding,
    check_input,
    notes_block,
    review_items,
)
from copilot.pipeline.tracking import RunRecord, Tracker

AI_FIXES_NOTE = (
    "Some of these fixes were AI-suggested. The checker cannot confirm that those "
    "changes are right, so read them before you rely on the code."
)

REWRITE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "code": {"type": "string"},
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"line": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["line", "text"],
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["code", "changes", "notes"],
}


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    line: int = Field(ge=0)
    text: str


class Rewrite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str
    changes: tuple[Change, ...]
    notes: tuple[str, ...]

    @field_validator("code")
    @classmethod
    def _code_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("code must not be empty")
        return value.replace("\r\n", "\n")


@dataclass(frozen=True)
class FixResult:
    # checked: the checker passes the corrected code.
    # not_fully_checked: it still fails after the last attempt; `problems` lists what.
    # not_checked: the checker itself broke on the corrected code.
    # error: no corrected code; see `message`.
    status: str
    run: RunRecord
    code: str = ""
    changes: tuple[Change, ...] = ()
    checks: tuple[CheckLine, ...] = ()
    problems: tuple[Problem, ...] = ()
    doc_links: tuple[tuple[str, str], ...] = ()
    notes: tuple[str, ...] = ()
    message: str = ""


@dataclass(frozen=True)
class ApplyRequest:
    code: str
    market_id: str
    timeframe: str
    findings: tuple[ReviewFinding, ...]


def fix_code(
    deps: Deps,
    tracker: Tracker,
    code: str,
    context: Context,
    problems: list[str],
    items: list[Item],
    extra: str = "",
    notes: tuple[str, ...] = (),
    on_progress: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> FixResult:
    """Rewrites `code` to fix `problems`, checking each attempt.

    `extra` is more text for the prompt, such as a wrapped error message.
    """
    settings = deps.settings

    def progress(stage: str) -> None:
        if should_stop is not None and should_stop():
            raise Cancelled
        if on_progress is not None:
            on_progress(stage)

    already_used = [r.name for r in map(deps.catalog.function, called_functions(code)) if r]
    names = sorted({*allowed_function_names(deps.catalog), *already_used}, key=str.lower)
    tracker.given.update(dict.fromkeys(item.key for item in items))

    current = code
    to_fix = list(problems)
    rewrite: Rewrite | None = None
    remaining: list[Problem] = []
    panel: list[CheckLine] = []
    try:
        for attempt in range(1, settings.max_attempts + 1):
            progress("fixing" if attempt == 1 else f"fixing attempt {attempt}")
            parts = [notes_block(items), "Function names you may use:\n" + ", ".join(names)]
            if extra:
                parts.append(extra)
            parts.append(wrap_block("pasted_code", numbered(current)))
            parts.append("Problems to fix:\n" + "\n".join(f"- {problem}" for problem in to_fix))
            rewrite = ask(
                deps.llm,
                tracker.meter,
                model=settings.strong_model or "",
                system=prompts.REWRITE_SYSTEM,
                user="\n\n".join(parts),
                schema_name="rewrite",
                schema=REWRITE_SCHEMA,
                parse=Rewrite.model_validate,
                max_output_tokens=settings.max_output_tokens,
            )

            progress("checking")
            result = check(rewrite.code, deps.catalog, context)
            if result.status == "checker_error":
                tracker.attempt(("checker_error",), 1)
                crash = Problem("checker", "checker_error", "The checker could not read this code.")
                return _result("not_checked", tracker, deps, rewrite, [], [crash], notes)
            panel = [CheckLine(entry.rule, entry.outcome) for entry in result.checks]
            found = checker_problems(result)
            # A Tip does not fail pasted code, but it is passed on.
            remaining = [p for p in found if p.severity != "tip"]
            tips = tuple(
                f"The checker also suggests: {p.text}" for p in found if p.severity == "tip"
            )
            tracker.attempt(tuple(dict.fromkeys(p.rule for p in remaining)), len(remaining))
            if not remaining:
                return _result("checked", tracker, deps, rewrite, panel, [], (*notes, *tips))
            current = rewrite.code
            to_fix = [problem.text for problem in remaining]
    except LLMError as error:
        return FixResult(status="error", run=tracker.record(), message=ERROR_MESSAGES[error.kind])
    except Cancelled:
        return FixResult(status="cancelled", run=tracker.record())

    assert rewrite is not None
    return _result("not_fully_checked", tracker, deps, rewrite, panel, remaining, notes)


def _result(
    status: str,
    tracker: Tracker,
    deps: Deps,
    rewrite: Rewrite,
    panel: list[CheckLine],
    problems: list[Problem],
    notes: tuple[str, ...],
) -> FixResult:
    last = len(rewrite.code.rstrip("\n").split("\n"))
    return FixResult(
        status=status,
        run=tracker.record(),
        code=rewrite.code,
        changes=tuple(change for change in rewrite.changes if change.line <= last),
        checks=tuple(panel),
        problems=tuple(problems),
        doc_links=doc_links_for(rewrite.code, deps.catalog),
        notes=tuple(dict.fromkeys([*notes, *rewrite.notes])),
    )


def run_apply_fixes(
    request: ApplyRequest,
    deps: Deps,
    on_progress: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> FixResult:
    """Review's "apply all fixes": rewrites the code to fix the given findings."""
    tracker = Tracker(deps.settings, deps.catalog, deps.embedder)
    context = check_input(request.code, request.market_id, request.timeframe, deps)
    if isinstance(context, str):
        return FixResult(status="error", run=tracker.record(), message=context)
    if not request.findings:
        return FixResult(status="error", run=tracker.record(), message="There is nothing to fix.")

    code = request.code.replace("\r\n", "\n")
    rules = tuple(dict.fromkeys(f.rule for f in request.findings if f.rule != "ai_review"))
    items = review_items(deps, code, context, rules)
    notes = (AI_FIXES_NOTE,) if any(f.label == AI_SUGGESTED for f in request.findings) else ()
    return fix_code(
        deps,
        tracker,
        code,
        context,
        [finding.text for finding in request.findings],
        items,
        notes=notes,
        on_progress=on_progress,
        should_stop=should_stop,
    )
