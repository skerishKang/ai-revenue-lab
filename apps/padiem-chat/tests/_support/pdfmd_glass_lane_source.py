"""Raw static sheet access for the #8812 PDF→MD glass lane contract (#8060).

Raw ``read_text`` stays here so the test module never reads a shipped file
itself (structure ratchet #8054 counts raw-static-reading test files).
"""
from __future__ import annotations

from _support import claw_static


def frame_sheet() -> str:
    return claw_static.sheet("shared-six-panel-frame.css")


def lane_sheet() -> str:
    return claw_static.sheet("util-pdfmd-glass-lane.css")


def index_html() -> str:
    return claw_static.sheet("index.html")
