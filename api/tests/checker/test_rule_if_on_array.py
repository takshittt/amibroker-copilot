import pytest

RULE = "if_on_array"


def test_if_on_a_price_comparison(found):
    (finding,) = found("x = 0;\nif (Close > Open)\n{\n  x = 1;\n}\n", RULE)
    assert finding.severity == "critical"
    assert finding.line == 2
    assert "IIf" in finding.fix_hint


def test_if_on_a_variable_holding_an_array(found):
    source = "avg = MA(Close, 20);\nup = Close > avg;\nif (up) { x = 1; }\n"
    (finding,) = found(source, RULE)
    assert finding.line == 3


def test_if_on_a_signal_variable(found):
    assert len(found("Buy = Cross(Close, MA(Close, 5));\nif (Buy) { x = 1; }\n", RULE)) == 1


def test_while_on_an_array(found):
    (finding,) = found("while (Close > Open) { x = 1; }\n", RULE)
    assert "while" in finding.message


@pytest.mark.parametrize(
    "source",
    [
        'n = Param("Length", 10, 1, 50, 1);\nif (n > 20) { x = 1; }\n',
        "if (LastValue(Close) > 100) { x = 1; }\n",
        "for (i = 1; i < 10; i++) { if (Close[i] > Close[i - 1]) { x = 1; } }\n",
        'show = ParamToggle("Show", "No|Yes", 1);\nif (show) { Plot(Close, "C", colorRed); }\n',
        "x = IIf(Close > Open, 1, 0);\n",
        # The type is not known, so the rule stays quiet.
        "if (SomeFlag) { x = 1; }\n",
        "y = IIf(Close > Open, 1, 0);\nif (y) { x = 1; }\n",
        "y = 5;\ny = Close;\nif (y) { x = 1; }\n",
        "function f(v) { if (v > 1) { return 1; } return 0; }\nv = Close;\n",
    ],
)
def test_conditions_that_are_numbers_or_not_known(found, source):
    assert found(source, RULE) == []
