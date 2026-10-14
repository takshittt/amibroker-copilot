"""Runs the test sets and reports the quality measures from spec.md section 10.

    python -m copilot.evals write <evals/write directory> [--json report.json]
    python -m copilot.evals review <evals/review directory> --kb <kb directory>
    python -m copilot.evals review <evals/review directory> --ai

`write` and `review --ai` make real model calls, so they cost money and
are run by hand. `review` without --ai runs only the checker: it is
free, needs no key and no database, and measures the Verified findings.
The manual correctness score is not something a program can give.
"""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from copilot.checker import Context, called_functions, check
from copilot.config import ConfigError, load_settings
from copilot.kb import Catalog, KBError, load_catalog
from copilot.kb.schema import TIMEFRAMES
from copilot.pipeline.orchestrator import Deps, WriteRequest, WriteResult, run_write
from copilot.pipeline.review import (
    AI_SUGGESTED,
    ReviewFinding,
    ReviewRequest,
    run_review,
    verified_findings,
)
from copilot.pipeline.setup import connect_deps

_ANSWERED = ("checked", "not_fully_checked", "not_checked")


class Expectation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # checked: the pipeline should produce code. clarify: it should ask first.
    status: Literal["checked", "clarify"]
    # Functions that should be among the items given to the model.
    retrieved: list[str] = []
    # Functions the finished code should call.
    calls: list[str] = []


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    market: str
    timeframe: str
    difficulty: Literal["easy", "medium", "hard"]
    request: str
    expect: Expectation


def load_tasks(directory: Path, catalog: Catalog) -> list[Task]:
    """Reads and validates every task file. Raises KBError listing every problem."""
    problems: list[str] = []
    tasks: list[Task] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            task = Task.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (ValidationError, yaml.YAMLError) as error:
            problems.append(f"{path.name}: {' '.join(str(error).split())[:300]}")
            continue
        if task.id != path.stem:
            problems.append(f"{path.name}: holds id {task.id!r}; it must match the file name")
        if catalog.market(task.market) is None:
            problems.append(f"{path.name}: unknown market {task.market!r}")
        if task.timeframe not in TIMEFRAMES:
            problems.append(f"{path.name}: unknown timeframe {task.timeframe!r}")
        for name in (*task.expect.retrieved, *task.expect.calls):
            if catalog.function(name) is None:
                problems.append(f"{path.name}: {name} is not in the function list")
        tasks.append(task)
    if not tasks and not problems:
        problems.append(f"{directory}: holds no task files")
    if problems:
        raise KBError(problems)
    return tasks


@dataclass(frozen=True)
class TaskOutcome:
    id: str
    expected: str
    status: str
    attempts: int
    invented_first_attempt: bool
    invented_in_answer: bool
    retrieved_found: int
    retrieved_expected: int
    calls_found: int
    calls_expected: int
    tokens_in: int
    tokens_out: int
    cost_usd: float | None
    latency_ms: int
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class Report:
    outcomes: tuple[TaskOutcome, ...]
    kb_version: int = 0
    models: dict = field(default_factory=dict)

    def _share(self, hits: int, total: int) -> float | None:
        return None if total == 0 else hits / total

    @property
    def metrics(self) -> dict:
        outcomes = self.outcomes
        wants_code = [o for o in outcomes if o.expected == "checked"]
        wants_question = [o for o in outcomes if o.expected == "clarify"]
        wrote = [o for o in outcomes if o.status in _ANSWERED]
        costs = [o.cost_usd for o in outcomes]
        return {
            "tasks": len(outcomes),
            # Of the tasks that should produce code, how many ended fully checked.
            "checker_pass_rate": self._share(
                sum(o.status == "checked" for o in wants_code), len(wants_code)
            ),
            "passed_first_attempt_rate": self._share(
                sum(o.status == "checked" and o.attempts == 1 for o in wants_code),
                len(wants_code),
            ),
            # Of the answers with code, how many called a function that does not exist.
            "invented_function_rate_first_attempt": self._share(
                sum(o.invented_first_attempt for o in wrote), len(wrote)
            ),
            "invented_function_rate_in_answer": self._share(
                sum(o.invented_in_answer for o in wrote), len(wrote)
            ),
            # Search quality: were the functions the task needs given to the model.
            "retrieval_recall": self._share(
                sum(o.retrieved_found for o in wants_code),
                sum(o.retrieved_expected for o in wants_code),
            ),
            "expected_calls_recall": self._share(
                sum(o.calls_found for o in wants_code), sum(o.calls_expected for o in wants_code)
            ),
            "clarify_when_expected_rate": self._share(
                sum(o.status == "clarify" for o in wants_question), len(wants_question)
            ),
            "errors": sum(o.status == "error" for o in outcomes),
            "average_attempts": self._share(sum(o.attempts for o in wrote), len(wrote)),
            "tokens_in": sum(o.tokens_in for o in outcomes),
            "tokens_out": sum(o.tokens_out for o in outcomes),
            "cost_usd": None if any(c is None for c in costs) else round(sum(costs), 6),
            "average_latency_ms": self._share(sum(o.latency_ms for o in outcomes), len(outcomes)),
        }


