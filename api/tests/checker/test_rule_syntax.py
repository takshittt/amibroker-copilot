RULE = "syntax"


def test_valid_code_has_no_syntax_findings(found):
    assert found("Buy = Cross(MA(Close, 5), MA(Close, 20));\nSell = 0;\n", RULE) == []


def test_bracket_never_closed(found):
    (finding,) = found("x = 1;\nBuy = Cross(MA(Close, 5), MA(Close, 20);\n", RULE)
    assert finding.severity == "critical"
    assert finding.line == 2
    assert "never closed" in finding.message


def test_extra_closing_bracket(found):
    (finding,) = found("Buy = Close > Open);\n", RULE)
    assert finding.line == 1


def test_missing_semicolon(found):
    (finding,) = found("Fast = EMA(Close, 9)\nSlow = EMA(Close, 21);\n", RULE)
    assert finding.line == 1
    assert "semicolon" in finding.message
    assert ";" in finding.fix_hint


def test_single_equals_in_an_if_condition(found):
    (finding,) = found("n = 5;\nif (n = 5)\n{\n  x = 1;\n}\n", RULE)
    assert finding.severity == "critical"
    assert finding.line == 2
    assert "==" in finding.fix_hint


def test_double_equals_in_a_condition_is_fine(found):
    assert found("n = 5;\nif (n == 5) { x = 1; }\n", RULE) == []


def test_single_equals_in_the_condition_of_iif(found):
    (finding,) = found("x = IIf(DayOfWeek() = 1, Close, Open);\n", RULE)
    assert finding.line == 1
    assert "IIf" in finding.message


def test_assignments_in_a_for_header_are_fine(found):
    assert found("for (i = 0; i < 10; i++) { x = i; }\n", RULE) == []


def test_string_never_closed(found):
    (finding,) = found('Plot(Close, "Close, colorRed);\n', RULE)
    assert finding.line == 1


def test_symbol_out_of_place_still_gets_a_fix_hint(found):
    (finding,) = found("x = 1;\nBuy = Close > ;\n", RULE)
    assert finding.line == 2
    assert finding.fix_hint
