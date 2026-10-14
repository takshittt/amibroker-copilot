import dataclasses

import psycopg
import pytest
from psycopg.rows import dict_row

from copilot.chunks import build_chunks
from copilot.config import DEFAULT_EMBEDDING_DIMENSIONS
from copilot.db.kb import load_catalog_from_db
from copilot.embeddings import FakeEmbedder
from copilot.indexer import index_kb
from copilot.kb import KBError, Notes

TABLES = {
    "kb_functions": "name",
    "kb_builtins": "name",
    "markets": "id",
    "kb_chunks": "kind, ref",
}


def snapshot(db):
    """Every knowledge base row, with embeddings as text so they compare exactly."""
    rows = {}
    for table, order in TABLES.items():
        extra = ", embedding::text as embedding_text" if table == "kb_chunks" else ""
        found = db.execute(f"select *{extra} from {table} order by {order}").fetchall()
        for row in found:
            row.pop("embedding", None)
        rows[table] = found
    return rows


@pytest.fixture
def embedder():
    return FakeEmbedder(DEFAULT_EMBEDDING_DIMENSIONS)


def test_first_run_loads_everything(db, catalog, notes, embedder):
    report = index_kb(db, catalog, notes, embedder)
    expected_chunks = len(build_chunks(catalog, notes))
    assert report.functions == len(catalog.functions) == 447
    assert report.builtins == len(catalog.builtins)
    assert report.markets == len(catalog.markets)
    assert report.chunks == report.embedded == expected_chunks
    assert report.deleted == 0

    rows = snapshot(db)
    assert len(rows["kb_functions"]) == 447
    assert len(rows["kb_chunks"]) == expected_chunks
    state = db.execute("select kb_version from kb_state").fetchall()
    assert state == [{"kb_version": catalog.kb_version}]


def test_running_twice_gives_the_same_rows_and_embeds_nothing(db, catalog, notes, embedder):
    index_kb(db, catalog, notes, embedder)
    first = snapshot(db)
    embedded_after_first = embedder.texts_embedded

    report = index_kb(db, catalog, notes, embedder)

    assert snapshot(db) == first
    assert report.embedded == 0
    assert report.deleted == 0
    assert embedder.texts_embedded == embedded_after_first
    assert db.execute("select count(*) as n from kb_state").fetchone()["n"] == 1


def test_stored_function_keeps_every_field(db, catalog, notes, embedder):
    index_kb(db, catalog, notes, embedder)
    row = db.execute("select * from kb_functions where name = 'StrFormat'").fetchone()
    assert row["is_variadic"] is True
    assert row["key"] == "strformat"
    assert row["params"] == [{"name": "formatstr", "type": "string", "optional": False}]
    assert row["since"] == "4.50"
    assert row["kb_version"] == catalog.kb_version


def test_stored_market_keeps_its_seasonal_rules(db, catalog, notes, embedder):
    index_kb(db, catalog, notes, embedder)
    row = db.execute("select * from markets where id = 'mcx'").fetchone()
    assert {rule["dst_active"]: rule["close"] for rule in row["dst_rules"]} == {
        True: "23:30",
        False: "23:55",
    }
    assert row["sessions"][0]["open"] == "09:00"


def test_only_a_changed_chunk_is_embedded_again(db, catalog, notes, embedder):
    index_kb(db, catalog, notes, embedder)
    before = db.execute(
        "select id, content_hash from kb_chunks where kind = 'mistake' and ref = 'if-on-array'"
    ).fetchone()

    mistake = notes.mistakes["if-on-array"]
    edited = mistake.model_copy(update={"explanation": mistake.explanation + " More words."})
    changed = dataclasses.replace(notes, mistakes={**notes.mistakes, "if-on-array": edited})
    report = index_kb(db, catalog, changed, embedder)

    assert report.embedded == 1
    after = db.execute(
        "select id, content_hash, content from kb_chunks "
        "where kind = 'mistake' and ref = 'if-on-array'"
    ).fetchone()
    assert after["id"] == before["id"]
    assert after["content_hash"] != before["content_hash"]
    assert "More words." in after["content"]