def score(task: Task, result: WriteResult) -> TaskOutcome:
    history = result.run.history
    retrieved = {ref.lower() for kind, ref in result.run.retrieved if kind == "function"}
    called = {name.lower() for name in called_functions(result.code)}
    return TaskOutcome(
        id=task.id,
        expected=task.expect.status,
        status=result.status,
        attempts=result.run.attempts,
        invented_first_attempt=bool(history) and "unknown_function" in history[0].failed_rules,
        invented_in_answer=any(p.rule == "unknown_function" for p in result.problems),
        retrieved_found=sum(name.lower() in retrieved for name in task.expect.retrieved),
        retrieved_expected=len(task.expect.retrieved),
        calls_found=sum(name.lower() in called for name in task.expect.calls),
        calls_expected=len(task.expect.calls),
        tokens_in=sum(result.run.tokens_in.values()),
        tokens_out=sum(result.run.tokens_out.values()),
        cost_usd=result.run.cost_usd,
        latency_ms=result.run.latency_ms,
        problems=tuple(p.text for p in result.problems)
        or ((result.message,) if result.message else ()),
    )


def run_evals(tasks: list[Task], deps: Deps, on_task=None) -> Report:
    outcomes = []
    for task in tasks:
        result = run_write(WriteRequest(task.request, task.market, task.timeframe), deps)
        outcome = score(task, result)
        outcomes.append(outcome)
        if on_task is not None:
            on_task(outcome)
    settings = deps.settings
    return Report(
        outcomes=tuple(outcomes),
        kb_version=deps.catalog.kb_version,
        models={
            "strong": settings.strong_model,
            "cheap": settings.cheap_model,
            "embedding": deps.embedder.model,
        },
    )


