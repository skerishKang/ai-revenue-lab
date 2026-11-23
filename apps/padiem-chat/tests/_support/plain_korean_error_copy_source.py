"""Source accessors for the plain-Korean error copy contract (#8060).

Raw reads live here. The test keeps its locale-copy, code-to-copy wiring and
raw-token absence contracts; it never reads a shipped file itself.
"""
from __future__ import annotations

import locale_bundle
from _support import claw_static


def locale() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def app_js() -> str:
    return claw_static.sheet("app.js")


def memory_js() -> str:
    return claw_static.sheet("chat-memory-module.js")


def run_history_js() -> str:
    return claw_static.sheet("chat-run-history-module.js")


def transport() -> str:
    return claw_static.sheet("chat-transport.js")


def front_worker() -> str:
    return claw_static.repo_source("apps/padiem-chat-front/worker.mjs")


def front_copy() -> str:
    return claw_static.repo_source("apps/padiem-chat-front/error-copy.mjs")


def front_test() -> str:
    return claw_static.repo_source("apps/padiem-chat-front/test/error_copy.test.mjs")
