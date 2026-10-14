import pytest

RULE = "exrem"

SIGNALS = "Buy = Close > MA(Close, 20);\nSell = Close < MA(Close, 20);\n"


def test_raw_signal_in_plot_shapes(found):
    source = SIGNALS + "PlotShapes(Buy * shapeUpArrow, colorGreen, 0, Low);\n"
    (finding,) = found(source, RULE)
    assert finding.severity == "warning"
    assert finding.line == 3
    assert finding.fix_hint == "Add Buy = ExRem(Buy, Sell); before this line."


def test_raw_signals_reaching_the_plot_through_a_variable(found):
    source = (
        SIGNALS
        + "shape = Buy * shapeUpArrow + Sell * shapeDownArrow;\n"
        + "PlotShapes(shape, colorGreen);\n"
    )
    findings = found(source, RULE)
    assert [f.line for f in findings] == [4, 4]
    assert sorted(f.message.split()[0] for f in findings) == ["Buy", "Sell"]


def test_raw_signal_in_an_exploration(found):
    source = SIGNALS + 'Filter = Buy OR Sell;\nAddColumn(Buy, "Buy");\n'
    findings = found(source, RULE)
    assert [f.line for f in findings] == [3, 3]
    assert "Filter" in findings[0].message


def test_only_the_uncleaned_signal_is_reported(found):
    source = (
        SIGNALS
        + "Buy = ExRem(Buy, Sell);\n"
        + "PlotShapes(Buy * shapeUpArrow, colorGreen);\n"
        + "PlotShapes(Sell * shapeDownArrow, colorRed);\n"
    )
    (finding,) = found(source, RULE)
    assert finding.line == 5
    assert finding.message.startswith("Sell")


def test_short_and_cover_are_a_pair_of_their_own(found):
    source = (
        "Short = Close < MA(Close, 20);\nCover = Close > MA(Close, 20);\n"
        "PlotShapes(Short * shapeDownArrow, colorRed);\n"
    )
    (finding,) = found(source, RULE)
    assert "ExRem(Short, Cover)" in finding.fix_hint


@pytest.mark.parametrize(
    "source",
    [
        # Cleaned both ways.
        SIGNALS
        + "Buy = ExRem(Buy, Sell);\nSell = ExRem(Sell, Buy);\n"
        + "PlotShapes(Buy * shapeUpArrow - Sell * shapeDownArrow, colorGreen);\n",
        # A backtest alone copes with repeated signals.
        SIGNALS,
        SIGNALS + 'Plot(Close, "Close", colorDefault, styleCandle);\n',
        # Nothing to pair the signal with.
        "Buy = Close > MA(Close, 20);\nPlotShapes(Buy * shapeUpArrow, colorGreen);\n",
        # The exploration does not show a signal.
        SIGNALS + 'Filter = Volume > 100000;\nAddColumn(Close, "Close");\n',
    ],
)
def test_cases_that_need_no_exrem(found, source):
    assert found(source, RULE) == []
