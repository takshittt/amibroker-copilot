"""Step 3: find the notes and functions the code will need.

Each query is searched by keyword and by meaning, and its two rankings
are merged with Reciprocal Rank Fusion. The queries' merged lists are
then interleaved, so every part of the strategy keeps its own best
notes. Some items skip the search and
are always included: functions the user named, the market's session
times, and the mistakes that matter for this kind of request.
"""

import re
from dataclasses import dataclass, field

import psycopg

from copilot.checker import Context
from copilot.chunks import signature
from copilot.config import Settings
from copilot.embeddings import Embedder
from copilot.kb import Catalog
from copilot.kb.schema import FunctionRecord, Market
from copilot.pipeline.brief import Brief
from copilot.pipeline.decompose import decompose
from copilot.search import Hit, chunks_with_tags, keyword_search, vector_search

RRF_K = 60
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MISTAKES_FROM_SEARCH = 3

# The categories v1 writes code from. A function outside them is real, and
# the checker accepts it in pasted code, but the generator is not offered it.
GENERATION_CATEGORIES = frozenset(
    [
        "indicator",
        "signal",
        "stops",
        "sizing",
        "time",
        "plot",
        "param",
        "math",
        "lookup",
        "backtest",
        "exploration",
        "statistics",
        "pattern",
        "string",
        "info",
    ]
)


@dataclass(frozen=True)
class Item:
    """One thing shown to the model: a note, a function or the market."""

    kind: str
    ref: str
    title: str
    content: str
    meta: dict = field(default_factory=dict, hash=False, compare=False)
    # Pinned items skip the reranker and always reach the generator.
    pinned: bool = False

    @property
    def key(self) -> tuple[str, str]:
        return (self.kind, self.ref)


@dataclass(frozen=True)
class Retrieved:
    queries: list[str]
    pinned: list[Item]
    candidates: list[Item]  # best first; none of them pinned


def rrf(rankings: list[list], k: int = RRF_K) -> list[tuple]:
    """Reciprocal Rank Fusion: score = sum of 1 / (k + rank) over the lists.

    Uses ranks, not scores, because the searches score on different
    scales. Returns (key, score), best first; ties keep a fixed order.
    """
    scores: dict = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


def names_in_text(text: str, catalog: Catalog) -> list[FunctionRecord]:
    """Functions the user named, for exact lookup.

    Many function names are ordinary words (Max, Day, Cross, Hold), so a
    word counts only when it is clearly meant as a function: it is
    followed by a bracket, or it is written exactly as AmiBroker writes
    it and that spelling is not a plain word (ApplyStop, TimeNum, RSI),
    or it is an all-capitals name of three or more letters in any case
    (rsi, macd).
    """
    found: dict[str, FunctionRecord] = {}
    for match in _WORD.finditer(text):
        word = match.group()
        record = catalog.function(word)
        if record is None:
            continue
        called = text[match.end() :].lstrip().startswith("(")
        name = record.name
        acronym = name.isupper() and len(name) >= 3
        distinctive = word == name and (
            name.isupper() or "_" in name or any(ch.isupper() for ch in name[1:])
        )
        if called or acronym or distinctive:
            found.setdefault(record.name.lower(), record)
    return list(found.values())


def function_item(record: FunctionRecord, pinned: bool = False) -> Item:
    content = signature(record)
    if record.description:
        content += f"\n{record.description}"
    return Item(
        kind="function",
        ref=record.name,
        title=record.name,
        content=content,
        meta={"category": record.category, "returns": record.returns, "doc_url": record.doc_url},
        pinned=pinned,
    )


def market_item(market: Market) -> Item:
    """The market's session times, in the exchange's own time zone."""
    lines = [f"{market.name} ({market.exchange}). Times are in the {market.timezone} time zone."]
    if market.never_closes:
        lines.append("This market never closes: it trades all day, every day.")
    for session in market.sessions:
        if market.never_closes:
            break
        days = ", ".join(session.days)
        lines.append(f"Session '{session.name}': {session.open} to {session.close} on {days}.")
    for rule in market.dst_rules:
        season = "is on daylight saving time" if rule.dst_active else "is on standard time"
        lines.append(
            f"While {rule.reference_timezone} {season}, session '{rule.session}' closes "
            f"at {rule.close} instead."
        )
    if market.dst_rules:
        lines.append(
            "Because the close moves during the year, the exit time must be a parameter "
            "the trader can change."
        )
    return Item("market", market.id, f"Market: {market.name}", "\n".join(lines), pinned=True)


