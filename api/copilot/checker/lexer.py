"""Turns AFL source into tokens. Every token keeps its line and column."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Token:
    kind: str  # ident, number, string, op, directive or eof
    text: str
    line: int
    col: int


class LexError(Exception):
    def __init__(self, message: str, line: int, col: int):
        self.message = message
        self.line = line
        self.col = col
        super().__init__(f"line {line}: {message}")


_NUMBER = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TWO_CHAR_OPS = frozenset(
    ["==", "!=", "<=", ">=", "&&", "||", "++", "--", "+=", "-=", "*=", "/=", "%=", "&=", "|="]
)
_ONE_CHAR_OPS = frozenset("+-*/%^<>=!&|~?:@()[]{},;.")
_BLANKS = frozenset(" \t\r\f\v﻿")


def tokenize(source: str) -> list[Token]:
    """Returns the tokens of `source`, ending with one eof token.

    Raises LexError for a comment or string that is never closed and for a
    character AFL does not use.
    """
    tokens: list[Token] = []
    i = 0
    line = 1
    col = 1
    length = len(source)
    line_has_token = False

    def step_over(text: str) -> None:
        nonlocal i, line, col
        i += len(text)
        newlines = text.count("\n")
        if newlines:
            line += newlines
            col = len(text) - text.rfind("\n")
        else:
            col += len(text)

    while i < length:
        ch = source[i]
        if ch == "\n":
            step_over(ch)
            line_has_token = False
            continue
        if ch in _BLANKS:
            step_over(ch)
            continue
        if source.startswith("//", i):
            end = source.find("\n", i)
            step_over(source[i : length if end == -1 else end])
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end == -1:
                raise LexError("a comment opened with /* is never closed", line, col)
            step_over(source[i : end + 2])
            continue

        if ch == "#" and not line_has_token:
            end = source.find("\n", i)
            text = source[i : length if end == -1 else end]
            tokens.append(Token("directive", text.strip(), line, col))
            step_over(text)
            continue

        if ch == '"':
            j = i + 1
            while j < length and source[j] != '"':
                j += 2 if source[j] == "\\" else 1
            if j >= length:
                raise LexError('a string opened with " is never closed', line, col)
            text = source[i : j + 1]
            kind = "string"
        elif number := _NUMBER.match(source, i):
            text = number.group()
            kind = "number"
        elif ident := _IDENT.match(source, i):
            text = ident.group()
            kind = "ident"
        elif source[i : i + 2] in _TWO_CHAR_OPS:
            text = source[i : i + 2]
            kind = "op"
        elif ch in _ONE_CHAR_OPS:
            text = ch
            kind = "op"
        else:
            raise LexError(f"unexpected character {ch!r}", line, col)

        tokens.append(Token(kind, text, line, col))
        step_over(text)
        line_has_token = True

    tokens.append(Token("eof", "", line, col))
    return tokens
