"""#3382 Phase 2 — the Claw general SSE answer must land in the answer DOM.

Closes the gap Phase 1 left open: the server frame vocabulary was asserted as bytes
(`test_b54_claw_general_p01_routing`) and the client was asserted only by searching
`app.js` source text, so nothing followed the answer across the real boundary.

This test captures the bytes the real B62 route returns for a generic Claw submit,
then feeds those exact bytes into the REAL `chat-transport.js` reader and the REAL
`app.js` render path inside a Node vm over a DOM shim. The client is therefore
tested against what the server actually sends, not against a hand-written double.

Network-free, model-free, provider-free: the P01 adapter is an injected stub and no
Engine, B14 or provider endpoint is ever contacted.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from kagent.p01_adapter import (
    P01AdapterError,
    P01DispatchClass,
    P01_FAILURE_DETAIL_PROVIDER_RATE_LIMITED,
)

APP_DIR = Path(__file__).resolve().parents[1]
STATIC = APP_DIR / "static"
GENERAL_ROUTE_PATH = "/api/claw/general"
SIGNED_IN_USER_ID = "usr_" + "7" * 32

# Distinctive sentinel answer: a match on it cannot come from the harness itself.
ANSWER_WITH_MARKUP = "견적 확정 <img src=x onerror=alert(1)> — 3건 [클릭](javascript:0)"


def _settings(**overrides) -> Settings:
    values = {
        "runtime_mode": "mock",
        "auth_mode": "google",
        "public_base_url": "https://chat.example.test",
        "google_client_id": "claw-answer-dom-client.apps.googleusercontent.com",
        "google_client_secret": "claw-answer-dom-google-secret",
        "session_secret": "claw-answer-dom-session-secret-not-a-real-credential",
        "session_max_age_seconds": 3600,
    }
    values.update(overrides)
    return Settings.from_values(**values)


class _AuthStore:
    """Presence-only auth stub: no history or conversation authority is exercised."""

    async def get_user(self, user_id: str):
        return None

    async def get_conversation(self, user_id: str, conversation_id: str):
        return None


def _outcome(answer: str | None) -> MagicMock:
    projection = MagicMock()
    projection.status = MagicMock(value="completed")
    projection.run_id = "run_answer_dom"
    outcome = MagicMock()
    outcome.projection = projection
    outcome.answer = answer
    outcome.p01_run_id = "p01_answer_dom"
    outcome.p01_event_count = 1
    return outcome


def _capture_server(
    *,
    answer: str | None = ANSWER_WITH_MARKUP,
    raises: BaseException | None = None,
    model_id: str | None = None,
) -> tuple[int, str, str]:
    """Drive the real route once and return (status, content-type, raw body)."""
    adapter = MagicMock()
    adapter.subject_identity_lane = False
    adapter.execute = (
        AsyncMock(side_effect=raises) if raises is not None else AsyncMock(return_value=_outcome(answer))
    )
    app = create_app(settings=_settings(), history_store=_AuthStore(), claw_p01_adapter=adapter)
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_settings(), SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    payload: dict = {
        "messages": [{"role": "user", "content": "견적 상태를 알려줘."}],
        "tier": "plus",
    }
    if model_id is not None:
        payload["model_id"] = model_id
    with client:
        response = client.post(GENERAL_ROUTE_PATH, json=payload)
    return response.status_code, response.headers.get("content-type", ""), response.text


def _capture_server_stream(answer: str | None) -> tuple[int, str, str]:
    return _capture_server(answer=answer)


# ── client harness ───────────────────────────────────────────────────────────


_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

const APP = fs.readFileSync(process.argv[2], "utf8");
const TRANSPORT = fs.readFileSync(process.argv[3], "utf8");
const CASES = JSON.parse(fs.readFileSync(process.argv[4], "utf8"));

function makeEl(tag, id) {
  const el = {
    tagName: String(tag || "div").toUpperCase(), id: id || "", className: "", textContent: "",
    hidden: false, disabled: false, children: [], listeners: {}, dataset: {}, attributes: {},
    style: {}, scrollTop: 0, scrollHeight: 0, clientHeight: 0, options: [], selectedIndex: 0,
    files: [], parentNode: null, innerHTML: "",
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
  };
  el.setAttribute = (k, v) => { el.attributes[k] = String(v); if (k.startsWith("data-")) el.dataset[k.slice(5).replace(/-(\w)/g, (m, c) => c.toUpperCase())] = String(v); };
  el.getAttribute = (k) => (k in el.attributes ? el.attributes[k] : null);
  el.removeAttribute = (k) => { delete el.attributes[k]; delete el.dataset[k.slice(5).replace(/-(\w)/g, (m, c) => c.toUpperCase())]; };
  el.removeEventListener = (t, fn) => {
    const list = el.listeners[t] || [];
    const at = list.indexOf(fn);
    if (at >= 0) list.splice(at, 1);
  };
  el.appendChild = (c) => {
    // A cloned <template> content is a fragment: a real append moves its children,
    // so the shim must too, or the message nodes never reach the list.
    if (c && !c.tagName && Array.isArray(c.children)) {
      c.children.forEach((grand) => el.appendChild(grand));
      return c;
    }
    el.children.push(c); c.parentNode = el; return c;
  };
  el.append = (...cs) => cs.forEach((c) => el.appendChild(c));
  el.prepend = (...cs) => cs.forEach((c) => { el.children.unshift(c); c.parentNode = el; });
  el.replaceChildren = (...cs) => { el.children = []; cs.forEach((c) => el.appendChild(c)); };
  el.remove = () => {};
  el.addEventListener = (t, fn) => { (el.listeners[t] = el.listeners[t] || []).push(fn); };
  el.matchesSelector = (sel) => {
    if (sel.startsWith(".")) return el.className.split(/\s+/).includes(sel.slice(1));
    if (sel.startsWith("[")) { const name = sel.slice(1, -1).split("=")[0]; return name in el.attributes; }
    return el.tagName === sel.toUpperCase();
  };
  el._synthetic = {};
  // The real page contains nodes this shim does not model. Returning a stable
  // synthetic node (rather than null) keeps app.js boot honest: null here would
  // crash the bundle on wiring lines and hide the behaviour under test.
  el.querySelector = (sel) => {
    const search = (node) => {
      for (const c of node.children || []) {
        if (c && c.matchesSelector && c.matchesSelector(sel)) return c;
        const deeper = search(c);
        if (deeper) return deeper;
      }
      return null;
    };
    const found = search(el);
    if (found) return found;
    if (!el._synthetic[sel]) el._synthetic[sel] = makeEl("div");
    return el._synthetic[sel];
  };
  el.querySelectorAll = () => el.children;
  el.focus = () => {};
  el.blur = () => {};
  el.scrollIntoView = () => {};
  el.click = () => (el.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, target: el, key: "" }));
  el.requestSubmit = () => (el.listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
  el.matches = () => false;
  // Assigning .value models a real keystroke: the app listens to input/change.
  let rawValue = "";
  Object.defineProperty(el, "value", {
    get: () => rawValue,
    set: (v) => {
      rawValue = v;
      (el.listeners.input || []).forEach((fn) => fn({ type: "input", target: el }));
      (el.listeners.change || []).forEach((fn) => fn({ type: "change", target: el }));
    },
  });
  return el;
}

// Mirror of index.html:774-775 — the two message templates the app clones.
function makeAssistantArticle() {
  const content = makeEl("div");
  content.className = "assistant-content";
  const label = makeEl("span");
  label.className = "demo-label";
  label.setAttribute("data-runtime-label", "");
  label.setAttribute("data-locale-key", "answer-preparing");
  const meta = makeEl("div");
  meta.className = "assistant-meta";
  const product = makeEl("span");
  product.setAttribute("data-assistant-product", "");
  product.textContent = "Padiem Chat";
  meta.append(product, label);
  const body = makeEl("div");
  body.className = "assistant-body";
  body.append(meta, content);
  const article = makeEl("article");
  article.className = "message assistant-message";
  article.append(makeEl("div"), body);
  return article;
}

function makeUserArticle() {
  const bubble = makeEl("div");
  bubble.className = "message-bubble";
  const article = makeEl("article");
  article.className = "message user-message";
  article.append(bubble);
  return article;
}

function templateFragment(root) {
  return {
    children: [root],
    querySelector: (sel) => (root.matchesSelector(sel) ? root : root.querySelector(sel)),
  };
}

function buildSandbox(sseCase) {
  const byId = {};
  const requests = [];
  const lifecycleSets = [];
  const committed = [];
  const conversationIds = [];
  let currentConversationId = null;

  // #3989: real app/transport code, deterministic per-case 400ms observation.
  // Each sandbox owns a separate clock and its actual scheduled callbacks;
  // never accelerate past them or replace the response reader with a fake.
  const RealDate = Date;
  let virtualNow = RealDate.now();
  let nextTimerId = 0;
  const virtualTimers = new Map();
  class VirtualDate extends RealDate {
    constructor(...args) { if (args.length) super(...args); else super(virtualNow); }
    static now() { return virtualNow; }
  }
  function schedule(callback, delay, repeat, args) {
    const period = repeat ? Math.max(1, Number(delay) || 0) : 0;
    const id = ++nextTimerId;
    virtualTimers.set(id, {
      when: virtualNow + (repeat ? period : Math.max(0, Number(delay) || 0)),
      period, callback, args,
    });
    return id;
  }
  const virtualSetTimeout = (fn, delay=0, ...args) => schedule(fn, delay, false, args);
  const virtualSetInterval = (fn, delay=0, ...args) => schedule(fn, delay, true, args);
  const virtualClearTimer = (id) => virtualTimers.delete(id);
  const flush = async () => {
    // Let nested real promise/microtask chains (including fragmented real SSE
    // decoding) settle before advancing the simulated wall clock.
    await new Promise((resolve) => setImmediate(resolve));
  };
  async function advanceClock(ms) {
    await flush();
    const end = virtualNow + ms;
    let count = 0;
    while (true) {
      let selectedId = null;
      let selected = null;
      for (const [id, timer] of virtualTimers) {
        if (timer.when <= end && (!selected || timer.when < selected.when)) {
          selectedId = id; selected = timer;
        }
      }
      if (!selected) break;
      virtualNow = selected.when;
      if (selected.period > 0) selected.when += selected.period;
      else virtualTimers.delete(selectedId);
      selected.callback(...selected.args);
      await flush();
      if (++count > 10000) throw new Error("unbounded virtual timer loop");
    }
    virtualNow = end;
    await flush();
  }

  const doc = {
    documentElement: { lang: "ko", classList: { add() {}, remove() {}, contains() { return false; } } },
    body: makeEl("body"),
    activeElement: null,
    getElementById: (id) => {
      if (/Template$/.test(id)) {
        byId.__templates = byId.__templates || {};
        if (!byId.__templates[id]) {
          byId.__templates[id] = makeEl("template", id);
          byId.__templates[id].content = {
            cloneNode: () => templateFragment(
              id === "assistantMessageTemplate" ? makeAssistantArticle() : makeUserArticle(),
            ),
          };
        }
        return byId.__templates[id];
      }
      if (!byId[id]) byId[id] = makeEl("div", id);
      return byId[id];
    },
    querySelector: (sel) => {
      if (sel === ".app-shell") return byId.shell;
      if (!doc._synthetic[sel]) doc._synthetic[sel] = makeEl("div");
      return doc._synthetic[sel];
    },
    querySelectorAll: () => [],
    createElement: (tag) => makeEl(tag),
    addEventListener() {},
  };
  byId.shell = makeEl("div", "app-shell");
  byId.shell.dataset = { state: "claw" };
  doc._synthetic = {};

  const decoder = new TextDecoder("utf-8");

  function jsonResponses(status, obj, headers) {
    const map = headers || {};
    return {
      ok: status >= 200 && status < 300,
      status,
      headers: { get(name) {
        const key = Object.keys(map).find((n) => n.toLowerCase() === String(name).toLowerCase());
        return key === undefined ? null : map[key];
      } },
      json: async () => obj,
    };
  }

  // A Response-like object over the captured server bytes, chunked so the reader
  // really has to reassemble frames across chunk boundaries.
  function streamResponse(rawText) {
    const bytes = Buffer.from(rawText, "utf8");
    const chunks = [];
    for (let i = 0; i < bytes.length; i += 7) chunks.push(bytes.subarray(i, Math.min(i + 7, bytes.length)));
    chunks.push(null);
    let at = 0;
    return {
      ok: true,
      status: 200,
      headers: { get: (name) => (String(name).toLowerCase() === "content-type" ? "text/event-stream; charset=utf-8" : null) },
      body: {
        getReader: () => ({
          read: async () => (at < chunks.length
            ? Promise.resolve(chunks[at++] === null ? { done: true } : { done: false, value: chunks[at - 1] })
            : Promise.resolve({ done: true })),
          cancel: async () => {},
          releaseLock: () => {},
        }),
      },
      json: async () => { throw new Error("not json"); },
    };
  }

  const sandbox = {
    console,
    document: doc,
    location: { href: "http://localhost/" },
    addEventListener: () => {},
    fetch: async (url, opts) => {
      const method = ((opts && opts.method) || "GET").toUpperCase();
      requests.push({
        url: String(url),
        method,
        // The wire body is recorded, not just the URL: asserting the lane alone
        // would miss a payload that drops the user's selection.
        body: opts && opts.body ? String(opts.body) : null,
      });
      if (String(url).startsWith("/api/claw/general")) {
        if (sseCase.mode === "stream") return streamResponse(sseCase.raw);
        return jsonResponses(sseCase.status, sseCase.body);
      }
      if (String(url).startsWith("/api/auth/status")) {
        return jsonResponses(200, { ready: true, authenticated: true, user: { name: "owner" }, history_ready: false, project_files_ready: false });
      }
      return jsonResponses(200, {});
    },
    setTimeout: virtualSetTimeout, clearTimeout: virtualClearTimer,
    setInterval: virtualSetInterval, clearInterval: virtualClearTimer,
    TextDecoder, TextEncoder, AbortController, Promise, JSON, Math, Date: VirtualDate, Buffer,
    __padiemLocale: { text: (key, vars) => (key === "ai-response" ? "AI 답변" : key) },
    PadiemChatLifecycle: {
      states: { IDLE: "idle", STREAMING: "streaming", COMPLETED: "completed", FAILED: "failed", CANCELLED: "cancelled", TIMED_OUT: "timed_out" },
      set: (el, state) => lifecycleSets.push(state),
    },
    PadiemConfirmDialog: { confirm: async () => true },
    PadiemChatConversationState: {
      reset() {},
      setConversationId: (id) => conversationIds.push(id),
      getConversationId: () => currentConversationId,
      outboundWithUser: (text) => [{ role: "user", content: text }],
      commitAssistant: (messages, answer) => committed.push(answer),
      setSkill() {}, getSkill: () => "auto",
    },
    PadiemAttachmentCapabilities: {
      limits: { imageBytes: 4194304, textBytes: 98304, textChars: 40000 },
      images: [{ mediaTypes: ["image/jpeg", "image/png", "image/webp"] }],
      textDocuments: [{ mediaTypes: ["text/plain"], extensions: [".txt"] }],
      copy: () => ({ idleNote: "idle", unsupportedFormat: "unsupported", textTooLarge: "too large" }),
    },
    PadiemBinaryDocuments: null,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  // The REAL transport module first, then the REAL app: app.js must consume the
  // production PadiemChatTransport, not a stand-in.
  vm.runInContext(TRANSPORT, sandbox, { filename: "chat-transport.js" });
  vm.runInContext(APP, sandbox, { filename: "app.js" });
  return { sandbox, byId, doc, requests, lifecycleSets, committed, conversationIds, advanceClock };
}

function collectAnswerDom(byId) {
  const list = byId.messageList;
  const articles = (list.children || []).filter((c) => c && c.matchesSelector && c.matchesSelector(".assistant-message"));
  if (!articles.length) return null;
  const article = articles[articles.length - 1];
  const content = article.querySelector(".assistant-content");
  const label = article.querySelector("[data-runtime-label]");
  const paragraphs = (content.children || []).map((c) => ({ tag: c.tagName, text: c.textContent, html: c.innerHTML }));
  const texts = [];
  const walk = (node) => (node.children || []).forEach((c) => {
    if (c.textContent) texts.push(c.textContent);
    walk(c);
  });
  walk(content);
  return {
    label: label ? label.textContent : null,
    productLabel: article.querySelector("[data-assistant-product]")?.textContent || null,
    childTags: (content.children || []).map((c) => c.tagName),
    paragraphText: paragraphs.filter((p) => p.tag === "P").map((p) => p.text).join("\n"),
    // Every text node under the answer content, so an error surface can be
    // asserted to carry the bounded copy rather than an answer.
    texts,
    buttons: (() => {
      const found = [];
      const scan = (node) => (node.children || []).forEach((c) => {
        if (c.tagName === "BUTTON") found.push(c.textContent);
        scan(c);
      });
      scan(article);
      return found;
    })(),
    // innerHTML is read on every node that receives answer text, not just the
    // container: assigning the answer as HTML on the paragraph is the injection.
    containerInnerHTML: content.innerHTML,
    childInnerHTML: paragraphs.map((p) => p.html).filter(Boolean),
  };
}

(async () => {
  const results = [];
  for (const sseCase of CASES) {
    const { byId, requests, lifecycleSets, committed, conversationIds, advanceClock } = buildSandbox(sseCase);
    byId.messageInput.value = sseCase.prompt || "견적 상태를 알려줘.";
    // The real Claw model field (index.html:677): a user selection has to be set
    // where the user sets it, or the wire assertion would only prove nothing.
    if (typeof sseCase.modelId === "string") byId.clawModelIdInput.value = sseCase.modelId;
    byId.composerForm.requestSubmit();
    // Preserve the FULL 400ms opportunity to catch delayed/duplicate POSTs
    // and terminal SSE frames. Drive real app timers without sleeping 400ms.
    await advanceClock(400);
    results.push({
      name: sseCase.name,
      requests,
      answerDom: collectAnswerDom(byId),
      lifecycleSets,
      committed,
      conversationIds,
      errorSurface: byId.runtimeNote ? byId.runtimeNote.textContent : "",
      shellState: byId.shell.dataset.state,
      transcriptVisible: byId.messageList.hidden === false,
      sendButtonDisabled: byId.sendButton ? byId.sendButton.disabled : null,
    });
  }
  console.log(JSON.stringify({ ok: true, results }));
})().catch((e) => {
  console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) }));
  process.exit(0);
});
"""


