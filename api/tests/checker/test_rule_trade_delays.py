import pytest

RULE = "trade_delays"

SIGNALS = (
    "Buy = Cross(EMA(Close, 9), EMA(Close, 21));\nSell = Cross(EMA(Close, 21), EMA(Close, 9));\n"
)


def test_signals_without_set_trade_delays(found):
    (finding,) = found("x = 1;\n" + SIGNALS, RULE)
    assert finding.severity == "warning"
    assert finding.line == 2
    assert "SetTradeDelays" in finding.fix_hint


def test_set_trade_delays_present(found):
    assert found("SetTradeDelays(1, 1, 1, 1);\n" + SIGNALS, RULE) == []


def test_indicator_with_no_signals_needs_no_delays(found):
    assert found('Plot(EMA(Close, 9), "EMA", colorRed);\n', RULE) == []


def test_two_calls_with_different_delays(found):
    source = "SetTradeDelays(1, 1, 1, 1);\n" + SIGNALS + "SetTradeDelays(0, 0, 0, 0);\n"
    (finding,) = found(source, RULE)
    assert finding.line == 4
    assert "line 1" in finding.message


def test_two_identical_calls_are_fine(found):
    source = "SetTradeDelays(1, 1, 1, 1);\n" + SIGNALS + "SetTradeDelays(1, 1, 1, 1);\n"
    assert found(source, RULE) == []


def test_zero_delay_with_a_fill_at_the_open(found):
    source = "SetTradeDelays(0, 0, 0, 0);\n" + SIGNALS + "BuyPrice = Open;\nSellPrice = Close;\n"
    (finding,) = found(source, RULE)
    assert finding.line == 4
    assert "BuyPrice" in finding.message


def test_zero_delay_with_the_open_alias(found):
    source = "SetTradeDelays(0, 0, 0, 0);\n" + SIGNALS + "SellPrice = O;\n"
    (finding,) = found(source, RULE)
    assert "SellPrice" in finding.message


@pytest.mark.parametrize(
    "source",
    [
        # Next bar's open: the usual, correct pairing.
        "SetTradeDelays(1, 1, 1, 1);\n" + SIGNALS + "BuyPrice = Open;\nSellPrice = Open;\n",
        # Same bar's close.
        "SetTradeDelays(0, 0, 0, 0);\n" + SIGNALS + "BuyPrice = Close;\nSellPrice = Close;\n",
        # The signal already reads the bar before, so it is known at the open.
        "SetTradeDelays(0, 0, 0, 0);\n"
        "Buy = Ref(Cross(EMA(Close, 9), EMA(Close, 21)), -1);\nBuyPrice = Open;\n",
        # Only the side with delay 0 is judged.
        "SetTradeDelays(1, 0, 1, 0);\n" + SIGNALS + "BuyPrice = Open;\nSellPrice = Close;\n",
    ],
)
def test_delays_that_agree_with_the_prices(found, source):
    assert found(source, RULE) == []
