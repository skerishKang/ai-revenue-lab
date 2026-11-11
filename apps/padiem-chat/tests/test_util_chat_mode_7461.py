"""#7461 (1차 PR) — 유틸 공통 대화 방식 틀(util-chat-mode) + 축사·인사말 연결 시험.

검증 범위:
1. 파일 경계 및 스코프: 코드는 static/util-*.js·util-*.css에만 존재(app.js 무변경),
   1차 PR에서는 공통 틀 + speech(축사·인사말) 1개만 대화 전환을 노출하고 sns·meeting은 폼 유지.
2. 빠진 필수 칸 질문 순서 및 생성 게이트: util-manifest.js의 fields·missingFields·nextQuestion을
   그대로 사용해 빠진 필수 칸을 순서대로 한 번에 하나씩 묻고(이미 채워진 칸은 건너뜀),
   필수 칸이 모두 채워졌을 때만 생성 함수를 호출함(빈 입력·부분 입력 시 서버 호출 0건).
3. 양방향 값 유지 및 동일 서버 경로: 폼에서 입력하던 값(선택 항목 포함)이 대화 방식으로 넘어가도
   유지되고, 대화로 모은 값이 폼으로 넘길 때 입력 칸에 그대로 채워지며, 유틸 화면(#util/speech)을
   떠나지 않고 같은 /api/chat/stream 경로로 생성·다듬기를 수행함.
4. 한국어 IME 조합 중 Enter 조기 전송 방지 및 옛 #util 주소 호환(#util, #util/, #util-speech,
   #util?tool=speech, #util/speech?mode=chat).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from css_rules import declaration, find_rules_with_selector, parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
CHAT_MODE_JS = (STATIC / "util-chat-mode.js").read_text(encoding="utf-8")
CHAT_MODE_CSS = (STATIC / "util-chat-mode.css").read_text(encoding="utf-8")
TOOLS_JS = (STATIC / "util-tools.js").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")


def test_static_boundary_script_order_and_tokens() -> None:
    assert '<link rel="stylesheet" href="./util-chat-mode.css" />' in INDEX
    assert '<script src="./util-chat-mode.js" defer></script>' in INDEX
    assert (
        INDEX.index("./util-manifest.js")
        < INDEX.index("./util-chat-mode.js")
        < INDEX.index("./util-tools.js")
        < INDEX.index("./util-app.js")
    )
    for token in ("PadiemUtilChatMode", "util-chat-intake", "util-mode-switch"):
        assert token not in APP_JS
    for sink in (".innerHTML", ".outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in CHAT_MODE_JS
    for storage in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
        assert storage not in CHAT_MODE_JS

    rules = parse_rules(CHAT_MODE_CSS)
    tabs = find_rules_with_selector(rules, ".util-mode-tab")
    active = find_rules_with_selector(rules, '.util-mode-tab[aria-pressed="true"]')
    assert tabs and active
    assert declaration(active[0], "background") == "var(--primary-bg)"
    assert declaration(active[0], "color") == "#fff"
    # Active state changes color only, never border-width/padding/font-weight.
    assert declaration(active[0], "padding") is None
    assert declaration(active[0], "font-weight") is None


NODE_HARNESS = r'''
const fs = require("node:fs");
const vm = require("node:vm");

const [manifestFile, markdownFile, contractFile, chatModeFile, toolsFile, appFile] = process.argv.slice(2);

const registry = [];
function El(tag) {
  return {
    tagName: String(tag || "div").toUpperCase(),
    id: "",
    className: "",
    type: "",
    name: "",
    value: "",
    textContent: "",
    placeholder: "",
    rows: 0,
    required: false,
    disabled: false,
    hidden: false,
    open: false,
    focused: false,
    noValidate: false,
    scrollTop: 0,
    scrollHeight: 100,
    children: [],
    attrs: {},
    dataset: {},
    listeners: {},
    parentElement: null,
    get classList() {
      const self = this;
      return {
        add: (...c) => { self.className = [...new Set([...String(self.className).split(/\s+/).filter(Boolean), ...c])].join(" "); },
        remove: (...c) => { const d = new Set(c); self.className = String(self.className).split(/\s+/).filter((x) => x && !d.has(x)).join(" "); },
        toggle: (c, on) => { if (on) self.classList.add(c); else self.classList.remove(c); },
        contains: (c) => String(self.className).split(/\s+/).includes(c),
      };
    },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    setAttribute(k, v) {
      this.attrs[k] = String(v);
      if (k === "id") this.id = String(v);
      if (k.startsWith("data-")) {
        const camel = k.slice(5).replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
        this.dataset[camel] = String(v);
      }
    },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    appendChild(child) { this.children.push(child); child.parentElement = this; return child; },
    replaceChildren(...nodes) { this.children = []; nodes.forEach((n) => this.appendChild(n)); },
    focus() { this.focused = true; },
    click() { (this.listeners.click || []).slice().forEach((fn) => fn({ target: this, preventDefault() {} })); },
    dispatchKeydown(ev) { (this.listeners.keydown || []).slice().forEach((fn) => fn(ev)); },
    closest(sel) {
      let cur = this;
      while (cur) { if (matches(cur, sel)) return cur; cur = cur.parentElement; }
      return null;
    },
    querySelector(sel) { return find(this, sel); },
    querySelectorAll(sel) { return findAll(this, sel); },
  };
}

function matches(el, sel) {
  if (!sel || !el || el.tagName === "#TEXT") return false;
  if (sel.startsWith(".")) return String(el.className || "").split(/\s+/).includes(sel.slice(1));
  if (sel.startsWith("#")) return el.id === sel.slice(1);
  const attr = /^\[([a-zA-Z0-9_-]+)(?:="([^"]*)")?\]$/.exec(sel);
  if (attr) {
    if (attr[1] === "name") return Boolean(el.name) && (attr[2] === undefined || el.name === attr[2]);
    const val = el.getAttribute(attr[1]);
    return val !== null && (attr[2] === undefined || val === attr[2]);
  }
  return el.tagName === sel.toUpperCase();
}
function walk(el, fn) { if (!el) return; fn(el); (el.children || []).forEach((c) => walk(c, fn)); }
function find(root, sel) { let out = null; walk(root, (e) => { if (!out && e !== root && matches(e, sel)) out = e; }); return out; }
function findAll(root, sel) { const out = []; walk(root, (e) => { if (e !== root && matches(e, sel)) out.push(e); }); return out; }
function fullText(el) { let out = ""; walk(el, (e) => { if (e.tagName === "#TEXT" || (!e.children.length && e.textContent)) out += e.textContent + " "; }); return out.trim(); }
function tick() { return new Promise((resolve) => setImmediate(resolve)); }

const shell = El("div"); shell.className = "app-shell"; shell.dataset.state = "home";
const utilView = El("section"); utilView.id = "utilView"; utilView.hidden = true; registry.push(utilView);
const utilHeader = El("header"); utilHeader.className = "util-header"; utilView.appendChild(utilHeader);
const utilTitle = El("h2"); utilTitle.id = "utilTitle"; utilHeader.appendChild(utilTitle); registry.push(utilTitle);
const utilKicker = El("p"); utilKicker.id = "utilKicker"; utilHeader.appendChild(utilKicker); registry.push(utilKicker);
const utilTagline = El("p"); utilTagline.id = "utilTagline"; utilHeader.appendChild(utilTagline); registry.push(utilTagline);
const root = El("div"); root.id = "utilAppRoot"; utilView.appendChild(root); registry.push(root);

const requests = [];
const listeners = {};
const loc = {
  _hash: "",
  pathname: "/index.html",
  search: "",
  get hash() { return this._hash; },
  set hash(v) {
    this._hash = String(v || "");
    (listeners.hashchange || []).forEach((fn) => fn());
  },
};
const history = {
  state: null,
  replaceState(_s, _t, url) {
    const idx = String(url).indexOf("#");
    loc._hash = idx >= 0 ? String(url).slice(idx) : "";
  },
};

const windowObj = {
  location: loc,
  history: history,
  fetch: (url, init) => {
    const body = JSON.parse((init && init.body) || "{}");
    requests.push({ url, credentials: init && init.credentials, body });
    return Promise.resolve({
      ok: true,
      status: 200,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ answer: "## 축사 초안\n\n광복절을 진심으로 경축합니다." }),
      body: null,
    });
  },
  addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
  dispatchEvent(ev) { (listeners[ev.type] || []).forEach((fn) => fn(ev)); },
  PadiemAuthSession: { get: () => ({ authenticated: true }) },
  PadiemTierSelection: { get: () => "plus" },
  PadiemAppSwitch: { openChat() { shell.dataset.state = "home"; }, openClaw() { shell.dataset.state = "claw"; } },
};
const document = {
  readyState: "complete",
  documentElement: { lang: "ko" },
  createElement(tag) { const n = El(tag); registry.push(n); return n; },
  createTextNode(t) { const n = El("#text"); n.textContent = String(t); return n; },
  getElementById(id) { const hits = registry.filter((e) => e.id === id); return hits.length ? hits[hits.length - 1] : null; },
  querySelector(sel) { return sel === ".app-shell" ? shell : null; },
  addEventListener() {},
};

const ctx = {
  document,
  window: windowObj,
  location: loc,
  history,
  MutationObserver: class { observe() {} },
  CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
  console,
  setTimeout: () => 0,
  clearTimeout: () => {},
};
ctx.globalThis = ctx;
vm.createContext(ctx);
[manifestFile, markdownFile, contractFile, chatModeFile, toolsFile, appFile].forEach((file) => {
  vm.runInContext(fs.readFileSync(file, "utf8"), ctx, { filename: file });
});

(async () => {
  const manifest = windowObj.PadiemUtilManifest;
  const chatMode = windowObj.PadiemUtilChatMode;

  // A. Shared engine question-order & gate proof on a 3-required-field schema (with 2nd pre-filled)
  const customFields = [
    { key: "step1", type: "text", required: true, label: { ko: "1단계" }, placeholder: { ko: "" }, question: { ko: "첫 번째 질문입니다." }, options: [] },
    { key: "step2", type: "text", required: true, label: { ko: "2단계" }, placeholder: { ko: "" }, question: { ko: "두 번째 질문입니다." }, options: [] },
    { key: "optMid", type: "text", required: false, label: { ko: "선택" }, placeholder: { ko: "" }, question: { ko: "선택 질문입니다." }, options: [] },
    { key: "step3", type: "text", required: true, label: { ko: "3단계" }, placeholder: { ko: "" }, question: { ko: "세 번째 질문입니다." }, options: [] },
  ];
  const customTool = { id: "custom3", fields: customFields };
  const customManifest = {
    getTool: (id) => (id === "custom3" ? customTool : null),
    missingFields: (_id, vals) => customFields.filter((f) => f.required && !String((vals && vals[f.key]) || "").trim()),
    nextQuestion: (_id, vals) => {
      const m = customFields.filter((f) => f.required && !String((vals && vals[f.key]) || "").trim());
      return m.length ? { fieldKey: m[0].key, field: m[0], question: m[0].question.ko } : null;
    },
  };
  let formBag = { step1: "", step2: "미리채움2", optMid: "", step3: "" };
  const generatedPayloads = [];
  const multi = chatMode.create({
    toolId: "custom3",
    manifest: customManifest,
    getValues: () => Object.assign({}, formBag),
    setValues: (next) => { formBag = Object.assign({}, formBag, next); },
    onGenerate: async (vals) => { generatedPayloads.push(vals); return true; },
  });
  multi.enter({});
  const askedSequence = () => findAll(multi.root, "[data-question-field]").map((n) => n.getAttribute("data-question-field"));
  const seqInitial = askedSequence(); // ["step1"]
  // Empty submit must not advance or generate
  await multi.submitAnswer("   ");
  const genAfterEmpty = generatedPayloads.length;
  // IME composing Enter must NOT submit
  const multiInput = find(multi.root, ".util-chat-input");
  multiInput.value = "조합중텍스트";
  multiInput.dispatchKeydown({ key: "Enter", shiftKey: false, isComposing: true, preventDefault() {} });
  await tick();
  const seqDuringIme = askedSequence();
  multiInput.value = "";
  // Answer step1 -> step2 was already pre-filled in form, so engine skips step2 and asks step3! Still 0 generations!
  await multi.submitAnswer("첫번째답");
  const seqAfterFirst = askedSequence(); // ["step1", "step3"]
  const genBeforeLast = generatedPayloads.length; // 0
  // Answer step3 -> all required fields filled -> generates!
  await multi.submitAnswer("세번째답");
  const genAfterAll = generatedPayloads.length; // 1

  // Also check real manifest multi-required-field tool ("sns": event -> content)
  let snsBag = { event: "", content: "" };
  const snsGens = [];
  const snsChat = chatMode.create({
    toolId: "sns",
    manifest: manifest,
    getValues: () => Object.assign({}, snsBag),
    setValues: (n) => { snsBag = Object.assign({}, snsBag, n); },
    onGenerate: async (v) => { snsGens.push(v); return true; },
  });
  snsChat.enter({});
  const snsFirstField = findAll(snsChat.root, "[data-question-field]").map((n) => n.getAttribute("data-question-field"));
  await snsChat.submitAnswer("주민 정원 설명회");
  const snsSecondField = findAll(snsChat.root, "[data-question-field]").map((n) => n.getAttribute("data-question-field"));
  const snsGenMid = snsGens.length;
  await snsChat.submitAnswer("신청 방법과 지원금 안내");
  const snsGenEnd = snsGens.length;

  // B. PR 2 scope check: speech, sns & meeting have mode switch; excel stays form-only
  loc.hash = "#util/sns";
  const snsHasModeSwitch = Boolean(find(root, ".util-mode-switch"));
  loc.hash = "#util/meeting";
  const meetingHasModeSwitch = Boolean(find(root, ".util-mode-switch"));
  loc.hash = "#util/excel";
  const excelHasModeSwitch = Boolean(find(root, ".util-mode-switch"));

  // C. #util/speech Form <-> Conversation bidirectional value preservation & same /api/chat/stream generation
  loc.hash = "#util/speech";
  const speechModeSwitch = find(root, ".util-mode-switch");
  const formTab = find(speechModeSwitch, '[data-util-mode="form"]');
  const chatTab = find(speechModeSwitch, '[data-util-mode="chat"]');
  const formEl = find(root, "#utilToolForm-speech");
  const chatEl = find(root, '[data-util-chat-intake="speech"]');
  const defaultState = {
    formVisible: formEl.hidden === false,
    chatHidden: chatEl.hidden === true,
    formPressed: formTab.getAttribute("aria-pressed"),
  };

  // Fill optional fields in Form first, leave required "event" blank, then switch to Conversation mode
  find(formEl, "#utilToolField-audience").value = "지역 주민 200명";
  find(formEl, "#utilToolField-author").value = "구의원 김의민";
  chatTab.click();

  const afterToChat = {
    shellState: shell.dataset.state,
    hash: loc.hash,
    formHidden: formEl.hidden === true,
    chatVisible: chatEl.hidden === false,
    summaryText: fullText(find(chatEl, ".util-chat-summary")),
    askedFields: findAll(chatEl, "[data-question-field]").map((n) => n.getAttribute("data-question-field")),
    requestsBeforeAnswer: requests.length,
  };

  // Answer required "event" in Conversation mode -> triggers /api/chat/stream with BOTH chat answer & form values!
  const chatTextarea = find(chatEl, "#utilChatInput-speech");
  chatTextarea.value = "제81주년 광복절 경축 기념식";
  chatTextarea.dispatchKeydown({ key: "Enter", shiftKey: false, isComposing: false, keyCode: 13, preventDefault() {} });
  await tick();
  await tick();

  const afterChatGenerate = {
    requestCount: requests.length,
    requestUrl: requests[0] && requests[0].url,
    requestUtil: requests[0] && requests[0].body.util,
    requestTier: requests[0] && requests[0].body.tier,
    promptText: requests[0] && requests[0].body.messages[0].content,
    outputText: fullText(find(root, "#utilOutput-speech")),
    stillInUtilScreen: shell.dataset.state === "util" && loc.hash === "#util/speech",
  };

  // Switch back to Form via "폼으로 열기" -> collected "event" is filled in #utilToolField-event and optional fields stay!
  find(chatEl, "[data-util-open-form]").click();
  const afterBackToForm = {
    formVisible: formEl.hidden === false,
    chatHidden: chatEl.hidden === true,
    eventValue: find(formEl, "#utilToolField-event").value,
    audienceValue: find(formEl, "#utilToolField-audience").value,
    authorValue: find(formEl, "#utilToolField-author").value,
    draftKept: fullText(find(root, "#utilOutput-speech")).indexOf("광복절") >= 0,
  };

  // Refine via "대화로 다듬기" button on the Result pane -> sends 2nd request on same /api/chat/stream
  find(root, "[data-util-refine-chat]").click();
  chatTextarea.value = "더 따뜻하고 간결하게 다듬어 주세요";
  find(chatEl, ".util-chat-composer").listeners.submit[0]({ preventDefault() {} });
  await tick();
  await tick();
  const afterRefine = {
    requestCount: requests.length,
    secondPromptHasRefinement: requests[1] && requests[1].body.messages[0].content.indexOf("더 따뜻하고 간결하게 다듬어 주세요") >= 0,
  };

  // D. Legacy #util URLs & ?mode=chat deep link
  loc.hash = "#util-speech";
  const legacyHyphen = { hash: loc.hash, tool: find(root, ".util-tool-screen").getAttribute("data-util-tool") };
  loc.hash = "#util?tool=speech";
  const legacyQuery = { hash: loc.hash, tool: find(root, ".util-tool-screen").getAttribute("data-util-tool") };
  loc.hash = "#util/speech?mode=chat";
  const deepChatMode = {
    activeMode: find(root, ".util-tool-workbench").getAttribute("data-active-mode"),
    chatVisible: find(root, '[data-util-chat-intake="speech"]').hidden === false,
  };

  console.log(JSON.stringify({
    seqInitial,
    genAfterEmpty,
    seqDuringIme,
    seqAfterFirst,
    genBeforeLast,
    genAfterAll,
    multiFinalBag: formBag,
    snsOrder: [snsFirstField, snsSecondField, snsGenMid, snsGenEnd],
    snsHasModeSwitch,
    meetingHasModeSwitch,
    excelHasModeSwitch,
    defaultState,
    afterToChat,
    afterChatGenerate,
    afterBackToForm,
    afterRefine,
    legacyHyphen,
    legacyQuery,
    deepChatMode,
  }));
})();
'''


def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required"
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "harness_7461.cjs"
        script.write_text(NODE_HARNESS, encoding="utf-8")
        completed = subprocess.run(
            [
                node,
                str(script),
                str(STATIC / "util-manifest.js"),
                str(STATIC / "util-tools-markdown.js"),
                str(STATIC / "util-tools-contract.js"),
                str(STATIC / "util-chat-mode.js"),
                str(STATIC / "util-tools.js"),
                str(STATIC / "util-app.js"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout.strip())


def test_question_order_ime_guard_and_generate_only_when_required_complete() -> None:
    out = _run_harness()
    # step2 was pre-filled, so order is strictly step1 -> step3; optional optMid is not blocking
    assert out["seqInitial"] == ["step1"]
    assert out["genAfterEmpty"] == 0
    assert out["seqDuringIme"] == ["step1"]
    assert out["seqAfterFirst"] == ["step1", "step3"]
    assert out["genBeforeLast"] == 0
    assert out["genAfterAll"] == 1
    assert out["multiFinalBag"] == {
        "step1": "첫번째답",
        "step2": "미리채움2",
        "optMid": "",
        "step3": "세번째답",
    }
    # Real manifest 2-required-field tool (sns): event -> content, 0 gen after 1st, 1 gen after 2nd
    assert out["snsOrder"] == [["event"], ["event", "content"], 0, 1]


def test_speech_form_chat_bidirectional_sync_in_app_stream_and_legacy_urls() -> None:
    out = _run_harness()
    # PR2 scope: speech, sns & meeting expose mode toggle; excel stays pending
    assert out["snsHasModeSwitch"] is True
    assert out["meetingHasModeSwitch"] is True
    assert out["excelHasModeSwitch"] is False
    assert out["defaultState"] == {"formVisible": True, "chatHidden": True, "formPressed": "true"}

    # Form -> Chat keeps typed optional fields and asks missing required field "event" inside #util/speech
    to_chat = out["afterToChat"]
    assert to_chat["shellState"] == "util"
    assert to_chat["hash"] == "#util/speech"
    assert to_chat["formHidden"] is True
    assert to_chat["chatVisible"] is True
    assert "지역 주민 200명" in to_chat["summaryText"]
    assert "구의원 김의민" in to_chat["summaryText"]
    assert to_chat["askedFields"] == ["event"]
    assert to_chat["requestsBeforeAnswer"] == 0

    # Answering required "event" triggers same /api/chat/stream with all collected values
    gen = out["afterChatGenerate"]
    assert gen["requestCount"] == 1
    assert gen["requestUrl"] == "/api/chat/stream"
    assert gen["requestUtil"] == "speech"
    assert gen["requestTier"] == "plus"
    assert "제81주년 광복절 경축 기념식" in gen["promptText"]
    assert "지역 주민 200명" in gen["promptText"]
    assert "구의원 김의민" in gen["promptText"]
    assert "광복절을 진심으로 경축합니다" in gen["outputText"]
    assert gen["stillInUtilScreen"] is True

    # Chat -> Form ("폼으로 열기") populates #utilToolField-event and keeps form values + draft
    back = out["afterBackToForm"]
    assert back == {
        "formVisible": True,
        "chatHidden": True,
        "eventValue": "제81주년 광복절 경축 기념식",
        "audienceValue": "지역 주민 200명",
        "authorValue": "구의원 김의민",
        "draftKept": True,
    }

    # "대화로 다듬기" sends refinement on the same /api/chat/stream route
    assert out["afterRefine"] == {"requestCount": 2, "secondPromptHasRefinement": True}

    # Legacy #util URLs & ?mode=chat deep link
    assert out["legacyHyphen"] == {"hash": "#util/speech", "tool": "speech"}
    assert out["legacyQuery"] == {"hash": "#util/speech", "tool": "speech"}
    assert out["deepChatMode"] == {"activeMode": "chat", "chatVisible": True}
