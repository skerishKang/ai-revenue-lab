"""Read the Claw lane's shipped sheets for the session-reopen contracts
(#8060 40차, #8061 방향: 원문 읽기는 _support가 담당).

``lane_source()`` keeps the exact five-sheet span the Claw run-card contracts
pin counts over (app.js plus the run-history·claw-status·claw-run·claw-form
modules). The other readers are single shipped sheets and the one test
module whose scoped harness exemption is pinned.
"""
from __future__ import annotations

import locale_bundle
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def lane_source() -> str:
    """app.js + the four Claw lane modules, in the contracts' span order."""
    return "\n".join([
        (_STATIC / "app.js").read_text(encoding="utf-8"),
        (_STATIC / "chat-run-history-module.js").read_text(encoding="utf-8"),
        (_STATIC / "chat-claw-status-module.js").read_text(encoding="utf-8"),
        (_STATIC / "chat-claw-run-module.js").read_text(encoding="utf-8"),
        (_STATIC / "chat-claw-form-module.js").read_text(encoding="utf-8"),
    ])


def streaming_source() -> str:
    return (_STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")


def history_module_source() -> str:
    return (_STATIC / "chat-history-module.js").read_text(encoding="utf-8")


def index_source() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def test_module_source(path: Path) -> str:
    """A sibling test module's source (the scoped exemption pin)."""
    return path.read_text(encoding="utf-8")
