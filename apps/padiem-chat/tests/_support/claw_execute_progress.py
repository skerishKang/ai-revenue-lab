"""#8060 39차: raw reads for the Claw execute progress contracts.

app.js, index.html, the Claw status/run/run-history modules, claw-workspace.css
and the shipped locale table are read here, so the contract tests receive the
text (and the parsed KO/EN table) without opening static files themselves.
Helper bodies are verbatim moves of what the test file did inline.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import locale_bundle

ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def app_js() -> str:
    return (ROOT / "static/app.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (ROOT / "static/index.html").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def status_module() -> str:
    return (ROOT / "static/chat-claw-status-module.js").read_text(encoding="utf-8")


def run_module() -> str:
    return (ROOT / "static/chat-claw-run-module.js").read_text(encoding="utf-8")


def run_history_module() -> str:
    return (ROOT / "static/chat-run-history-module.js").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def workspace_css() -> str:
    return (ROOT / "static/claw-workspace.css").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def locale_table() -> dict[str, dict[str, str]]:
    """Parse the shipped KO/EN copy out of locale.js.

    The behavioral harness renders against THESE strings rather than a local
    duplicate, so shipped copy and asserted copy cannot drift apart. A drifted
    harness is exactly how a literal ``{seconds}`` placeholder once reached the
    live status region while every test counted green (#2766 review).
    """
    source = locale_source()
    pattern = re.compile(r'"([A-Za-z0-9_\-]+)":\s*"((?:[^"\\]|\\.)*)"')

    def unescape(value: str) -> str:
        out = value.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
        return out.replace("\\\\", "\\")

    def pairs(block: str) -> dict[str, str]:
        return {key: unescape(value) for key, value in pattern.findall(block)}

    assert "en: {" in source
    ko_part, en_part = source.split("en: {", 1)
    table = {"ko": pairs(ko_part), "en": pairs(en_part)}
    assert table["ko"] and table["en"]
    return table


def wait_block() -> str:
    module = status_module()
    assert "── In-flight elapsed wait (#2763)" in module
    constants = "\n".join(
        line.strip()
        for line in module.splitlines()
        if line.strip().startswith("const CLAW_WAIT_")
    )
    wait = module.split("── In-flight elapsed wait (#2763)", 1)[1].split("\n      return {", 1)[0]
    return constants + "\n" + wait
