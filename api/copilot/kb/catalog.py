"""Loads the files in /kb into one in-memory Catalog.

This is the only reader of the function list. Loading is also the
validation: every problem in every file is collected and raised together
as one KBError.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from copilot.kb.schema import BuiltinRecord, FunctionRecord, Market, Record


class KBError(Exception):
    """The knowledge base has problems. `problems` holds one line for each."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


@dataclass(frozen=True)
class Catalog:
    """Everything the checker and retrieval know about AFL names and markets.

    AFL ignores case, so `functions`, `builtins` and `aliases` are keyed by
    lower-case name. Use the lookup methods instead of reading the keys.
    """

    functions: Mapping[str, FunctionRecord]
    builtins: Mapping[str, BuiltinRecord]
    markets: Mapping[str, Market]
    kb_version: int
    # Lower-case alias -> lower-case built-in name ("c" -> "close").
    aliases: Mapping[str, str] = field(default_factory=dict)

    def function(self, name: str) -> FunctionRecord | None:
        return self.functions.get(name.lower())

    def builtin(self, name: str) -> BuiltinRecord | None:
        key = name.lower()
        return self.builtins.get(self.aliases.get(key, key))

    def market(self, market_id: str) -> Market | None:
        return self.markets.get(market_id)


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that refuses a mapping with the same key twice."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate key {key!r}", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _read_yaml(path: Path, label: str, problems: list[str]) -> Any:
    """Returns the parsed file, or None after recording why it could not be read."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        problems.append(f"{label}: file is missing")
        return None
    except (OSError, UnicodeDecodeError) as error:
        problems.append(f"{label}: cannot be read: {error}")
        return None
    try:
        return yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 (a SafeLoader subclass)
    except yaml.YAMLError as error:
        problems.append(f"{label}: not valid YAML: {' '.join(str(error).split())}")
        return None


def _validate[R: Record](model: type[R], data: Any, label: str, problems: list[str]) -> R | None:
    try:
        return model.model_validate(data)
    except ValidationError as error:
        for item in error.errors():
            where = ".".join(str(part) for part in item["loc"])
            message = item["msg"].removeprefix("Value error, ")
            problems.append(f"{label}: {where}: {message}" if where else f"{label}: {message}")
        return None


def _read_version(kb_dir: Path, problems: list[str]) -> int:
    try:
        text = (kb_dir / "VERSION").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        problems.append("VERSION: file is missing")
        return 0
    if not text.isascii() or not text.isdigit() or int(text) < 1:
        problems.append(f"VERSION: must hold one whole number, 1 or more, but holds {text!r}")
        return 0
    return int(text)


def _read_functions(kb_dir: Path, problems: list[str]) -> list[tuple[str, FunctionRecord]]:
    """Returns (label, record) for each valid function file."""
    directory = kb_dir / "functions"
    if not directory.is_dir():
        problems.append("functions: directory is missing")
        return []
    found = []
    paths = sorted(directory.iterdir())
    for path in paths:
        label = f"functions/{path.name}"
        if path.name.startswith("."):
            continue
        if path.suffix != ".yaml" or not path.is_file():
            problems.append(f"{label}: only .yaml files belong in functions")
            continue
        data = _read_yaml(path, label, problems)
        if data is None:
            continue
        if not isinstance(data, dict):
            problems.append(f"{label}: must hold one function record, not a list or a bare value")
            continue
        record = _validate(FunctionRecord, data, label, problems)
        if record is None:
            continue
        expected = f"{record.name.lower()}.yaml"
        if path.name != expected:
            problems.append(
                f"{label}: holds function {record.name!r}, so it must be named {expected}"
            )
        found.append((label, record))
    if not any(path.suffix == ".yaml" for path in paths):
        problems.append("functions: holds no function files")
    return found


def _read_list[R: Record](
    kb_dir: Path, file_name: str, model: type[R], key: str, problems: list[str]
) -> list[tuple[str, R]]:
    """Returns (label, record) for each valid entry of a file that holds a list."""
    data = _read_yaml(kb_dir / file_name, file_name, problems)
    if data is None:
        return []
    if not isinstance(data, list):
        problems.append(f"{file_name}: must hold a list of records")
        return []
    found = []
    for number, item in enumerate(data, start=1):
        label = f"{file_name}: entry {number}"
        if isinstance(item, dict) and isinstance(item.get(key), str):
            label += f" ({item[key]})"
        record = _validate(model, item, label, problems)
        if record is not None:
            found.append((label, record))
    return found


def load_catalog(kb_dir: Path | str) -> Catalog:
    """Reads and validates the knowledge base at `kb_dir`.

    Raises KBError listing every problem found, each with the file it is in.
    """
    kb_dir = Path(kb_dir)
    if not kb_dir.is_dir():
        raise KBError([f"{kb_dir}: knowledge base directory is missing"])

    problems: list[str] = []
    kb_version = _read_version(kb_dir, problems)
    function_entries = _read_functions(kb_dir, problems)
    builtin_entries = _read_list(kb_dir, "builtins.yaml", BuiltinRecord, "name", problems)
    market_entries = _read_list(kb_dir, "markets.yaml", Market, "id", problems)

    # One namespace for functions, built-ins and aliases, compared without case.
    defined_in: dict[str, str] = {}

    def claim(name: str, label: str) -> bool:
        first = defined_in.setdefault(name.lower(), label)
        if first is not label:
            problems.append(f"{label}: name {name!r} is already defined in {first}")
            return False
        return True

    functions: dict[str, FunctionRecord] = {}
    for label, function in function_entries:
        if claim(function.name, label):
            functions[function.name.lower()] = function

    builtins: dict[str, BuiltinRecord] = {}
    aliases: dict[str, str] = {}
    for label, builtin in builtin_entries:
        if claim(builtin.name, label):
            builtins[builtin.name.lower()] = builtin
        for alias in builtin.aliases:
            if claim(alias, label):
                aliases[alias.lower()] = builtin.name.lower()

    markets: dict[str, Market] = {}
    for label, market in market_entries:
        if market.id in markets:
            problems.append(f"{label}: market id {market.id!r} is already defined")
        else:
            markets[market.id] = market

    if problems:
        raise KBError(problems)
    return Catalog(
        functions=functions,
        builtins=builtins,
        markets=markets,
        kb_version=kb_version,
        aliases=aliases,
    )
