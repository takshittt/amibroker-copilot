"""Runs the Write test set and reports the quality measures from spec.md section 10.

    python -m copilot.evals <evals/write directory> [--json report.json]

Every task makes real model calls, so this costs money and is run by
hand. Review samples are added at stage 6; the manual correctness score
is not something a program can give.
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from copilot.checker import called_functions
from copilot.config import ConfigError, load_settings
from copilot.kb import Catalog, KBError
from copilot.kb.schema import TIMEFRAMES
from copilot.pipeline.orchestrator import Deps, WriteRequest, WriteResult, run_write
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


def main(argv: list[str] | None = None, deps: Deps | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m copilot.evals", description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--json", type=Path, help="also write the report to this file")
    args = parser.parse_args(argv)

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
            tasks,
            deps,
            on_task=lambda o: print(f"... {o.id}: {o.status}", file=sys.stderr),
        )
    finally:
        if own_connection:
            deps.conn.close()
    print(render(report))
    if args.json:
        payload = {
            "kb_version": report.kb_version,
            "models": report.models,
            "metrics": report.metrics,
            "outcomes": [asdict(outcome) for outcome in report.outcomes],
        }
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