def _run_client(cases: list[dict]) -> list[dict]:
    node = shutil.which("node")
    assert node, "node runtime is required for the client harness"
    harness = Path(tempfile.mkdtemp(prefix="claw-answer-dom-")) / "harness.cjs"
    harness.write_text(_HARNESS, encoding="utf-8", newline="\n")
    cases_path = harness.parent / "cases.json"
    cases_path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8", newline="\n")
    result = subprocess.run(
        [node, str(harness), str(STATIC / "app.js"), str(STATIC / "chat-transport.js"), str(cases_path)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"harness exited {result.returncode}: {result.stderr[:4000]}"
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload.get("ok") is True, payload
    return payload["results"]


def _case(name: str, answer: str | None, *, expect_stream: bool = True) -> tuple[dict, str | None]:
    status, content_type, raw = _capture_server_stream(answer)
    if expect_stream:
        assert status == 200 and content_type.startswith("text/event-stream"), (status, content_type, raw[:400])
        return {"name": name, "mode": "stream", "raw": raw}, raw
    return {"name": name, "mode": "json", "status": status, "body": json.loads(raw)}, raw


def test_server_stream_really_carries_the_answer_and_terminal_frames() -> None:
    """The bytes the client will consume are the route's own output, not a fixture."""
    case, raw = _case("markup-answer", ANSWER_WITH_MARKUP)
    assert 'event: delta' in raw
    assert ANSWER_WITH_MARKUP in raw
    assert 'event: done' in raw
    assert raw.count("event: delta") == 1, "the general lane projects one bounded terminal answer"


def test_claw_answer_lands_in_the_answer_dom_and_commits() -> None:
    case, _raw = _case("markup-answer", ANSWER_WITH_MARKUP)
    result = _run_client([case])[0]
    general_calls = [r for r in result["requests"] if r["url"] == GENERAL_ROUTE_PATH]
    stream_calls = [r for r in result["requests"] if r["url"] == "/api/chat/stream"]

    assert len(general_calls) == 1, result["requests"]
    # #3539 lane purity has to hold on the client too: no silent reroute.
    assert stream_calls == [], stream_calls
    # #3931: the user and real assistant answer remain in Claw's transcript.
    assert result["shellState"] == "claw", result
    assert result["transcriptVisible"] is True, result

    dom = result["answerDom"]
    assert dom is not None, "no assistant article was rendered for a 200 SSE answer"
    assert dom["paragraphText"] == ANSWER_WITH_MARKUP, dom
    assert dom["label"] == "AI 답변", dom
    assert dom["productLabel"] == "Padiem Claw", dom
    assert "completed" in result["lifecycleSets"], result["lifecycleSets"]
    assert result["committed"] == [ANSWER_WITH_MARKUP], result["committed"]


def test_markup_in_an_answer_is_rendered_as_text_not_markup() -> None:
    case, _raw = _case("markup-answer", ANSWER_WITH_MARKUP)
    result = _run_client([case])[0]
    dom = result["answerDom"]
    assert dom["childTags"] == ["P"], dom
    assert dom["paragraphText"] == ANSWER_WITH_MARKUP, dom
    assert dom["containerInnerHTML"] == "", dom
    assert dom["childInnerHTML"] == [], dom


def test_empty_answer_fails_closed_at_the_route_instead_of_rendering_blank_success() -> None:
    """Measured, not assumed: the route refuses an empty Engine answer with 502.

    The Phase 1 audit guessed that a "200 + done with no answer text" hole existed.
    Feeding the real route a completed outcome whose answer is empty shows it does
    not: no stream is produced at all, so the client cannot present a blank success.
    """
    case, raw = _case("empty-answer", "", expect_stream=False)
    assert json.loads(raw)["error"]["code"] == "engine_execution_failed", raw

    result = _run_client([case])[0]
    assert [r for r in result["requests"] if r["url"] == "/api/chat/stream"] == [], result["requests"]
    assert result["committed"] == [], result["committed"]
    assert "completed" not in result["lifecycleSets"], result["lifecycleSets"]
    dom = result["answerDom"]
    assert (dom["paragraphText"] if dom else "") == "", dom


# ── Phase 2 acceptance supplements (CENTRAL review of #3846) ────────────────
#
# Cases labelled "harness-authored" carry SSE frames no production route emits
# (EOF-before-done, error-after-delta, duplicate done, done-with-handle). They
# exist to exercise the real reader's terminal contract and are not claimed to be
# server output. Everything else is captured from the real route.

TEST_ONLY_MODEL_ID = "test-only/3382-ui-contract-model"
CONVERSATION_HANDLE = "conv_" + "3" * 32


def _frames(*pairs) -> str:
    return "".join("event: %s\ndata: %s\n\n" % (event, data) for event, data in pairs)


def _lane_only(result: dict) -> list[str]:
    """Dispatch URLs only: the claim is about lanes that send work, so GET boot
    traffic (auth status, history) is deliberately excluded rather than allowed in."""
    return sorted({r["url"] for r in result["requests"] if r["method"] == "POST"})


def _general_posts(result: dict) -> list[dict]:
    return [r for r in result["requests"] if r["url"] == GENERAL_ROUTE_PATH]


def test_a_syntactically_valid_user_selection_is_accepted_by_the_route() -> None:
    """UI-contract scope only: not registration, entitlement or provider readiness."""
    status, content_type, raw = _capture_server(answer=ANSWER_WITH_MARKUP, model_id=TEST_ONLY_MODEL_ID)
    assert status == 200 and content_type.startswith("text/event-stream"), raw[:400]
    assert ANSWER_WITH_MARKUP in raw


def test_user_selected_model_id_reaches_the_wire_request_exactly_once() -> None:
    _status, _ctype, raw = _capture_server(answer=ANSWER_WITH_MARKUP, model_id=TEST_ONLY_MODEL_ID)
    result = _run_client([{"name": "selection", "mode": "stream", "raw": raw, "modelId": TEST_ONLY_MODEL_ID}])[0]

    general = _general_posts(result)
    assert len(general) == 1, result["requests"]
    assert general[0]["method"] == "POST"
    sent = json.loads(general[0]["body"])
    assert sent["model_id"] == TEST_ONLY_MODEL_ID, sent
    assert general[0]["body"].count(TEST_ONLY_MODEL_ID) == 1, general[0]["body"]
    # The selection must not smuggle a second lane in behind the answer.
    assert _lane_only(result) == [GENERAL_ROUTE_PATH], _lane_only(result)
    assert result["answerDom"]["paragraphText"] == ANSWER_WITH_MARKUP, result["answerDom"]


def test_no_selection_sends_no_model_id_field() -> None:
    """The control that keeps the wire assertion above from being vacuous."""
    _status, _ctype, raw = _capture_server(answer=ANSWER_WITH_MARKUP)
    result = _run_client([{"name": "no-selection", "mode": "stream", "raw": raw}])[0]
    general = _general_posts(result)
    assert len(general) == 1, result["requests"]
    assert "model_id" not in json.loads(general[0]["body"]), general[0]["body"]
    assert result["answerDom"]["paragraphText"] == ANSWER_WITH_MARKUP


def test_502_engine_failure_shows_bounded_error_and_never_dispatches_again() -> None:
    failure = P01AdapterError(
        "engine_execution_failed",
        "Engine 실행에 실패했습니다.",
        dispatch_class=P01DispatchClass.DISPATCHED,
    )
    status, _ctype, raw = _capture_server(raises=failure)
    assert status == 502, raw[:400]
    body = json.loads(raw)
    assert body["error"]["code"] == "engine_execution_failed", body

    result = _run_client([{"name": "502", "mode": "json", "status": status, "body": body}])[0]
    assert len(_general_posts(result)) == 1, "an error must not cause a second dispatch"
    assert _lane_only(result) == [GENERAL_ROUTE_PATH], _lane_only(result)
    assert result["committed"] == [], result["committed"]
    assert "completed" not in result["lifecycleSets"], result["lifecycleSets"]
    dom = result["answerDom"]
    assert dom["paragraphText"] == "", dom
    assert dom["label"] == "connection-error", dom
    # #3935: only GET-based run-history navigation is allowed, never a replay.
    assert dom["buttons"] == ["claw-general-open-runs"], "Claw must expose only the read-only run-history action"


def test_502_provider_rate_limit_gets_the_bounded_classification_copy() -> None:
    failure = P01AdapterError(
        "engine_execution_failed",
        "Engine 실행에 실패했습니다.",
        dispatch_class=P01DispatchClass.DISPATCHED,
        failure_detail=P01_FAILURE_DETAIL_PROVIDER_RATE_LIMITED,
    )
    status, _ctype, raw = _capture_server(raises=failure)
    assert status == 502, raw[:400]
    body = json.loads(raw)
    assert body["error"]["detail"] == P01_FAILURE_DETAIL_PROVIDER_RATE_LIMITED, body

    result = _run_client([{"name": "rate-limited", "mode": "json", "status": status, "body": body}])[0]
    dom = result["answerDom"]
    assert "claw-general-provider-limit" in dom["texts"], dom
    assert "completed" not in result["lifecycleSets"], result["lifecycleSets"]
    assert result["committed"] == [], result["committed"]
    assert len(_general_posts(result)) == 1


def test_stream_that_ends_without_a_done_frame_never_completes() -> None:
    """harness-authored: a partial stream must not be presented as a finished answer."""
    raw = _frames(("delta", json.dumps({"delta": "부분 응답"})))
    result = _run_client([{"name": "eof", "mode": "stream", "raw": raw}])[0]
    assert result["committed"] == [], result["committed"]
    assert "completed" not in result["lifecycleSets"], result["lifecycleSets"]
    assert result["answerDom"]["label"] == "connection-error", result["answerDom"]
    assert len(_general_posts(result)) == 1


def test_error_frame_after_a_real_delta_is_terminal_and_uncommitted() -> None:
    """harness-authored error frame following a delivered delta."""
    raw = _frames(
        ("delta", json.dumps({"delta": "일부 텍스트 "})),
        ("error", json.dumps({"error": {"code": "engine_execution_failed", "message": "실패"}})),
    )
    result = _run_client([{"name": "error-frame", "mode": "stream", "raw": raw}])[0]
    assert result["committed"] == [], result["committed"]
    assert "completed" not in result["lifecycleSets"], result["lifecycleSets"]
    assert len(_general_posts(result)) == 1


def test_duplicate_done_frame_commits_the_answer_only_once() -> None:
    """harness-authored second done frame; the reader must not double-commit."""
    raw = _frames(
        ("delta", json.dumps({"delta": ANSWER_WITH_MARKUP})),
        ("done", json.dumps({"done": True})),
        ("done", json.dumps({"done": True})),
    )
    result = _run_client([{"name": "dup-done", "mode": "stream", "raw": raw}])[0]
    assert result["committed"] == [ANSWER_WITH_MARKUP], result["committed"]


def test_real_done_frame_carries_no_conversation_handle_and_the_client_invents_none() -> None:
    """Measured limitation of the general lane, recorded rather than papered over."""
    _status, _ctype, raw = _capture_server(answer=ANSWER_WITH_MARKUP)
    assert any(line.startswith("data: ") and '"done"' in line for line in raw.splitlines()), raw[:400]
    assert "conversation_id" not in raw, "the route does not return a handle today"

    result = _run_client([{"name": "no-handle", "mode": "stream", "raw": raw}])[0]
    assert result["conversationIds"] == [], result["conversationIds"]
    assert result["committed"] == [ANSWER_WITH_MARKUP], result["committed"]


def test_done_frame_conversation_handle_updates_canonical_state_exactly_once() -> None:
    """harness-authored done frame carrying a handle: the production reader and
    app.js must adopt it once and still commit the answer exactly once."""
    raw = _frames(
        ("delta", json.dumps({"delta": ANSWER_WITH_MARKUP})),
        ("done", json.dumps({"done": True, "conversation_id": CONVERSATION_HANDLE})),
    )
    result = _run_client([{"name": "handle", "mode": "stream", "raw": raw}])[0]
    assert result["conversationIds"] == [CONVERSATION_HANDLE], result["conversationIds"]
    assert result["committed"] == [ANSWER_WITH_MARKUP], result["committed"]
    assert "completed" in result["lifecycleSets"], result["lifecycleSets"]
