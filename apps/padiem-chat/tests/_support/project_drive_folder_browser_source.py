"""Source accessors for the Project Drive folder browser QA (#8060).

The shipped module and the test-side Node driver are read here. The test only
asserts on the driver's observed behavior and user-facing copy.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_TESTS = Path(__file__).resolve().parents[1]


def module_source() -> str:
    return claw_static.sheet("project-drive-folder.js")


def driver_source() -> str:
    return (_TESTS / "drive_folder_browser_driver.js").read_text(encoding="utf-8")
