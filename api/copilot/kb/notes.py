"""Loads the text notes in /kb: mistakes, concepts, examples and error notes.

Like the catalog loader, loading is the validation: every problem in
every file is collected and raised together as one KBError. A folder
that does not exist simply means there are no notes of that kind yet.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from copilot.kb.catalog import Catalog, KBError, _read_yaml, _UniqueKeyLoader, _validate
from copilot.kb.schema import (
    SLUG_PATTERN,
    ConceptNote,
    ErrorNote,
    ExampleRecord,
    MistakeRecord,
    Record,
)

_SLUG = re.compile(SLUG_PATTERN)


@dataclass(frozen=True)
class Notes:
    """Every note, keyed by id."""

    mistakes: dict[str, MistakeRecord] = field(default_factory=dict)
    concepts: dict[str, ConceptNote] = field(default_factory=dict)
    examples: dict[str, ExampleRecord] = field(default_factory=dict)
    errors: dict[str, ErrorNote] = field(default_factory=dict)


def _files(kb_dir: Path, folder: str, suffixes: tuple[str, ...], problems: list[str]) -> list[Path]:
    """Returns the files of a notes folder, after reporting any that do not belong."""
    directory = kb_dir / folder
    if not directory.is_dir():
        return []
    found = []
    for path in sorted(directory.iterdir()):
        if path.name.startswith("."):
            continue
        label = f"{folder}/{path.name}"
        if path.suffix not in suffixes or not path.is_file():
            problems.append(f"{label}: only {' and '.join(suffixes)} files belong in {folder}")
        elif not _SLUG.match(path.stem):
            problems.append(
                f"{label}: file name must be lower-case words joined by hyphens, like trailing-stop"
            )
        else:
            found.append(path)
    return found


def _read_yaml_notes[R: Record](
    kb_dir: Path, folder: str, model: type[R], problems: list[str]
) -> dict[str, R]:
    found: dict[str, R] = {}
    for path in _files(kb_dir, folder, (".yaml",), problems):
        label = f"{folder}/{path.name}"
        data = _read_yaml(path, label, problems)
        if data is None:
            continue
        if not isinstance(data, dict):
            problems.append(f"{label}: must hold one record, not a list or a bare value")
            continue
        record = _validate(model, data, label, problems)
        if record is None:
            continue
        if record.id != path.stem:  # type: ignore[attr-defined]
            problems.append(
                f"{label}: holds {record.id!r}, so it must be named {record.id}.yaml"  # type: ignore[attr-defined]
            )
            continue
        found[path.stem] = record
    return found


def _read_markdown(
    path: Path, label: str, problems: list[str]
) -> tuple[dict[str, Any], str] | None:
    """Splits a Markdown file into its `---` header and its body."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        problems.append(f"{label}: cannot be read: {error}")
        return None
    match = re.match(r"---\n(.*?)\n---[ \t]*(?:\n|$)(.*)", text, re.DOTALL)
    if match is None:
        problems.append(f"{label}: must start with a header between two '---' lines")
        return None
    try:
        header = yaml.load(match.group(1), Loader=_UniqueKeyLoader)  # noqa: S506 (SafeLoader)
    except yaml.YAMLError as error:
        problems.append(f"{label}: header is not valid YAML: {' '.join(str(error).split())}")
        return None
    if not isinstance(header, dict):
        problems.append(f"{label}: the header must hold fields such as 'title: ...'")
        return None
    return header, match.group(2).strip()


def _read_concepts(kb_dir: Path, problems: list[str]) -> dict[str, ConceptNote]:
    found = {}
    for path in _files(kb_dir, "concepts", (".md",), problems):
        label = f"concepts/{path.name}"
        parts = _read_markdown(path, label, problems)
        if parts is None:
            continue
        header, body = parts
        record = _validate(
            ConceptNote, {**header, "id": path.stem, "content": body}, label, problems
        )
        if record is not None:
            found[path.stem] = record
    return found


def _read_examples(kb_dir: Path, problems: list[str]) -> dict[str, ExampleRecord]:
    paths = _files(kb_dir, "examples", (".afl", ".md"), problems)
    found = {}
    for stem in sorted({path.stem for path in paths}):
        code_path = kb_dir / "examples" / f"{stem}.afl"
        text_path = kb_dir / "examples" / f"{stem}.md"
        missing = [path for path in (code_path, text_path) if not path.is_file()]
        if missing:
            problems.append(
                f"examples/{missing[0].name}: file is missing; an example needs "
                f"both {stem}.afl and {stem}.md"
            )
            continue
        label = f"examples/{stem}.md"
        parts = _read_markdown(text_path, label, problems)
        if parts is None:
            continue
        header, body = parts
        try:
            code = code_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            problems.append(f"examples/{stem}.afl: cannot be read: {error}")
            continue
        data = {**header, "id": stem, "description": body, "code": code}
        record = _validate(ExampleRecord, data, label, problems)
        if record is not None:
            found[stem] = record
    return found


def load_notes(kb_dir: Path | str) -> Notes:
    """Reads and validates the notes at `kb_dir`.

    Raises KBError listing every problem found, each with the file it is in.
    """
    kb_dir = Path(kb_dir)
    problems: list[str] = []
    notes = Notes(
        mistakes=_read_yaml_notes(kb_dir, "mistakes", MistakeRecord, problems),
        concepts=_read_concepts(kb_dir, problems),
        examples=_read_examples(kb_dir, problems),
        errors=_read_yaml_notes(kb_dir, "errors", ErrorNote, problems),
    )
    if problems:
        raise KBError(problems)
    return notes


def cross_check(catalog: Catalog, notes: Notes) -> list[str]:
    """Problems that only show when the notes are read against the catalog."""
    problems = []
    for example in notes.examples.values():
        if catalog.market(example.market) is None:
            problems.append(f"examples/{example.id}.md: unknown market {example.market!r}")
    return problems
