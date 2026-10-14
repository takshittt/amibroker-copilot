import datetime

import pytest
from pydantic import ValidationError

from copilot.kb.schema import BuiltinRecord, FunctionRecord, Market


def function_data(**changes):
    data = {
        "name": "ApplyStop",
        "category": "stops",
        "returns": "none",
        "params": [
            {"name": "type", "type": "number", "optional": False},
            {"name": "mode", "type": "number", "optional": False},
            {"name": "amount", "type": "any", "optional": False},
            {"name": "exitatstop", "type": "number", "optional": True},
        ],
        "description": "Sets a stop for the backtester.",
        "doc_url": "https://www.amibroker.com/guide/afl/applystop.html",
    }
    data.update(changes)
    return data


def builtin_data(**changes):
    data = {
        "name": "Close",
        "kind": "variable",
        "type": "array",
        "description": "Closing price of each bar.",
        "aliases": ["C"],
    }
    data.update(changes)
    return data


def market_data(**changes):
    data = {
        "id": "mcx",
        "name": "MCX commodities",
        "exchange": "MCX",
        "timezone": "Asia/Kolkata",
        "sessions": [
            {
                "name": "regular",
                "open": "09:00",
                "close": "23:55",
                "days": ["mon", "tue", "wed", "thu", "fri"],
            }
        ],
        "dst_rules": [
            {
                "session": "regular",
                "reference_timezone": "America/New_York",
                "dst_active": True,
                "close": "23:30",
            },
            {
                "session": "regular",
                "reference_timezone": "America/New_York",
                "dst_active": False,
                "close": "23:55",
            },
        ],
        "last_verified": datetime.date(2026, 10, 14),
    }
    data.update(changes)
    return data


# Function records


def test_valid_function_loads():
    record = FunctionRecord.model_validate(function_data())
    assert record.name == "ApplyStop"
    assert record.returns == "none"
    assert [p.name for p in record.params] == ["type", "mode", "amount", "exitatstop"]
    assert record.min_args == 3
    assert record.max_args == 4


def test_function_with_no_params_loads():
    record = FunctionRecord.model_validate(function_data(name="TimeNum", params=[]))
    assert record.min_args == 0
    assert record.max_args == 0


@pytest.mark.parametrize("returns", ["array", "number", "string", "none", "any"])
def test_function_accepts_each_return_type(returns):
    assert FunctionRecord.model_validate(function_data(returns=returns)).returns == returns


def test_function_rejects_unknown_field():
    with pytest.raises(ValidationError, match="notes"):
        FunctionRecord.model_validate(function_data(notes="extra"))


@pytest.mark.parametrize("field", ["name", "category", "returns", "params", "doc_url"])
def test_function_rejects_missing_field(field):
    data = function_data()
    del data[field]
    with pytest.raises(ValidationError, match=field):
        FunctionRecord.model_validate(data)


def test_function_rejects_unknown_return_type():
    with pytest.raises(ValidationError, match="returns"):
        FunctionRecord.model_validate(function_data(returns="matrix"))


def test_function_rejects_unknown_category():
    with pytest.raises(ValidationError, match="category"):
        FunctionRecord.model_validate(function_data(category="magic"))


def test_function_rejects_unknown_param_type():
    params = [{"name": "x", "type": "integer", "optional": False}]
    with pytest.raises(ValidationError, match="type"):
        FunctionRecord.model_validate(function_data(params=params))


def test_function_rejects_param_with_unknown_field():
    params = [{"name": "x", "type": "number", "optional": False, "default": 1}]
    with pytest.raises(ValidationError, match="default"):
        FunctionRecord.model_validate(function_data(params=params))


def test_function_rejects_required_param_after_optional():
    params = [
        {"name": "a", "type": "number", "optional": True},
        {"name": "b", "type": "number", "optional": False},
    ]
    with pytest.raises(ValidationError, match="required parameter 'b' follows an optional"):
        FunctionRecord.model_validate(function_data(params=params))


