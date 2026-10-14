"""Builds function records from saved pages of the official AFL reference.

A maintenance tool, run by hand. It is not part of the checker or the
pipeline, and CI never runs it.

    python -m copilot.kb.importer fetch <cache directory>
    python -m copilot.kb.importer write <cache directory> <kb directory>
    python -m copilot.kb.importer compare <cache directory> <kb directory>

Only facts are taken from a page: the function's name, its parameter
names, which parameters have defaults, the return type, the category and
the version that introduced it. The page's descriptive text is never
stored; descriptions in /kb are written by hand in our own words.

`write` never changes a file that already exists, so hand-made
corrections in /kb survive a re-run.
"""

import html
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from copilot.kb.catalog import KBError, load_catalog
from copilot.kb.schema import FunctionRecord

REFERENCE_URL = "https://www.amibroker.com/guide/afl/"
INDEX_URL = "https://www.amibroker.com/guide/a_funref.html"

# AmiBroker's category headings -> ours. Hand edits in /kb refine these.
CATEGORIES = {
    "Math functions": "math",
    "Indicators": "indicator",
    "Moving averages, summation": "indicator",
    "Exploration / Indicators": "plot",
    "Trading system toolbox": "backtest",
    "Date/Time": "time",
    "Lowest/Highest": "lookup",
    "Statistical functions": "statistics",
    "Basic price pattern detection": "pattern",
    "Composites": "composite",
    "Referencing other symbol data": "foreign",
    "Time Frame functions": "timeframe",
    "String manipulation": "string",
    "Information / Categories": "info",
    "File Input/Output functions": "file",
    "Low-level graphics": "graphics",
    "GUI functions": "gui",
    "Matrix functions": "matrix",
    "Text-to-Speech functions": "speech",
    "Miscellaneous functions": "misc",
    "Map functions": "misc",
}

_RETURNS = {"ARRAY": "array", "NUMBER": "number", "STRING": "string", "NOTHING": "none"}

Param = tuple[str, str, bool]  # name, type, optional


def _p(spec: str) -> list[Param]:
    """Shorthand for override tables: "name:type" items, `?` marks optional."""
    params = []
    for item in spec.split():
        name, _, kind = item.partition(":")
        params.append((name, kind.rstrip("?"), kind.endswith("?")))
    return params


# Pages whose syntax or returns line is incomplete, mistyped or ambiguous.
# Each entry replaces what the page would give. Keys are lower-case names.
OVERRIDES: dict[str, dict] = {
    # Variadic: the page lists example arguments that are not all required.
    "printf": {"params": _p("formatstr:string"), "variadic": True},
    "strformat": {"params": _p("formatstr:string"), "variadic": True},
    "_tracef": {"params": _p("formatstr:string"), "variadic": True},
    "setsortcolumns": {"params": _p("col1:any"), "variadic": True},
    "addsummaryrows": {"params": _p("flags:any format:any? onlycols:any?"), "variadic": True},
    # "Two or more points", so two x, y pairs are required.
    "gfxpolygon": {"params": _p("x1:any y1:any x2:any y2:any"), "variadic": True},
    "gfxpolyline": {"params": _p("x1:any y1:any x2:any y2:any"), "variadic": True},
    # The syntax line is cut short or has no brackets; taken from the page's text and example.
    "createobject": {"params": _p("server_class:string")},
    "createstaticobject": {"params": _p("server_class:string")},
    "gettradinginterface": {"params": _p("name:string")},
    "getpricestyle": {"params": []},
    "internetgetstatuscode": {"params": _p("handle:any?")},
    # The RETURNS cell is empty; taken from the page's text where it says.
    "reverse": {"returns": "array"},
    "staticvarsettext": {"returns": "number"},
    "guicheckbox": {"returns": "number"},
    "guisetcheck": {"returns": "any"},
    "getextradataforeign": {"returns": "any"},
    # Given a single number these give a single number, although the page says ARRAY.
    "isempty": {"returns": "any"},
    "istrue": {"returns": "any"},
    # Checked by hand and correct as the importer reads them: a second
    # function on the page, or a syntax line that misspells the name.
    "rsi": {},
    "cci": {},
    "strsort": {},
    "staticvargenerateranks": {},
}


@dataclass(frozen=True)
class Page:
    key: str  # file name without .html
    name: str
    category_text: str
    since: str | None
    syntax: str
    returns: str


_PAGE = re.compile(r"AFL Function Reference - \S+ (.*?) SYNTAX (.*?) RETURNS (.*?) ?FUNCTION ")
_VERSION = re.compile(r"\(AmiBroker ([0-9.]+)\)\s*$")


