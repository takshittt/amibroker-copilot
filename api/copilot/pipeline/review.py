"""Review mode: the checker's findings, then the model's.

Checker findings are labelled Verified: they are certain. The model's
are labelled AI-suggested. The two are never mixed, and a review never
says that code is correct.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from copilot.checker import CheckResult, Context, called_functions, check
from copilot.config import Settings
from copilot.pipeline import prompts
from copilot.pipeline.brief import wrap_block
from copilot.pipeline.generate import numbered
from copilot.pipeline.llm import LLMError, ask
from copilot.pipeline.orchestrator import Cancelled, CheckLine, Deps
from copilot.pipeline.retrieve import Item, function_item, hit_item, market_item, search_queries
from copilot.pipeline.tracking import RunRecord, Tracker
from copilot.search import chunks_with_tags, mistakes_without_rule

VERIFIED = "Verified"
AI_SUGGESTED = "AI-suggested"

_SIGNAL = re.compile(r"\b(buy|sell|short|cover)\s*(\[[^\]]*\]\s*)?=(?!=)", re.IGNORECASE)
_MAX_FUNCTION_ITEMS = 25
_FROM_SEARCH = 5
CHECKER_FAILED_NOTE = (
    "The checker could not run on this code, so there are no Verified findings. "
    "That does not mean the code is correct."
)
AI_FAILED_NOTE = "The AI review could not be completed, so only the checker's findings are shown."

REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "severity": {"type": "string", "enum": ["critical", "warning", "tip"]},
                    "line": {"type": "integer"},
                    "problem": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["severity", "line", "problem", "fix"],
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["findings", "summary"],
}


class _AIFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["critical", "warning", "tip"]
    line: int
    problem: str
    fix: str


class _AIReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    findings: list[_AIFinding]
    summary: str


@dataclass(frozen=True)
class ReviewRequest:
    code: str
    market_id: str
    timeframe: str


@dataclass(frozen=True)
class ReviewFinding:
    label: str  # Verified or AI-suggested
    severity: str
    line: int | None
    message: str
    fix: str
    rule: str  # the checker rule, or "ai_review"

    @property
    def text(self) -> str:
        where = f"line {self.line}: " if self.line else ""
        fix = f" Fix: {self.fix}" if self.fix else ""
        return f"[{self.label}] {where}{self.message}{fix}"


@dataclass(frozen=True)
class ReviewResult:
    # reviewed: findings are listed (possibly none). error: no review; see message.
    status: str
    run: RunRecord
    findings: tuple[ReviewFinding, ...] = ()
    checks: tuple[CheckLine, ...] = ()
    checker_status: str = ""  # passed, failed or checker_error
    ai_review: str = ""  # done or failed
    summary: str = ""
    notes: tuple[str, ...] = ()
    message: str = ""


def check_input(code: str, market_id: str, timeframe: str, deps: Deps) -> Context | str:
    """Returns the checker context, or the reason the request is refused."""
    if not code.strip():
        return "Paste the AFL code you want looked at."
    size = len(code.encode("utf-8"))
    if size > deps.settings.max_code_bytes:
        return f"That code is too long ({size} bytes). The limit is {deps.settings.max_code_bytes}."
    market = deps.catalog.market(market_id)
    if market is None:
        return f"Unknown market {market_id!r}."
    try:
        return Context(timeframe=timeframe, market_id=market.id)
    except ValueError as error:
        return str(error)


def verified_findings(result: CheckResult) -> list[ReviewFinding]:
    return [
        ReviewFinding(VERIFIED, f.severity, f.line, f.message, f.fix_hint, f.rule)
        for f in result.findings
    ]


def review_items(
    deps: Deps, code: str, context: Context, failed_rules: tuple[str, ...]
) -> list[Item]:
    """What the model is shown beside the code. Nothing here is reranked:
    the set is small and every part is there for a reason."""
    catalog = deps.catalog
    items: dict[tuple[str, str], Item] = {}

    def add(item: Item) -> None:
        items.setdefault(item.key, item)

    market = catalog.market(context.market_id or "")
    if market is not None:
        add(market_item(market))

    names = called_functions(code)
    known = [catalog.function(name) for name in names]
    for record in [r for r in known if r is not None][:_MAX_FUNCTION_ITEMS]:
        add(function_item(record, pinned=True))

    tags = [f"rule-{rule}" for rule in failed_rules]
    if _SIGNAL.search(code):
        tags.append("backtest")
        if context.is_intraday:
            tags.append("intraday")
    for hit in chunks_with_tags(deps.conn, "mistake", tags):
        add(hit_item(hit, pinned=True))
    for hit in mistakes_without_rule(deps.conn):
        add(hit_item(hit, pinned=True))

    if names:
        query = " ".join(names[:40])
        found = search_queries(
            deps.conn, deps.embedder, [query], deps.settings, kinds=["mistake", "concept"]
        )
        for hit in found[:_FROM_SEARCH]:
            add(hit_item(hit, pinned=True))
    return list(items.values())


def notes_block(items: list[Item]) -> str:
    return "Reference notes:\n\n" + "\n\n".join(
        f"### {item.kind}: {item.title}\n{item.content}" for item in items
    )


def _ai_findings(review: _AIReview, line_count: int, settings: Settings) -> list[ReviewFinding]:
    findings = []
    for found in review.findings:
        problem = found.problem.strip()
        if not problem:
            continue
        line = found.line if 1 <= found.line <= line_count else None
        findings.append(
            ReviewFinding(
                AI_SUGGESTED, found.severity, line, problem, found.fix.strip(), "ai_review"
            )
        )
    return findings[: settings.max_ai_findings]


def run_review(
    request: ReviewRequest,
    deps: Deps,
    on_progress: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> ReviewResult:
    """Checks the code, then asks the model for what the checker cannot see.

    If the model fails, the checker's findings are still returned.
    """
    tracker = Tracker(deps.settings, deps.catalog, deps.embedder)

    def progress(stage: str) -> None:
        if should_stop is not None and should_stop():
            raise Cancelled
        if on_progress is not None:
            on_progress(stage)

    context = check_input(request.code, request.market_id, request.timeframe, deps)
    if isinstance(context, str):
        return ReviewResult(status="error", run=tracker.record(), message=context)
    code = request.code.replace("\r\n", "\n")

    try:
        progress("checking")
        result = check(code, deps.catalog, context)
        verified = verified_findings(result)
        notes = [CHECKER_FAILED_NOTE] if result.status == "checker_error" else []
        failed_rules = tuple(dict.fromkeys(f.rule for f in verified))

        progress("searching")
        items = review_items(deps, code, context, failed_rules)
        tracker.given.update(dict.fromkeys(item.key for item in items))

        progress("reviewing")
        already = "\n".join(f"- {finding.text}" for finding in verified) or "- none"
        user = "\n\n".join(
            [
                f"Timeframe: {context.timeframe}",
                notes_block(items),
                f"Findings the checker already made (do not repeat these):\n{already}",
                wrap_block("pasted_code", numbered(code)),
                "Review this code.",
            ]
        )
        ai: list[ReviewFinding] = []
        summary = ""
        try:
            review = ask(
                deps.llm,
                tracker.meter,
                model=deps.settings.strong_model or "",
                system=prompts.REVIEW_SYSTEM,
                user=user,
                schema_name="review",
                schema=REVIEW_SCHEMA,
                parse=_AIReview.model_validate,
                max_output_tokens=deps.settings.max_output_tokens,
            )
            line_count = len(code.rstrip("\n").split("\n"))
            ai = _ai_findings(review, line_count, deps.settings)
            summary = review.summary.strip()
            ai_review = "done"
        except LLMError as error:
            ai_review = "failed"
            notes.append(AI_FAILED_NOTE)
            tracker.notes.append(f"AI review failed ({error.kind}).")
    except Cancelled:
        return ReviewResult(status="cancelled", run=tracker.record())

    # By line, the checker's finding first on a shared line; findings about the whole code last.
    findings = sorted(
        [*verified, *ai], key=lambda f: (f.line is None, f.line or 0, f.label != VERIFIED)
    )
    return ReviewResult(
        status="reviewed",
        run=tracker.record(),
        findings=tuple(findings),
        checks=tuple(CheckLine(entry.rule, entry.outcome) for entry in result.checks),
        checker_status=result.status,
        ai_review=ai_review,
        summary=summary,
        notes=tuple(notes),
    )
