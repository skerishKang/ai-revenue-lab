"""#3580 shipped browser script behavioral tests, no network or browser service."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests" / "web_xlsx_p01_owner_ui_node.js"
STATIC = ROOT / "static"


def test_hark_browser_p01_ui_has_closed_explicit_controls():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "claw-web-xlsx-sources.js").read_text(encoding="utf-8")
    css = (STATIC / "claw-local-handoff.css").read_text(encoding="utf-8")
    for ident in (
        "clawWebXlsxP01Panel", "clawWebXlsxP01Selected",
        "clawWebXlsxP01Status", "clawWebXlsxP01Refresh",
        "clawWebXlsxP01Approve", "clawWebXlsxP01Deny",
    ):
        assert f'id="{ident}"' in html
        assert f'$("{ident}")' in js
    assert html.count('id="clawWebXlsxP01Approve"') == 1
    assert html.count('id="clawWebXlsxP01Deny"') == 1
    assert 'id="clawWebXlsxP01Approve" hidden disabled' in html
    assert 'id="clawWebXlsxP01Deny" hidden disabled' in html
    assert ".claw-web-office-approval[hidden]" in css
    assert "P01 승인" in html
    assert 'SELECTIONS + "/" + encodeURIComponent(ref) + "/p01-decision"' in js
    assert 'SELECTIONS + "/" + encodeURIComponent(selectionRef) + "/p01-status"' in js
    assert 'body: JSON.stringify({ decision })' in js
    assert "attemptedRefs.add(ref)" in js
    assert 'credentials: "same-origin", cache: "no-store"' in js


def test_browser_real_xlsx_approval_ui_one_shot_and_server_only_state():
    if shutil.which("node") is None:
        pytest.skip("Node unavailable locally; required B62 Linux CI browser test")
    result = subprocess.run(
        ["node", str(SCRIPT)], capture_output=True, text=True,
        timeout=20, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for marker in (
        "WEB_XLSX_REAL_BROWSER_OWNER_DECISION=PASS",
        "WEB_XLSX_ONE_SHOT_UNKNOWN_OUTCOME=PASS",
        "WEB_XLSX_SERVER_STATUS_ONLY=PASS",
    ):
        assert marker in result.stdout
