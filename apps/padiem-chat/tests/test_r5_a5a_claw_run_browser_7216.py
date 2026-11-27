"""#7216 R5 A5a (claw-run) — 실제 Chromium에서 app.js clawRun 등록부 경유 호출 계약.

app.js에서 추출한 clawRun 등록부 연결부(app.provide("clawRun") 미러)와 15개
전달 함수 대역을 실제 헤드리스 Chromium 페이지에 주입하고, chat-claw-run-module.js와
함께 각 이름을 직접 호출해 화면 갱신·라이브 상태 읽기·콘솔 오류 0건을 검증한다.
"""
from __future__ import annotations

import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from _support.a5a_run_browser import app_js, static_dir

APP = app_js()
_STATIC_DIR = static_dir()

NAMES = (
    "setClawDocumentAction",
    "clearClawArtifact",
    "formatClawBytes",
    "renderClawArtifactMeta",
    "safeClawErrorMessage",
    "downloadClawArtifact",
    "revealClawCard",
    "setApprovalControlsBusy",
    "renderClawApprovalControls",
    "clearImmediateApprovalControls",
    "applyImmediateApprovalDecision",
    "renderClawRequestEcho",
    "clawClaimDispatchKey",
    "releaseClawDispatchKey",
    "runClawExecution",
)


def _extract_app_wiring() -> str:
    # R5 2부 B2: the module is created at the original declaration position;
    # that deps block is the app-side wiring the harness has to supply.
    # B7: app.js reaches the module through the registry (app.provide("clawRun")).
    # The harness mirrors that path: an app stub whose provide returns the piece
    # and carries the shared accessors the deps prototype must supply, the same
    # deps getters extracted from app.js, and the same per-name delegates the
    # exercise calls — each reading the registered piece. The extraction stops at
    # the real block end ("\n  }, app)));") — the create block no longer contains
    # a "\n  });" line, so an index-based end overshoots into the DOM const block
    # and redeclares the harness page locals (B6 regression, fixed here).
    create_start = APP.index('const clawRun = app.provide("clawRun",')
    create_end = APP.index("\n  }, app)));", create_start) + len("\n  }, app)));")
    create_block = APP[create_start:create_end]
    factory_block = (
        create_block
        + "\n  function clawRunModule() { return clawRun; }"
    )
    forwarders = []
    for name in NAMES:
        # B7: the one-line forwarders are gone from app.js — the harness
        # mirrors the registry path (clawRunModule() → app.provide("clawRun")).
        forwarders.append(
            f"function {name}(...a) {{ return clawRunModule().{name}(...a); }}"
        )
    # The deps names the module resolves through the shared context prototype in
    # app.js; the stub mirrors those shared accessors as live reads over the
    # same page locals the exercise and the harness stubs own.
    app_stub_getters = (
        "PRODUCT_CLAW", "authState", "chatTransport", "clawApprovalEpoch",
        "clawExecuteButton", "clawLastDispatchKey", "clawResultCard",
        "clawResultDocx", "clawResultEmpty", "clawResultHint", "clawResultPreview",
        "clawT", "clearClawRecovery", "clearClawWait", "conversationState",
        "failureCodeNote", "input", "mappedUiError", "safeLocalUiMessage",
        "setClawAreaState", "setClawButtonsBusy", "setClawStatus",
    )
    return (
        "  const app = {\n"
        "    provide(_name, piece) { return piece; },\n"
        + "".join(f"    get {n}() {{ return {n}; }},\n" for n in app_stub_getters)
        + "    get clawInFlight() { return clawInFlight; },\n"
        + "    set clawInFlight(value) { clawInFlight = value; },\n"
        + "    get clawApprovalInFlight() { return clawApprovalInFlight; },\n"
        + "    set clawApprovalInFlight(value) { clawApprovalInFlight = value; },\n"
        + "    set clawLastDispatchKey(value) { clawLastDispatchKey = value; },\n"
        + "  };\n"
        # B7 14차+15차: the clawRun deps getters read the retry/recovery/wait
        # and dispatch names through the clawStatus registry piece
        # (app.provide("clawStatus") in app.js); mirror it over the same
        # page-local stubs the deps used to reference bare.
        + "  function clawStatusModule() { return {\n"
        + "    clawRetryRemaining,\n"
        + "    clawRetryAfterFromResponse,\n"
        + "    isAmbiguousClawFailure,\n"
        + "    beginClawRetryCooldown,\n"
        + "    showClawAmbiguousRecoveryHint,\n"
        + "    beginClawWait,\n"
        + "    clawCurrentDispatchIsUncertain,\n"
        + "    clawVisibleExecutePayload,\n"
        + "    clawExecuteWireKey,\n"
        + "  }; }\n"
        + factory_block
        + "\n"
        + "\n".join(forwarders)
    )


