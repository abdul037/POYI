"""Phase 1 tools: all read-only.

Client tools are plain functions decorated with `beta_tool`; the SDK builds the
schema from the signature and docstring. Server tools are dicts and run on
Anthropic's side.
"""

from __future__ import annotations

import ast
import math
import operator
from datetime import datetime
from typing import Any

from anthropic import beta_tool

from poyi.config import Settings

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_NAMES: dict[str, Any] = {
    "pi": math.pi,
    "e": math.e,
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "floor": math.floor,
    "ceil": math.ceil,
    "min": min,
    "max": max,
}
_MAX_POWER = 10_000


def _evaluate(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POWER:
            raise ValueError("exponent too large")
        return _BINARY[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_evaluate(node.operand))
    if isinstance(node, ast.Name) and node.id in _NAMES and not callable(_NAMES[node.id]):
        return _NAMES[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _NAMES:
        fn = _NAMES[node.func.id]
        if not callable(fn) or node.keywords:
            raise ValueError("unsupported call")
        return fn(*(_evaluate(arg) for arg in node.args))
    raise ValueError(f"unsupported expression: {ast.dump(node)[:60]}")


def safe_calculate(expression: str) -> str:
    """Evaluate an arithmetic expression without touching Python's eval."""
    expression = expression.strip().replace("^", "**")
    tree = ast.parse(expression, mode="eval")
    value = _evaluate(tree)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


@beta_tool
def current_time() -> str:
    """The current local date and time, with the weekday and timezone."""
    now = datetime.now().astimezone()
    return now.strftime("%A %d %B %Y, %H:%M %Z")


@beta_tool
def calculate(expression: str) -> str:
    """Evaluate arithmetic exactly. Use for any sum you would otherwise do in your head.

    Args:
        expression: A plain arithmetic expression such as "2340 * 0.17" or
            "sqrt(2) * pi". Supports + - * / // % ** and sqrt, log, log10,
            sin, cos, tan, abs, round, floor, ceil, min, max, pi, e.
    """
    try:
        return safe_calculate(expression)
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError) as exc:
        return f"Could not evaluate {expression!r}: {exc}"


WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}
WEB_FETCH = {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5}


def default_tools(settings: Settings | None = None, *, web: bool | None = None) -> list[Any]:
    """The Phase 1 tool list. `web=False` drops the server tools (cheaper evals)."""
    settings = settings or Settings()
    use_web = settings.web if web is None else web
    tools: list[Any] = [current_time, calculate]
    if use_web:
        tools.extend([WEB_SEARCH, WEB_FETCH])
    return tools
