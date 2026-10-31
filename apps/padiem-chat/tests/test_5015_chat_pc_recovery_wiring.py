"""#5015 live PC result recovery: producer/consumer wiring contracts.

The Node test exercises the pure owner-scoped recovery controller. This Python
test keeps that JS contract in the normal pytest gate and pins the small app
wiring that makes a dropped live response recover from the durable run result
without a second PC POST.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
APP_JS = STATIC / "app.js"
INDEX_HTML = STATIC / "index.html"
TRANSPORT_JS = STATIC / "chat-transport.js"
RECOVERY_JS = STATIC / "chat-pc-result-recovery.js"
NODE_TEST = ROOT / "tests" / "test_5015_chat_pc_recovery.mjs"


def test_frontend_recovery_controller_contract():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    completed = subprocess.run(
        [node, "--test", str(NODE_TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_pc_run_handle_and_recovery_are_wired_to_the_real_consumer():
    app_js = APP_JS.read_text(encoding="utf-8")
    transport = TRANSPORT_JS.read_text(encoding="utf-8")
    index = INDEX_HTML.read_text(encoding="utf-8")
    assert "createChatPcRunId" in transport
    assert "payload.pc_run_id = pcRunId" in app_js
    assert "contextSnapshot.pcRunId || chatTransport.createChatPcRunId" in app_js
    assert "PadiemChatPcRecovery?.create" in app_js
    assert "recoverStoredPcResult(" in app_js
    assert "recoverOnce({" in app_js
    assert "waitForResult({" in app_js
    assert "resolvedPcRuns.has(runId)" in app_js
    assert "resolvedPcRuns.add(runId)" in app_js
    assert "chat-pc-result-recovery.js" in index
    # The recovery call is in the outer request catch, before the generic
    # renderError. A stream-incomplete error is handed to that catch.
    outer = app_js.split("async function requestAnswer(", 1)[1]
    outer = outer.split("function clawGeneralRequestActive(", 1)[0]
    assert outer.index("recoverStoredPcResult(") < outer.index("renderError(")
    assert "!clawGeneralRequest && contextSnapshot?.pcRunId && !terminalError" in app_js
    recovery = RECOVERY_JS.read_text(encoding="utf-8")
    assert "method: \"GET\"" in recovery
    assert "resolved.add(runId)" in recovery
    assert "answer_source" in recovery
    assert "result.run_id !== runId" in recovery


def test_server_accepts_only_a_canonical_client_recovery_handle():
    source = (ROOT / "app" / "chat_pc_drive.py").read_text(encoding="utf-8")
    assert "validate_chat_pc_run_id" in source
    assert "chat_pc_run_id_invalid" in source
    assert "lane_run_id = run_id or _new_lane_run_id()" in source
    assert "chat_pc_run_id_conflict" in source

    routes = (ROOT / "app" / "orchestration_routes.py").read_text(encoding="utf-8")
    # The Engine stream now receives the canonical recovery handle only after
    # the same server PC verification; the surface still owns no PC executor.
    assert "resolve_chat_pc_stream_context" in routes
    assert '_client_lane_run_id(raw.get("pc_run_id"))' in routes
    assert "session_id=pc_run_id" in routes
    assert "execute_chat_pc_drive_lane" not in routes

    chat_routes = (ROOT / "app" / "chat_routes.py").read_text(encoding="utf-8")
    # The direct Chat stream entry remains compatible. Its handle travels into the
    # lane so the staged run keeps the browser's id, and into the pinned-scope
    # notice lookup for the same completion frame.
    assert chat_routes.count("run_id=raw.get(\"pc_run_id\")") == 2

    contract = (ROOT / "app" / "request_contract.py").read_text(encoding="utf-8")
    assert "\"pc_run_id\", \"web_search\"}" in contract
    assert "validate_chat_pc_run_id" in contract


def test_request_contract_accepts_only_the_canonical_pc_run_handle():
    from app.request_contract import BrowserRequestError, _validate_payload

    valid = "chat_pcq_" + "e" * 32
    _validate_payload({
        "messages": [{"role": "user", "content": "내 PC 파일을 읽어줘"}],
        "pc_run_id": valid,
    })
    for invalid in ("chat_pcq_not-hex", "chat_" + "e" * 32, "chat_pcq_" + "e" * 31):
        try:
            _validate_payload({
                "messages": [{"role": "user", "content": "내 PC 파일을 읽어줘"}],
                "pc_run_id": invalid,
            })
        except BrowserRequestError:
            pass
        else:
            raise AssertionError(invalid)
