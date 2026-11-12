"""#7216 R5 A3 (pc-run) — 실제 Chromium에서 app.js 전달 함수 7개 호출 계약.

app.js에서 추출한 pcRunModule() 연결부와 7개 한 줄 전달 함수를 실제 헤드리스
Chromium 페이지에 주입하고, chat-pc-run-module.js와 함께 각 전달 함수를 직접
호출해 화면 갱신·라이브 deps getter 읽기·콘솔 오류 0건을 검증한다.
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
STRICT = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")

NAMES = (
    "showPcRuntimeStatus",
    "waitForAcceptedPcRun",
    "pcWaitElapsed",
    "findUnfinishedPcRun",
    "resumeUnfinishedPcRun",
    "renderStoredPcAnswer",
    "recoverStoredPcResult",
)


def _extract_app_wiring() -> str:
    factory_start = APP.index("let pcRunModuleInstance = null;")
    factory_end = APP.index("\n  const shell = document.querySelector", factory_start)
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


def test_pc_run_forwarders_execute_in_headless_chromium_with_zero_console_errors(tmp_path) -> None:
    wiring = _extract_app_wiring()
    harness_html = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>R5 pc-run browser contract</title></head>
<body>
<div id="thread"></div>
<script src="/chat-pc-run-module.js"></script>
<script>
{STRICT}
(() => {{
  "use strict";
  const MESSAGE_LIFECYCLE = {{ STREAMING: "streaming", COMPLETED: "completed", FAILED: "failed" }};
  let authState = {{ authenticated: false, user: null }};
  let conversationProduct = "chat";
  const resolvedPcRuns = new Set();
  const notes = [];
  const reopened = [];
  const committed = [];
  let recentLoads = 0;

  window.PadiemClawRunEventProjection = {{
    label: (kind, lang) => `${{lang}}:${{kind}}`,
  }};
  window.PadiemChatPcScopeNotice = {{ render() {{}} }};
  window.PadiemChatPcRecovery = {{
    validRunId: (id) => typeof id === "string" && id.startsWith("chat_pcq_"),
  }};
  window.PadiemChatLifecycle = {{
    set(a, s) {{ a.dataset.lifecycle = s; }},
    setTaskHint(a, h) {{ a.dataset.hint = h || ""; }},
    releasePreparingRuntimeLabel() {{}},
    applyRuntimeLabel(a, text) {{ a.dataset.runtimeLabel = text; }},
    elapsedClockText: () => "01:15",
  }};
  const PadiemChatLifecycle = window.PadiemChatLifecycle;

  const conversationState = {{
    getConversationId: () => "conv_b1",
    setProduct() {{}},
    setConversationId() {{}},
    commitAssistant(_m, ans) {{ committed.push(ans); }},
  }};
  const pcResultRecovery = {{
    recoverOnce: async () => ({{ kind: "completed", answer: "복구 응답", conversationId: "conv_b1" }}),
    waitForResult: async (opts) => {{
      if (opts.onPending) opts.onPending();
      return {{ kind: "completed", conversationId: opts.conversationId }};
    }},
  }};
  function idleNote() {{ return "idle"; }}
  function loadRecentConversations() {{ recentLoads += 1; }}
  async function openSavedConversation(id) {{ reopened.push(id); }}
  function renderStreamError() {{}}
  function setNote(t, s) {{ notes.push({{ t, s }}); }}
  function uiT(k) {{ return k; }}

  const origFetch = window.fetch.bind(window);
  window.fetch = async (url, init) => {{
    const s = String(url);
    if (s.endsWith("/api/claw/runs")) {{
      return new Response(JSON.stringify({{
        ok: true,
        runs: [{{
          run_id: "chat_pcq_" + "9".repeat(32),
          status: "running",
          created_at: new Date(Date.now() - 75000).toISOString(),
          session: {{ conversation_id: "conv_b1" }},
        }}],
      }}), {{ status: 200, headers: {{ "Content-Type": "application/json" }} }});
    }}
    if (s.includes("/pending-result")) {{
      return new Response(JSON.stringify({{
        result: {{
          run_id: "run_live_1",
          conversation_id: "conv_b1",
          status: "completed",
          answer: "라이브 PC 결과",
          answer_source: "pc_command_result",
        }},
      }}), {{ status: 200, headers: {{ "Content-Type": "application/json" }} }});
    }}
    return origFetch(url, init);
  }};
  window.setTimeout = (fn) => {{ fn(); return 1; }};

  {wiring}

  window.__exercise = async () => {{
    // Mutate closure state before first call to prove live getter binding.
    authState = {{ authenticated: true, user: {{ id: "u_browser" }} }};
    conversationProduct = "claw";

    const makeArt = () => {{
      const art = document.createElement("article");
      const content = document.createElement("div");
      content.className = "assistant-content";
      art.appendChild(content);
      document.getElementById("thread").appendChild(art);
      return art;
    }};

    const a1 = makeArt();
    const sOk = showPcRuntimeStatus(a1, "tool_started");
    const elapsed = pcWaitElapsed(new Date(Date.now() - 75000).toISOString());
    const found = await findUnfinishedPcRun("conv_b1");
    await resumeUnfinishedPcRun("conv_b1");
    await waitForAcceptedPcRun(
      a1,
      {{ run_id: "run_live_1", conversation_id: "conv_b1" }},
      [],
      new AbortController().signal,
      "claw"
    );
    const a2 = makeArt();
    const rRendered = renderStoredPcAnswer(
      a2,
      {{ answer: "직접 렌더 응답", conversationId: "conv_b1" }},
      [],
      {{ product: "claw" }}
    );
    const a3 = makeArt();
    const rRecovered = await recoverStoredPcResult(
      a3,
      {{ pcRunId: "run_rec_1", conversationId: "conv_b1", product: "claw" }},
      [],
      null,
      new AbortController().signal
    );
    return {{
      sOk,
      elapsed,
      foundId: found?.run_id || null,
      reopened,
      a1Text: a1.textContent,
      a2Text: a2.textContent,
      a3Text: a3.textContent,
      rRendered,
      rRecovered,
      recentLoads,
      notesCount: notes.length,
    }};
  }};
}})();
</script>
</body></html>
"""
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
    assert result["sOk"] is True
    assert result["elapsed"] == "01:15"
    assert result["foundId"] == "chat_pcq_" + "9" * 32
    assert result["reopened"] == ["conv_b1"]
    assert result["a1Text"] == "라이브 PC 결과"
    assert result["a2Text"] == "직접 렌더 응답"
    assert result["a3Text"] == "복구 응답"
    assert result["rRendered"] is True
    assert result["rRecovered"] is True
    assert result["recentLoads"] >= 2
