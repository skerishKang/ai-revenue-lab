"""Strict AST allowlist validation for generated Python code.

The previous implementation used a deny-list-style regex scan plus an AST
allowlist that permitted *any* ``ast.Call``. That meant a bare arbitrary call
such as ``danger()`` or ``open(...)`` passed structural validation. This module
replaces that with a true allow-list: only the node types required by the
initial curriculum are permitted, and ``Call`` is restricted to ``print()``.

Rejected outright: Attribute, Import, ImportFrom, Lambda, FunctionDef,
AsyncFunctionDef, ClassDef, With, AsyncWith, Try, Raise, Delete, Global,
Nonlocal, Subscript, arbitrary Call, dunder names, and the builtins
open/eval/exec/input/__import__/compile/getattr/setattr.
"""

from __future__ import annotations

import ast

# Node types permitted in initial-curriculum code. Anything not listed here is
# rejected. ``Call`` is permitted structurally but further restricted to
# ``print()`` only (see _check_call).
_ALLOWED_NODES: tuple[type, ...] = (
    ast.Module,
    ast.Assign,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.Expr,
    ast.Call,
    ast.If,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)

# Builtins that must never appear as a called or referenced name.
_FORBIDDEN_NAMES = frozenset(
    {
        "open",
        "eval",
        "exec",
        "input",
        "compile",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "breakpoint",
        "exit",
        "quit",
    }
)

# The only callable allowed.
_ALLOWED_CALLABLES = frozenset({"print"})


def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _check_call(node: ast.Call) -> str | None:
    """Return an issue string if this Call is not an allowed ``print()``."""
    func = node.func
    if not isinstance(func, ast.Name):
        # Attribute calls (obj.method()), subscript calls, etc. are forbidden.
        return "unsafe_code: call_not_print"
    if func.id not in _ALLOWED_CALLABLES:
        return f"unsafe_code: forbidden_call_{func.id}"
    if node.keywords:
        # print(**kwargs) / print(sep=...) — reject keyword forms to keep the
        # surface minimal and predictable.
        return "unsafe_code: call_with_kwargs"
    return None


def validate_code_ast(code: str) -> list[str]:
    """Validate ``code`` against the allowlist.

    Returns a list of issue strings; empty means the code is structurally safe.
    """
    if not code or not code.strip():
        return ["unsafe_code: empty"]

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ["unsafe_code: syntax_error"]
    except Exception:
        return ["unsafe_code: unparseable"]

    issues: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            issues.append(f"unsafe_code: disallowed_node_{type(node).__name__}")
            continue

        if isinstance(node, ast.Call):
            call_issue = _check_call(node)
            if call_issue:
                issues.append(call_issue)

        if isinstance(node, ast.Name):
            if _is_dunder(node.id):
                issues.append(f"unsafe_code: dunder_name_{node.id}")
            elif node.id in _FORBIDDEN_NAMES:
                issues.append(f"unsafe_code: forbidden_name_{node.id}")

    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for issue in issues:
        if issue not in seen:
            seen.add(issue)
            unique.append(issue)
    return unique


def is_safe_code(code: str) -> bool:
    return not validate_code_ast(code)


def simulate_print_output(code: str) -> str | None:
    """Deterministically simulate ``print`` output for allowlisted code.

    Returns the simulated stdout (space-joined per print call, newline between
    calls), or ``None`` if the code is not safe or cannot be simulated. This is
    used only to cross-check a provider's declared ``expected_output``; it never
    executes arbitrary code.
    """
    if not is_safe_code(code):
        return None

    try:
        tree = ast.parse(code)
    except Exception:
        return None

    env: dict[str, object] = {}
    lines: list[str] = []

    def _eval_expr(expr: ast.expr) -> object:
        if isinstance(expr, ast.Constant):
            return expr.value
        if isinstance(expr, ast.Name) and expr.id in env:
            return env[expr.id]
        raise ValueError("cannot evaluate expression")

    try:
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign):
                if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                    raise ValueError("unsupported assignment target")
                env[stmt.targets[0].id] = _eval_expr(stmt.value)
            elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                if not (isinstance(call.func, ast.Name) and call.func.id == "print"):
                    raise ValueError("only print calls are simulatable")
                parts = [str(_eval_expr(arg)) for arg in call.args]
                lines.append(" ".join(parts))
            else:
                # If/Compare etc. are structurally allowed but not simulated.
                raise ValueError("statement not simulatable")
    except Exception:
        return None

    return "\n".join(lines)


def validate_code_output(code: str, expected_output: str) -> bool:
    """Check ``code`` is safe and its simulated output matches ``expected_output``.

    If ``expected_output`` is empty, only structural safety is required.
    """
    issues = validate_code_ast(code)
    if issues:
        return False

    expected = (expected_output or "").strip()
    if not expected:
        return True

    simulated = simulate_print_output(code)
    if simulated is None:
        # Could not simulate deterministically; do not accept a declared output
        # we cannot verify.
        return False
    return simulated.strip() == expected
