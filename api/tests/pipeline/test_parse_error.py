import pytest

from copilot.pipeline.fix_error import ParsedError, parse_error


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Error 32. Syntax error, probably missing semicolon at the end of the previous line",
            ParsedError(number=32),
        ),
        (
            "Ln: 14, Col: 9 : Error 29.\nVariable 'slow' used without having been initialized.",
            ParsedError(number=29, line=14, column=9),
        ),
        (
            "Formula.afl\nLine 7, Column 21:\nBuy = Cross(Fast\n----^\nError 31. Syntax error",
            ParsedError(number=31, line=7, column=21),
        ),
        ("error 6 on line 12", ParsedError(number=6, line=12)),
        (
            "Warning 501. Assignment within conditional. Did you mean == instead of = ?",
            ParsedError(number=501, is_warning=True),
        ),
        ("ERROR #701: Missing buy/sell variable assignments", ParsedError(number=701)),
        ("it says something about a missing semicolon", ParsedError()),
        ("", ParsedError()),
    ],
)
def test_parse_error(text, expected):
    assert parse_error(text) == expected


def test_the_first_error_number_is_used():
    assert parse_error("Error 30. Syntax error\nError 31. also").number == 30


def test_numbers_that_are_not_error_numbers_are_ignored():
    parsed = parse_error("MA(Close, 20) failed with Error 17 near 91500")
    assert parsed.number == 17
    assert parsed.line is None
