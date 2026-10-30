"""#5573 step 1: the one connect flow is the page's own script, and it lies to
nobody.

The browser harness runs the real module against a scripted fetch, so the
owner's contract is executed rather than described: a first-time account (zero
PCs) gets one modal whose single press downloads the connect program and whose
wait closes itself when the server sees the PC; an account that already has a
PC never sees the modal, only one line; the popover carries names and states
and nothing else.
"""
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
STATIC = HERE.parents[0] / "static"
MODULE = STATIC / "pc-connect-flow.js"
HARNESS = HERE / "pc_connect_flow_harness.js"
INDEX = STATIC / "index.html"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required for the browser harness")


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([NODE, *args], capture_output=True, text=True, timeout=120,
                          encoding="utf-8", errors="replace")


def test_the_page_loads_the_flow_and_its_own_sheet():
    html = INDEX.read_text(encoding="utf-8")
    assert './pc-connect-flow.js' in html
    assert './pc-connect-flow.css' in html
    source = MODULE.read_text(encoding="utf-8")
    # The flow is one surface with one entry point; nothing here may render a
    # pairing code or speak to another endpoint.
    assert "innerHTML" not in source
    assert '"/api/pc/pairings"' in source
    assert "code=" not in source
    # The static persistence gate forbids browser storage, and the flow keeps
    # none: the server's pairing list is the only memory.
    for forbidden in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
        assert forbidden not in source


def test_the_harness_flow_passes_every_check():
    result = _run(str(HARNESS), str(MODULE))
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "PC_CONNECT_FLOW=PASS" in output
    # 25 checks: the first-time flow (modal, one press, download, self-closing
    # wait), the one-line no-modal path for a connected account, the refusals
    # that read as refusals, the popover that carries names and states only,
    # and the card that never paints an unread state as "연결 안 됨".
    assert output.count("PC_CONNECT_FLOW_CHECK") == 25
    assert "FAIL" not in output


def test_the_harness_itself_fails_when_the_flow_lies():
    """Differential proof: the same harness refuses a flow that reports the
    connect program as ready while the server says it is not. Edited copy, not
    shipped code."""
    broken = MODULE.read_text(encoding="utf-8").replace(
        'notReady: "PC 연결 기능은 아직 준비 중입니다. 잠시 후 다시 시도해 주세요.",',
        'notReady: "연결됐어요 ✓",',
    )
    assert broken != MODULE.read_text(encoding="utf-8")
    temporary = HERE / "_pc_connect_flow_broken.js"
    temporary.write_text(broken, encoding="utf-8")
    try:
        result = _run(str(HARNESS), str(temporary))
    finally:
        temporary.unlink(missing_ok=True)
    assert result.returncode != 0
    assert "PC_CONNECT_FLOW=FAIL" in result.stdout + result.stderr
    assert ("a not-ready server reads as 준비 중, never as 연결됐어요 FAIL"
            in result.stdout)
