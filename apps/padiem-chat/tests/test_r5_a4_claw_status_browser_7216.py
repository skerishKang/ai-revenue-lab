"""#7216 R5 A4 (claw status) — 실제 Chromium에서 app.js 전달 함수 19개 호출 계약.

app.js에서 추출한 clawStatusModule() 연결부와 19개 한 줄 전달 함수를 실제
헤드리스 Chromium 페이지에 주입하고, chat-claw-status-module.js와 함께 각 전달
함수를 직접 호출해 화면 갱신·라이브 상태 읽기·콘솔 오류 0건을 검증한다.
"""
from __future__ import annotations

import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")

NAMES = (
    "syncComposerForClaw",
    "setClawStatus",
    "setClawAreaState",
    "setClawButtonsBusy",
    "clawRetryRemaining",
    "clawVisibleExecutePayload",
    "clawExecuteWireKey",
    "clawCurrentDispatchIsUncertain",
    "noteClawContentEdited",
    "clawRetryAfterFromResponse",
    "isAmbiguousClawFailure",
    "clearClawRecovery",
    "renderClawRetryBox",
    "beginClawRetryCooldown",
    "showClawAmbiguousRecoveryHint",
    "applyClawWaitStageCopy",
    "renderClawWait",
    "beginClawWait",
    "clearClawWait",
)


def _extract_app_wiring() -> str:
    factory_start = APP.index("let clawStatusModuleInstance = null;")
    factory_end = APP.index("\n  function syncComposerForClaw(...a)", factory_start)
    factory_block = APP[factory_start:factory_end]
    forwarders = []
    for name in NAMES:
        match = re.search(
            rf"^\s*(?:async\s+)?function\s+{re.escape(name)}\(\.\.\.a\)\s*\{{[^\n]+\}}",
            APP,
            re.M,
        )
        assert match is not None, name
        forwarders.append(match.group(0).strip())
    return factory_block + "\n" + "\n".join(forwarders)


