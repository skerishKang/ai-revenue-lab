"""#8204: the operations PC table must not ship broken Korean text."""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
FILES = ("admin.html", "admin-ops.js")
BROKEN_RUN = re.compile(r"\?{3,}")
ANY_RUN = re.compile(r"\?{2,}")
HEADING = re.compile(r'id="opsPcVersionsHeading".*?id="opsPcVersionsStatus"', re.DOTALL)
VERSION_STATUS = re.compile(r'"opsPcVersionsStatus"\s*,\s*"[^"]*"')
DISPLAY_TOKEN = "item.display_name"
MASK_TOKEN = "slice(-6)"


def _read(name):
    return (STATIC / name).read_text(encoding="utf-8")


def test_no_three_question_run_in_shipped_static_files():
    for name in FILES:
        assert BROKEN_RUN.search(_read(name)) is None


def test_pc_version_section_has_no_question_runs():
    html = _read(FILES[0])
    section = HEADING.search(html)
    assert section is not None
    assert ANY_RUN.search(section.group(0)) is None
    js = _read(FILES[1])
    for match in VERSION_STATUS.finditer(js):
        assert ANY_RUN.search(match.group(0)) is None


def test_pc_version_rows_mask_the_node_identifier():
    js = _read(FILES[1])
    assert DISPLAY_TOKEN in js
    assert MASK_TOKEN in js