def test_function_rejects_duplicate_param_name():
    params = [
        {"name": "period", "type": "number", "optional": False},
        {"name": "Period", "type": "number", "optional": False},
    ]
    with pytest.raises(ValidationError, match="duplicate parameter"):
        FunctionRecord.model_validate(function_data(params=params))


@pytest.mark.parametrize("name", ["Apply Stop", "2MA", "", "MA()"])
def test_function_rejects_name_that_is_not_an_identifier(name):
    with pytest.raises(ValidationError, match="name"):
        FunctionRecord.model_validate(function_data(name=name))


@pytest.mark.parametrize(
    "url",
    [
        "http://www.amibroker.com/guide/afl/applystop.html",
        "https://example.com/applystop.html",
        "applystop.html",
    ],
)
def test_function_rejects_doc_url_outside_the_official_site(url):
    with pytest.raises(ValidationError, match="doc_url"):
        FunctionRecord.model_validate(function_data(doc_url=url))


def test_records_are_frozen():
    record = FunctionRecord.model_validate(function_data())
    with pytest.raises(ValidationError):
        record.name = "Other"


# Built-in records


def test_valid_builtin_loads():
    record = BuiltinRecord.model_validate(builtin_data())
    assert record.name == "Close"
    assert record.aliases == ["C"]


def test_builtin_aliases_default_to_empty():
    data = builtin_data()
    del data["aliases"]
    assert BuiltinRecord.model_validate(data).aliases == []


def test_builtin_rejects_unknown_field():
    with pytest.raises(ValidationError, match="value"):
        BuiltinRecord.model_validate(builtin_data(value=1))


@pytest.mark.parametrize("field", ["name", "kind", "type", "description"])
def test_builtin_rejects_missing_field(field):
    data = builtin_data()
    del data[field]
    with pytest.raises(ValidationError, match=field):
        BuiltinRecord.model_validate(data)


def test_builtin_rejects_unknown_kind():
    with pytest.raises(ValidationError, match="kind"):
        BuiltinRecord.model_validate(builtin_data(kind="function"))


def test_builtin_rejects_type_none():
    with pytest.raises(ValidationError, match="type"):
        BuiltinRecord.model_validate(builtin_data(type="none"))


@pytest.mark.parametrize("value", [True, False, None])
def test_builtin_name_read_by_yaml_as_a_non_string_says_to_quote_it(value):
    # Unquoted True, False and Null in YAML arrive as booleans and None.
    with pytest.raises(ValidationError, match="put quotes around"):
        BuiltinRecord.model_validate(builtin_data(name=value))


def test_builtin_rejects_alias_equal_to_its_own_name():
    with pytest.raises(ValidationError, match="alias"):
        BuiltinRecord.model_validate(builtin_data(aliases=["close"]))


# Markets


def test_valid_market_loads():
    market = Market.model_validate(market_data())
    assert market.id == "mcx"
    assert market.sessions[0].open == "09:00"
    assert {rule.dst_active: rule.close for rule in market.dst_rules} == {
        True: "23:30",
        False: "23:55",
    }


def test_market_without_dst_rules_loads():
    market = Market.model_validate(market_data(dst_rules=[]))
    assert market.dst_rules == []


def test_market_last_verified_may_be_empty():
    market = Market.model_validate(market_data(last_verified=None))
    assert market.last_verified is None


def test_market_rejects_missing_last_verified():
    data = market_data()
    del data["last_verified"]
    with pytest.raises(ValidationError, match="last_verified"):
        Market.model_validate(data)


def test_market_rejects_unknown_field():
    with pytest.raises(ValidationError, match="holidays"):
        Market.model_validate(market_data(holidays=[]))


def test_market_time_read_by_yaml_as_a_number_says_to_quote_it():
    # Unquoted 15:30 in YAML arrives as the base-60 number 930.
    data = market_data()
    data["sessions"][0]["close"] = 930
    with pytest.raises(ValidationError, match="put quotes around"):
        Market.model_validate(data)


@pytest.mark.parametrize("time", ["9:15", "24:00", "09:60", "0915", "09:15:00"])
def test_market_rejects_badly_formed_time(time):
    data = market_data(dst_rules=[])
    data["sessions"][0]["open"] = time
    with pytest.raises(ValidationError, match="open"):
        Market.model_validate(data)


