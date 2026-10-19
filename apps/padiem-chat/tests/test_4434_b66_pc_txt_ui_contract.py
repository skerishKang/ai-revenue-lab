"""#4434 follow-up: static contract for the minimal B66 PC TXT request UI.

The browser only names a server-listed conversation, a .txt relative path
and a server-listed device. It never mints run ids, never renders file bytes
and never claims a connection. New surface lives only in B66-owned
``b66-quote-runtime.js``/``b66-quote-runtime.css``; common Chat/Claw files and
the #5006/#5007 surfaces stay untouched.
"""
from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = Path(__file__).resolve().parents[1] / "app"
REF = Path(__file__).resolve().parents[2].parent / "reference" / "business-66-padiem-quote-v1"


def _js() -> str:
    return (STATIC / "b66-quote-runtime.js").read_text(encoding="utf-8")


def test_txt_request_surface_exists_and_is_bounded():
    js = _js()
    for element_id in (
        '"b66QuotePcTxt"', '"b66QuotePcConversation"', '"b66QuotePcPath"',
        '"b66QuotePcRequest"', '"b66QuotePcRunStatus"', '"b66QuotePcTxtTitle"',
    ):
        assert element_id in js
    assert 'PC_TXT_READ_PATH = "/api/b66/connect/txt-reads/request"' in js
    assert 'PC_DIALOGUES_PATH = "/api/b66/ai/dialogues?limit=20"' in js
    assert 'PC_RESULT_PATH_PREFIX = "/api/b66/runs/"' in js
    assert "MAX_PC_DIRECTORY_BYTES = 32768" in js
    assert "/^chat_[0-9a-f]{32}$/" in js
    assert "/^run_[A-Za-z0-9]{12,80}$/" in js
    assert "attempt < 20" in js
    assert "textContent" in js
    assert "innerHTML" not in js


def test_txt_request_never_mints_server_owned_values():
    js = _js()
    body = js.split("async function requestPcTxtRead()", 1)[1].split(
        "async function pollPcRunResult(", 1)[0]
    assert "root_ref" not in body
    assert "run_id" not in body or "data.run_id" in body
    assert "confirmed" not in body
    assert "Math.random" not in body
    assert "Date.now" not in body


def test_txt_poll_reports_terminal_states_without_file_bytes():
    js = _js()
    poll = js.split("async function pollPcRunResult(", 1)[1].split(
        "window.addEventListener(\"padiem:capabilitychange\"", 1)[0]
    assert 'method: "POST"' in poll
    assert "pcRunPending" in poll
    assert "pcRunDone" in poll
    assert "pcRunFailed" in poll
    assert "responseText" not in poll
    assert "stdout" not in poll
    assert "content" not in poll or "textContent" in poll


def test_common_and_product_surfaces_untouched():
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    for marker in (
        "b66QuotePcTxt", "b66QuotePcConversation", "b66QuotePcPath",
        "b66QuotePcRequest", "b66QuotePcRunStatus", "txt-reads/request",
        "pcRunPending", "pcRunDone",
    ):
        assert marker not in app_js
    css = (STATIC / "b66-quote-runtime.css").read_text(encoding="utf-8")
    assert "b66-quote-connect-txt" in css
    assert "b66-quote-connect-request" in css
    assert "b66-quote-connect-run-status" in css
