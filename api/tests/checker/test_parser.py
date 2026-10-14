import pytest

from copilot.checker.lexer import tokenize
from copilot.checker.parser import (
    AssignExpr,
    Binary,
    Block,
    Call,
    Directive,
    ExprStmt,
    For,
    FunctionDef,
    If,
    Name,
    Num,
    Subscript,
    Unary,
    While,
    bracket_problems,
    parse,
    walk,
)


def parsed(source):
    program = parse(tokenize(source))
    assert program.problems == [], [p.message for p in program.problems]
    return program


def problems(source):
    return parse(tokenize(source)).problems


def only_expr(source):
    (statement,) = parsed(source).body
    assert isinstance(statement, ExprStmt)
    return statement.expr


# Statements


def test_assignment():
    expr = only_expr("Buy = Cross(Fast, Slow);")
    assert isinstance(expr, AssignExpr)
    assert expr.target.name == "Buy"
    assert expr.op == "="
    assert isinstance(expr.value, Call)
    assert expr.line == 1


def test_call_keeps_name_arguments_and_line():
    program = parsed("x = 1;\ny = MA(Close,\n  20);")
    call = next(node for node in walk(program.body) if isinstance(node, Call))
    assert call.name == "MA"
    assert len(call.args) == 2
    assert call.line == 2


def test_call_with_no_arguments():
    expr = only_expr("tn = TimeNum();")
    assert expr.value.name == "TimeNum"
    assert expr.value.args == []


def test_nested_calls_count_their_own_arguments():
    expr = only_expr("x = IIf(Cross(a, b), MA(C, 5), 0);")
    assert len(expr.value.args) == 3
    assert [len(arg.args) for arg in expr.value.args[:2]] == [2, 2]


def test_if_else_with_blocks():
    (statement,) = parsed("if (x > 1) { a = 1; } else { a = 2; b = 3; }").body
    assert isinstance(statement, If)
    assert isinstance(statement.cond, Binary)
    assert len(statement.then.body) == 1
    assert len(statement.orelse.body) == 2


def test_if_without_braces():
    (statement,) = parsed("if (x) a = 1; else a = 2;").body
    assert isinstance(statement.then, ExprStmt)
    assert isinstance(statement.orelse, ExprStmt)


def test_function_declaration():
    (statement,) = parsed("function Mid(a, b) { result = (a + b) / 2; return result; }").body
    assert isinstance(statement, FunctionDef)
    assert statement.name == "Mid"
    assert statement.params == ["a", "b"]
    assert len(statement.body.body) == 2


def test_procedure_declaration_with_no_parameters():
    (statement,) = parsed('procedure Draw() { Plot(C, "c", colorRed); }').body
    assert isinstance(statement, FunctionDef)
    assert statement.params == []


def test_include_line():
    program = parsed("#include <tools.afl>\nBuy = 1;")
    assert isinstance(program.body[0], Directive)
    assert program.body[0].is_include
    assert program.body[0].line == 1


def test_for_loop_with_subscripts():
    (statement,) = parsed("for (i = 1; i < BarCount; i++) { x[i] = x[i - 1] + C[i]; }").body
    assert isinstance(statement, For)
    assert isinstance(statement.init, AssignExpr)
    assert isinstance(statement.cond, Binary)
    inner = statement.body.body[0].expr
    assert isinstance(inner.target, Subscript)


def test_while_and_do_while():
    program = parsed("while (i < 5) i++; do { i--; } while (i > 0);")
    assert isinstance(program.body[0], While)
    assert len(program.body) == 2


def test_switch_with_cases():
    parsed("switch (mode) { case 1: x = 1; break; default: x = 0; break; }")


def test_local_and_global_declarations():
    parsed("function f() { local a, b; global c; a = 1; return a; }")


def test_empty_statement_and_empty_source():
    assert parsed("").body == []
    assert len(parsed(";;").body) == 2


# Expressions


