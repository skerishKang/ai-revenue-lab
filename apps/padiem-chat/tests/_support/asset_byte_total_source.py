"""Parsed views of the byte-ceiling contract sources (#8060).

Raw reads live here. Tests receive AST/token-derived names, numeric values,
expression signatures, byte prefixes and control-flow counts, so a ceiling
reintroduced with different whitespace or quote style is still caught. This
is the file-specific accessor; the shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

_APP = Path(__file__).resolve().parents[2] / "app"
_STATIC = Path(__file__).resolve().parents[2] / "static"
_MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"

_JS_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_JS_NUMBER = re.compile(r"\b\d[\d_]*(?:\.[\d_]+)?\b")
_JS_MULT = re.compile(r"\b\d[\d_]*(?:\s*\*\s*\d[\d_]*)+\b")


def forward_migration_sql(name: str) -> str:
    """The forward-migration text, read only inside this accessor."""
    return (_MIGRATIONS / name).read_text(encoding="utf-8")


def migration_sources() -> list[tuple[str, str]]:
    """Every migration as ``(filename, text)`` in replay order."""
    return [
        (path.name, path.read_text(encoding="utf-8"))
        for path in sorted(_MIGRATIONS.glob("*.sql"))
    ]


def _module(name: str) -> ast.Module:
    return ast.parse((_APP / f"{name}.py").read_text(encoding="utf-8"))


def _number(node: ast.AST) -> int | float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        inner = _number(node.operand)
        if inner is not None:
            return -inner if isinstance(node.op, ast.USub) else inner
    if isinstance(node, ast.BinOp):
        left, right = _number(node.left), _number(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.FloorDiv) and right:
            return left // right
    return None


def app_numbers(name: str) -> set[int | float]:
    """Every numeric constant and constant arithmetic result in a module."""
    result = set()
    for node in ast.walk(_module(name)):
        value = _number(node)
        if value is not None:
            result.add(value)
    return result


def app_names(name: str) -> set[str]:
    """Every identifier, attribute and declared name in a module."""
    result = set()
    for node in ast.walk(_module(name)):
        if isinstance(node, ast.Name):
            result.add(node.id)
        elif isinstance(node, ast.Attribute):
            result.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            result.add(node.name)
        elif isinstance(node, ast.arg):
            result.add(node.arg)
    return result


def app_comparisons(name: str) -> set[str]:
    """Unparsed comparisons, e.g. ``len(data) != record.size_bytes``."""
    return {
        ast.unparse(node)
        for node in ast.walk(_module(name))
        if isinstance(node, ast.Compare)
    }


def _bytes_startswith(node: ast.AST) -> bytes | None:
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "startswith" and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, bytes)):
        return node.args[0].value
    return None


def negated_startswith_prefixes(name: str) -> set[bytes]:
    """Bytes prefixes of a denied ``not value.startswith(b"...")`` check."""
    result = set()
    for node in ast.walk(_module(name)):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            prefix = _bytes_startswith(node.operand)
            if prefix is not None:
                result.add(prefix)
    return result


def not_if_targets(name: str) -> Counter:
    """Counts of ``if not <target>:`` branches in a module."""
    result: Counter = Counter()
    for node in ast.walk(_module(name)):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.UnaryOp)
                and isinstance(node.test.op, ast.Not)):
            result[ast.unparse(node.test.operand)] += 1
    return result


def not_in_membership_bytes(name: str) -> set[bytes]:
    """Bytes constants on the left of a ``b"..." not in value`` denial."""
    result = set()
    for node in ast.walk(_module(name)):
        if not isinstance(node, ast.Compare):
            continue
        for op in node.ops:
            if (isinstance(op, ast.NotIn) and isinstance(node.left, ast.Constant)
                    and isinstance(node.left.value, bytes)):
                result.add(node.left.value)
    return result


def negative_slice_bounds(name: str) -> set[int]:
    """Negative lower bounds of slices, e.g. ``value[-1024:]``."""
    result = set()
    for node in ast.walk(_module(name)):
        if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice)
                and node.slice.lower is not None):
            bound = _number(node.slice.lower)
            if isinstance(bound, int) and bound < 0:
                result.add(bound)
    return result


def js_identifiers(sheet: str) -> set[str]:
    """Identifiers in a shipped JS sheet, read only inside this accessor."""
    text = (_STATIC / sheet).read_text(encoding="utf-8")
    return set(_JS_IDENT.findall(text))


def js_numbers(sheet: str) -> set[int | float]:
    """Numeric literals and constant multiplication results in a JS sheet."""
    text = (_STATIC / sheet).read_text(encoding="utf-8")
    result = set()
    for match in _JS_NUMBER.findall(text):
        cleaned = match.replace("_", "")
        result.add(float(cleaned) if "." in cleaned else int(cleaned))
    for match in _JS_MULT.findall(text):
        factors = [int(part.replace("_", "")) for part in match.split("*")]
        product = 1
        for factor in factors:
            product *= factor
        result.add(product)
    return result
