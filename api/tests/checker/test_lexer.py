import pytest

from copilot.checker.lexer import LexError, tokenize


def kinds_and_texts(source):
    return [(t.kind, t.text) for t in tokenize(source) if t.kind != "eof"]


def test_identifiers_numbers_and_operators():
    assert kinds_and_texts("Buy = Cross(C, 20.5);") == [
        ("ident", "Buy"),
        ("op", "="),
        ("ident", "Cross"),
        ("op", "("),
        ("ident", "C"),
        ("op", ","),
        ("number", "20.5"),
        ("op", ")"),
        ("op", ";"),
    ]


@pytest.mark.parametrize("text", ["0", "14", "2.5", ".5", "1e6", "1.5E-3", "91500"])
def test_number_forms(text):
    assert kinds_and_texts(text) == [("number", text)]


@pytest.mark.parametrize("op", ["==", "!=", "<=", ">=", "&&", "||", "++", "--", "+=", "-=", "*="])
def test_two_character_operators_are_one_token(op):
    assert kinds_and_texts(f"a {op} b")[1] == ("op", op)


def test_identifier_may_start_with_underscore():
    assert kinds_and_texts("_SECTION_BEGIN")[0] == ("ident", "_SECTION_BEGIN")


def test_string_keeps_its_quotes_and_inner_text():
    assert kinds_and_texts('Plot(C, "Close // not a comment", colorRed);')[4] == (
        "string",
        '"Close // not a comment"',
    )


def test_string_with_escaped_quote():
    assert kinds_and_texts(r'x = "say \"hi\"";')[2] == ("string", r'"say \"hi\""')


def test_line_comment_is_skipped():
    assert kinds_and_texts("a = 1; // Buy = TrailStop();\nb = 2;") == [
        ("ident", "a"),
        ("op", "="),
        ("number", "1"),
        ("op", ";"),
        ("ident", "b"),
        ("op", "="),
        ("number", "2"),
        ("op", ";"),
    ]


def test_block_comment_is_skipped_and_lines_still_count():
    tokens = tokenize("/* one\n   two\n*/ x = 1;")
    assert tokens[0].text == "x"
    assert tokens[0].line == 3


def test_every_token_keeps_line_and_column():
    tokens = tokenize("a = 1;\n  Buy = a;")
    buy = next(t for t in tokens if t.text == "Buy")
    assert (buy.line, buy.col) == (2, 3)
    assert (tokens[0].line, tokens[0].col) == (1, 1)
    last_a = [t for t in tokens if t.text == "a"][-1]
    assert (last_a.line, last_a.col) == (2, 9)


def test_include_line_is_one_directive_token():
    tokens = tokenize('#include <common.afl>\nBuy = 1;\n#include_once "x.afl"')
    assert (tokens[0].kind, tokens[0].text, tokens[0].line) == (
        "directive",
        "#include <common.afl>",
        1,
    )
    assert tokens[-2].kind == "directive"
    assert tokens[-2].line == 3


def test_end_of_file_token_is_always_last():
    assert tokenize("")[-1].kind == "eof"
    assert tokenize("a;")[-1].kind == "eof"


def test_block_comment_never_closed():
    with pytest.raises(LexError) as raised:
        tokenize("a = 1;\n/* never closed\nb = 2;")
    assert raised.value.line == 2
    assert "never closed" in raised.value.message


def test_string_never_closed():
    with pytest.raises(LexError) as raised:
        tokenize('a = 1;\nTitle = "oops;\n')
    assert raised.value.line == 2
    assert "never closed" in raised.value.message


def test_unexpected_character():
    with pytest.raises(LexError) as raised:
        tokenize("a = 1 $ 2;")
    assert (raised.value.line, raised.value.col) == (1, 7)