def _show(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def render(report: Report) -> str:
    lines = [
        f"Write evals: kb_version {report.kb_version}, models {report.models}",
        "",
        f"{'task':<34}{'expected':<10}{'result':<20}{'attempts':<9}problems",
    ]
    for o in report.outcomes:
        ok = o.status == o.expected
        mark = "" if ok else "  <-- not as expected"
        lines.append(
            f"{o.id:<34}{o.expected:<10}{o.status:<20}{o.attempts:<9}{len(o.problems)}{mark}"
        )
    lines.append("")
    lines.extend(f"{name:<40}{_show(value)}" for name, value in report.metrics.items())
    return "\n".join(lines)


# Review samples

_CONTEXT = re.compile(r"^// context: timeframe=(\S+) market=(\S+)$", re.MULTILINE)
_PLANTED = re.compile(r"^// planted: (verified (\w+)|ai (\d+) (.+)|none)$", re.MULTILINE)
_HEADER_LINE = re.compile(r"^// (context|planted):.*$", re.MULTILINE)
# An AI finding counts as finding a planted bug when it is this close to its line.
AI_LINE_TOLERANCE = 3


@dataclass(frozen=True)
class Planted:
    kind: str  # verified or ai
    rule: str = ""  # for verified: the checker rule that must fire
    line: int = 0  # for ai: where the bug is
    description: str = ""


@dataclass(frozen=True)
class ReviewSample:
    id: str
    market: str
    timeframe: str
    code: str  # with the header lines blanked, so nothing gives the answer away
    planted: tuple[Planted, ...]


def load_review_samples(directory: Path, catalog: Catalog) -> list[ReviewSample]:
    """Reads every .afl sample. Its header says what is planted in it:

    // context: timeframe=5min market=nse_fo
    // planted: verified lookahead_ref      (a checker rule that must fire)
    // planted: ai 23 Cross is swapped      (a line the AI review must flag)
    // planted: none                        (a clean sample)
    """
    problems: list[str] = []
    samples: list[ReviewSample] = []
    for path in sorted(directory.glob("*.afl")):
        text = path.read_text(encoding="utf-8")
        context = _CONTEXT.search(text)
        marks = _PLANTED.findall(text)
        if context is None:
            problems.append(f"{path.name}: needs a '// context: timeframe=... market=...' line")
            continue
        if not marks:
            problems.append(f"{path.name}: needs '// planted: ...' lines, or '// planted: none'")
            continue
        timeframe, market = context.groups()
        if catalog.market(market) is None:
            problems.append(f"{path.name}: unknown market {market!r}")
        if timeframe not in TIMEFRAMES:
            problems.append(f"{path.name}: unknown timeframe {timeframe!r}")
        planted = []
        for _, rule, line, description in marks:
            if rule:
                planted.append(Planted("verified", rule=rule))
            elif line:
                planted.append(Planted("ai", line=int(line), description=description))
            elif len(marks) > 1:
                problems.append(f"{path.name}: 'planted: none' cannot stand beside other bugs")
        # Blank the header lines but keep them, so line numbers do not move.
        code = _HEADER_LINE.sub("//", text)
        samples.append(ReviewSample(path.stem, market, timeframe, code, tuple(planted)))
    if not samples and not problems:
        problems.append(f"{directory}: holds no samples")
    if problems:
        raise KBError(problems)
    return samples


@dataclass(frozen=True)
class ReviewOutcome:
    id: str
    verified_planted: int
    verified_found: int
    verified_missed: tuple[str, ...]
    # Verified findings for a rule that was not planted in this sample.
    false_alarms: tuple[str, ...]
    ai_planted: int
    ai_found: int
    ai_missed: tuple[str, ...]
    ai_other: int  # AI findings that are not near a planted bug
    clean: bool
    cost_usd: float | None = 0.0


def score_review(
    sample: ReviewSample, findings: list[ReviewFinding], cost_usd=0.0
) -> ReviewOutcome:
    verified = [f for f in findings if f.label != AI_SUGGESTED]
    ai = [f for f in findings if f.label == AI_SUGGESTED]
    wanted_rules = [p.rule for p in sample.planted if p.kind == "verified"]
    wanted_lines = [p for p in sample.planted if p.kind == "ai"]
    fired = {f.rule for f in verified}

    def near(planted: Planted) -> bool:
        return any(f.line and abs(f.line - planted.line) <= AI_LINE_TOLERANCE for f in ai)

    matched = [p for p in wanted_lines if near(p)]
    other = [
        f
        for f in ai
        if not any(f.line and abs(f.line - p.line) <= AI_LINE_TOLERANCE for p in wanted_lines)
    ]
    return ReviewOutcome(
        id=sample.id,
        verified_planted=len(wanted_rules),
        verified_found=sum(rule in fired for rule in wanted_rules),
        verified_missed=tuple(rule for rule in wanted_rules if rule not in fired),
        false_alarms=tuple(
            f"{f.rule} (line {f.line}, {f.severity})"
            for f in verified
            if f.rule not in wanted_rules
        ),
        ai_planted=len(wanted_lines),
        ai_found=len(matched),
        ai_missed=tuple(p.description for p in wanted_lines if p not in matched),
        ai_other=len(other),
        clean=not sample.planted,
        cost_usd=cost_usd,
    )


@dataclass(frozen=True)
class ReviewReport:
    outcomes: tuple[ReviewOutcome, ...]
    with_ai: bool
    kb_version: int = 0
    models: dict = field(default_factory=dict)

    @property
    def metrics(self) -> dict:
        outcomes = self.outcomes
        clean = [o for o in outcomes if o.clean]

        def share(hits: int, total: int) -> float | None:
            return None if total == 0 else hits / total

        metrics = {
            "samples": len(outcomes),
            "clean_samples": len(clean),
            # Bugs the checker must catch: found against planted.
            "verified_bugs_planted": sum(o.verified_planted for o in outcomes),
            "verified_bugs_found": sum(o.verified_found for o in outcomes),
            "verified_recall": share(
                sum(o.verified_found for o in outcomes), sum(o.verified_planted for o in outcomes)
            ),
            # Verified findings nobody planted. The checker should give none.
            "verified_false_alarms": sum(len(o.false_alarms) for o in outcomes),
            "clean_samples_with_a_false_alarm": sum(bool(o.false_alarms) for o in clean),
            "ai_bugs_planted": sum(o.ai_planted for o in outcomes),
        }
        if self.with_ai:
            costs = [o.cost_usd for o in outcomes]
            metrics.update(
                {
                    "ai_bugs_found": sum(o.ai_found for o in outcomes),
                    "ai_recall": share(
                        sum(o.ai_found for o in outcomes), sum(o.ai_planted for o in outcomes)
                    ),
                    # AI findings on code with nothing planted: likely false alarms.
                    "ai_findings_on_clean_samples": sum(o.ai_other for o in clean),
                    "ai_findings_elsewhere": sum(o.ai_other for o in outcomes if not o.clean),
                    "cost_usd": None if any(c is None for c in costs) else round(sum(costs), 6),
                }
            )
        return metrics


def run_review_evals(
    samples: list[ReviewSample], catalog: Catalog, deps: Deps | None = None, on_sample=None
) -> ReviewReport:
    """With `deps`, runs the full review including the model. Without, the checker only."""
    outcomes = []
    for sample in samples:
        if deps is None:
            context = Context(timeframe=sample.timeframe, market_id=sample.market)
            findings = verified_findings(check(sample.code, catalog, context))
            cost_usd: float | None = 0.0
        else:
            result = run_review(ReviewRequest(sample.code, sample.market, sample.timeframe), deps)
            findings = list(result.findings)
            cost_usd = result.run.cost_usd
        outcome = score_review(sample, findings, cost_usd)
        outcomes.append(outcome)
        if on_sample is not None:
            on_sample(outcome)
    models = {}
    if deps is not None:
        models = {"strong": deps.settings.strong_model, "embedding": deps.embedder.model}
    return ReviewReport(tuple(outcomes), deps is not None, catalog.kb_version, models)


def render_review(report: ReviewReport) -> str:
    mode = "checker and AI" if report.with_ai else "checker only (the AI review was not run)"
    lines = [f"Review evals: {mode}, kb_version {report.kb_version}", ""]
    for o in report.outcomes:
        parts = [f"verified {o.verified_found}/{o.verified_planted}"]
        if report.with_ai:
            parts.append(f"ai {o.ai_found}/{o.ai_planted}")
        notes = []
        if o.verified_missed:
            notes.append("MISSED " + ", ".join(o.verified_missed))
        if o.false_alarms:
            notes.append("FALSE ALARM " + "; ".join(o.false_alarms))
        if report.with_ai and o.ai_missed:
            notes.append("AI MISSED " + "; ".join(o.ai_missed))
        if report.with_ai and o.ai_other:
            notes.append(f"{o.ai_other} other AI finding{'' if o.ai_other == 1 else 's'}")
        lines.append(f"{o.id:<40}{'  '.join(parts):<28}{'  |  '.join(notes)}")
    lines.append("")
    lines.extend(f"{name:<40}{_show(value)}" for name, value in report.metrics.items())
    return "\n".join(lines)


def _save(path: Path | None, payload: dict) -> None:
    if path is not None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _main_write(args, deps: Deps | None) -> int:
    own_connection = deps is None
    try:
        if deps is None:
            deps = connect_deps(load_settings())
        tasks = load_tasks(args.directory, deps.catalog)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 2
    except KBError as error:
        print("\n".join(error.problems), file=sys.stderr)
        return 2
    try:
        report = run_evals(
            tasks, deps, on_task=lambda o: print(f"... {o.id}: {o.status}", file=sys.stderr)
        )
    finally:
        if own_connection:
            deps.conn.close()
    print(render(report))
    _save(
        args.json,
        {
            "kb_version": report.kb_version,
            "models": report.models,
            "metrics": report.metrics,
            "outcomes": [asdict(outcome) for outcome in report.outcomes],
        },
    )
    return 0


def _main_review(args, deps: Deps | None) -> int:
    own_connection = False
    try:
        if args.ai and deps is None:
            deps = connect_deps(load_settings())
            own_connection = True
        if deps is not None:
            catalog = deps.catalog
        elif args.kb is not None:
            catalog = load_catalog(args.kb)
        else:
            print("Give --kb <kb directory> for a checker-only run, or --ai.", file=sys.stderr)
            return 2
        samples = load_review_samples(args.directory, catalog)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 2
    except KBError as error:
        print("\n".join(error.problems), file=sys.stderr)
        return 2
    try:
        report = run_review_evals(samples, catalog, deps if args.ai or deps else None)
    finally:
        if own_connection and deps is not None:
            deps.conn.close()
    print(render_review(report))
    _save(
        args.json,
        {
            "kb_version": report.kb_version,
            "with_ai": report.with_ai,
            "models": report.models,
            "metrics": report.metrics,
            "outcomes": [asdict(outcome) for outcome in report.outcomes],
        },
    )
    return 0


def main(argv: list[str] | None = None, deps: Deps | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m copilot.evals", description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    write = modes.add_parser("write", help="run the Write tasks (real model calls)")
    write.add_argument("directory", type=Path)
    write.add_argument("--json", type=Path, help="also write the report to this file")
    review = modes.add_parser("review", help="run the Review samples")
    review.add_argument("directory", type=Path)
    review.add_argument("--kb", type=Path, help="kb directory, for a checker-only run")
    review.add_argument("--ai", action="store_true", help="also run the AI review (real calls)")
    review.add_argument("--json", type=Path, help="also write the report to this file")
    args = parser.parse_args(argv)
    return _main_write(args, deps) if args.mode == "write" else _main_review(args, deps)


if __name__ == "__main__":
    sys.exit(main())