def test_keywords_and_or_not_in_any_case():
    expr = only_expr("Buy = a AND NOT b or c;").value
    assert isinstance(expr, Binary)
    assert expr.op == "or"
    assert expr.left.op == "and"
    assert isinstance(expr.left.right, Unary)
    assert expr.left.right.op == "not"


def test_multiplication_binds_tighter_than_addition():
    expr = only_expr("x = a + b * c;").value
    assert expr.op == "+"
    assert expr.right.op == "*"


def test_comparison_binds_tighter_than_and():
    expr = only_expr("x = a > b AND c < d;").value
    assert expr.op == "and"
    assert (expr.left.op, expr.right.op) == (">", "<")


def test_negative_number_is_a_unary_minus():
    expr = only_expr("x = Ref(C, -1);").value
    lag = expr.args[1]
    assert isinstance(lag, Unary)
    assert lag.op == "-"
    assert isinstance(lag.operand, Num)
    assert lag.operand.value == 1


def test_parentheses_group():
    expr = only_expr("x = (a + b) * c;").value
    assert expr.op == "*"
    assert expr.left.op == "+"


def test_assignment_inside_a_condition_parses_as_an_assignment():
    (statement,) = parsed("if (x = 5) y = 1;").body
    assert isinstance(statement.cond, AssignExpr)


def test_names_keep_line_and_column():
    expr = only_expr("x =\n  Close;")
    assert isinstance(expr.value, Name)
    assert (expr.value.line, expr.value.col) == (2, 3)


def test_member_call_has_no_function_name():
    expr = only_expr('ab = CreateObject("Broker.Application"); ').value
    assert expr.name == "CreateObject"
    call = only_expr("ab.RefreshAll();")
    assert isinstance(call, Call)
    assert call.name is None


def test_walk_visits_nested_nodes_in_source_order():
    program = parsed("a = MA(C, 5);\nif (LastValue(a) > 1) { b = HHV(H, 3); }")
    names = [node.name for node in walk(program.body) if isinstance(node, Call)]
    assert names == ["MA", "LastValue", "HHV"]


def test_block_statement():
    (statement,) = parsed("{ a = 1; b = 2; }").body
    assert isinstance(statement, Block)


# Problems


def test_missing_semicolon_is_reported_on_the_line_it_belongs_to():
    found = problems("a = 1\nb = 2;\nc = 3;")
    assert [(p.line, "semicolon" in p.message) for p in found] == [(1, True)]


def test_two_missing_semicolons_are_both_reported():
    found = problems("a = 1\nb = 2\nc = 3;")
    assert [p.line for p in found] == [1, 2]


def test_missing_semicolon_at_end_of_file():
    found = problems("a = 1;\nb = 2")
    assert [p.line for p in found] == [2]


def test_unexpected_token_is_reported_once_and_parsing_stops():
    found = problems("a = 1;\nb = 2 3;\nc = ) ;\n")
    assert len(found) == 1
    assert found[0].line == 2


def test_missing_operand():
    found = problems("a = 1 + ;")
    assert len(found) == 1
    assert found[0].line == 1


def test_else_without_if():
    assert len(problems("else a = 1;")) == 1


@pytest.mark.parametrize(
    ("source", "line", "text"),
    [
        ("a = MA(C, 5;\nb = 1;", 1, "("),
        ("a = 1;\nif (x) {\n b = 2;\n", 2, "{"),
        ("a = x[1;", 1, "["),
    ],
)
def test_bracket_never_closed(source, line, text):
    found = bracket_problems(tokenize(source))
    assert len(found) == 1
    assert found[0].line == line
    assert text in found[0].message
    assert "never closed" in found[0].message


def test_closing_bracket_with_nothing_open():
    found = bracket_problems(tokenize("a = 1;\nb = 2);\n"))
    assert [(p.line, ")" in p.message) for p in found] == [(2, True)]


def test_mismatched_bracket():
    found = bracket_problems(tokenize("a = MA(C, 5];"))
    assert len(found) == 1
    assert found[0].line == 1


def test_balanced_brackets_have_no_problems():
    assert bracket_problems(tokenize("if (a[1] > 2) { b = MA(C, (3)); }")) == []
