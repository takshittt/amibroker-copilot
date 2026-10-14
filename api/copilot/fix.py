"""Fix-from-error on the command line.

    python -m copilot.fix --market nse_fo --timeframe 5min strategy.afl --error "Error 32. ..."

Give the error AmiBroker showed with --error, or put it in a file and
use --error-file. Makes real OpenAI calls.
"""

import argparse
import sys
from pathlib import Path

from copilot.pipeline.fix_error import FixErrorRequest, run_fix_error
from copilot.pipeline.orchestrator import Deps
from copilot.review import open_deps, read_code, render_fix


def main(argv: list[str] | None = None, deps: Deps | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m copilot.fix", description=__doc__)
    parser.add_argument("--market", required=True)
    parser.add_argument("--timeframe", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--error", help="the error text AmiBroker showed")
    source.add_argument("--error-file", type=Path, help="a file holding that text")
    parser.add_argument("file", type=Path, help="the AFL file that gave the error")
    args = parser.parse_args(argv)

    code = read_code(args.file)
    error_text = args.error if args.error is not None else read_code(args.error_file)
    if code is None or error_text is None:
        return 2
    own_connection = deps is None
    deps = deps or open_deps()
    if deps is None:
        return 2
    try:
        result = run_fix_error(
            FixErrorRequest(code, error_text, args.market, args.timeframe),
            deps,
            on_progress=lambda stage: print(f"... {stage}", file=sys.stderr),
        )
    finally:
        if own_connection:
            deps.conn.close()
    print(render_fix(result))
    return 0 if result.status == "checked" else 1


if __name__ == "__main__":
    sys.exit(main())
