import pytest

RULE = "intrabar_stop_price"


def test_stop_hit_on_the_low_without_sell_price(found):
    source = "stopLevel = Ref(LLV(Low, 10), -1);\nBuy = Close > Open;\nSell = Low < stopLevel;\n"
    (finding,) = found(source, RULE)
    assert finding.severity == "warning"
    assert finding.line == 3
    assert "SellPrice" in finding.message
    assert "SellPrice" in finding.fix_hint


def test_breakout_on_the_high_without_buy_price(found):
    (finding,) = found("level = Ref(HHV(High, 20), -1);\nBuy = High > level;\n", RULE)
    assert "BuyPrice" in finding.message


def test_alias_and_reversed_comparison(found):
    (finding,) = found("level = Ref(HHV(H, 20), -1);\nCover = level <= H;\n", RULE)
    assert "CoverPrice" in finding.message


def test_cross_of_a_level_over_the_low(found):
    (finding,) = found("level = Ref(LLV(L, 20), -1);\nShort = Cross(level, L);\n", RULE)
    assert "ShortPrice" in finding.message


def test_trigger_reached_through_a_variable(found):
    source = "stopHit = Low <= Ref(LLV(Low, 5), -1);\nSell = stopHit OR Close < Open;\n"
    (finding,) = found(source, RULE)
    assert finding.line == 1


@pytest.mark.parametrize(
    "source",
    [
        # The price is set.
        "lvl = Ref(LLV(Low, 10), -1);\nSell = Low < lvl;\nSellPrice = Min(Open, lvl);\n",
        "lvl = Ref(HHV(High, 20), -1);\nBuy = High > lvl;\nBuyPrice = Max(Open, lvl);\n",
        # Signals on the close are not intrabar.
        "Buy = Close > Ref(HHV(High, 20), -1);\nSell = Close < Ref(LLV(Low, 20), -1);\n",
        "Buy = Cross(Close, HHV(High, 20));\n",
        # High falling or Low rising is not a level being hit.
        "Sell = High < Ref(High, -1);\nBuy = Low > Ref(Low, -1);\n",
        # Used in a plot only.
        'Buy = Close > Open;\nPlot(Low < Ref(Low, -1), "Lower low", colorRed);\n',
    ],
)
def test_cases_that_need_no_price(found, source):
    assert found(source, RULE) == []