HARNESS_TOP = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>R5 claw-run browser contract</title></head>
<body>
<textarea id="input"></textarea>
<div id="clawStatus"></div>
<div id="clawResultArea"></div>
<div id="clawResultPreview"></div>
<div id="clawResultCard"></div>
<div id="clawResultEmpty"></div>
<div id="clawResultKind"></div>
<div id="clawResultBadge"></div>
<div id="clawApprovalActions"></div>
<div id="clawRequestEcho"><div id="clawRequestEchoText"></div></div>
<div id="clawArtifactMeta"><div id="clawArtifactName"></div><div id="clawArtifactSize"></div></div>
<div id="clawResultSuccessNote"></div>
<div id="clawResultHint"></div>
<button id="clawExecuteButton"></button>
<button id="clawResultDocx"></button>
<script src="/chat-claw-run-module.js"></script>
<script>
"""

HARNESS_MID = """
(() => {
  "use strict";
  const input = document.getElementById("input");
  const clawStatus = document.getElementById("clawStatus");
  const clawResultArea = document.getElementById("clawResultArea");
  const clawResultPreview = document.getElementById("clawResultPreview");
  const clawResultCard = document.getElementById("clawResultCard");
  const clawResultEmpty = document.getElementById("clawResultEmpty");
  const clawResultKind = document.getElementById("clawResultKind");
  const clawResultBadge = document.getElementById("clawResultBadge");
  const clawApprovalActions = document.getElementById("clawApprovalActions");
  const clawRequestEcho = document.getElementById("clawRequestEcho");
  const clawRequestEchoText = document.getElementById("clawRequestEchoText");
  const clawArtifactMeta = document.getElementById("clawArtifactMeta");
  const clawArtifactName = document.getElementById("clawArtifactName");
  const clawArtifactSize = document.getElementById("clawArtifactSize");
  const clawResultSuccessNote = document.getElementById("clawResultSuccessNote");
  const clawResultHint = document.getElementById("clawResultHint");
  const clawExecuteButton = document.getElementById("clawExecuteButton");
  const clawResultDocx = document.getElementById("clawResultDocx");

  let clawInFlight = false;
  let clawApprovalInFlight = false;
  let clawApprovalEpoch = 1;
  let clawLastDispatchKey = null;
  const notes = [];
  const areaStates = [];
  let payloadContent = "hello";
  let retryRemaining = 0;
  let uncertain = false;
  let historyLoads = 0;
  const conversationState = { setConversationId(id, product) { notes.push(["conv", id, product]); } };
  function clawT(key) { return key; }
  function setClawStatus(message, state) { notes.push([message, state]); }
  function setClawAreaState(state) { areaStates.push(state); }
  function setClawButtonsBusy(busy) { clawInFlight = busy; }
  const conversationModule = () => ({ clawBoundedRefusalCopy, failureCodeNote });
  function clawBoundedRefusalCopy(code) {
    return code === "tier_unavailable" ? { message: "bounded-message", hint: "bounded-hint" } : null;
  }
  function approvalDecisionErrorMessage() { return "decision-error"; }
  function mappedUiError(message) { const e = new Error(message); e.code = "ui_error"; return e; }
  function safeLocalUiMessage(error, fallback) { return (error && error.message) || fallback; }
  function failureCodeNote() { return null; }
  async function loadClawRunHistory() { historyLoads += 1; }
  // B7: app.js reaches the run-history module through the registry
  // (app.provide("runHistory")), and the extracted deps getters read the
  // registry value the same way this stub mirrors.
  const runHistory = { loadClawRunHistory };
  function clawRetryRemaining() { return retryRemaining; }
  function clawCurrentDispatchIsUncertain() { return uncertain; }
  function clawVisibleExecutePayload() {
    return { content: payloadContent, channel: "sms", action: "quote" };
  }
  function clawExecuteWireKey(payload) { return JSON.stringify(payload); }
  function clearClawRecovery() {}
  function clawRetryAfterFromResponse() { return null; }
  function isAmbiguousClawFailure() { return false; }
  function beginClawRetryCooldown() {}
  function showClawAmbiguousRecoveryHint() {}
  function beginClawWait() {}
  function clearClawWait() {}
  const PRODUCT_CLAW = "claw";
  const authState = { authenticated: true };
  const chatTransport = { createRequestId: () => "req-browser" };
  window.PadiemClawPdfPreview = {
    create(parts) { notes.push(["pdf-preview", parts.document_id]); return { set() {}, clear() {} }; },
  };
  window.__fetchLog = [];
  window.__queue = [];
  window.fetch = (url, opts) => {
    window.__fetchLog.push({ url: String(url), method: (opts && opts.method) || "GET",
      headers: (opts && opts.headers) || {}, body: opts && opts.body });
    const next = window.__queue.length ? window.__queue.shift() : { status: 404, body: { ok: false } };
    return Promise.resolve({
      ok: next.status >= 200 && next.status < 400,
      status: next.status,
      json: () => Promise.resolve(next.body),
      blob: () => Promise.resolve({ size: 3 }),
    });
  };
"""

HARNESS_BOTTOM = """
  window.__exercise = async () => {
    const out = {};

    out.bytes500 = formatClawBytes(500);
    out.bytes2k = formatClawBytes(2048);
    out.bytes5m = formatClawBytes(5 * 1024 * 1024);
    out.bytesNeg = formatClawBytes(-1);

    setClawDocumentAction(true, "doc_" + "a".repeat(32), "report.docx");
    out.docId = clawResultDocx.dataset.documentId;
    out.docName = clawResultDocx.dataset.filename;
    out.docEnabled = !clawResultDocx.disabled;
    setClawDocumentAction(false);
    out.docDisabled = clawResultDocx.disabled;
    out.docIdCleared = !("documentId" in clawResultDocx.dataset);

    renderClawArtifactMeta({ document_id: "doc_" + "b".repeat(32), filename: "a.pdf",
      byte_length: 2048, media_type: "application/pdf" });
    out.metaHidden = clawArtifactMeta.hidden;
    out.metaName = clawArtifactName.textContent;
    out.metaSize = clawArtifactSize.textContent;
    out.previewNote = notes[notes.length - 1][0];

    clearClawArtifact();
    out.metaHiddenAfterClear = clawArtifactMeta.hidden;
    out.successHiddenAfterClear = clawResultSuccessNote.hidden;

    out.safeTier = safeClawErrorMessage({ error: { code: "tier_unavailable" } }, { status: 400 });
    out.safeRate = safeClawErrorMessage({ error: { code: "rate_limited" } }, { status: 429 });
    out.safeGeneric = safeClawErrorMessage(null, { status: 503 });

    revealClawCard("견적서", false);
    out.cardHidden = clawResultCard.hidden;
    out.kindText = clawResultKind.textContent;
    out.badgeKey = clawResultBadge.dataset.localeKey;

    setApprovalControlsBusy(clawApprovalActions, true);
    out.approveDisabled = clawApprovalActions.children.length === 0
      ? null : clawApprovalActions.children[1].disabled;
    setApprovalControlsBusy(clawApprovalActions, false);

    renderClawApprovalControls(clawApprovalActions, "run_1", null);
    out.approvalChildren = clawApprovalActions.children.length;
    out.approveText = clawApprovalActions.children[1].textContent;
    out.denyText = clawApprovalActions.children[2].textContent;
    clawApprovalActions.children[1].click();
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));
    const lastFetch = window.__fetchLog[window.__fetchLog.length - 1];
    out.decisionUrl = lastFetch.url;
    out.decisionBody = JSON.parse(lastFetch.body);

    clearImmediateApprovalControls();
    out.approvalHiddenAfterClear = clawApprovalActions.hidden;

    const resultText = { run_id: "run_9", status: "completed", result_text: "완료" };
    await applyImmediateApprovalDecision(resultText);
    out.previewAfterDecision = clawResultPreview.textContent;
    out.historyLoadsAfterDecision = historyLoads;

    renderClawRequestEcho("보낸 요청");
    out.echoText = clawRequestEchoText.textContent;
    out.echoHidden = clawRequestEcho.hidden;

    const key = clawClaimDispatchKey();
    out.key = key;
    out.keyOnButton = clawExecuteButton.dataset.clawDispatchKey;
    out.keyRepeat = clawClaimDispatchKey();
    releaseClawDispatchKey(key);
    out.keyCleared = !("clawDispatchKey" in clawExecuteButton.dataset);
    releaseClawDispatchKey("other");
    out.keyStillCleared = !("clawDispatchKey" in clawExecuteButton.dataset);

    window.__queue.push({ status: 200, body: { ok: true, result: {
      conversation_id: "conv_5", title: "견적 완료", status: "completed", result_text: "완료 문구",
      artifact: { document_id: "doc_" + "c".repeat(32), filename: "r.docx", byte_length: 2048,
        media_type: "application/pdf" } } } });
    await runClawExecution();
    const exec = window.__fetchLog[window.__fetchLog.length - 1];
    out.executeUrl = exec.url;
    out.executeMethod = exec.method;
    out.idempotencyKey = exec.headers["Idempotency-Key"];
    out.executeBody = JSON.parse(exec.body);
    out.lastDispatchKey = clawLastDispatchKey;
    out.convNote = notes.some((n) => n[0] === "conv" && n[1] === "conv_5" && n[2] === "claw");
    out.kindAfterRun = clawResultKind.textContent;
    out.previewAfterRun = clawResultPreview.textContent;
    out.areaStateAfterRun = areaStates[areaStates.length - 1];
    out.inFlightAfterRun = clawInFlight;

    clawInFlight = true;
    await runClawExecution();
    out.noFetchWhileBusy = window.__fetchLog.length;
    clawInFlight = false;

    return out;
  };
})();
</script>
</body></html>
"""


def test_claw_run_forwarders_execute_in_headless_chromium_with_zero_console_errors(tmp_path) -> None:
    wiring = _extract_app_wiring()
    harness_html = HARNESS_TOP + HARNESS_MID + wiring + HARNESS_BOTTOM
    harness_file = tmp_path / "harness.html"
    harness_file.write_text(harness_html, encoding="utf-8")

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server's spelling
            # #7601: a real browser asks for the icon on its own. The throwaway
            # test server has no icon and answered 404, which the browser logs
            # as a console error, so the zero-console-errors assertion failed
            # for a request the page never made. Answer 204 for the icon only:
            # every console error the page itself can cause is still recorded.
            if self.path.split("?", 1)[0] == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            super().do_GET()

        def translate_path(self, path: str) -> str:
            clean = path.split("?", 1)[0].lstrip("/")
            if clean == "harness.html":
                return str(harness_file)
            return str(_STATIC_DIR / clean)

        def log_message(self, *_args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    console_errors: list[str] = []
    page_errors: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.on(
                    "console",
                    lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
                )
                page.on("pageerror", lambda err: page_errors.append(str(err)))
                page.goto(f"http://127.0.0.1:{port}/harness.html", wait_until="load")
                result = page.evaluate("() => window.__exercise()")
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()

    assert console_errors == []
    assert page_errors == []
    assert result["bytes500"] == "500 B"
    assert result["bytes2k"] == "2 KB"
    assert result["bytes5m"] == "5.0 MB"
    assert result["bytesNeg"] == ""
    assert result["docId"] == "doc_" + "a" * 32
    assert result["docName"] == "report.docx"
    assert result["docEnabled"] is True
    assert result["docDisabled"] is True
    assert result["docIdCleared"] is True
    assert result["metaHidden"] is False
    assert result["metaName"] == "a.pdf"
    assert result["metaSize"] == "2 KB"
    assert result["previewNote"] == "pdf-preview"
    assert result["metaHiddenAfterClear"] is True
    assert result["successHiddenAfterClear"] is True
    assert result["safeTier"] == "bounded-message"
    assert result["safeRate"] == "claw-error-rate-limited"
    assert result["safeGeneric"] == "claw-error-generic"
    assert result["cardHidden"] is False
    assert result["kindText"] == "견적서"
    assert result["badgeKey"] == "claw-result-badge"
    assert result["approvalChildren"] == 4
    assert result["approveText"] == "claw-approval-approve"
    assert result["denyText"] == "claw-approval-deny"
    assert result["decisionUrl"] == "/api/claw/approvals/decision"
    assert result["decisionBody"] == {"run_id": "run_1", "decision": "approve"}
    assert result["approvalHiddenAfterClear"] is True
    assert result["previewAfterDecision"] == "완료"
    assert result["historyLoadsAfterDecision"] == 1
    assert result["echoText"] == "보낸 요청"
    assert result["echoHidden"] is False
    assert result["key"] == "claw-req-browser"
    assert result["keyOnButton"] == "claw-req-browser"
    assert result["keyRepeat"] == "claw-req-browser"
    assert result["keyCleared"] is True
    assert result["keyStillCleared"] is True
    assert result["executeUrl"] == "/api/claw/manual-intake/execute"
    assert result["executeMethod"] == "POST"
    assert result["idempotencyKey"] == "claw-req-browser"
    assert result["executeBody"] == {"content": "hello", "channel": "sms", "action": "quote"}
    assert result["lastDispatchKey"] == '{"content":"hello","channel":"sms","action":"quote"}'
    assert result["convNote"] is True
    assert result["kindAfterRun"] == "견적 완료"
    assert result["previewAfterRun"] == "완료 문구"
    assert result["areaStateAfterRun"] == "success"
    assert result["inFlightAfterRun"] is False
    assert result["noFetchWhileBusy"] == 2
