"""Validates a knowledge base directory: `python -m copilot.kb <kb directory>`.

Exits 0 when every file is valid, 1 when any problem is found.
"""

import sys
from pathlib import Path

from copilot.kb.catalog import KBError, load_catalog


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m copilot.kb <kb directory>", file=sys.stderr)
        return 2

    kb_dir = Path(args[0])
    try:
        catalog = load_catalog(kb_dir)
    except KBError as error:
        for problem in error.problems:
            print(problem, file=sys.stderr)
        count = len(error.problems)
        print(f"{count} problem{'' if count == 1 else 's'} in {kb_dir}", file=sys.stderr)
        return 1

    print(
        f"KB ok: {len(catalog.functions)} functions, {len(catalog.builtins)} built-ins, "
        f"{len(catalog.markets)} markets, kb_version {catalog.kb_version}"
    )
    unverified = [market.id for market in catalog.markets.values() if market.last_verified is None]
    if unverified:
        print(f"Session times not yet verified for: {', '.join(unverified)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
