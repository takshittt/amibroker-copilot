import pytest

RULE = "arg_count"


def test_too_few_arguments(found):
    (finding,) = found("x = 1;\ny = MA(Close);\n", RULE)
    assert finding.severity == "critical"
    assert finding.line == 2
    assert finding.message == "MA takes 2 arguments but is called with 1."


def test_too_many_arguments(found):
    (finding,) = found("y = Cross(Close, Open, 1);\n", RULE)
    assert "2 arguments" in finding.message
    assert "with 3" in finding.message


@pytest.mark.parametrize(
    "call",
    [
        "RSI()",
        "RSI(14)",
        "MACD()",
        "MACD(12, 26)",
        "ValueWhen(Close > Open, Close)",
        "ValueWhen(Close > Open, Close, 2)",
        "ApplyStop(stopTypeLoss, stopModePercent, 2)",
        "ApplyStop(stopTypeLoss, stopModePercent, 2, True, False, 0, 0, -1)",
        'Param("Length", 10)',
        'Param("Length", 10, 1, 50, 1)',
        'Plot(Close, "Close", colorRed)',
        "TimeNum()",
    ],
)
def test_optional_arguments_may_be_left_out(found, call):
    assert found(f"x = {call};\n", RULE) == []


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        ("RSI(14, 2)", "0 to 1 arguments"),
        ("TimeNum(1)", "no arguments"),
        ("BarsSince()", "1 argument"),
        ("SetTradeDelays(1, 1)", "4 arguments"),
        ('Plot(Close, "Close")', "3 to 9 arguments"),
        ("ApplyStop(stopTypeLoss, stopModePercent)", "3 to 8 arguments"),
    ],
)
def test_wrong_counts_say_what_is_expected(found, call, expected):
    (finding,) = found(f"x = {call};\n", RULE)
    assert expected in finding.message


def test_function_written_in_the_code_is_checked_against_its_own_parameters(found):
    source = "function Mid(a, b) { return (a + b) / 2; }\nx = Mid(High, Low);\ny = Mid(High);\n"
    (finding,) = found(source, RULE)
    assert finding.line == 3
    assert "Mid takes 2 arguments" in finding.message


def test_unknown_function_is_left_to_the_other_rule(found):
    assert found("x = TrailStop(1, 2, 3);\n", RULE) == []


def test_nested_calls_are_counted_separately(found):
    (finding,) = found("x = MA(EMA(Close, 5), 10) + MA(EMA(Close), 10);\n", RULE)
    assert "EMA" in finding.message
