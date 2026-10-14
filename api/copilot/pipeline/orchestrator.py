"""Runs the Write pipeline: steps 1 to 7, in order, with retries.

The model writes; this file and the checker decide what counts as
correct. An answer is "checked" only when the checker passed it with
nothing to report and every requirement is accounted for.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

import psycopg

from copilot.checker import CheckResult, Context, called_functions, check
from copilot.config import Settings
from copilot.embeddings import Embedder
from copilot.kb import Catalog
from copilot.pipeline.brief import Brief, build_brief
from copilot.pipeline.generate import ExplanationBlock, Feedback, Generation, generate
from copilot.pipeline.llm import LLM, LLMError, UsageMeter
from copilot.pipeline.rerank import rerank
from copilot.pipeline.retrieve import (
    GENERATION_CATEGORIES,
    Item,
    allowed_function_names,
    retrieve,
)
from copilot.pipeline.tracking import AttemptRecord, RunRecord, cost

TIME_ZONE_NOTE = (
    "This code uses the time of each bar. AmiBroker reads that time from your data, so if "
    "your data feed is in a different time zone from the exchange, the times will be off. "
    "Check the first and last bar of a session on an intraday chart before relying on them."
)
_TIME_FUNCTIONS = frozenset(["timenum", "paramtime"])
ERROR_MESSAGES = {
    "rate_limited": "The service is busy right now. Please try again in a minute.",
    "unavailable": "The AI service could not be reached. Please try again.",
    "rejected": "The AI service refused the request. This is a setup problem on our side.",
    "invalid_output": "The AI gave an answer we could not read. Please try again.",
}


@dataclass(frozen=True)
class WriteRequest:
    text: str
    market_id: str
    timeframe: str
    # The conversation's latest code, when this request is a change to it.
    previous_code: str = ""


@dataclass(frozen=True)
class Deps:
    """What the pipeline needs from outside."""

    conn: psycopg.Connection
    catalog: Catalog
    llm: LLM
    embedder: Embedder
    settings: Settings


@dataclass(frozen=True)
class Problem:
    """One thing wrong with an attempt. All of these are found by code, not by the model."""

    source: str  # checker, coverage or scope
    rule: str
    message: str
    line: int | None = None
    severity: str = "critical"
    fix_hint: str = ""

    @property
    def text(self) -> str:
        where = f"line {self.line}: " if self.line else ""
        hint = f" {self.fix_hint}" if self.fix_hint else ""
        return f"{where}{self.message}{hint}"


@dataclass(frozen=True)
class CheckLine:
    """One line of the check panel."""

    name: str
    outcome: str  # passed, failed or skipped


@dataclass(frozen=True)
class WriteResult:
    # checked: passed every check.
    # not_fully_checked: checks still failed after the last attempt; `problems` lists them.
    # not_checked: the checker itself broke, so nothing is known about the code.
    # clarify: `questions` must be answered first; no code was written.
    # error: no answer; `message` says why.
    # cancelled: stopped by the caller.
    status: str
    run: RunRecord
    brief: Brief | None = None
    questions: tuple[str, ...] = ()
    code: str = ""
    explanation_blocks: tuple[ExplanationBlock, ...] = ()
    checks: tuple[CheckLine, ...] = ()
    problems: tuple[Problem, ...] = ()
    doc_links: tuple[tuple[str, str], ...] = ()
    notes: tuple[str, ...] = ()
    message: str = ""


class Cancelled(Exception):
    """The caller asked the run to stop."""


def coverage_problems(brief: Brief, generation: Generation) -> list[Problem]:
    """Every requirement must be mapped to lines that exist in the code."""
    problems = []
    covered = {entry.id: entry for entry in generation.requirements_covered}
    last = generation.line_count
    for ident, text in brief.requirements:
        entry = covered.get(ident)
        if entry is None:
            problems.append(
                Problem(
                    "coverage",
                    "requirements_covered",
                    f"Requirement {ident} is not accounted for: {text}",
                    fix_hint="Carry it out in the code and list its lines in requirements_covered.",
                )
            )
        elif entry.start_line > entry.end_line or entry.end_line > last:
            problems.append(
                Problem(
                    "coverage",
                    "requirements_covered",
                    f"Requirement {ident} points to lines {entry.start_line} to "
                    f"{entry.end_line}, but the code has {last} lines.",
                    fix_hint="Give the lines that really carry it out.",
                )
            )
    return problems


def scope_problems(code: str, catalog: Catalog) -> list[Problem]:
    """Real functions that v1 does not write code with (multi-timeframe, OLE, and so on)."""
    problems = []
    for name in called_functions(code):
        record = catalog.function(name)
        if record is not None and record.category not in GENERATION_CATEGORIES:
            problems.append(
                Problem(
                    "scope",
                    "v1_scope",
                    f"{record.name} is a real function, but it belongs to an area this tool "
                    f"does not write code for yet ({record.category}).",
                    fix_hint="Write the code without it.",
                )
            )
    return problems


def checker_problems(result: CheckResult) -> list[Problem]:
    return [
        Problem("checker", f.rule, f.message, f.line, f.severity, f.fix_hint)
        for f in result.findings
    ]


def _panel(result: CheckResult, coverage: list[Problem], scope: list[Problem]) -> list[CheckLine]:
    lines = [CheckLine(entry.rule, entry.outcome) for entry in result.checks]
    lines.append(CheckLine("requirements_covered", "failed" if coverage else "passed"))
    lines.append(CheckLine("v1_scope", "failed" if scope else "passed"))
    return lines


def doc_links_for(code: str, catalog: Catalog) -> tuple[tuple[str, str], ...]:
    links = []
    for name in called_functions(code):
        record = catalog.function(name)
        if record is not None:
            links.append((record.name, record.doc_url))
    return tuple(links)


def _retry_queries(problems: list[Problem]) -> tuple[str, ...]:
    """Searches for the parts that went wrong, so the retry gets better notes."""
    queries = []
    for problem in problems:
        if problem.rule == "unknown_function":
            name = problem.message.split(" ", 1)[0]
            # "SuperTrend" -> "Super Trend", so the words can match descriptions.
            words = "".join(f" {ch}" if ch.isupper() else ch for ch in name).strip()
            queries.append(words)
    return tuple(dict.fromkeys(queries))


def run_write(
    request: WriteRequest,
    deps: Deps,
    on_progress: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> WriteResult:
    """Runs the whole pipeline for one request. Never raises for a model
    failure: the result's status says what happened."""
    started = time.monotonic()
    settings = deps.settings
    meter = UsageMeter()
    history: list[AttemptRecord] = []
    run_notes: list[str] = []
    given: dict[tuple[str, str], None] = {}

    def progress(stage: str) -> None:
        if should_stop is not None and should_stop():
            raise Cancelled
        if on_progress is not None:
            on_progress(stage)

    def record() -> RunRecord:
        return RunRecord(
            attempts=len(history),
            history=tuple(history),
            calls=dict(meter.calls),
            tokens_in=dict(meter.tokens_in),
            tokens_out=dict(meter.tokens_out),
            cost_usd=cost(meter, settings),
            latency_ms=int((time.monotonic() - started) * 1000),
            model_versions={
                "strong": settings.strong_model,
                "cheap": settings.cheap_model,
                "embedding": deps.embedder.model,
            },
            kb_version=deps.catalog.kb_version,
            retrieved=tuple(given),
            notes=tuple(run_notes),
        )

    def failed(message: str) -> WriteResult:
        return WriteResult(status="error", run=record(), message=message)

    text = request.text.strip()
    if not text:
        return failed("Describe the strategy you want written.")
    if len(text) > settings.max_request_chars:
        return failed(
            f"That request is too long ({len(text)} characters). "
            f"The limit is {settings.max_request_chars}."
        )
    market = deps.catalog.market(request.market_id)
    if market is None:
        return failed(f"Unknown market {request.market_id!r}.")
    try:
        context = Context(timeframe=request.timeframe, market_id=market.id)
    except ValueError as error:
        return failed(str(error))

    brief: Brief | None = None
    try:
        progress("understanding")
        previous = request.previous_code
        brief = build_brief(deps.llm, meter, settings, text, market, request.timeframe, previous)
        # A change to existing code takes what the brief leaves out from that code.
        if brief.missing_critical and not previous:
            return WriteResult(
                status="clarify", run=record(), brief=brief, questions=tuple(brief.questions)
            )

        progress("searching")
        found = retrieve(deps.conn, deps.embedder, deps.catalog, settings, brief, text)
        kept, note = rerank(deps.llm, meter, settings, brief, found.candidates)
        if note:
            run_notes.append(note)
        items: dict[tuple[str, str], Item] = {item.key: item for item in [*found.pinned, *kept]}
        function_names = allowed_function_names(deps.catalog)

        feedback: Feedback | None = None
        generation: Generation | None = None
        problems: list[Problem] = []
        panel: list[CheckLine] = []
        for attempt in range(1, settings.max_attempts + 1):
            progress("writing" if attempt == 1 else f"fixing attempt {attempt}")
            given.update(dict.fromkeys(items))
            generation = generate(
                deps.llm,
                meter,
                settings,
                brief,
                text,
                list(items.values()),
                function_names,
                feedback,
                request.previous_code,
            )

            progress("checking")
            result = check(generation.code, deps.catalog, context)
            if result.status == "checker_error":
                history.append(AttemptRecord(attempt, ("checker_error",), 1))
                return _answer(
                    "not_checked",
                    record(),
                    brief,
                    generation,
                    deps.catalog,
                    panel=[],
                    problems=[
                        Problem("checker", "checker_error", "The checker could not read this code.")
                    ],
                )
            coverage = coverage_problems(brief, generation)
            scope = scope_problems(generation.code, deps.catalog)
            problems = [*checker_problems(result), *coverage, *scope]
            panel = _panel(result, coverage, scope)
            rules = tuple(dict.fromkeys(problem.rule for problem in problems))
            history.append(AttemptRecord(attempt, rules, len(problems)))
            if not problems:
                return _answer("checked", record(), brief, generation, deps.catalog, panel, [])

            if attempt < settings.max_attempts:
                # Search again for the parts that failed, and pin the matching mistakes.
                checker_rules = tuple(p.rule for p in problems if p.source == "checker")
                again = retrieve(
                    deps.conn,
                    deps.embedder,
                    deps.catalog,
                    settings,
                    brief,
                    text,
                    failed_rules=tuple(dict.fromkeys(checker_rules)),
                    extra_queries=_retry_queries(problems),
                )
                extra = [*again.pinned]
                if _retry_queries(problems):
                    extra.extend(c for c in again.candidates[:5] if c.kind == "function")
                for item in extra:
                    items.setdefault(item.key, item)
                feedback = Feedback(generation.code, tuple(problem.text for problem in problems))

        assert generation is not None
        return _answer(
            "not_fully_checked", record(), brief, generation, deps.catalog, panel, problems
        )
    except LLMError as error:
        return WriteResult(
            status="error", run=record(), brief=brief, message=ERROR_MESSAGES[error.kind]
        )
    except Cancelled:
        return WriteResult(status="cancelled", run=record(), brief=brief)


def _answer(
    status: str,
    run: RunRecord,
    brief: Brief,
    generation: Generation,
    catalog: Catalog,
    panel: list[CheckLine],
    problems: list[Problem],
) -> WriteResult:
    """Step 7: everything the user is shown."""
    notes = [*brief.notes, *generation.notes]
    called = {name.lower() for name in called_functions(generation.code)}
    if called & _TIME_FUNCTIONS:
        notes.append(TIME_ZONE_NOTE)
    last = generation.line_count
    blocks = tuple(
        block
        for block in generation.explanation_blocks
        if block.start_line <= block.end_line <= last
    )
    return WriteResult(
        status=status,
        run=run,
        brief=brief,
        code=generation.code,
        explanation_blocks=blocks,
        checks=tuple(panel),
        problems=tuple(problems),
        doc_links=doc_links_for(generation.code, catalog),
        notes=tuple(dict.fromkeys(notes)),
    )
