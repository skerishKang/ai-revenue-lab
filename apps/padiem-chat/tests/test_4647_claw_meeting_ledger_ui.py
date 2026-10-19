"""#4647 meeting ledger UI contract, executed by Node against the real module.

The node script runs `meeting-capture.js`'s own mount() with a stub DOM and a
recorded fetch, so these markers are executed behavior rather than source grep.
No network, Drive call, Engine call or model call happens here.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
STATIC = TESTS.parents[0] / "static"
SCRIPT = TESTS / "meeting_ledger_node.js"
MARKERS = (
    "MEETING_LEDGER_CREATE_END_RECEIPT=PASS",
    "MEETING_LEDGER_NO_CONTENT_OR_SCOPE=PASS",
    "MEETING_LEDGER_OUTAGE_KEEPS_CAPTURE=PASS",
    "MEETING_LEDGER_DELETE_BOUNDARY=PASS",
    "MEETING_LEDGER_DETAIL_TRUTHFUL_STATES=PASS",
)

HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CAPTURE = (STATIC / "meeting-capture.js").read_text(encoding="utf-8")
CSS = (STATIC / "meeting-capture.css").read_text(encoding="utf-8")


def test_meeting_ledger_node_behavior_runs_green():
    if shutil.which("node") is None:
        pytest.skip("Node runtime unavailable; run CI for the browser contract")
    result = subprocess.run(["node", str(SCRIPT)], capture_output=True, text=True,
                            encoding="utf-8", timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    for marker in MARKERS:
        assert marker in result.stdout


def test_records_block_lives_inside_the_existing_meeting_view():
    start = HTML.index('<section id="meetingView"')
    records_start = HTML.index('class="meeting-records"', start)
    block = HTML[records_start: HTML.index("</section>", records_start)]
    assert block.startswith('class="meeting-records" aria-labelledby="meetingRecordsTitle"')
    for identifier in ("meetingRecordsList", "meetingRecordsEmpty", "meetingRecordsStatus",
                       "meetingRecordsDetail", "meetingTitleInput", "meetingSaveTitle"):
        assert f'id="{identifier}"' in block, identifier
    # The records section adds exactly one polite live region of its own.
    assert block.count('role="status"') == 1
    # Records reuse the page: no new dialog, modal or second recorder surface.
    assert '<dialog id="meetingRecords' not in HTML
    assert re.search(r'meeting-records[\s\S]{0,400}id="meetingTitleInput"', block)


def test_ledger_endpoints_are_the_only_new_network_surface_in_the_page():
    paths = {value.strip('"') for value in re.findall(r'"(/api/claw/[a-z/-]+)"', CAPTURE)}
    assert paths == {"/api/claw/meetings"}, paths
    assert "EventSource" not in CAPTURE and "new WebSocket" not in CAPTURE
    # Owner, workspace and Drive scope are never assembled in the browser.
    for forbidden in ("user_id", "workspace_id", "oauth", "access_token", "refresh_token",
                      "drive_file_id: null"):
        assert forbidden not in CAPTURE.lower(), forbidden


def test_ledger_wiring_keeps_the_pinned_capture_contracts():
    # The recorder's own affordance lines are unchanged by the ledger work.
    assert 'startButton.disabled = state.active || state.pending || !signedIn' in CAPTURE
    assert 'controller.snapshot().active && !uploadInFlight' in CAPTURE
    assert 'shell.dataset.state = "meeting";' in CAPTURE
    assert "meetingClose" not in CAPTURE
    # Capture never depends on the ledger result.
    assert "await controller.start(selected); void startLedger(selected);" in CAPTURE
    assert 'recordArtifact(kind === "text" ? "transcript" : kind, result, blob)' in CAPTURE


def test_records_css_adds_no_competing_surface():
    assert ".meeting-records-list { display: grid; gap: 6px; }" in CSS
    assert "max-width: 1080px" not in CSS
    assert ".meeting-view dialog" not in CSS