def test_market_rejects_session_that_closes_before_it_opens():
    data = market_data(dst_rules=[])
    data["sessions"][0]["open"] = "15:30"
    data["sessions"][0]["close"] = "09:15"
    with pytest.raises(ValidationError, match="close must be after open"):
        Market.model_validate(data)


def test_market_rejects_unknown_time_zone():
    with pytest.raises(ValidationError, match="time zone"):
        Market.model_validate(market_data(timezone="Asia/Mumbai"))


def test_market_rejects_unknown_day():
    data = market_data(dst_rules=[])
    data["sessions"][0]["days"] = ["monday"]
    with pytest.raises(ValidationError, match="days"):
        Market.model_validate(data)


def test_market_rejects_no_sessions():
    with pytest.raises(ValidationError, match="sessions"):
        Market.model_validate(market_data(sessions=[], dst_rules=[]))


def test_market_rejects_duplicate_session_name():
    data = market_data(dst_rules=[])
    data["sessions"].append(dict(data["sessions"][0]))
    with pytest.raises(ValidationError, match="duplicate session"):
        Market.model_validate(data)


def test_market_rejects_dst_rule_for_a_session_it_does_not_have():
    data = market_data()
    data["dst_rules"][0]["session"] = "evening"
    with pytest.raises(ValidationError, match="no session named 'evening'"):
        Market.model_validate(data)


def test_market_rejects_a_single_seasonal_rule():
    # A close that moves with daylight saving needs one rule per season.
    data = market_data()
    del data["dst_rules"][1]
    with pytest.raises(ValidationError, match="one rule for each season"):
        Market.model_validate(data)


def test_market_rejects_dst_rule_with_unknown_reference_time_zone():
    data = market_data()
    for rule in data["dst_rules"]:
        rule["reference_timezone"] = "America/Wall_Street"
    with pytest.raises(ValidationError, match="time zone"):
        Market.model_validate(data)


# Fields added for the full function list (stage 3)


def test_function_description_may_be_left_out():
    data = function_data()
    del data["description"]
    assert FunctionRecord.model_validate(data).description is None


def test_function_description_given_must_not_be_empty():
    with pytest.raises(ValidationError, match="description"):
        FunctionRecord.model_validate(function_data(description=""))


def test_variadic_function_has_no_upper_argument_limit():
    params = [{"name": "formatstr", "type": "string", "optional": False}]
    record = FunctionRecord.model_validate(function_data(params=params, variadic=True))
    assert record.variadic
    assert record.min_args == 1
    assert record.max_args is None


def test_function_is_not_variadic_unless_it_says_so():
    assert not FunctionRecord.model_validate(function_data()).variadic


def test_variadic_must_be_true_or_false():
    with pytest.raises(ValidationError, match="variadic"):
        FunctionRecord.model_validate(function_data(variadic="yes"))


@pytest.mark.parametrize("since", ["3.70", "5.0", "6.30"])
def test_function_may_record_the_version_that_introduced_it(since):
    assert FunctionRecord.model_validate(function_data(since=since)).since == since


def test_function_since_defaults_to_nothing():
    assert FunctionRecord.model_validate(function_data()).since is None


@pytest.mark.parametrize("since", [5.0, 6, "six", "6", "v6.0"])
def test_function_since_must_be_quoted_major_dot_minor(since):
    # Unquoted 5.0 in YAML arrives as a number and would lose "6.30" vs "6.3".
    with pytest.raises(ValidationError, match="since"):
        FunctionRecord.model_validate(function_data(since=since))


@pytest.mark.parametrize(
    "category",
    [
        "statistics",
        "pattern",
        "composite",
        "foreign",
        "timeframe",
        "string",
        "info",
        "file",
        "graphics",
        "gui",
        "matrix",
        "speech",
        "cbi",
        "misc",
    ],
)
def test_categories_for_the_full_list(category):
    assert FunctionRecord.model_validate(function_data(category=category)).category == category
