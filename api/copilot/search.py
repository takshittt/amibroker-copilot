"""The two searches over kb_chunks: by keyword and by meaning.

Merging the two result lists and reranking belong to the pipeline.
"""

import re
from dataclasses import dataclass

import psycopg

from copilot.embeddings import vector_literal

_WORD = re.compile(r"[A-Za-z0-9_]+")
_COLUMNS = "kind, ref, title, content, tags, meta"
# Rank weights for text in the body (three unused levels, then B) and in the title (A).
_WEIGHTS = [0.1, 0.1, 0.2, 1.0]


@dataclass(frozen=True)
class Hit:
    kind: str
    ref: str
    title: str
    content: str
    tags: tuple[str, ...]
    meta: dict
    score: float


def _hits(rows: list[dict]) -> list[Hit]:
    return [
        Hit(
            kind=row["kind"],
            ref=row["ref"],
            title=row["title"],
            content=row["content"],
            tags=tuple(row["tags"]),
            meta=row["meta"],
            score=float(row["score"]),
        )
        for row in rows
    ]


def keyword_search(
    conn: psycopg.Connection, query: str, limit: int = 30, kinds: list[str] | None = None
) -> list[Hit]:
    """Full-text search. A chunk matches when it has any of the query's words.

    Chunks holding more of the different words come first. Among those,
    the order follows Postgres's cover-density rank with the title
    weighted well above the body, so an exact function name beats a long
    note that merely mentions it, and words standing together beat words
    far apart. The score is that rank.
    """
    words = list(dict.fromkeys(word.lower() for word in _WORD.findall(query)))
    if not words:
        return []
    # Only letters, digits and underscores reach to_tsquery, so the text is safe to join.
    rows = conn.execute(
        f"select {_COLUMNS}, ts_rank_cd(%s::float4[], tsv, q, 1) as score, "
        "(select count(*) from unnest(%s::text[]) as word "
        " where tsv @@ to_tsquery('english', word)) as matched "
        "from kb_chunks, to_tsquery('english', %s) as q "
        "where tsv @@ q and (%s::text[] is null or kind = any(%s)) "
        "order by matched desc, score desc, kind, ref limit %s",
        (_WEIGHTS, words, " | ".join(words), kinds, kinds, limit),
    ).fetchall()
    return _hits(rows)


def vector_search(
    conn: psycopg.Connection,
    embedding: list[float],
    limit: int = 30,
    kinds: list[str] | None = None,
) -> list[Hit]:
    """Nearest chunks by cosine distance. The score is the cosine similarity.

    This is an exact scan of every chunk, with no vector index: see
    api/migrations/0002_exact_vector_search.sql for why.
    """
    literal = vector_literal(embedding)
    rows = conn.execute(
        f"select {_COLUMNS}, 1 - (embedding <=> %s::vector) as score "
        "from kb_chunks where (%s::text[] is null or kind = any(%s)) "
        "order by embedding <=> %s::vector, kind, ref limit %s",
        (literal, kinds, kinds, literal, limit),
    ).fetchall()
    return _hits(rows)
