"""Source accessors for the PC connect flow and file-lane guidance tests (#8060).

Raw reads live here. The two contract tests keep their assertions and receive
the shipped text through these accessors.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"
_LANE_STORAGE = (_STATIC.parent.parent / "padiem-file-lane" / "src"
                 / "padiem_file_lane" / "storage.py")


def index_html() -> str:
    return claw_static.sheet("index.html")


def pc_connect_flow_js() -> str:
    return claw_static.sheet("pc-connect-flow.js")


def pc_connect_flow_path() -> Path:
    return _STATIC / "pc-connect-flow.js"


def file_lane_storage_source() -> str:
    return _LANE_STORAGE.read_text(encoding="utf-8")
