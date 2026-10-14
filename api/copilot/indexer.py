"""Loads the knowledge base files into Postgres.

    python -m copilot.indexer <kb directory> [--fake-embeddings]

The database tables are a copy of /kb and nothing else writes them, so
running the indexer again brings them back in line with the files. Only
chunks whose text changed are embedded again.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from copilot.chunks import Chunk, build_chunks
from copilot.config import ConfigError, load_settings
from copilot.db.connection import connect
from copilot.embeddings import Embedder, FakeEmbedder, OpenAIEmbedder, vector_literal
from copilot.kb import Catalog, KBError, Notes, load_catalog, load_notes
from copilot.kb.notes import cross_check


@dataclass(frozen=True)
class IndexReport:
    kb_version: int
    functions: int
    builtins: int
    markets: int
    chunks: int
    embedded: int
    deleted: int


def index_kb(
    conn: psycopg.Connection, catalog: Catalog, notes: Notes, embedder: Embedder
) -> IndexReport:
    """Makes the knowledge base tables match `catalog` and `notes`.

    Does not commit. Call it inside a transaction: the caller commits on
    success and rolls back on failure, so a failed run changes nothing.
    """
    version = catalog.kb_version
    with conn.cursor() as cursor:
        cursor.execute("delete from kb_functions")
        cursor.executemany(
            "insert into kb_functions (name, params, is_variadic, returns, description, "
            "doc_url, category, since, kb_version) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    f.name,
                    Jsonb([p.model_dump() for p in f.params]),
                    f.variadic,
                    f.returns,
                    f.description,
                    f.doc_url,
                    f.category,
                    f.since,
                    version,
                )
                for f in catalog.functions.values()
            ],
        )
        cursor.execute("delete from kb_builtins")
        cursor.executemany(
            "insert into kb_builtins (name, kind, type, description, aliases, kb_version) "
            "values (%s, %s, %s, %s, %s, %s)",
            [
                (b.name, b.kind, b.type, b.description, list(b.aliases), version)
                for b in catalog.builtins.values()
            ],
        )
        cursor.execute("delete from markets")
        cursor.executemany(
            "insert into markets (id, name, exchange, timezone, sessions, dst_rules, "
            "last_verified, kb_version) values (%s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    m.id,
                    m.name,
                    m.exchange,
                    m.timezone,
                    Jsonb([s.model_dump() for s in m.sessions]),
                    Jsonb([r.model_dump() for r in m.dst_rules]),
                    m.last_verified,
                    version,
                )
                for m in catalog.markets.values()
            ],
        )

        chunks = build_chunks(catalog, notes)
        embedded, deleted = _sync_chunks(cursor, chunks, embedder, version)

        cursor.execute(
            "insert into kb_state (singleton, kb_version, indexed_at) values (true, %s, now()) "
            "on conflict (singleton) do update set kb_version = excluded.kb_version, "
            "indexed_at = excluded.indexed_at",
            (version,),
        )
    return IndexReport(
        kb_version=version,
        functions=len(catalog.functions),
        builtins=len(catalog.builtins),
        markets=len(catalog.markets),
        chunks=len(chunks),
        embedded=embedded,
        deleted=deleted,
    )


def _sync_chunks(
    cursor: psycopg.Cursor, chunks: list[Chunk], embedder: Embedder, version: int
) -> tuple[int, int]:
    """Returns how many chunks were embedded and how many old ones were deleted."""
    cursor.execute("select kind, ref, content_hash, embedding_model from kb_chunks")
    stored = {(row["kind"], row["ref"]): row for row in cursor.fetchall()}

    unchanged: list[Chunk] = []
    changed: list[Chunk] = []
    for chunk in chunks:
        row = stored.get((chunk.kind, chunk.ref))
        same = (
            row is not None
            and row["content_hash"] == chunk.content_hash
            and row["embedding_model"] == embedder.model
        )
        (unchanged if same else changed).append(chunk)

    # Tags and extra fields are not part of the embedded text, so refresh them anyway.
    cursor.executemany(
        "update kb_chunks set tags = %s, meta = %s, kb_version = %s where kind = %s and ref = %s",
        [(list(c.tags), Jsonb(c.meta), version, c.kind, c.ref) for c in unchanged],
    )

    vectors = embedder.embed([chunk.text for chunk in changed]) if changed else []
    if len(vectors) != len(changed):
        raise RuntimeError(f"asked for {len(changed)} embeddings but got {len(vectors)}")
    for vector in vectors:
        if len(vector) != embedder.dimensions:
            raise RuntimeError(
                f"an embedding has {len(vector)} numbers but {embedder.dimensions} are expected"
            )
    cursor.executemany(
        "insert into kb_chunks (kind, ref, title, content, tags, meta, content_hash, "
        "embedding, embedding_model, kb_version) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s) "
        "on conflict (kind, ref) do update set title = excluded.title, "
        "content = excluded.content, tags = excluded.tags, meta = excluded.meta, "
        "content_hash = excluded.content_hash, embedding = excluded.embedding, "
        "embedding_model = excluded.embedding_model, kb_version = excluded.kb_version",
        [
            (
                c.kind,
                c.ref,
                c.title,
                c.content,
                list(c.tags),
                Jsonb(c.meta),
                c.content_hash,
                vector_literal(vector),
                embedder.model,
                version,
            )
            for c, vector in zip(changed, vectors, strict=True)
        ],
    )

    current = {(chunk.kind, chunk.ref) for chunk in chunks}
    gone = [key for key in stored if key not in current]
    cursor.executemany("delete from kb_chunks where kind = %s and ref = %s", gone)
    return len(changed), len(gone)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    fake = "--fake-embeddings" in args
    args = [arg for arg in args if arg != "--fake-embeddings"]
    if len(args) != 1:
        print(
            "usage: python -m copilot.indexer <kb directory> [--fake-embeddings]", file=sys.stderr
        )
        return 2

    try:
        catalog = load_catalog(Path(args[0]))
        notes = load_notes(Path(args[0]))
        problems = cross_check(catalog, notes)
        if problems:
            raise KBError(problems)
    except KBError as error:
        for problem in error.problems:
            print(problem, file=sys.stderr)
        print("The knowledge base has problems; nothing was indexed.", file=sys.stderr)
        return 1

    try:
        settings = load_settings()
        if fake:
            embedder: Embedder = FakeEmbedder(settings.embedding_dimensions)
        else:
            embedder = OpenAIEmbedder.from_settings(settings)
        conn = connect(settings)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 2

    with conn:  # commits on success, rolls back if indexing raises
        report = index_kb(conn, catalog, notes, embedder)
    print(
        f"Indexed kb_version {report.kb_version}: {report.functions} functions, "
        f"{report.builtins} built-ins, {report.markets} markets, {report.chunks} chunks "
        f"({report.embedded} embedded with {embedder.model}, {report.deleted} removed)"
    )
    if fake:
        print("Fake embeddings were used: keyword search works, search by meaning does not.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
