from copilot.checker import Context, check
from copilot.db.kb import get_functions, load_catalog_from_db


def test_catalog_from_the_database_equals_the_one_from_the_files(indexed, catalog):
    from_db = load_catalog_from_db(indexed)
    assert from_db.kb_version == catalog.kb_version
    assert from_db.functions == catalog.functions
    assert from_db.builtins == catalog.builtins
    assert from_db.aliases == catalog.aliases
    assert from_db.markets == catalog.markets


def test_checker_gives_the_same_result_with_either_catalog(indexed, catalog):
    source = (
        "SetTradeDelays(1, 1, 1, 1);\nBuy = Cross(C, MA(C, 20)) AND Ref(C, 1) > C;\n"
        "Sell = TrailStop(2);\nx = StrFormat();\n"
    )
    context = Context(timeframe="daily")
    assert check(source, load_catalog_from_db(indexed), context) == check(source, catalog, context)


def test_exact_lookup_ignores_case_and_skips_unknown_names(indexed, catalog):
    found = get_functions(indexed, ["applystop", "TIMENUM", "TrailStop", "ApplyStop"])
    assert [f.name for f in found] == ["ApplyStop", "TimeNum"]
    assert found[0] == catalog.function("ApplyStop")


def test_exact_lookup_with_no_names(indexed):
    assert get_functions(indexed, []) == []
