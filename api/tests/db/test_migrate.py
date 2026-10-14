import psycopg
import pytest
from psycopg.rows import dict_row

from copilot.config import DEFAULT_EMBEDDING_DIMENSIONS
from copilot.db.migrate import MIGRATIONS_DIR, migrate

TABLES = {
    "users",
    "conversations",
    "messages",
    "runs",
    "feedback",
    "kb_functions",
    "kb_builtins",
    "kb_chunks",
    "kb_state",
    "markets",
    "schema_migrations",
}


def test_fresh_database_gets_every_migration(migrated):
    assert migrated == sorted(path.name for path in MIGRATIONS_DIR.glob("*.sql"))
    assert migrated[0] == "0001_initial.sql"


def test_every_table_exists(db):
    rows = db.execute("select tablename from pg_tables where schemaname = 'public'").fetchall()
    assert {row["tablename"] for row in rows} == TABLES


def test_running_again_applies_nothing(database_url, migrated):
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        assert migrate(conn) == []
        count = conn.execute("select count(*) as n from schema_migrations").fetchone()["n"]
    assert count == len(migrated)


def test_a_failing_migration_leaves_no_trace(database_url, migrated, tmp_path):
    (tmp_path / "9001_good.sql").write_text("create table scratch_good (id integer);")
    (tmp_path / "9002_bad.sql").write_text(
        "create table scratch_bad (id integer); select no_such_function();"
    )
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        try:
            with pytest.raises(psycopg.Error):
                migrate(conn, tmp_path)
            conn.rollback()
            names = {
                row["name"] for row in conn.execute("select name from schema_migrations").fetchall()
            }
            tables = {
                row["tablename"]
                for row in conn.execute(
                    "select tablename from pg_tables where tablename like 'scratch%'"
                ).fetchall()
            }
            assert "9001_good.sql" in names
            assert "9002_bad.sql" not in names
            assert tables == {"scratch_good"}
        finally:
            conn.rollback()
            conn.execute("drop table if exists scratch_good, scratch_bad")
            conn.execute("delete from schema_migrations where name like '900%'")
            conn.commit()


def test_embedding_column_matches_the_configured_size(db):
    row = db.execute(
        "select atttypmod from pg_attribute "
        "where attrelid = 'kb_chunks'::regclass and attname = 'embedding'"
    ).fetchone()
    assert row["atttypmod"] == DEFAULT_EMBEDDING_DIMENSIONS


def test_email_is_unique_whatever_its_case(db):
    db.execute("insert into users (email, name, password_hash) values ('A@x.in', 'A', 'h')")
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute("insert into users (email, name, password_hash) values ('a@X.in', 'B', 'h')")


def test_deleting_a_user_removes_their_history(db):
    user = db.execute(
        "insert into users (email, name, password_hash) values ('u@x.in', 'U', 'h') returning id"
    ).fetchone()["id"]
    conversation = db.execute(
        "insert into conversations (user_id, mode) values (%s, 'write') returning id", (user,)
    ).fetchone()["id"]
    db.execute(
        "insert into messages (conversation_id, role, content) values (%s, 'user', 'hi')",
        (conversation,),
    )
    db.execute("delete from users where id = %s", (user,))
    assert db.execute("select count(*) as n from conversations").fetchone()["n"] == 0
    assert db.execute("select count(*) as n from messages").fetchone()["n"] == 0


def test_conversation_mode_is_restricted(db):
    user = db.execute(
        "insert into users (email, name, password_hash) values ('m@x.in', 'M', 'h') returning id"
    ).fetchone()["id"]
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("insert into conversations (user_id, mode) values (%s, 'chat')", (user,))