def parse_page(key: str, page_html: str) -> Page | None:
    """Reads one saved reference page. Returns None if it is not one."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", page_html))
    text = re.sub(r"\s+", " ", text)
    match = _PAGE.search(text)
    if match is None:
        return None
    heading, syntax, returns = (part.strip() for part in match.groups())

    since = None
    version = _VERSION.search(heading)
    if version:
        since = version.group(1)
        if "." not in since:  # the site writes 5.0 as "50"
            since = f"{since[:-1]}.{since[-1]}"
        heading = heading[: version.start()].strip()

    category_text = next(
        (known for known in sorted(CATEGORIES, key=len, reverse=True) if heading.endswith(known)),
        "",
    )
    name = heading.split(" - ")[0].strip()
    return Page(key, name, category_text, since, syntax, returns)


_FORM = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(([^()]*)\)")
_QUOTED = re.compile(r"''[^']*''|\"[^\"]*\"|``[^`]*``")
_QUOTES = "'\"`"


def _identifier(raw: str, taken: set[str]) -> str:
    name = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_") or "arg"
    if name[0].isdigit():
        name = f"p{name}"
    unique = name
    number = 2
    while unique in taken:
        unique = f"{name}_{number}"
        number += 1
    taken.add(unique)
    return unique


def parse_forms(syntax: str) -> list[tuple[str, list[Param], bool]]:
    """Returns (name, parameters, variadic) for each call form in a syntax line."""
    forms = []
    for name, inside in _FORM.findall(syntax):
        inside = re.sub(r"=\s*','", "= COMMA", inside)  # a default that is a comma
        inside = _QUOTED.sub(lambda quoted: quoted.group().replace(",", " "), inside)
        params: list[Param] = []
        variadic = False
        taken: set[str] = set()
        for piece in inside.split(","):
            piece = piece.strip()
            if not piece:
                continue
            if set(piece) <= set(". "):
                variadic = True
                continue
            raw, equals, _ = piece.partition("=")
            ident = _identifier(raw, taken)
            if any(quote in raw for quote in _QUOTES) or ident == "string":
                kind = "string"
            elif re.fullmatch(r"array[0-9]*", ident):
                kind = "array"
            else:
                kind = "any"
            params.append((ident, kind, bool(equals)))
        forms.append((name, params, variadic))
    return forms


def _merge(forms: list[tuple[str, list[Param], bool]]) -> tuple[list[Param], bool]:
    """One parameter list covering every form of the same function."""
    if not forms:
        return [], False
    longest = max(forms, key=lambda form: len(form[1]))[1]
    required = min(sum(1 for param in form[1] if not param[2]) for form in forms)
    params: list[Param] = []
    optional_seen = False
    for position, (name, kind, optional) in enumerate(longest):
        optional_seen = optional_seen or optional or position >= required
        params.append((name, kind, optional_seen))
    return params, any(form[2] for form in forms)


def _returns(written: str, category: str) -> str:
    plain = re.sub(r"\(.*?\)", "", written).strip().upper()
    kind = _RETURNS.get(plain, "any")
    # A maths function gives a number for a number, whatever the page says.
    if kind == "array" and category == "math":
        return "any"
    return kind


def _record(
    name: str, page: Page, params: list[Param], variadic: bool, returns: str, category: str
) -> dict:
    record: dict = {
        "name": name,
        "category": category,
        "returns": returns,
        "params": [{"name": n, "type": t, "optional": o} for n, t, o in params],
    }
    if variadic:
        record["variadic"] = True
    record["doc_url"] = f"{REFERENCE_URL}{page.key}.html"
    if page.since:
        record["since"] = page.since
    return record


def build_records(page: Page, own_pages: set[str]) -> tuple[list[dict], list[str]]:
    """Returns the records a page gives, and notes on anything a person should check.

    `own_pages` holds the keys of every page, so that a second function
    named on this page is left alone when it has a page of its own.
    """
    if page.name.startswith("#"):
        return [], []  # #include and #pragma are directives, not functions

    notes: list[str] = []
    category = CATEGORIES.get(page.category_text)
    if category is None:
        category = "misc"
        notes.append(f"{page.name}: unknown category {page.category_text!r}; filed as misc")

    forms = parse_forms(page.syntax)
    own = [form for form in forms if form[0].lower() == page.name.lower()]
    others: dict[str, list] = {}
    for form in forms:
        if form[0].lower() != page.name.lower():
            others.setdefault(form[0], []).append(form)

    if not forms:
        notes.append(f"{page.name}: no call form found in {page.syntax!r}")
    elif not own:
        # The page's syntax line carries a different name (a slip on the page).
        wrong = next(iter(others))
        notes.append(f"{page.name}: the syntax line calls it {wrong}; its parameters are used")
        own = others.pop(wrong)

    params, variadic = _merge(own)
    returns = _returns(page.returns, category)
    if not page.returns:
        notes.append(f"{page.name}: the RETURNS cell is empty; recorded as any")
    if variadic:
        notes.append(f"{page.name}: variadic; check which arguments are required")

    override = OVERRIDES.get(page.name.lower())
    if override is not None:
        params = override.get("params", params)
        variadic = override.get("variadic", variadic)
        returns = override.get("returns", returns)
        notes = [note for note in notes if not note.startswith(f"{page.name}:")]

    records = [_record(page.name, page, params, variadic, returns, category)]
    for other, other_forms in others.items():
        if other.lower() in own_pages:
            continue
        other_params, other_variadic = _merge(other_forms)
        records.append(_record(other, page, other_params, other_variadic, returns, category))
        if override is None:
            notes.append(f"{page.name}: second function {other} on the same page")

    for record in records:
        FunctionRecord.model_validate(record)
    return records, notes


def to_yaml(record: dict) -> str:
    """Formats a record the way the files in kb/functions are written."""
    lines = [
        f"name: {record['name']}",
        f"category: {record['category']}",
        f"returns: {record['returns']}",
    ]
    if record["params"]:
        lines.append("params:")
        for param in record["params"]:
            optional = "true" if param["optional"] else "false"
            lines.append(
                f"  - {{name: {param['name']}, type: {param['type']}, optional: {optional}}}"
            )
    else:
        lines.append("params: []")
    if record.get("variadic"):
        lines.append("variadic: true")
    lines.append(f"doc_url: {record['doc_url']}")
    if record.get("since"):
        lines.append(f'since: "{record["since"]}"')
    return "\n".join(lines) + "\n"


def _build_all(cache: Path) -> tuple[list[dict], list[str]]:
    paths = sorted(cache.glob("*.html"))
    own_pages = {path.stem for path in paths}
    records: list[dict] = []
    notes: list[str] = []
    for path in paths:
        page = parse_page(path.stem, path.read_text(encoding="utf-8", errors="replace"))
        if page is None:
            if not path.stem.startswith("_include") and path.stem != "_pragma":
                notes.append(f"{path.name}: not a reference page")
            continue
        found, page_notes = build_records(page, own_pages)
        records.extend(found)
        notes.extend(page_notes)
    return records, notes


def _fetch(cache: Path) -> int:
    from urllib.request import urlopen  # only this action touches the network

    cache.mkdir(parents=True, exist_ok=True)
    with urlopen(INDEX_URL, timeout=30) as response:  # noqa: S310 (fixed https URL)
        index = response.read().decode("utf-8", errors="replace")
    keys = sorted(set(re.findall(r'href="\./afl/([a-z0-9_]+)\.html"', index, re.IGNORECASE)))
    fetched = 0
    for key in keys:
        target = cache / f"{key.lower()}.html"
        if target.exists():
            continue
        with urlopen(f"{REFERENCE_URL}{key}.html", timeout=30) as response:  # noqa: S310
            target.write_bytes(response.read())
        fetched += 1
    print(f"{len(keys)} pages in the index, {fetched} downloaded to {cache}")
    return 0


def _write(cache: Path, kb_dir: Path) -> int:
    records, notes = _build_all(cache)
    functions = kb_dir / "functions"
    functions.mkdir(parents=True, exist_ok=True)
    written = 0
    for record in records:
        target = functions / f"{record['name'].lower()}.yaml"
        if target.exists():
            continue
        target.write_text(to_yaml(record), encoding="utf-8")
        written += 1
    for note in notes:
        print(f"check: {note}")
    print(f"{len(records)} functions on the pages, {written} written, {len(notes)} to check")
    return 0


def _compare(cache: Path, kb_dir: Path) -> int:
    records, _ = _build_all(cache)
    try:
        catalog = load_catalog(kb_dir)
    except KBError as error:
        for problem in error.problems:
            print(problem, file=sys.stderr)
        return 1
    missing = 0
    differ = 0
    for record in records:
        page = FunctionRecord.model_validate(record)
        ours = catalog.function(page.name)
        if ours is None:
            missing += 1
            print(f"missing: {page.name}")
            continue
        theirs = (page.min_args, page.max_args, page.returns)
        if (ours.min_args, ours.max_args, ours.returns) != theirs:
            differ += 1
            print(
                f"differs: {page.name}: kb has {ours.min_args}..{ours.max_args} -> "
                f"{ours.returns}, the page gives {theirs[0]}..{theirs[1]} -> {theirs[2]}"
            )
    print(f"{len(records)} functions on the pages, {missing} missing from the kb, {differ} differ")
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 2 and args[0] == "fetch":
        return _fetch(Path(args[1]))
    if len(args) == 3 and args[0] == "write":
        return _write(Path(args[1]), Path(args[2]))
    if len(args) == 3 and args[0] == "compare":
        return _compare(Path(args[1]), Path(args[2]))
    print(
        "usage: python -m copilot.kb.importer fetch <cache>\n"
        "       python -m copilot.kb.importer write <cache> <kb>\n"
        "       python -m copilot.kb.importer compare <cache> <kb>",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
