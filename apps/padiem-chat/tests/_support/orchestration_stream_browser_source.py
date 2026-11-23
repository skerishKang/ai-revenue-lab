"""Static source accessors for the orchestration stream browser contract (#8060).

Raw reads live here. The test keeps its behavioral observation, closed-label
contracts and user-facing redaction copy; it never reads a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def transport() -> str:
    return claw_static.sheet("chat-transport.js")


def app() -> str:
    return claw_static.sheet("app.js")


def stream() -> str:
    return claw_static.sheet("chat-streaming-module.js")


def lifecycle() -> str:
    return claw_static.sheet("message-lifecycle.js")


def panel() -> str:
    return claw_static.sheet("thought-panel.js")


def capability_css() -> str:
    return claw_static.sheet("capability-presentation.css")


def styles() -> str:
    return claw_static.sheet("styles.css")


def rich_response_css() -> str:
    return claw_static.sheet("rich-response.css")


def server_source() -> str:
    return claw_static.server_source("orchestration_stream")
