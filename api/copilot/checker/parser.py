"""A light parser for AFL: statements, assignments, calls and conditions.

It accepts more than v1 generates (loops, switch, subscripts), because
pasted code in Review mode contains them. It never raises on bad source:
problems are collected in `Program.problems`. Parsing stops at the first
token that makes no sense, so one mistake is not reported many times.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field, fields

from copilot.checker.lexer import Token


class Node:
    """Base of every syntax tree node. Nodes compare by identity."""


@dataclass(eq=False)
class Num(Node):
    value: float
    line: int


@dataclass(eq=False)
class Str(Node):
    value: str
    line: int


@dataclass(eq=False)
class Name(Node):
    name: str
    line: int
    col: int


@dataclass(eq=False)
class Call(Node):
    # None when the thing called is not a plain name, as in `obj.Method()`.
    name: str | None
    target: Node | None
    args: list[Node]
    line: int


@dataclass(eq=False)
class Unary(Node):
    op: str
    operand: Node
    line: int


@dataclass(eq=False)
class Postfix(Node):
    op: str
    operand: Node
    line: int


@dataclass(eq=False)
class Binary(Node):
    op: str  # "and", "or" and "not" are stored in lower case
    left: Node
    right: Node
    line: int


@dataclass(eq=False)
class Subscript(Node):
    base: Node
    index: Node
    line: int


@dataclass(eq=False)
class Member(Node):
    base: Node
    name: str
    line: int


@dataclass(eq=False)
class AssignExpr(Node):
    target: Node
    op: str
    value: Node
    line: int


@dataclass(eq=False)
class ExprStmt(Node):
    expr: Node
    line: int


@dataclass(eq=False)
class Block(Node):
    body: list[Node]
    line: int


@dataclass(eq=False)
class If(Node):
    cond: Node
    then: Node
    orelse: Node | None
    line: int


@dataclass(eq=False)
class While(Node):
    cond: Node
    body: Node
    line: int


@dataclass(eq=False)
class DoWhile(Node):
    body: Node
    cond: Node
    line: int


@dataclass(eq=False)
class For(Node):
    init: Node | None
    cond: Node | None
    step: Node | None
    body: Node
    line: int


@dataclass(eq=False)
class Switch(Node):
    subject: Node
    body: Node
    line: int


@dataclass(eq=False)
class Case(Node):
    value: Node | None  # None for `default:`
    line: int


@dataclass(eq=False)
class FunctionDef(Node):
    name: str
    params: list[str]
    body: Block
    line: int


@dataclass(eq=False)
class Return(Node):
    value: Node | None
    line: int


@dataclass(eq=False)
class Jump(Node):
    kind: str  # break or continue
    line: int


@dataclass(eq=False)
class Declare(Node):
    kind: str  # local or global
    names: list[str]
    line: int


@dataclass(eq=False)
class Directive(Node):
    text: str
    line: int

    @property
    def is_include(self) -> bool:
        return self.text.lower().startswith("#include")


@dataclass(frozen=True)
class SyntaxProblem:
    message: str
    line: int
    fix_hint: str = ""


@dataclass(eq=False)
class Program:
    body: list[Node] = field(default_factory=list)
    problems: list[SyntaxProblem] = field(default_factory=list)


def walk(root: Node | list | None) -> Iterator[Node]:
    """Yields `root` and every node under it, in source order."""
    stack: list = [root]
    while stack:
        current = stack.pop()
        if isinstance(current, list):
            stack.extend(reversed(current))
        elif isinstance(current, Node):
            yield current
            stack.extend(reversed([getattr(current, f.name) for f in fields(current)]))


_CLOSER = {"(": ")", "[": "]", "{": "}"}
_OPENER = {closer: opener for opener, closer in _CLOSER.items()}


def bracket_problems(tokens: list[Token]) -> list[SyntaxProblem]:
    """Reports brackets that are never closed, never opened, or mismatched."""
    found: list[SyntaxProblem] = []
    open_brackets: list[Token] = []
    for token in tokens:
        if token.kind != "op":
            continue
        if token.text in _CLOSER:
            open_brackets.append(token)
        elif token.text in _OPENER:
            if not open_brackets:
                found.append(
                    SyntaxProblem(
                        f"'{token.text}' has no matching '{_OPENER[token.text]}' before it",
                        token.line,
                        f"Remove the extra '{token.text}' or add the missing "
                        f"'{_OPENER[token.text]}'.",
                    )
                )
                return found
            opener = open_brackets.pop()
            if _CLOSER[opener.text] != token.text:
                found.append(
                    SyntaxProblem(
                        f"'{opener.text}' opened on line {opener.line} is closed by "
                        f"'{token.text}' instead of '{_CLOSER[opener.text]}'",
                        token.line,
                        f"Close it with '{_CLOSER[opener.text]}'.",
                    )
                )
                return found
    for opener in open_brackets:
        found.append(
            SyntaxProblem(
                f"'{opener.text}' opened here is never closed",
                opener.line,
                f"Add the missing '{_CLOSER[opener.text]}'.",
            )
        )
    return found


_KEYWORDS = frozenset(
    [
        "if",
        "else",
        "while",
        "do",
        "for",
        "switch",
        "case",
        "default",
        "function",
        "procedure",
        "return",
        "break",
        "continue",
        "local",
        "global",
        "and",
        "or",
        "not",
    ]
)
_ASSIGN_OPS = frozenset(["=", "+=", "-=", "*=", "/=", "%=", "&=", "|="])
_COMPARE_OPS = frozenset(["==", "!=", "<", ">", "<=", ">="])


class _Stop(Exception):
    """Raised at a token that makes no sense; ends the parse."""

    def __init__(self, message: str, line: int, fix_hint: str = ""):
        self.problem = SyntaxProblem(message, line, fix_hint)
        super().__init__(message)


class _Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0
        self.problems: list[SyntaxProblem] = []

    # Token helpers

    @property
    def current(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        token = self.tokens[self.pos]
        if token.kind != "eof":
            self.pos += 1
        return token

    def at_op(self, *texts: str) -> bool:
        return self.current.kind == "op" and self.current.text in texts

    def at_word(self, *words: str) -> bool:
        return self.current.kind == "ident" and self.current.text.lower() in words

    def describe(self, token: Token) -> str:
        return "the end of the file" if token.kind == "eof" else f"'{token.text}'"

    def expect_op(self, text: str) -> Token:
        if not self.at_op(text):
            raise _Stop(
                f"expected '{text}' but found {self.describe(self.current)}", self.current.line
            )
        return self.advance()

    def end_statement(self) -> None:
        """Consumes the semicolon that ends a statement, or reports it missing."""
        if self.at_op(";"):
            self.advance()
            return
        previous = self.tokens[self.pos - 1]
        token = self.current
        if token.kind == "eof" or token.line > previous.line or self.at_op("}"):
            self.problems.append(
                SyntaxProblem(
                    "missing semicolon at the end of this statement",
                    previous.line,
                    "Add ; at the end of the line.",
                )
            )
            return
        raise _Stop(f"unexpected {self.describe(token)}", token.line)

    # Statements

    def program(self) -> Program:
        body: list[Node] = []
        try:
            while self.current.kind != "eof":
                body.append(self.statement())
        except _Stop as stop:
            self.problems.append(stop.problem)
        return Program(body, self.problems)

    def statement(self) -> Node:
        token = self.current
        if token.kind == "directive":
            self.advance()
            return Directive(token.text, token.line)
        if self.at_op(";"):
            self.advance()
            return Block([], token.line)
        if self.at_op("{"):
            return self.block()
        if token.kind == "ident":
            word = token.text.lower()
            if word == "if":
                return self.if_statement()
            if word == "while":
                self.advance()
                cond = self.condition()
                return While(cond, self.statement(), token.line)
            if word == "do":
                self.advance()
                body = self.statement()
                if not self.at_word("while"):
                    raise _Stop("expected 'while' after the body of 'do'", self.current.line)
                self.advance()
                cond = self.condition()
                self.end_statement()
                return DoWhile(body, cond, token.line)
            if word == "for":
                return self.for_statement()
            if word == "switch":
                self.advance()
                subject = self.condition()
                return Switch(subject, self.block(), token.line)
            if word in ("case", "default"):
                self.advance()
                value = self.expression() if word == "case" else None
                self.expect_op(":")
                return Case(value, token.line)
            if word in ("function", "procedure"):
                return self.function_definition()
            if word == "return":
                self.advance()
                value = None if self.at_op(";") else self.expression()
                self.end_statement()
                return Return(value, token.line)
            if word in ("break", "continue"):
                self.advance()
                self.end_statement()
                return Jump(word, token.line)
            if word in ("local", "global"):
                return self.declaration()
        expr = self.expression()
        self.end_statement()
        return ExprStmt(expr, token.line)

    def block(self) -> Block:
        opening = self.expect_op("{")
        body: list[Node] = []
        while not self.at_op("}"):
            if self.current.kind == "eof":
                raise _Stop("'{' opened here is never closed", opening.line, "Add the missing '}'.")
            body.append(self.statement())
        self.advance()
        return Block(body, opening.line)

    def condition(self) -> Node:
        self.expect_op("(")
        expr = self.expression()
        self.expect_op(")")
        return expr

    def if_statement(self) -> If:
        token = self.advance()
        cond = self.condition()
        then = self.statement()
        orelse = None
        if self.at_word("else"):
            self.advance()
            orelse = self.statement()
        return If(cond, then, orelse, token.line)

    def for_statement(self) -> For:
        token = self.advance()
        self.expect_op("(")
        init = None if self.at_op(";") else self.expression()
        self.expect_op(";")
        cond = None if self.at_op(";") else self.expression()
        self.expect_op(";")
        step = None if self.at_op(")") else self.expression()
        self.expect_op(")")
        return For(init, cond, step, self.statement(), token.line)

    def plain_name(self, what: str) -> str:
        token = self.current
        if token.kind != "ident" or token.text.lower() in _KEYWORDS:
            raise _Stop(f"expected {what} but found {self.describe(token)}", token.line)
        return self.advance().text

    def function_definition(self) -> FunctionDef:
        token = self.advance()
        name = self.plain_name("a function name")
        self.expect_op("(")
        params: list[str] = []
        while not self.at_op(")"):
            params.append(self.plain_name("a parameter name"))
            if not self.at_op(")"):
                self.expect_op(",")
        self.advance()
        return FunctionDef(name, params, self.block(), token.line)

    def declaration(self) -> Declare:
        token = self.advance()
        names = [self.plain_name("a variable name")]
        while self.at_op(","):
            self.advance()
            names.append(self.plain_name("a variable name"))
        self.end_statement()
        return Declare(token.text.lower(), names, token.line)

    # Expressions, lowest precedence first

    def expression(self) -> Node:
        left = self.logical_or()
        if self.at_op(*_ASSIGN_OPS):
            op = self.advance()
            return AssignExpr(left, op.text, self.expression(), op.line)
        return left

    def logical_or(self) -> Node:
        left = self.logical_and()
        while self.at_op("||") or self.at_word("or"):
            op = self.advance()
            left = Binary("or", left, self.logical_and(), op.line)
        return left

    def logical_and(self) -> Node:
        left = self.bitwise()
        while self.at_op("&&") or self.at_word("and"):
            op = self.advance()
            left = Binary("and", left, self.bitwise(), op.line)
        return left

    def bitwise(self) -> Node:
        left = self.comparison()
        while self.at_op("|", "&"):
            op = self.advance()
            left = Binary(op.text, left, self.comparison(), op.line)
        return left

    def comparison(self) -> Node:
        left = self.additive()
        while self.at_op(*_COMPARE_OPS):
            op = self.advance()
            left = Binary(op.text, left, self.additive(), op.line)
        return left

    def additive(self) -> Node:
        left = self.multiplicative()
        while self.at_op("+", "-"):
            op = self.advance()
            left = Binary(op.text, left, self.multiplicative(), op.line)
        return left

    def multiplicative(self) -> Node:
        left = self.unary()
        while self.at_op("*", "/", "%"):
            op = self.advance()
            left = Binary(op.text, left, self.unary(), op.line)
        return left

    def unary(self) -> Node:
        if self.at_op("-", "+", "!", "~", "++", "--"):
            op = self.advance()
            return Unary("not" if op.text == "!" else op.text, self.unary(), op.line)
        if self.at_word("not"):
            op = self.advance()
            return Unary("not", self.unary(), op.line)
        return self.power()

    def power(self) -> Node:
        base = self.postfix()
        if self.at_op("^"):
            op = self.advance()
            return Binary("^", base, self.unary(), op.line)
        return base

    def postfix(self) -> Node:
        expr = self.primary()
        while True:
            if self.at_op("("):
                opening = self.advance()
                args: list[Node] = []
                while not self.at_op(")"):
                    args.append(self.expression())
                    if not self.at_op(")"):
                        self.expect_op(",")
                self.advance()
                if isinstance(expr, Name):
                    expr = Call(expr.name, None, args, expr.line)
                else:
                    expr = Call(None, expr, args, opening.line)
            elif self.at_op("["):
                opening = self.advance()
                index = self.expression()
                self.expect_op("]")
                expr = Subscript(expr, index, opening.line)
            elif self.at_op("."):
                dot = self.advance()
                expr = Member(expr, self.plain_name("a name after '.'"), dot.line)
            elif self.at_op("++", "--"):
                op = self.advance()
                expr = Postfix(op.text, expr, op.line)
            else:
                return expr

    def primary(self) -> Node:
        token = self.current
        if token.kind == "number":
            self.advance()
            return Num(float(token.text), token.line)
        if token.kind == "string":
            self.advance()
            return Str(token.text[1:-1], token.line)
        if token.kind == "ident" and token.text.lower() not in _KEYWORDS:
            self.advance()
            return Name(token.text, token.line, token.col)
        if self.at_op("("):
            self.advance()
            expr = self.expression()
            self.expect_op(")")
            return expr
        raise _Stop(f"unexpected {self.describe(token)}", token.line)


def parse(tokens: list[Token]) -> Program:
    """Parses tokens from `tokenize`. Problems are returned, never raised."""
    return _Parser(tokens).program()