def hit_item(hit: Hit, pinned: bool = False) -> Item:
    return Item(hit.kind, hit.ref, hit.title, hit.content, hit.meta, pinned)


def interleave(rankings: list[list]) -> list:
    """Takes the best of each list in turn, then the second best of each, and so on.

    This keeps every query's top results near the front, so each part of
    the strategy gets its own notes whatever the other parts found.
    """
    merged: dict = {}
    for position in range(max((len(ranking) for ranking in rankings), default=0)):
        for ranking in rankings:
            if position < len(ranking):
                merged.setdefault(ranking[position], None)
    return list(merged)


def search_queries(
    conn: psycopg.Connection,
    embedder: Embedder,
    queries: list[str],
    settings: Settings,
    kinds: list[str] | None = None,
) -> list[Hit]:
    """Searches every query by keyword and by meaning.

    The two rankings of one query are merged with Reciprocal Rank Fusion.
    The merged lists of the different queries are then interleaved.
    """
    if not queries:
        return []
    hits: dict[tuple[str, str], Hit] = {}
    per_query: list[list[tuple[str, str]]] = []
    vectors = embedder.embed(queries)
    for query, vector in zip(queries, vectors, strict=True):
        by_keyword = keyword_search(conn, query, limit=settings.search_limit, kinds=kinds)
        by_meaning = vector_search(conn, vector, limit=settings.search_limit, kinds=kinds)
        for hit in (*by_keyword, *by_meaning):
            hits.setdefault((hit.kind, hit.ref), hit)
        fused = rrf([[(h.kind, h.ref) for h in by_keyword], [(h.kind, h.ref) for h in by_meaning]])
        per_query.append([key for key, _ in fused])
    return [hits[key] for key in interleave(per_query)]


def mistake_tags(brief: Brief, failed_rules: tuple[str, ...] = ()) -> list[str]:
    """The tags whose mistake entries are always shown for this request: the
    rules the last attempt broke, and the kinds of mistake that fit the brief."""
    tags = [f"rule-{rule}" for rule in failed_rules]
    if brief.kind == "strategy":
        tags.append("backtest")
        if Context(timeframe=brief.timeframe).is_intraday:
            tags.append("intraday")
    return tags


def retrieve(
    conn: psycopg.Connection,
    embedder: Embedder,
    catalog: Catalog,
    settings: Settings,
    brief: Brief,
    text: str,
    failed_rules: tuple[str, ...] = (),
    extra_queries: tuple[str, ...] = (),
) -> Retrieved:
    """`failed_rules` and `extra_queries` are for a retry: the checker rules
    the last attempt broke, and searches for the parts that went wrong."""
    queries = list(dict.fromkeys([*decompose(brief), *extra_queries]))
    market = catalog.market(brief.market_id)

    pinned: dict[tuple[str, str], Item] = {}

    def pin(item: Item) -> None:
        pinned.setdefault(item.key, item)

    if market is not None:
        pin(market_item(market))
    for record in names_in_text(text, catalog):
        pin(function_item(record, pinned=True))

    # Mistakes: the ones tagged for this request, and the best few found by searching.
    for hit in chunks_with_tags(conn, "mistake", mistake_tags(brief, failed_rules)):
        pin(hit_item(hit, pinned=True))
    for hit in search_queries(conn, embedder, queries, settings, kinds=["mistake"])[
        :_MISTAKES_FROM_SEARCH
    ]:
        pin(hit_item(hit, pinned=True))

    candidates = [
        hit_item(hit)
        for hit in search_queries(conn, embedder, queries, settings)
        if (hit.kind, hit.ref) not in pinned
    ]
    return Retrieved(queries, list(pinned.values()), candidates[: settings.candidate_limit])


def allowed_function_names(catalog: Catalog) -> list[str]:
    """The names the generator may use, read from the one function list."""
    return sorted(
        (f.name for f in catalog.functions.values() if f.category in GENERATION_CATEGORIES),
        key=str.lower,
    )