HARNESS_TOP = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>R5 claw-status browser contract</title></head>
<body>
<div id="shell"></div>
<textarea id="input"></textarea>
<div id="clawStatus"></div>
<div id="clawResultArea"></div>
<button id="clawGenerateBtn"></button>
<button id="clawExecuteButton"></button>
<input id="clawChannel">
<input id="clawAction">
<input id="clawSender">
<div id="clawRetryBox"><div id="clawRetryCopy"></div><button id="clawRetryButton"></button><div id="clawRetryHint"></div></div>
<div id="clawWait" hidden></div>
<div id="clawWorkspace"></div>
<script src="/chat-claw-status-module.js"></script>
<script>
"""

HARNESS_MID = """
(() => {
  "use strict";
  const timers = new Map();
  let nextTimer = 1;
  window.setInterval = (fn) => { const id = nextTimer++; timers.set(id, fn); return id; };
  window.clearInterval = (id) => { timers.delete(id); };
  const tick = () => { for (const fn of [...timers.values()]) fn(); };

  const input = document.getElementById("input");
  const shell = document.getElementById("shell");
  const clawStatus = document.getElementById("clawStatus");
  const clawResultArea = document.getElementById("clawResultArea");
  const clawGenerateBtn = document.getElementById("clawGenerateBtn");
  const clawExecuteButton = document.getElementById("clawExecuteButton");
  const clawChannel = document.getElementById("clawChannel");
  const clawAction = document.getElementById("clawAction");
  const clawSender = document.getElementById("clawSender");
  const clawRetryBox = document.getElementById("clawRetryBox");
  const clawRetryCopy = document.getElementById("clawRetryCopy");
  const clawRetryButton = document.getElementById("clawRetryButton");
  const clawRetryHint = document.getElementById("clawRetryHint");
  const clawWait = document.getElementById("clawWait");
  const clawWorkspace = document.getElementById("clawWorkspace");
  clawChannel.value = "sms";
  clawAction.value = "quote";
  clawSender.value = "sender";
  clawWorkspace.dataset.view = "manual";

  let clawInFlight = false;
  let clawRetrySeconds = 0;
  let clawRetryTimer = null;
  let clawWaitStartedAt = 0;
  let clawWaitTimer = null;
  let clawWaitRevealed = false;
  let clawWaitAnnouncedStage = 0;
  const clawUncertainKeys = new Set();
  let clawLastDispatchKey = null;
  const conversationState = { getConversationId: () => "conv_a4" };
  function clawT(key, vars) { return vars ? key + ":" + vars.seconds : key; }
  function localeOr(key, fallback) { return fallback || key; }
  function selectedProductTier() { return "pro"; }
"""

HARNESS_BOTTOM = """
  window.__exercise = () => {
    const out = {};
    input.value = "hello";
    syncComposerForClaw(true);
    out.tier = shell.dataset.clawTier;
    out.placeholder = input.placeholder;
    out.describedby = input.getAttribute("aria-describedby");
    syncComposerForClaw(false);
    out.placeholderIdle = input.placeholder;
    out.tierAfterFalse = shell.dataset.clawTier;

    setClawStatus("running", "running", "run-key");
    out.statusHidden = clawStatus.hidden;
    out.statusText = clawStatus.textContent;
    out.statusState = clawStatus.dataset.state;
    out.statusKey = clawStatus.dataset.localeKey;
    setClawStatus("", null, null);
    out.statusHiddenAfter = clawStatus.hidden;
    out.ariaInvalidAfter = input.getAttribute("aria-invalid");

    setClawAreaState("ready");
    out.areaState = clawResultArea.dataset.clawState;

    setClawButtonsBusy(true);
    out.busy = clawInFlight;
    out.genDisabled = clawGenerateBtn.disabled;
    out.execDisabled = clawExecuteButton.disabled;
    setClawButtonsBusy(false);
    out.busyAfter = clawInFlight;
    out.execDisabledAfter = clawExecuteButton.disabled;

    const payload = clawVisibleExecutePayload();
    out.payload = payload;
    const key = clawExecuteWireKey(payload);
    out.wireKey = key;
    out.retryRemaining0 = clawRetryRemaining();

    clawUncertainKeys.add(key);
    out.uncertain = clawCurrentDispatchIsUncertain();
    noteClawContentEdited();
    clawUncertainKeys.clear();
    out.uncertainAfter = clawCurrentDispatchIsUncertain();

    out.retryAfter5 = clawRetryAfterFromResponse({ headers: { get: () => "5" } });
    out.retryAfter0 = clawRetryAfterFromResponse({ headers: { get: () => "0" } });
    out.retryAfterDate = clawRetryAfterFromResponse({ headers: { get: () => "Wed, 21 Oct 2015 07:28:00 GMT" } });
    out.ambiguous502 = isAmbiguousClawFailure({}, { status: 502 });
    out.ambiguousEngine = isAmbiguousClawFailure({ error: { code: "engine_execution_failed" } }, { status: 400 });
    out.ambiguousBad = isAmbiguousClawFailure({ error: { code: "bad_request" } }, { status: 400 });

    renderClawRetryBox();
    out.retryReadyText = clawRetryCopy.textContent;
    beginClawRetryCooldown(2);
    out.retryVisible = !clawRetryBox.hidden;
    out.retry2 = clawRetryCopy.textContent;
    out.execDisabledCooldown = clawExecuteButton.disabled;
    tick();
    out.retry1 = clawRetryCopy.textContent;
    tick();
    out.retrySecondsAfter = clawRetrySeconds;
    out.retryTimerAfter = clawRetryTimer;
    out.retryReadyAfter = clawRetryCopy.textContent;
    out.execDisabledAfterCooldown = clawExecuteButton.disabled;

    clawLastDispatchKey = "dispatch-key";
    showClawAmbiguousRecoveryHint();
    out.hintHidden = clawRetryHint.hidden;
    out.hintText = clawRetryHint.textContent;
    out.hintUncertain = clawUncertainKeys.has("dispatch-key");
    out.retryBoxHiddenAfterHint = clawRetryBox.hidden;

    beginClawWait();
    out.waitStarted = clawWaitStartedAt > 0;
    out.waitTimer = clawWaitTimer !== null;
    out.waitRevealed0 = renderClawWait();
    clawWaitStartedAt = Date.now() - 31000;
    out.waitRevealed1 = renderClawWait();
    out.waitHidden = clawWait.hidden;
    out.waitStage = clawWaitAnnouncedStage;
    out.waitKey = clawStatus.dataset.localeKey;
    applyClawWaitStageCopy();
    out.waitCopy = clawStatus.textContent;
    clearClawWait();
    out.waitTimerAfter = clawWaitTimer;
    out.waitStartedAfter = clawWaitStartedAt;
    out.waitHiddenAfter = clawWait.hidden;

    beginClawRetryCooldown(1);
    clearClawRecovery({ syncControls: true });
    out.retryBoxHidden = clawRetryBox.hidden;
    out.retryCopyEmpty = clawRetryCopy.textContent;
    out.retryButtonDisabled = clawRetryButton.disabled;
    out.retryHintHidden = clawRetryHint.hidden;
    out.retrySecondsFinal = clawRetrySeconds;
    out.retryTimerFinal = clawRetryTimer;
    return out;
  };
})();
</script>
</body></html>
"""


def test_claw_status_forwarders_execute_in_headless_chromium_with_zero_console_errors(tmp_path) -> None:
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
            return str(STATIC / clean)

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
    assert result["tier"] == "pro"
    assert result["placeholder"] == "Paste a business request you received by chat, SMS, or email."
    assert result["describedby"] == "clawStatus"
    assert result["placeholderIdle"] == "Ask anything"
    assert result["tierAfterFalse"] == "pro"
    assert result["statusHidden"] is False
    assert result["statusText"] == "running"
    assert result["statusState"] == "running"
    assert result["statusKey"] == "run-key"
    assert result["statusHiddenAfter"] is True
    assert result["ariaInvalidAfter"] is None
    assert result["areaState"] == "ready"
    assert result["busy"] is True
    assert result["genDisabled"] is True
    assert result["execDisabled"] is True
    assert result["busyAfter"] is False
    assert result["execDisabledAfter"] is False
    assert result["payload"] == {
        "content": "hello",
        "channel": "sms",
        "action": "quote",
        "sender_hint": "sender",
        "tier": "pro",
        "conversation_id": "conv_a4",
    }
    assert isinstance(result["wireKey"], str) and result["wireKey"]
    assert result["retryRemaining0"] == 0
    assert result["uncertain"] is True
    assert result["uncertainAfter"] is False
    assert result["retryAfter5"] == 5
    assert result["retryAfter0"] is None
    assert result["retryAfterDate"] is None
    assert result["ambiguous502"] is True
    assert result["ambiguousEngine"] is True
    assert result["ambiguousBad"] is False
    assert result["retryReadyText"] == "claw-retry-ready"
    assert result["retryVisible"] is True
    assert result["retry2"] == "claw-retry-waiting:2"
    assert result["execDisabledCooldown"] is True
    assert result["retry1"] == "claw-retry-waiting:1"
    assert result["retrySecondsAfter"] == 0
    assert result["retryTimerAfter"] is None
    assert result["retryReadyAfter"] == "claw-retry-ready"
    assert result["execDisabledAfterCooldown"] is False
    assert result["hintHidden"] is False
    assert result["hintText"] == "claw-error-check-runs"
    assert result["hintUncertain"] is True
    assert result["retryBoxHiddenAfterHint"] is True
    assert result["waitStarted"] is True
    assert result["waitTimer"] is True
    assert result["waitRevealed0"] is False
    assert result["waitRevealed1"] is True
    assert result["waitHidden"] is False
    assert result["waitStage"] == 2
    assert result["waitKey"] == "claw-wait-very-long"
    assert result["waitCopy"] == "claw-wait-very-long"
    assert result["waitTimerAfter"] is None
    assert result["waitStartedAfter"] == 0
    assert result["waitHiddenAfter"] is True
    assert result["retryBoxHidden"] is True
    assert result["retryCopyEmpty"] == ""
    assert result["retryButtonDisabled"] is True
    assert result["retryHintHidden"] is True
    assert result["retrySecondsFinal"] == 0
    assert result["retryTimerFinal"] is None
