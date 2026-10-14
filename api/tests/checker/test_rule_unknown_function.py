RULE = "unknown_function"


def test_invented_function_is_critical(found):
    (finding,) = found("x = 1;\nstop = TrailStop(Close, 2);\n", RULE)
    assert finding.severity == "critical"
    assert finding.line == 2
    assert "TrailStop" in finding.message


def test_real_functions_pass(found):
    assert found("x = MA(Close, 20) + EMA(Close, 9) + ATR(14) + HHV(High, 5);\n", RULE) == []


def test_function_names_ignore_case(found):
    assert found("x = ma(Close, 20) + EMA(close, 9) + iif(Close > Open, 1, 0);\n", RULE) == []


def test_misspelled_name_gets_a_suggestion(found):
    (finding,) = found("x = ValueWhn(Close > Open, Close);\n", RULE)
    assert "ValueWhen" in finding.fix_hint


def test_function_written_in_the_code_is_known(found):
    source = "function Mid(a, b) { return (a + b) / 2; }\nx = Mid(High, Low);\n"
    assert found(source, RULE) == []


def test_each_unknown_call_is_reported(found):
    lines = [f.line for f in found("a = Foo(1);\nb = MA(Close, 5);\nc = Bar(2) + Foo(3);\n", RULE)]
    assert lines == [1, 3, 3]


def test_unknown_function_inside_another_call(found):
    (finding,) = found("Buy = Cross(SuperTrend(10, 3), Close);\n", RULE)
    assert "SuperTrend" in finding.message


def test_with_an_include_it_is_a_warning(found):
    (finding,) = found("#include <mytools.afl>\nx = MyHelper(Close);\n", RULE)
    assert finding.severity == "warning"
    assert finding.line == 2
    assert "#include" in finding.message


def test_function_named_in_a_comment_or_string_is_not_a_call(found):
    assert found('// x = TrailStop(1);\nTitle = "TrailStop(2)";\n', RULE) == []


def test_variable_with_brackets_is_not_a_call(found):
    assert found("x = Close;\ny = x[0] + (x);\n", RULE) == []


def test_functions_from_the_full_list_are_known(found):
    source = (
        "x = StochK(14, 3) + ADX(14) + HMA(Close, 20) + RSIa(Close, 14);\n"
        'Title = StrFormat("%s", Name()) + NumToStr(Close, 1.2);\n'
        'y = StaticVarGet("state");\nz = TimeFrameGetPrice("C", inDaily, -1);\n'
        'fh = fopen("notes.txt", "w");\n'
    )
    assert found(source, RULE) == []
