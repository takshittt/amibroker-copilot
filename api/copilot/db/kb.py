"""Reads the knowledge base tables back into a Catalog.

At runtime the checker gets its Catalog from here. The tables are a copy
of the /kb files, so this is the same function list as the files give.
"""

import psycopg

from copilot.kb import Catalog, KBError
from copilot.kb.schema import BuiltinRecord, FunctionRecord, Market

_FUNCTION_COLUMNS = "name, params, is_variadic, returns, description, doc_url, category, since"


def _function(row: dict) -> FunctionRecord:
    return FunctionRecord.model_validate(
        {
            "name": row["name"],
            "category": row["category"],
            "returns": row["returns"],
            "params": row["params"],
            "variadic": row["is_variadic"],
            "description": row["description"],
            "doc_url": row["doc_url"],
            "since": row["since"],
        }
    )


def load_catalog_from_db(conn: psycopg.Connection) -> Catalog:
    """Raises KBError when the indexer has never been run on this database."""
    state = conn.execute("select kb_version from kb_state").fetchone()
    if state is None:
        raise KBError(["the database holds no knowledge base; run the indexer first"])

    functions = {}
    for row in conn.execute(f"select {_FUNCTION_COLUMNS} from kb_functions").fetchall():
        record = _function(row)
        functions[record.name.lower()] = record

    builtins = {}
    aliases = {}
    rows = conn.execute("select name, kind, type, description, aliases from kb_builtins").fetchall()
    for row in rows:
        builtin = BuiltinRecord.model_validate(row)
        builtins[builtin.name.lower()] = builtin
        for alias in builtin.aliases:
            aliases[alias.lower()] = builtin.name.lower()

    markets = {}
    rows = conn.execute(
        "select id, name, exchange, timezone, sessions, dst_rules, last_verified from markets"
    ).fetchall()
    for row in rows:
        market = Market.model_validate(row)
        markets[market.id] = market

    return Catalog(
        functions=functions,
        builtins=builtins,
        markets=markets,
        kb_version=state["kb_version"],
        aliases=aliases,
    )


def get_functions(conn: psycopg.Connection, names: list[str]) -> list[FunctionRecord]:
    """Exact lookup by name, ignoring case. Unknown names are simply absent."""
    keys = sorted({name.lower() for name in names})
    if not keys:
        return []
    rows = conn.execute(
        f"select {_FUNCTION_COLUMNS} from kb_functions where key = any(%s) order by key", (keys,)
    ).fetchall()
    return [_function(row) for row in rows]
