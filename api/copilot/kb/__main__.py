"""Validates a knowledge base directory: `python -m copilot.kb <kb directory>`.

Exits 0 when every file is valid, 1 when any problem is found.
"""

import sys
from pathlib import Path

from copilot.kb.catalog import KBError, load_catalog
from copilot.kb.notes import cross_check, load_notes


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m copilot.kb <kb directory>", file=sys.stderr)
        return 2

    kb_dir = Path(args[0])
    problems: list[str] = []
    catalog = notes = None
    try:
        catalog = load_catalog(kb_dir)
    except KBError as error:
        problems.extend(error.problems)
    try:
        notes = load_notes(kb_dir)
    except KBError as error:
        problems.extend(error.problems)
    if catalog is not None and notes is not None:
        problems.extend(cross_check(catalog, notes))

    if problems or catalog is None or notes is None:
        for problem in problems:
            print(problem, file=sys.stderr)
        count = len(problems)
        print(f"{count} problem{'' if count == 1 else 's'} in {kb_dir}", file=sys.stderr)
        return 1

    print(
        f"KB ok: {len(catalog.functions)} functions, {len(catalog.builtins)} built-ins, "
        f"{len(catalog.markets)} markets, kb_version {catalog.kb_version}"
    )
    print(
        f"Notes: {len(notes.mistakes)} mistakes, {len(notes.concepts)} concepts, "
        f"{len(notes.examples)} examples, {len(notes.errors)} error notes"
    )
    unverified = [market.id for market in catalog.markets.values() if market.last_verified is None]
    if unverified:
        print(f"Session times not yet verified for: {', '.join(unverified)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
