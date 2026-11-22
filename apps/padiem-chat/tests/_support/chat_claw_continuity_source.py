"""Parsed views of the Chat/Claw one-conversation contracts (#8060).

Raw reads live here. Tests receive declarations, token sets, normalized
function statements and constant values. This is the file-specific accessor;
the shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import _r5_function_source as r5

_TESTS = Path(__file__).resolve().parents[1]
_APP = _TESTS.parent / "app"
_STATIC = _TESTS.parent / "static"
_STATE_JS = _STATIC / "conversation-state.js"
_HISTORY_PY = _APP / "history_constants.py"

_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_CHAIN = re.compile(r"(?:[A-Za-z_$][\w$]*)(?:\??\.[A-Za-z_$][\w$]*)+")
_CALL = re.compile(r"([A-Za-z_$][\w$]*)\s*\(")
_DECL = re.compile(r"function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)")
_CONST = re.compile(r"const\s+([A-Za-z_$][\w$]*)\s*=\s*([^;]+);")


def app_js_path() -> Path:
    return r5.APP_JS


def state_js_path() -> Path:
    return _STATE_JS


def transport_js_path() -> Path:
    return _STATIC / "chat-transport.js"


def _state_source() -> str:
    return _STATE_JS.read_text(encoding="utf-8")


def state_function_signatures() -> set[str]:
    return {
        f"function {match.group(1)}({match.group(2)})"
        for match in _DECL.finditer(_state_source())
    }


def state_conversation_initializer() -> str | None:
    for match in _CONST.finditer(_state_source()):
        if match.group(1) == "conversation":
            return " ".join(match.group(2).split())
    return None


def _state_chains() -> set[str]:
    return {"".join(chain.split()) for chain in _CHAIN.findall(_state_source())}


def state_call_chains() -> set[str]:
    return _state_chains()


def state_chain_objects() -> set[str]:
    return {match.group(0).split(".")[0].split("?")[0] for match in _CHAIN.finditer(_state_source())}


def state_call_names() -> set[str]:
    return set(_CALL.findall(_state_source()))


def state_identifiers() -> set[str]:
    return set(_IDENT.findall(_state_source()))


def app_identifiers() -> set[str]:
    return set(_IDENT.findall(r5.app_source()))


def function_statements(name: str, *, prefix: str = "function ") -> list[str]:
    """Normalized statements of a real function definition (#8060)."""
    body = r5.function_body(name, prefix=prefix)
    return [" ".join(line.split()) for line in body.splitlines()]


def history_constants() -> dict[str, object]:
    """Top-level constant assignments in the shipped server module."""
    tree = ast.parse(_HISTORY_PY.read_text(encoding="utf-8"))
    result: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            result[target.id] = ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            result[target.id] = ast.unparse(node.value)
    return result
