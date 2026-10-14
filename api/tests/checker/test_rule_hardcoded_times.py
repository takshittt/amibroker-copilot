import pytest

RULE = "hardcoded_times"


def test_number_compared_with_time_num(found):
    (finding,) = found("x = 1;\nSell = Close < Open OR TimeNum() >= 151500;\n", RULE)
    assert finding.severity == "tip"
    assert finding.line == 2
    assert "151500" in finding.message
    assert "ParamTime" in finding.fix_hint


def test_number_compared_with_a_variable_holding_the_time(found):
    (finding,) = found("tn = TimeNum();\nBuy = Close > Open AND tn < 143000;\n", RULE)
    assert finding.line == 2


def test_number_on_the_left(found):
    assert len(found("late = 151500 <= TimeNum();\n", RULE)) == 1


def test_cross_of_the_time_over_a_number(found):
    assert len(found("Sell = Cross(TimeNum(), 151459);\n", RULE)) == 1


def test_two_times_on_one_line_give_one_tip(found):
    assert len(found("ok = TimeNum() >= 93000 AND TimeNum() <= 143000;\n", RULE)) == 1


@pytest.mark.parametrize(
    "source",
    [
        'ExitTime = ParamTime("Exit", "15:15");\nSell = TimeNum() >= ExitTime;\n',
        'ExitTime = Param("Exit", 151500, 90000, 153000, 100);\nSell = TimeNum() >= ExitTime;\n',
        # A variable at the top is an editable setting too.
        "ExitTime = 151500;\ntn = TimeNum();\nSell = tn >= ExitTime;\n",
        # Numbers that have nothing to do with the time.
        "Buy = RSI(14) < 30 AND Close > 100;\n",
        "x = DayOfWeek() == 1;\n",
    ],
)
def test_times_kept_out_of_the_logic(found, source):
    assert found(source, RULE) == []
