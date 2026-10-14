"""Review mode on the command line.

    python -m copilot.review --market nse_fo --timeframe 5min strategy.afl [--apply]

Lists the findings, each labelled Verified (the checker) or AI-suggested
(the model). With --apply it then rewrites the code to fix them.
Makes real OpenAI calls.
"""

import argparse
import sys
from pathlib import Path

from copilot.config import ConfigError, load_settings
from copilot.kb import KBError
from copilot.pipeline.orchestrator import Deps
from copilot.pipeline.review import ReviewRequest, ReviewResult, run_review
from copilot.pipeline.rewrite import ApplyRequest, FixResult, run_apply_fixes
from copilot.pipeline.setup import connect_deps

_HEADINGS = {
    "checked": "CHECKED: the corrected code passes the checker.",
    "not_fully_checked": "NOT FULLY CHECKED: the corrected code still fails these checks.",
    "not_checked": "NOT CHECKED: the checker could not run on the corrected code. "
    "Treat it as unverified.",
}
_MARKS = {"passed": "pass", "failed": "FAIL", "skipped": "skip"}


def _usage(run) -> str:
    cost = "unknown" if run.cost_usd is None else f"${run.cost_usd:.4f}"
    return (
        f"{sum(run.tokens_in.values())} tokens in, {sum(run.tokens_out.values())} out, "
        f"cost {cost}, {run.latency_ms / 1000:.1f} s, kb_version {run.kb_version}"
    )


def render_review(result: ReviewResult) -> str:
    if result.status == "error":
        return f"No review: {result.message}"
    if result.status == "cancelled":
        return "Stopped before the review was ready."

    lines = []
    if result.findings:
        lines.append(f"{len(result.findings)} finding{'' if len(result.findings) == 1 else 's'}:")
        for finding in result.findings:
            where = f"line {finding.line}" if finding.line else "whole code"
            lines.append(
                f"  [{finding.label}] {finding.severity.upper()}, {where}: {finding.message}"
            )
            if finding.fix:
                lines.append(f"      Fix: {finding.fix}")
    else:
        lines.append("No findings. This does not prove the code is correct.")
    lines.append("")
    if result.summary:
        lines += [f"AI summary: {result.summary}", ""]
    if result.checks:
        lines += ["Checks (Verified)", "-----------------"]
        lines.extend(f"  [{_MARKS[line.outcome]}] {line.name}" for line in result.checks)
        lines.append("")
    if result.notes:
        lines.extend(f"Note: {note}" for note in result.notes)
        lines.append("")
    lines.append(_usage(result.run))
    return "\n".join(lines)


def render_fix(result: FixResult) -> str:
    if result.status == "error":
        return f"No corrected code: {result.message}"
    if result.status == "cancelled":
        return "Stopped before the corrected code was ready."

    lines = [_HEADINGS[result.status]]
    lines.extend(f"  - {problem.text}" for problem in result.problems)
    lines += ["", "Corrected code", "--------------", result.code.rstrip("\n"), ""]
    if result.changes:
        lines += ["What changed", "------------"]
        for change in result.changes:
            where = f"Line {change.line}: " if change.line else ""
            lines.append(f"  {where}{change.text}")
        lines.append("")
    if result.checks:
        lines += ["Checks (Verified)", "-----------------"]
        lines.extend(f"  [{_MARKS[line.outcome]}] {line.name}" for line in result.checks)
        lines.append("")
    if result.notes:
        lines.extend(f"Note: {note}" for note in result.notes)
        lines.append("")
    lines.append(
        f"{result.run.attempts} attempt{'' if result.run.attempts == 1 else 's'}, "
        + _usage(result.run)
    )
    return "\n".join(lines)


def open_deps() -> Deps | None:
    """Connects everything, or prints why it cannot and returns None."""
    try:
        return connect_deps(load_settings())
    except ConfigError as error:
        print(error, file=sys.stderr)
    except KBError as error:
        print("\n".join(error.problems), file=sys.stderr)
    return None


def read_code(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        print(f"Cannot read {path}: {error}", file=sys.stderr)
        return None


def main(argv: list[str] | None = None, deps: Deps | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m copilot.review", description=__doc__)
    parser.add_argument("--market", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--apply", action="store_true", help="also rewrite the code to fix them")
    parser.add_argument("file", type=Path, help="the AFL file to review")
    args = parser.parse_args(argv)

    code = read_code(args.file)
    if code is None:
        return 2
    own_connection = deps is None
    deps = deps or open_deps()
    if deps is None:
        return 2

    def progress(stage: str) -> None:
        print(f"... {stage}", file=sys.stderr)

    try:
        review = run_review(ReviewRequest(code, args.market, args.timeframe), deps, progress)
        print(render_review(review))
        if review.status != "reviewed":
            return 1
        if args.apply and review.findings:
            fixed = run_apply_fixes(
                ApplyRequest(code, args.market, args.timeframe, review.findings), deps, progress
            )
            print()
            print(render_fix(fixed))
            return 0 if fixed.status == "checked" else 1
    finally:
        if own_connection:
            deps.conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
