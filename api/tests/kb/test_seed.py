"""The real knowledge base in /kb loads and holds what stage 2 needs."""

from pathlib import Path

import pytest

from copilot.kb import load_catalog

KB_DIR = Path(__file__).resolve().parents[3] / "kb"

# The functions plan.md names for the stage 1 seed.
PLANNED_FUNCTIONS = [
    "MA",
    "EMA",
    "RSI",
    "ATR",
    "Cross",
    "Ref",
    "IIf",
    "ExRem",
    "ApplyStop",
    "SetTradeDelays",
    "TimeNum",
    "Param",
    "Plot",
    "HHV",
    "LLV",
    "ValueWhen",
]

V1_MARKETS = ["nse_eq", "nse_fo", "bse_eq", "mcx", "nyse", "nasdaq", "lse", "crypto"]


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(KB_DIR)


def test_real_kb_loads(catalog):
    assert len(catalog.functions) >= 40
    assert catalog.kb_version >= 1


@pytest.mark.parametrize("name", PLANNED_FUNCTIONS)
def test_planned_function_is_present(catalog, name):
    assert catalog.function(name) is not None


def test_argument_counts_of_functions_the_rules_depend_on(catalog):
    assert (catalog.function("Ref").min_args, catalog.function("Ref").max_args) == (2, 2)
    assert (catalog.function("ExRem").min_args, catalog.function("ExRem").max_args) == (2, 2)
    delays = catalog.function("SetTradeDelays")
    assert (delays.min_args, delays.max_args) == (4, 4)
    assert (catalog.function("RSI").min_args, catalog.function("RSI").max_args) == (0, 1)
    assert catalog.function("TimeNum").max_args == 0


def test_return_types_the_array_rule_depends_on(catalog):
    assert catalog.function("MA").returns == "array"
    assert catalog.function("Param").returns == "number"
    assert catalog.function("LastValue").returns == "number"
    assert catalog.function("SetTradeDelays").returns == "none"
    # Array or number depending on the arguments, so the type is not known.
    assert catalog.function("IIf").returns == "any"


PRICE_ALIASES = {"O": "Open", "H": "High", "L": "Low", "C": "Close", "V": "Volume", "OI": "OpenInt"}


@pytest.mark.parametrize(("alias", "name"), PRICE_ALIASES.items())
def test_price_aliases_resolve(catalog, alias, name):
    assert catalog.builtin(alias).name == name
    assert catalog.builtin(name).type == "array"


@pytest.mark.parametrize(
    "name",
    ["Buy", "Sell", "Short", "Cover", "BuyPrice", "SellPrice", "ShortPrice", "CoverPrice"],
)
def test_signal_and_price_variables_are_present(catalog, name):
    assert catalog.builtin(name).kind == "variable"


@pytest.mark.parametrize("name", ["True", "False", "Null", "stopTypeTrailing", "stopModePoint"])
def test_constants_are_present(catalog, name):
    assert catalog.builtin(name).kind == "constant"


def test_v1_markets_are_present(catalog):
    assert sorted(catalog.markets) == sorted(V1_MARKETS)


def test_mcx_has_one_close_for_each_us_daylight_saving_season(catalog):
    rules = catalog.market("mcx").dst_rules
    assert len(rules) == 2
    assert {rule.reference_timezone for rule in rules} == {"America/New_York"}
    assert {rule.dst_active for rule in rules} == {True, False}
    assert len({rule.close for rule in rules}) == 2


def test_only_mcx_has_seasonal_rules(catalog):
    assert [m.id for m in catalog.markets.values() if m.dst_rules] == ["mcx"]


# Functions documented on another function's reference page.
SHARED_PAGES = {"rsia": "rsi", "ccia": "cci"}


def test_every_function_links_to_its_reference_page(catalog):
    for key, function in catalog.functions.items():
        page = SHARED_PAGES.get(key, key)
        assert function.doc_url == f"https://www.amibroker.com/guide/afl/{page}.html"


def test_the_full_function_list_is_present(catalog):
    assert len(catalog.functions) == 447
    assert catalog.kb_version >= 2


def test_functions_that_take_any_number_of_arguments(catalog):
    variadic = sorted(f.name for f in catalog.functions.values() if f.variadic)
    assert variadic == [
        "AddSummaryRows",
        "GfxPolygon",
        "GfxPolyline",
        "SetSortColumns",
        "StrFormat",
        "_TRACEF",
        "printf",
    ]
    assert catalog.function("StrFormat").min_args == 1
    assert catalog.function("StrFormat").max_args is None


def test_functions_v1_generates_from_all_have_a_description(catalog):
    in_scope = {
        "indicator",
        "signal",
        "stops",
        "sizing",
        "time",
        "plot",
        "param",
        "math",
        "exploration",
        "statistics",
        "pattern",
    }
    missing = sorted(
        f.name for f in catalog.functions.values() if f.category in in_scope and not f.description
    )
    assert missing == []


def test_descriptions_that_warn_about_looking_ahead(catalog):
    for name in ["Peak", "Trough", "ZIG", "Ref"]:
        assert "ahead" in catalog.function(name).description
