"""Write mode on the command line.

    python -m copilot.write --market nse_fo --timeframe 5min "Buy when ..."

Needs DATABASE_URL (indexed with real embeddings), OPENAI_API_KEY,
STRONG_MODEL and CHEAP_MODEL.
"""

import argparse
import sys

from copilot.config import ConfigError, load_settings
from copilot.kb import KBError
from copilot.pipeline.orchestrator import Deps, WriteRequest, WriteResult, run_write
from copilot.pipeline.setup import connect_deps

_HEADINGS = {
    "checked": "CHECKED: this code passed every check.",
    "not_fully_checked": "NOT FULLY CHECKED: these checks still failed after the last attempt.",
    "not_checked": "NOT CHECKED: the checker could not run on this code. Treat it as unverified.",
}
_MARKS = {"passed": "pass", "failed": "FAIL", "skipped": "skip"}


def render(result: WriteResult) -> str:
    """The answer as plain text. Code is never shown without its check status."""
    lines: list[str] = []
    if result.status == "clarify":
        lines.append("Before writing the code, I need to know:")
        lines.extend(f"  - {question}" for question in result.questions)
        return "\n".join(lines)
    if result.status == "error":
        return f"No answer: {result.message}"
    if result.status == "cancelled":
        return "Stopped before an answer was ready."

    lines.append(_HEADINGS[result.status])
    for problem in result.problems:
        lines.append(f"  - {problem.text}")
    lines += ["", "Code", "----", result.code.rstrip("\n"), ""]

    if result.explanation_blocks:
        lines += ["What it does", "------------"]
        for block in result.explanation_blocks:
            lines.append(f"  Lines {block.start_line}-{block.end_line}: {block.text}")
        lines.append("")
    if result.checks:
        lines += ["Checks (Verified)", "-----------------"]
        lines.extend(f"  [{_MARKS[line.outcome]}] {line.name}" for line in result.checks)
        lines.append("")
    if result.notes:
        lines += ["Notes", "-----"]
        lines.extend(f"  - {note}" for note in result.notes)
        lines.append("")
    if result.doc_links:
        lines += ["Official documentation", "----------------------"]
        lines.extend(f"  {name}: {url}" for name, url in result.doc_links)
        lines.append("")

    run = result.run
    cost = "unknown" if run.cost_usd is None else f"${run.cost_usd:.4f}"
    lines.append(
        f"{run.attempts} attempt{'' if run.attempts == 1 else 's'}, "
        f"{sum(run.tokens_in.values())} tokens in, {sum(run.tokens_out.values())} out, "
        f"cost {cost}, {run.latency_ms / 1000:.1f} s, kb_version {run.kb_version}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None, deps: Deps | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m copilot.write", description=__doc__)
    parser.add_argument("--market", required=True, help="market id, for example nse_fo")
    parser.add_argument("--timeframe", required=True, help="for example 5min or daily")
    parser.add_argument("text", help="the strategy in plain English")
    args = parser.parse_args(argv)

    own_connection = deps is None
    if deps is None:
        try:
            deps = connect_deps(load_settings())
        except ConfigError as error:
            print(error, file=sys.stderr)
            return 2
        except KBError as error:
            print("\n".join(error.problems), file=sys.stderr)
            return 2

    try:
        result = run_write(
            WriteRequest(args.text, args.market, args.timeframe),
            deps,
            on_progress=lambda stage: print(f"... {stage}", file=sys.stderr),
        )
    finally:
        if own_connection:
            deps.conn.close()
    print(render(result))
    return 0 if result.status in ("checked", "clarify") else 1


if __name__ == "__main__":
    sys.exit(main())