def test_note_that_is_gone_is_deleted(db, catalog, notes, embedder):
    index_kb(db, catalog, notes, embedder)
    fewer = {key: value for key, value in notes.mistakes.items() if key != "if-on-array"}
    report = index_kb(db, catalog, dataclasses.replace(notes, mistakes=fewer), embedder)
    assert report.deleted == 1
    assert report.embedded == 0
    count = db.execute("select count(*) as n from kb_chunks where ref = 'if-on-array'").fetchone()
    assert count["n"] == 0


def test_function_that_is_gone_is_deleted(db, catalog, notes, embedder):
    index_kb(db, catalog, notes, embedder)
    functions = {key: value for key, value in catalog.functions.items() if key != "applystop"}
    report = index_kb(db, dataclasses.replace(catalog, functions=functions), notes, embedder)
    assert report.functions == 446
    assert report.deleted == 1
    assert db.execute("select count(*) as n from kb_functions").fetchone()["n"] == 446
    left = db.execute("select count(*) as n from kb_chunks where ref = 'ApplyStop'").fetchone()
    assert left["n"] == 0


def test_another_embedding_model_embeds_everything_again(db, catalog, notes, embedder):
    first = index_kb(db, catalog, notes, embedder)
    other = FakeEmbedder(DEFAULT_EMBEDDING_DIMENSIONS, model="another-model")
    report = index_kb(db, catalog, notes, other)
    assert report.embedded == first.chunks
    models = db.execute("select distinct embedding_model from kb_chunks").fetchall()
    assert models == [{"embedding_model": "another-model"}]


def test_tags_are_refreshed_without_embedding_again(db, catalog, notes, embedder):
    index_kb(db, catalog, notes, embedder)
    mistake = notes.mistakes["if-on-array"]
    retagged = mistake.model_copy(update={"tags": ["arrays", "iif", "beginner"]})
    changed = dataclasses.replace(notes, mistakes={**notes.mistakes, "if-on-array": retagged})
    report = index_kb(db, catalog, changed, embedder)
    assert report.embedded == 0
    tags = db.execute("select tags from kb_chunks where ref = 'if-on-array'").fetchone()["tags"]
    assert "beginner" in tags


def test_failed_run_rolled_back_by_the_caller_changes_nothing(db, catalog, notes, embedder):
    index_kb(db, catalog, notes, embedder)
    before = snapshot(db)

    class Broken(FakeEmbedder):
        def embed(self, texts):
            raise RuntimeError("embedding service is down")

    mistake = notes.mistakes["if-on-array"]
    edited = mistake.model_copy(update={"explanation": "Different."})
    changed = dataclasses.replace(notes, mistakes={**notes.mistakes, "if-on-array": edited})
    fewer = {key: value for key, value in catalog.functions.items() if key != "ma"}
    # The way the command line runs it: one transaction around the whole run.
    with pytest.raises(RuntimeError, match="down"), db.transaction():
        index_kb(
            db,
            dataclasses.replace(catalog, functions=fewer),
            changed,
            Broken(DEFAULT_EMBEDDING_DIMENSIONS),
        )
    assert snapshot(db) == before


def test_index_kb_does_not_commit(database_url, migrated, catalog, notes, embedder):
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        index_kb(conn, catalog, notes, embedder)
        conn.rollback()
        assert conn.execute("select count(*) as n from kb_functions").fetchone()["n"] == 0


def test_embedding_of_the_wrong_size_is_refused(db, catalog, notes):
    class WrongSize(FakeEmbedder):
        def embed(self, texts):
            return [[0.1, 0.2] for _ in texts]

    with pytest.raises(RuntimeError, match="2 numbers"):
        index_kb(db, catalog, notes, WrongSize(DEFAULT_EMBEDDING_DIMENSIONS))


def test_empty_notes_index_functions_only(db, catalog, embedder):
    report = index_kb(db, catalog, Notes(), embedder)
    kinds = db.execute("select distinct kind from kb_chunks").fetchall()
    assert kinds == [{"kind": "function"}]
    assert report.chunks == sum(1 for f in catalog.functions.values() if f.description)


def test_database_that_was_never_indexed(db):
    with pytest.raises(KBError, match="run the indexer"):
        load_catalog_from_db(db)
