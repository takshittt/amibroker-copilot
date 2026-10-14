import pytest

RULE = "lookahead_ref"


def test_positive_ref_in_a_signal(found):
    (finding,) = found("x = 1;\nBuy = Ref(Close, 1) > Close;\n", RULE)
    assert finding.severity == "critical"
    assert finding.line == 2
    assert "Buy" in finding.message
    assert "-1" in finding.fix_hint


def test_positive_ref_reaching_a_signal_through_variables(found):
    source = "tomorrow = Ref(Close, 1);\nup = tomorrow > Close;\nSell = up AND Close > Open;\n"
    (finding,) = found(source, RULE)
    assert finding.line == 1
    assert "Sell" in finding.message


def test_positive_period_held_in_a_variable(found):
    (finding,) = found("shift = 2;\nShort = Ref(High, shift) < High;\n", RULE)
    assert finding.line == 2


def test_positive_ref_inside_a_function_the_signal_calls(found):
    source = "function Next(v)\n{\n  return Ref(v, 1);\n}\nCover = Next(Close) > Close;\n"
    (finding,) = found(source, RULE)
    assert finding.line == 3


def test_one_ref_feeding_two_signals_is_reported_once(found):
    source = "peek = Ref(Close, 1);\nBuy = peek > Close;\nSell = peek < Close;\n"
    assert len(found(source, RULE)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "Buy = Ref(Close, -1) > Ref(Close, -2);\n",
        "Buy = Close > Ref(HHV(High, 20), -1);\n",
        "Buy = Ref(Close, 0) > Open;\n",
        # Only plotted, never traded on.
        'Buy = Close > Open;\nPlot(Ref(Close, 1), "Next close", colorRed);\n',
        'future = Ref(Close, 5);\nPlot(future, "Shifted", colorBlue);\n',
        # The period is not known for certain.
        'n = Param("Shift", 1, 1, 5, 1);\nBuy = Ref(Close, n) > Close;\n',
        "shift = -1;\nBuy = Ref(Close, shift) > Close;\n",
    ],
)
def test_refs_that_do_not_look_ahead_in_a_signal(found, source):
    assert found(source, RULE) == []
