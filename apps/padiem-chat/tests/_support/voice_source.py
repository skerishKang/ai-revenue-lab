"""Shipped-source accessors for voice contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
_STATIC = _TESTS.parent / "static"
_APP = _TESTS.parent / "app"


def _repo_root() -> Path:
    repo = Path(__file__).resolve().parent
    while repo != repo.parent and not (repo / "apps" / "padiem-chat-front" / "worker.mjs").exists():
        repo = repo.parent
    return repo


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def voice_authority_js() -> str:
    return (_STATIC / "voice-live-transcript-turn.js").read_text(encoding="utf-8")


def voice_adapter_js() -> str:
    return (_STATIC / "voice-stt-input.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def front_worker_mjs() -> str:
    return (_repo_root() / "apps" / "padiem-chat-front" / "worker.mjs").read_text(encoding="utf-8")


def front_wrangler_toml() -> str:
    return (_repo_root() / "apps" / "padiem-chat-front" / "wrangler.toml").read_text(encoding="utf-8")


def voice_stt_routes_py() -> str:
    return (_APP / "voice_stt_routes.py").read_text(encoding="utf-8")
