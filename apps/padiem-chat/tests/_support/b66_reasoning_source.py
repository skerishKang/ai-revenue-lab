"""Parsed views for the B66 reasoning-level contracts (#8060 44차).

The raw ``read_text`` calls live here. Contract tests receive parsed values
(identifier/token sets, parsed registry JSON) and assert on those, so no test
module pins shipped source text by reading it itself. File paths are fixed in
this module, never in the tests.
"""
from __future__ import annotations

import ast
import io
import json
import os
import re
import tokenize
from pathlib import Path

from _support.claw_static import server_source, sheet

_CHAT = Path(__file__).resolve().parents[2]
_ROOT = Path(__file__).resolve().parents[4]

_JS_IDENTIFIER_RX = re.compile(r"[A-Za-z_$][\w$]*")

_APP_PREFIX = "apps/padiem-chat/app/"
_STATIC_PREFIX = "apps/padiem-chat/static/"


def _source(relative: str) -> str:
    """Read a source by repo-relative path, reusing the shared read helpers.

    ``claw_static`` already owns the Chat server-source and shipped-sheet reads;
    only the reference JS and the B14 registry JSON fall outside its paths.
    """
    if relative.startswith(_APP_PREFIX) and relative.endswith(".py"):
        return server_source(Path(relative).stem)
    if relative.startswith(_STATIC_PREFIX):
        return sheet(Path(relative).name)
    return (_ROOT / relative).read_text(encoding="utf-8")


def python_tokens(relative: str) -> set[str]:
    """Names, string literals and comments parsed from a Python source file.

    A forbidden provider parameter can only be referenced as a name, a string
    literal or a comment; collecting those tokens with ``ast``/``tokenize``
    keeps the guard's meaning while handing the test a parsed set.
    """
    source = _source(relative)
    tokens: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            tokens.add(node.id)
        elif isinstance(node, ast.Attribute):
            tokens.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            tokens.add(node.name)
        elif isinstance(node, ast.arg):
            tokens.add(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            tokens.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            tokens.add(node.value)
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            tokens.add(tok.string)
    return tokens


def js_identifiers(relative: str) -> set[str]:
    """Identifier tokens in a shipped JS source (strings/comments included).

    The regex tokenises the file instead of matching one long substring, so the
    test asserts membership of whole identifiers rather than pinning raw text.
    """
    return set(_JS_IDENTIFIER_RX.findall(_source(relative)))


def imported_top_level_modules(relative: str) -> set[str]:
    """Top-level module names imported by a Python source, parsed from its AST."""
    tree = ast.parse(_source(relative))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def has_self_assignment(relative: str, name: str) -> bool:
    """Whether a source reassigns ``name`` to itself (parsed, not text-matched)."""
    source = _source(relative)
    if relative.endswith(".py"):
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Name):
                continue
            if node.value.id != name:
                continue
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return True
        return False
    return re.search(
        rf"\b{re.escape(name)}\s*=\s*{re.escape(name)}\b", source
    ) is not None


def registry_upstream_model(model_id: str) -> str:
    """Upstream model id for ``model_id`` in the effective B14 registry (JSON parsed)."""
    raw = (
        os.environ.get("PADIEM_MODELS_REGISTRY_OVERRIDE", "").strip()
        or os.environ.get("PADIEM_MODELS_REGISTRY", "").strip()
    )
    path = (
        Path(raw).expanduser()
        if raw
        else _ROOT / "apps" / "korean-ai-platform" / "app" / "pilot" / "b14_models.json"
    )
    row = next(
        m
        for m in json.loads(path.read_text(encoding="utf-8")).get("models", [])
        if m.get("id") == model_id
    )
    return row["upstream_model"]
