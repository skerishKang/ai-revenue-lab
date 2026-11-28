"""#7809 13/13: final facade cleanup and real PC intent binding checks."""
from __future__ import annotations

import ast
import importlib

from _support.claw_general_modules import (
    CLAW_GENERAL_MODULES,
    patch_bound,
    source_of,
)


def test_entry_dead_imports_are_absent_and_routes_remain_unchanged_objects():
    entry = importlib.import_module("app.claw_general_routes")
    text = source_of(entry)
    tree = ast.parse(text)
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(alias.asname or alias.name for alias in node.names)
    assert imported.isdisjoint({"hashlib", "secrets", "latest_native_calendar_text"})
    assert callable(entry.claw_general_execute)
    assert callable(entry._claw_general_terminal)
    assert "claw_general_pc_intent" in CLAW_GENERAL_MODULES


def test_chat_pc_command_reads_narrow_intent_at_module_scope():
    lane = importlib.import_module("app.chat_pc_command")
    intent = importlib.import_module("app.claw_general_pc_intent")
    entry = importlib.import_module("app.claw_general_routes")
    assert lane._requested_local_command is intent._requested_local_command
    assert lane._requested_natural_pc_query is intent._requested_natural_pc_query
    assert entry._requested_local_command is intent._requested_local_command
    assert entry._requested_natural_pc_query is intent._requested_natural_pc_query
    tree = ast.parse(source_of(lane))
    imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)]
    assert any(node.module == "claw_general_pc_intent"
               and {a.name for a in node.names}
               == {"_requested_local_command", "_requested_natural_pc_query"}
               for node in imports)
    assert not any(isinstance(node, ast.ImportFrom)
                   and node.module == "claw_general_routes"
                   for node in ast.walk(tree))


def test_patch_bound_reaches_real_chat_command_caller(monkeypatch):
    lane = importlib.import_module("app.chat_pc_command")
    fake = lambda _text: (True, "sentinel-explicit-command")
    assert patch_bound(monkeypatch, "_requested_local_command", fake, modules=[lane]) == [lane]
    assert lane.chat_pc_command_for_turn("내 PC에서 `whoami` 실행해") == "sentinel-explicit-command"
    assert lane._match_command("내 PC에서 `whoami` 실행해") == (True, "sentinel-explicit-command")


def test_patch_bound_reaches_real_chat_natural_command_caller(monkeypatch):
    lane = importlib.import_module("app.chat_pc_command")
    fake = lambda _text: (True, "sentinel-natural-command")
    assert patch_bound(monkeypatch, "_requested_natural_pc_query", fake, modules=[lane]) == [lane]
    assert lane.chat_pc_command_for_turn("내 컴퓨터의 프로세스는?") == "sentinel-natural-command"
    # A file question retains the existing refusal even when the natural
    # matcher recognizes a PC query.
    assert lane.chat_pc_command_for_turn("내 컴퓨터 파일 보여줘") is None
