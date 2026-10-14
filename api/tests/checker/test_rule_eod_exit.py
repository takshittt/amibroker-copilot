RULE = "eod_exit"

ENTRIES = "Buy = Cross(EMA(Close, 9), EMA(Close, 21));\n"


def test_intraday_strategy_with_no_time_exit(found):
    source = "x = 1;\n" + ENTRIES + "Sell = Cross(EMA(Close, 21), EMA(Close, 9));\n"
    (finding,) = found(source, RULE, timeframe="5min")
    assert finding.severity == "warning"
    assert finding.line == 2
    assert "Sell" in finding.message
    assert "TimeNum" in finding.fix_hint


def test_time_filter_on_entries_only_is_not_an_exit(found):
    source = (
        "Buy = Cross(EMA(Close, 9), EMA(Close, 21)) AND TimeNum() < 143000;\n"
        "Sell = Cross(EMA(Close, 21), EMA(Close, 9));\n"
    )
    assert len(found(source, RULE, timeframe="15min")) == 1


def test_exit_that_uses_the_time_passes(found):
    source = ENTRIES + "Sell = Cross(EMA(Close, 21), EMA(Close, 9)) OR TimeNum() >= 151500;\n"
    assert found(source, RULE, timeframe="5min") == []


def test_exit_time_reached_through_variables_passes(found):
    source = (
        'ExitTime = ParamTime("Exit", "15:15");\n'
        "tn = TimeNum();\n"
        "dayEnd = tn >= ExitTime;\n" + ENTRIES + "Sell = dayEnd;\n"
    )
    assert found(source, RULE, timeframe="5min") == []


def test_each_side_needs_its_own_exit(found):
    source = (
        ENTRIES
        + "Short = Cross(EMA(Close, 21), EMA(Close, 9));\n"
        + "Sell = Short OR TimeNum() >= 151500;\n"
        + "Cover = Buy;\n"
    )
    (finding,) = found(source, RULE, timeframe="5min")
    assert finding.line == 2
    assert "Cover" in finding.message


def test_entry_with_no_exit_at_all(found):
    (finding,) = found(ENTRIES, RULE, timeframe="hourly")
    assert "Sell" in finding.message


def test_daily_strategy_is_not_checked(found):
    source = ENTRIES + "Sell = Cross(EMA(Close, 21), EMA(Close, 9));\n"
    assert found(source, RULE, timeframe="daily") == []


def test_intraday_indicator_with_no_signals_passes(found):
    assert found('Plot(EMA(Close, 9), "EMA", colorRed);\n', RULE, timeframe="5min") == []


def test_market_that_never_closes_needs_no_end_of_day_exit(run):
    source = ENTRIES + "Sell = Cross(EMA(Close, 21), EMA(Close, 9));\n"
    rules = {f.rule for f in run(source, timeframe="hourly", market_id="crypto").findings}
    assert RULE not in rules


def test_market_that_closes_still_needs_one_when_the_market_is_given(run):
    source = ENTRIES + "Sell = Cross(EMA(Close, 21), EMA(Close, 9));\n"
    rules = {f.rule for f in run(source, timeframe="hourly", market_id="nse_fo").findings}
    assert RULE in rules


def test_unknown_market_is_treated_as_one_that_closes(run):
    source = ENTRIES + "Sell = Cross(EMA(Close, 21), EMA(Close, 9));\n"
    rules = {f.rule for f in run(source, timeframe="hourly", market_id="moon").findings}
    assert RULE in rules
