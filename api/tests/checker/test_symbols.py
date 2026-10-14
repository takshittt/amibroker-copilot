import pytest

from copilot.checker.findings import Context
from copilot.checker.lexer import tokenize
from copilot.checker.parser import Call, If, Name, parse
from copilot.checker.symbols import Analysis


@pytest.fixture
def analyse(catalog):
    def _analyse(source):
        program = parse(tokenize(source))
        assert program.problems == []
        return Analysis(program, catalog, Context(timeframe="daily"), [])

    return _analyse


# The array or number guess


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("x = MA(Close, 20);", "array"),
        ("x = Close;", "array"),
        ("x = C;", "array"),
        ("x = Close > Open;", "array"),
        ("x = 2 * ATR(14);", "array"),
        ("x = -Close;", "array"),
        ('x = Param("Length", 10, 1, 50, 1);', "number"),
        ("x = 5;", "number"),
        ("x = 2 + 3 * 4;", "number"),
        ("x = LastValue(Close) > 100;", "number"),
        ("x = Close[5];", "number"),
        ("x = True;", "number"),
        ('x = "hello";', "string"),
        # IIf gives an array or a number depending on its arguments.
        ("x = IIf(Close > Open, 1, 0);", "unknown"),
        ("x = Max(a, b);", "unknown"),
        ("x = NotInTheList(5);", "unknown"),
        ("x = y;", "unknown"),
        ("x = y + 1;", "unknown"),
    ],
)
def test_type_of_a_variable(analyse, source, expected):
    assert analyse(source).var_type("x") == expected


def test_array_wins_over_unknown_in_arithmetic(analyse):
    assert analyse("x = y + Close;").var_type("x") == "array"


def test_variable_assigned_both_kinds_is_unknown(analyse):
    assert analyse("x = 5; x = Close;").var_type("x") == "unknown"


def test_variable_that_refers_to_itself(analyse):
    assert analyse("x = 0; x = x + 1;").var_type("x") == "number"
    assert analyse("Buy = Cross(a, b); Buy = ExRem(Buy, Sell);").var_type("buy") == "array"


def test_type_follows_through_other_variables(analyse):
    analysis = analyse("n = 20; avg = MA(Close, n); up = Close > avg; k = n * 2;")
    assert analysis.var_type("up") == "array"
    assert analysis.var_type("k") == "number"


def test_variable_names_ignore_case(analyse):
    assert analyse("Fast = EMA(C, 9);").var_type("FAST") == "array"


def test_call_to_a_function_written_in_the_code_is_unknown(analyse):
    analysis = analyse("function Mid(a, b) { return (a + b) / 2; } x = Mid(High, Low);")
    assert analysis.var_type("x") == "unknown"
    assert "mid" in analysis.functions


def test_function_parameter_hides_a_variable_of_the_same_name(analyse):
    analysis = analyse("x = Close; function f(x) { if (x > 1) { return 1; } return 0; }")
    condition = next(node for node in analysis.nodes if isinstance(node, If)).cond
    assert analysis.type_of(condition, analysis.shadow(condition)) == "unknown"
    assert analysis.type_of(condition) == "array"


# Assignments, includes and constants


def test_assignments_are_recorded_with_lines(analyse):
    analysis = analyse("Buy = 0;\nx = 1;\nBuy = x;")
    assert [a.line for a in analysis.assignments["buy"]] == [1, 3]
    assert analysis.is_assigned("BUY")
    assert not analysis.is_assigned("Sell")
    assert analysis.first_line("buy") == 1


def test_subscript_assignment_counts_for_the_variable(analyse):
    analysis = analyse("for (i = 0; i < BarCount; i++) { Buy[i] = 1; }")
    assert analysis.is_assigned("Buy")
    assert analysis.assignments["buy"][0].subscripted


def test_include_is_noticed(analyse):
    assert analyse("#include <x.afl>\nBuy = 1;").has_include
    assert not analyse("Buy = 1;").has_include


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("x = Ref(C, 1);", 1),
        ("x = Ref(C, -1);", -1),
        ("x = Ref(C, +2);", 2),
        ("n = 3; x = Ref(C, n);", 3),
        ("n = -3; x = Ref(C, n);", -3),
        ("n = 3; n = 4; x = Ref(C, n);", None),
        ('n = Param("n", 1, 1, 5, 1); x = Ref(C, n);', None),
        ("x = Ref(C, y);", None),
    ],
)
def test_constant_value_of_an_argument(analyse, source, expected):
    analysis = analyse(source)
    ref = next(call for call in analysis.calls if call.name == "Ref")
    assert analysis.const_value(ref.args[1]) == expected


# What a variable depends on


def names_of(nodes, kind):
    return sorted({node.name for node in nodes if isinstance(node, kind)})


def test_reachable_follows_variables(analyse):
    analysis = analyse(
        "tn = TimeNum(); late = tn >= 151500; trend = C > MA(C, 50); Sell = late OR Cross(a, b);"
    )
    nodes = analysis.reachable_from("sell")
    assert names_of(nodes, Call) == ["Cross", "TimeNum"]
    assert "trend" not in names_of(nodes, Name)


def test_reachable_follows_functions_written_in_the_code(analyse):
    analysis = analyse("function Next(x) { return Ref(x, 1); } Buy = Next(Close) > Close;")
    assert "Ref" in names_of(analysis.reachable_from("buy"), Call)


def test_reachable_copes_with_circular_definitions(analyse):
    analysis = analyse("a = b; b = a; Buy = a;")
    assert names_of(analysis.reachable_from("buy"), Name) == ["a", "b"]


def test_reachable_stops_at_named_variables(analyse):
    analysis = analyse("Buy = Cross(a, b); shape = Buy * shapeUpArrow;")
    value = analysis.assignments["shape"][0].node.value
    nodes = analysis.reachable([value], stop=frozenset(["buy"]))
    assert names_of(nodes, Call) == []
    assert "Buy" in names_of(nodes, Name)


def test_canonical_name_resolves_price_aliases(analyse):
    analysis = analyse("x = 1;")
    assert analysis.canonical("H") == "high"
    assert analysis.canonical("Close") == "close"
    assert analysis.canonical("MyVar") == "myvar"
