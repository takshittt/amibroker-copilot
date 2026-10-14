"""The symbol table: what the code defines, and what each name depends on.

Built once for each check and handed to every rule.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from copilot.checker.findings import Context
from copilot.checker.parser import (
    AssignExpr,
    Binary,
    Call,
    Directive,
    DoWhile,
    For,
    FunctionDef,
    If,
    Name,
    Node,
    Num,
    Postfix,
    Program,
    Str,
    Subscript,
    SyntaxProblem,
    Unary,
    While,
    walk,
)
from copilot.kb import Catalog

SIGNALS = ("buy", "sell", "short", "cover")
SIGNAL_LABEL = {"buy": "Buy", "sell": "Sell", "short": "Short", "cover": "Cover"}
PRICE_OF = {"buy": "BuyPrice", "sell": "SellPrice", "short": "ShortPrice", "cover": "CoverPrice"}
COMPARISONS = frozenset(["==", "!=", "<", ">", "<=", ">="])
_NUMBER_RESULT = COMPARISONS | {"and", "or"}
_NO_NAMES: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Assignment:
    name: str  # lower case
    node: AssignExpr
    subscripted: bool  # `x[i] = ...`

    @property
    def line(self) -> int:
        return self.node.line


class Analysis:
    def __init__(
        self,
        program: Program,
        catalog: Catalog,
        context: Context,
        syntax_problems: list[SyntaxProblem],
    ):
        self.program = program
        self.catalog = catalog
        self.context = context
        self.syntax_problems = syntax_problems

        self.nodes: list[Node] = list(walk(program.body))
        self.calls: list[Call] = [n for n in self.nodes if isinstance(n, Call) and n.name]
        self.functions: dict[str, FunctionDef] = {
            n.name.lower(): n for n in self.nodes if isinstance(n, FunctionDef)
        }
        self.has_include = any(isinstance(n, Directive) and n.is_include for n in self.nodes)
        # (statement, condition) for every if, while, do-while and for.
        self.conditions: list[tuple[Node, Node]] = [
            (n, n.cond)
            for n in self.nodes
            if isinstance(n, If | While | DoWhile | For) and n.cond is not None
        ]

        # Inside a function body its parameter names hide outer variables.
        self._shadow: dict[int, frozenset[str]] = {}
        for function in self.functions.values():
            params = frozenset(param.lower() for param in function.params)
            for node in walk(function.body):
                self._shadow[id(node)] = params

        self.assignments: dict[str, list[Assignment]] = {}
        for node in self.nodes:
            if not isinstance(node, AssignExpr):
                continue
            target = node.target
            subscripted = False
            while isinstance(target, Subscript):
                target = target.base
                subscripted = True
            if isinstance(target, Name):
                key = target.name.lower()
                self.assignments.setdefault(key, []).append(Assignment(key, node, subscripted))

        self._var_types: dict[str, str] = {}
        self._typing: set[str] = set()

    # Names

    def canonical(self, name: str) -> str:
        """Lower-case name, with a built-in alias turned into its full name (H -> high)."""
        builtin = self.catalog.builtin(name)
        return builtin.name.lower() if builtin else name.lower()

    def is_assigned(self, name: str) -> bool:
        return name.lower() in self.assignments

    def first_line(self, name: str) -> int:
        return self.assignments[name.lower()][0].line

    def values_of(self, name: str) -> list[Node]:
        return [a.node.value for a in self.assignments.get(name.lower(), [])]

    def calls_named(self, name: str) -> list[Call]:
        return [call for call in self.calls if call.name.lower() == name.lower()]

    def shadow(self, node: Node) -> frozenset[str]:
        return self._shadow.get(id(node), _NO_NAMES)

    # The array or number guess

    def type_of(self, expr: Node, shadow: frozenset[str] = _NO_NAMES) -> str:
        """Returns array, number, string or unknown. Rules act only on a known type."""
        return self._type(expr, shadow) or "unknown"

    def var_type(self, name: str) -> str:
        return self._var_type(name.lower()) or "unknown"

    def _var_type(self, key: str) -> str | None:
        if key in self._var_types:
            return self._var_types[key]
        if key in self._typing:
            return None  # the variable refers to itself; judge it by its other parts
        self._typing.add(key)
        kinds: set[str] = set()
        for assignment in self.assignments.get(key, []):
            if assignment.subscripted:
                kinds.add("array")
                continue
            kind = self._type(assignment.node.value, self.shadow(assignment.node))
            if kind is not None:
                kinds.add(kind)
        self._typing.discard(key)
        result = kinds.pop() if len(kinds) == 1 else "unknown"
        self._var_types[key] = result
        return result

    def _type(self, expr: Node, shadow: frozenset[str]) -> str | None:
        if isinstance(expr, Num):
            return "number"
        if isinstance(expr, Str):
            return "string"
        if isinstance(expr, Name):
            key = expr.name.lower()
            if key in shadow:
                return "unknown"
            builtin = self.catalog.builtin(expr.name)
            if builtin is not None:
                return builtin.type
            if key in self.assignments:
                return self._var_type(key)
            return "unknown"
        if isinstance(expr, Call):
            if expr.name is None or expr.name.lower() in self.functions:
                return "unknown"
            function = self.catalog.function(expr.name)
            if function is not None and function.returns in ("array", "number", "string"):
                return function.returns
            return "unknown"
        if isinstance(expr, Subscript):
            return "number"
        if isinstance(expr, Unary | Postfix):
            return self._type(expr.operand, shadow)
        if isinstance(expr, AssignExpr):
            return self._type(expr.value, shadow)
        if isinstance(expr, Binary):
            left = self._type(expr.left, shadow)
            right = self._type(expr.right, shadow)
            if "array" in (left, right):
                return "array"
            if left is None or right is None:
                return left or right
            if "unknown" in (left, right):
                return "unknown"
            if left == right == "string" and expr.op not in _NUMBER_RESULT:
                return "string"
            return "number"
        return "unknown"

    # Constants

    def const_value(self, expr: Node, _depth: int = 0) -> float | None:
        """The number an expression always has, or None when that is not certain."""
        if isinstance(expr, Num):
            return expr.value
        if isinstance(expr, Unary) and expr.op in ("-", "+"):
            value = self.const_value(expr.operand, _depth)
            if value is None:
                return None
            return -value if expr.op == "-" else value
        if isinstance(expr, Name) and _depth < 10 and self.catalog.builtin(expr.name) is None:
            assignments = self.assignments.get(expr.name.lower(), [])
            if len(assignments) == 1 and assignments[0].node.op == "=":
                if not assignments[0].subscripted:
                    return self.const_value(assignments[0].node.value, _depth + 1)
        return None

    # What a value depends on

    def reachable(self, exprs: Iterable[Node], stop: frozenset[str] = _NO_NAMES) -> list[Node]:
        """Every node that `exprs` depend on, following variables and functions
        written in the code. Variables named in `stop` are not followed."""
        seen_vars: set[str] = set()
        seen_functions: set[str] = set()
        found: list[Node] = []
        queue: list[Node] = list(exprs)
        while queue:
            for node in walk(queue.pop()):
                found.append(node)
                if isinstance(node, Name):
                    key = node.name.lower()
                    if key not in stop and key not in seen_vars:
                        seen_vars.add(key)
                        queue.extend(self.values_of(key))
                elif isinstance(node, Call) and node.name:
                    key = node.name.lower()
                    if key in self.functions and key not in seen_functions:
                        seen_functions.add(key)
                        queue.append(self.functions[key].body)
        return found

    def reachable_from(self, name: str) -> list[Node]:
        """Every node the variable `name` depends on."""
        return self.reachable(self.values_of(name))
