"""#7461 (3/3) — Excel 열기·검토 대화 방식 연결 시험.

검증 범위:
1. #util/excel 화면이 다른 유틸과 같은 공통 대화 틀(PadiemUtilChatMode)을 쓰는지
   - 모드 전환(폼·대화 두 탭), 매니페스트 질문(file → goal) 순서, 하드코딩 질문 금지.
2. 대화 방식에서 XLSX 첨부 → 검토 목표(goal) 입력 시 기존 백엔드 라우트 1건 호출
   - 첨부만으로는 요청 0건(선택 칸인 검토 목표를 먼저 물어 한도를 먼저 쓰지 않음),
   - 목표 입력 시에만 /api/util/excel/review 1건, 새로운 서버 경로 없음.
3. 폼 ↔ 대화 넘기기 시 상태 유지
   - 대화에서 올린 파일은 폼에서 그대로 검토되고(파일 이름 표기), 검토 목표도 유지.
   - 폼에서 다시 대화로 넘어가면 같은 값을 이어서 씀.
4. 실패 안내는 폼 방식과 동일한 문구(서버 안내 문구 우선, 413·429 로컬 문구).
5. app.js 무변경(파일 경계)과 DOM sink 금지 등 정적 경계.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

# #8060: shipped reads live in _support; the wiring and behavior checks stay.
from _support import util_chat_mode_excel_source as sheets

APP_JS = sheets.app_js()
MANIFEST_JS = sheets.manifest_js()
CHAT_MODE_JS = sheets.chat_mode_js()
EXCEL_JS = sheets.excel_js()


def test_excel_chat_mode_scope_and_boundaries() -> None:
    # The conversational intake lives in the util modules; app.js gains nothing.
    for token in ("PadiemUtilChatMode", "util-chat-intake", "util-mode-switch"):
        assert token not in APP_JS
    for mod_src in (CHAT_MODE_JS, EXCEL_JS):
        for sink in (".innerHTML", ".outerHTML", "insertAdjacentHTML", "document.write"):
            assert sink not in mod_src
    # No tool questions hardcoded in the engine — Excel's questions come from
    # the manifest exactly like every other tool.
    assert "열어 검토할 Excel" not in CHAT_MODE_JS
    assert "시트에서 중점적으로 확인할 항목" not in CHAT_MODE_JS
    # The review goal stays OPTIONAL in the manifest (the form behavior is
    # unchanged); the chat intake asks it via the engine's opt-in list.
    assert 'fld("goal", "textarea", false,' in MANIFEST_JS
    assert 'askOptional: ["goal"],' in EXCEL_JS
    # Both modes reuse the single existing server route — the module has
    # exactly one fetch call site and no new endpoint.
    assert EXCEL_JS.count("fetch(") == 1
    assert "/api/util/excel/review" in EXCEL_JS
    # The engine marks the opt-in optional ask so an empty answer can skip it.
    assert "fromOptionalAsk" in CHAT_MODE_JS


NODE_HARNESS = r'''
const fs = require("node:fs");
const vm = require("node:vm");

const [manifestFile, markdownFile, contractFile, chatModeFile, toolsFile, quoteFile, pdfmdFile, excelFile, appFile] = process.argv.slice(2);

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
    accept: "",
    multiple: false,
    rows: 0,
    maxLength: 0,
    tabIndex: 0,
    required: false,
    disabled: false,
    hidden: false,
    checked: false,
    open: false,
    focused: false,
    noValidate: false,
    isConnected: true,
    scrollTop: 0,
    scrollHeight: 100,
    style: {},
    children: [],
    attrs: {},
    dataset: {},
    listeners: {},
    parentElement: null,
    files: null,
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
    removeAttribute(k) { delete this.attrs[k]; },
    hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    appendChild(child) {
      if (child.parentElement && child.parentElement !== this) {
        const idx = child.parentElement.children.indexOf(child);
        if (idx >= 0) child.parentElement.children.splice(idx, 1);
      }
      this.children.push(child);
      child.parentElement = this;
      return child;
    },
    insertBefore(child, refNode) {
      if (!refNode) return this.appendChild(child);
      if (child.parentElement) {
        const oldIdx = child.parentElement.children.indexOf(child);
        if (oldIdx >= 0) child.parentElement.children.splice(oldIdx, 1);
      }
      const idx = this.children.indexOf(refNode);
      if (idx < 0) return this.appendChild(child);
      child.parentElement = this;
      this.children.splice(idx, 0, child);
      return child;
    },
    replaceChildren(...nodes) { this.children = []; nodes.forEach((n) => this.appendChild(n)); },
    focus() { this.focused = true; },
    scrollIntoView() {},
    getBoundingClientRect() { return { top: 0, left: 0, width: 300, height: 44 }; },
    click() { (this.listeners.click || []).slice().forEach((fn) => fn({ target: this, preventDefault() {} })); },
    dispatchChange() { (this.listeners.change || []).slice().forEach((fn) => fn({ target: this })); },
    dispatchInput() { (this.listeners.input || []).slice().forEach((fn) => fn({ target: this })); },
    dispatchKeydown(ev) { (this.listeners.keydown || []).slice().forEach((fn) => fn(ev)); },
    submitForm() { (this.listeners.submit || []).slice().forEach((fn) => fn({ preventDefault() {} })); },
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
async function settle(n = 5) { for (let i = 0; i < n; i += 1) await tick(); }

const shell = El("div"); shell.className = "app-shell"; shell.dataset.state = "home";
const utilView = El("section"); utilView.id = "utilView"; utilView.hidden = true; registry.push(utilView);
const utilHeader = El("header"); utilHeader.className = "util-header"; utilView.appendChild(utilHeader);
const utilTitle = El("h2"); utilTitle.id = "utilTitle"; utilHeader.appendChild(utilTitle); registry.push(utilTitle);
const utilKicker = El("p"); utilKicker.id = "utilKicker"; utilHeader.appendChild(utilKicker); registry.push(utilKicker);
const utilTagline = El("p"); utilTagline.id = "utilTagline"; utilHeader.appendChild(utilTagline); registry.push(utilTagline);
const root = El("div"); root.id = "utilAppRoot"; utilView.appendChild(root); registry.push(root);

const requests = [];
let excelFailMode = null; // null | 413 | 422 | 429
const excelReviews = [];
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
const historyObj = {
  state: null,
  replaceState(_s, _t, url) {
    const idx = String(url).indexOf("#");
    loc._hash = idx >= 0 ? String(url).slice(idx) : "";
  },
};

function xlsxReviewPayload() {
  return {
    ok: true,
    review: {
      sheets: [{ index: 0, title: "예산", rows: 3, columns: 4, empty: false, truncated: false }],
      preview: {
        sheet_title: "예산",
        headers: ["항목", "금액"],
        rows: [["노트북", "1,200,000"]],
      },
      summary: {
        sheet_count: 1,
        readable_sheet_count: 1,
        empty_sheet_indices: [],
        truncated_sheet_titles: [],
        total_data_rows: 3,
        review_note: "",
      },
    },
  };
}

function fakeFetch(url, init) {
  const method = (init && init.method) || "GET";
  let parsedBody = null;
  if (init && typeof init.body === "string") {
    try { parsedBody = JSON.parse(init.body); } catch (_) { parsedBody = init.body; }
  }
  requests.push({ url, method, headers: (init && init.headers) || {}, body: parsedBody });

  const excelMatch = /^\/api\/util\/excel\/review(\?.*)?$/.exec(url);
  if (excelMatch && method === "POST") {
    const query = excelMatch[1] || "";
    const params = new URLSearchParams(query.startsWith("?") ? query.slice(1) : query);
    excelReviews.push({
      url,
      goal: params.get("goal") || "",
      filename: decodeURIComponent((init.headers && init.headers["X-Padiem-Filename"]) || ""),
      media: (init.headers && init.headers["X-Padiem-Media-Type"]) || "",
      contentType: (init.headers && init.headers["Content-Type"]) || "",
    });
    if (excelFailMode === 413) {
      return Promise.resolve({
        ok: false, status: 413,
        headers: { get: () => "application/json" },
        json: () => Promise.resolve({ error: { code: "document_size_limit", message: "서버가 내려준 크기 상한 안내 문구" } }),
      });
    }
    if (excelFailMode === 422) {
      return Promise.resolve({
        ok: false, status: 422,
        headers: { get: () => "application/json" },
        json: () => Promise.resolve({ error: { code: "invalid_document", message: "XLSX 파일만 업로드할 수 있습니다." } }),
      });
    }
    if (excelFailMode === 429) {
      return Promise.resolve({
        ok: false, status: 429,
        headers: { get: () => "application/json" },
        json: () => Promise.reject(new Error("non-json refusal")),
      });
    }
    return Promise.resolve({
      ok: true, status: 200,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve(xlsxReviewPayload()),
    });
  }
  if (url === "/api/projects" && method === "GET") {
    return Promise.resolve({
      ok: true, status: 200,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ projects: [{ id: "proj_util_1", name: "유틸" }] }),
    });
  }
  if (url.startsWith("/api/pc/pairings")) {
    return Promise.resolve({
      ok: true, status: 200,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ ok: true, links: [] }),
    });
  }
  return Promise.resolve({ ok: true, status: 200, headers: { get: () => "application/json" }, json: () => Promise.resolve({}) });
}

const windowObj = {
  location: loc,
  history: historyObj,
  fetch: fakeFetch,
  addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
  dispatchEvent(ev) { (listeners[ev.type] || []).forEach((fn) => fn(ev)); },
  PadiemAuthSession: { get: () => ({ authenticated: true }) },
  PadiemAuthGate: { authenticated: () => true },
  PadiemTierSelection: { get: () => "plus" },
  PadiemAppSwitch: { openChat() { shell.dataset.state = "home"; }, openClaw() { shell.dataset.state = "claw"; } },
};
const document = {
  readyState: "complete",
  documentElement: { lang: "ko" },
  body: El("body"),
  head: El("head"),
  createElement(tag) { const n = El(tag); registry.push(n); return n; },
  createTextNode(t) { const n = El("#text"); n.textContent = String(t); return n; },
  getElementById(id) { const hits = registry.filter((e) => e.id === id); return hits.length ? hits[hits.length - 1] : null; },
  querySelector(sel) { return sel === ".app-shell" ? shell : null; },
  addEventListener() {},
};

const ctx = {
  document,
  window: windowObj,
  fetch: fakeFetch,
  location: loc,
  history: historyObj,
  URL: { createObjectURL: () => "blob:test", revokeObjectURL: () => {} },
  URLSearchParams,
  MutationObserver: class { observe() {} },
  CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
  console,
  setTimeout: () => 0,
  clearTimeout: () => {},
};
ctx.globalThis = ctx;
vm.createContext(ctx);
[manifestFile, markdownFile, contractFile, chatModeFile, toolsFile, quoteFile, pdfmdFile, excelFile, appFile].forEach((file) => {
  vm.runInContext(fs.readFileSync(file, "utf8"), ctx, { filename: file });
});

function xlsxFile(name) {
  return { name, type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)) };
}

async function openExcelChat() {
  loc.hash = "#util/excel";
  await settle(8);
  const chat = find(root, '[data-util-chat-intake="excel"]');
  find(root, '[data-util-mode="chat"]').click();
  await settle(4);
  return chat;
}

(async () => {
  const out = {};

  // ── 1. 기본 진입: 폼 방식 + 모드 스위치, 대화 칸은 숨겨져 있다 ──
  loc.hash = "#util/excel";
  await settle(8);
  out.defaultEntry = {
    formVisible: find(root, "#utilToolForm-excel").hidden === false,
    hasModeSwitch: Boolean(find(root, '[data-util-mode="form"]')) && Boolean(find(root, '[data-util-mode="chat"]')),
    intakeHidden: find(root, '[data-util-chat-intake="excel"]').hidden === true,
  };

  // ── 2. 대화 방식: 파일 질문 → 첨부(요청 0건) → 검토 목표 질문 ──
  requests.length = 0; excelReviews.length = 0; excelFailMode = null;
  loc.hash = "#util";
  await settle(6);
  const chat = await openExcelChat();
  const askedFile = findAll(chat, "[data-question-field]").map((n) => n.getAttribute("data-question-field"));
  const hasFileTrigger = Boolean(find(chat, "[data-util-chat-file-trigger]"));
  const excelInput = find(chat, "#utilChatInput-excel");
  excelInput.value = "   ";
  find(chat, ".util-chat-composer").submitForm();
  await settle();
  const reqAfterEmpty = requests.length;
  const fileInputNode = find(chat, "[data-util-chat-file]");
  fileInputNode.files = [xlsxFile("예산.xlsx")];
  fileInputNode.dispatchChange();
  await settle(10);
  const reqAfterAttach = requests.filter((r) => r.method === "POST").length;
  const askedAfterAttach = findAll(chat, "[data-question-field]").map((n) => n.getAttribute("data-question-field"));
  const goalBubble = find(chat, '[data-question-field="goal"]');
  const goalBubbleText = goalBubble ? fullText(goalBubble) : "";

  // ── 3. 검토 목표 입력 → 기존 라우트 1건 + 결과 표시 ──
  excelInput.value = "합계 수식과 단가 누락 확인";
  find(chat, ".util-chat-composer").submitForm();
  await settle(10);
  out.chatReview = {
    askedFile,
    hasFileTrigger,
    reqAfterEmpty,
    reqAfterAttach,
    askedAfterAttach,
    goalBubbleHasSkipHint: goalBubbleText.includes("비워 두고 보내") && goalBubbleText.includes("시트에서 중점적으로"),
    reviewCount: excelReviews.length,
    reviewGoal: excelReviews[0] ? excelReviews[0].goal : "",
    reviewFilename: excelReviews[0] ? excelReviews[0].filename : "",
    reviewMedia: excelReviews[0] ? excelReviews[0].media : "",
    outputHasSheets: fullText(find(root, ".util-result-output")).includes("시트 목록") && fullText(find(root, ".util-result-output")).includes("예산"),
    outputHasSummaryRows: fullText(find(root, ".util-result-output")).includes("3"),
    readyBubble: fullText(chat).includes("검토 결과를 준비했습니다"),
  };

  // ── 4. 폼으로 열기: 올린 파일과 검토 목표 유지, 폼 제출도 같은 라우트 ──
  find(chat, "[data-util-open-form]").click();
  await settle(4);
  out.backToForm = {
    formVisible: find(root, "#utilToolForm-excel").hidden === false,
    goalKept: find(root, ".util-excel-goal").value,
    carriedFileName: fullText(find(root, ".util-excel-form")).includes("예산.xlsx"),
  };
  requests.length = 0; excelReviews.length = 0;
  find(root, "#utilToolForm-excel").submitForm();
  await settle(10);
  out.formResubmit = {
    reviewCount: excelReviews.length,
    reviewGoal: excelReviews[0] ? excelReviews[0].goal : "",
    reviewFilename: excelReviews[0] ? excelReviews[0].filename : "",
  };

  // ── 5. 다시 대화로: 같은 값을 이어서 다듬기(목표 누적) ──
  requests.length = 0; excelReviews.length = 0;
  find(root, '[data-util-mode="chat"]').click();
  await settle(4);
  const refineChat = find(root, '[data-util-chat-intake="excel"]');
  const excelInput2 = find(refineChat, "#utilChatInput-excel");
  excelInput2.value = "합계 수식 유무도 확인";
  find(refineChat, ".util-chat-composer").submitForm();
  await settle(10);
  out.refineAgain = {
    reviewCount: excelReviews.length,
    reviewGoal: excelReviews[0] ? excelReviews[0].goal : "",
    reviewFilename: excelReviews[0] ? excelReviews[0].filename : "",
  };

  // ── 6. 실패 안내: 서버 문구 우선(413) / 한도 문구(429), 폼과 같은 문구 ──
  loc.hash = "#util";
  await settle(6);
  requests.length = 0; excelReviews.length = 0;
  excelFailMode = 413;
  const failChat = await openExcelChat();
  const failFile = find(failChat, "[data-util-chat-file]");
  failFile.files = [xlsxFile("큰파일.xlsx")];
  failFile.dispatchChange();
  await settle(8);
  const failInput = find(failChat, "#utilChatInput-excel");
  failInput.value = "";
  find(failChat, ".util-chat-composer").submitForm();
  await settle(10);
  out.fail413 = {
    reviewCount: excelReviews.length,
    statusText: fullText(find(root, ".util-excel-status")),
    failedBubble: fullText(failChat).includes("검토를 마치지 못했습니다"),
    outputEmpty: find(root, ".util-result-output").getAttribute("data-empty") === "true",
  };

  loc.hash = "#util";
  await settle(6);
  excelFailMode = 429;
  const quotaChat = await openExcelChat();
  const quotaFile = find(quotaChat, "[data-util-chat-file]");
  quotaFile.files = [xlsxFile("예산2.xlsx")];
  quotaFile.dispatchChange();
  await settle(8);
  const quotaInput = find(quotaChat, "#utilChatInput-excel");
  quotaInput.value = "부가세 누락 확인";
  find(quotaChat, ".util-chat-composer").submitForm();
  await settle(10);
  out.fail429 = {
    statusText: fullText(find(root, ".util-excel-status")),
  };

  // ── 7. ?mode=chat 딥링크 ──
  loc.hash = "#util";
  await settle(6);
  excelFailMode = null;
  loc.hash = "#util/excel?mode=chat";
  await settle(8);
  out.deepLink = {
    intakeVisible: find(root, '[data-util-chat-intake="excel"]').hidden === false,
    formHidden: find(root, "#utilToolForm-excel").hidden === true,
  };

  console.log(JSON.stringify(out));
})();
'''

def _run_excel_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required"
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "harness_excel_chat_7461.cjs"
        script.write_text(NODE_HARNESS, encoding="utf-8")
        completed = subprocess.run(
            [
                node,
                str(script),
                sheets.static_path("util-manifest.js"),
                sheets.static_path("util-tools-markdown.js"),
                sheets.static_path("util-tools-contract.js"),
                sheets.static_path("util-chat-mode.js"),
                sheets.static_path("util-tools.js"),
                sheets.static_path("util-quote.js"),
                sheets.static_path("util-pdfmd.js"),
                sheets.static_path("util-excel.js"),
                sheets.static_path("util-app.js"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout.strip())


def test_excel_chat_mode_upload_goal_result_and_state_sync() -> None:
    out = _run_excel_harness()

    # 1. 기본 진입
    assert out["defaultEntry"] == {
        "formVisible": True,
        "hasModeSwitch": True,
        "intakeHidden": True,
    }

    # 2. 대화 방식: 파일 질문 먼저, 첨부만으로는 요청 0건, 그다음 검토 목표 질문
    chat = out["chatReview"]
    assert chat["askedFile"] == ["file"]
    assert chat["hasFileTrigger"] is True
    assert chat["reqAfterEmpty"] == 0
    assert chat["reqAfterAttach"] == 0
    assert chat["askedAfterAttach"] == ["file", "goal"]
    assert chat["goalBubbleHasSkipHint"] is True

    # 3. 검토 목표 입력 시에만 기존 라우트 1건 — 같은 경로, 같은 헤더, 결과 표시
    assert chat["reviewCount"] == 1
    assert chat["reviewGoal"] == "합계 수식과 단가 누락 확인"
    assert chat["reviewFilename"] == "예산.xlsx"
    assert chat["reviewMedia"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert chat["outputHasSheets"] is True
    assert chat["outputHasSummaryRows"] is True
    assert chat["readyBubble"] is True

    # 4. 폼으로 열기 — 올린 파일(이름 표기)과 검토 목표 유지, 폼 제출도 같은 라우트
    assert out["backToForm"] == {
        "formVisible": True,
        "goalKept": "합계 수식과 단가 누락 확인",
        "carriedFileName": True,
    }
    assert out["formResubmit"]["reviewCount"] == 1
    assert out["formResubmit"]["reviewGoal"] == "합계 수식과 단가 누락 확인"
    assert out["formResubmit"]["reviewFilename"] == "예산.xlsx"

    # 5. 다시 대화로 넘어가 다듬기 — 목표가 누적되어 같은 파일로 재검토
    assert out["refineAgain"]["reviewCount"] == 1
    assert out["refineAgain"]["reviewGoal"] == "합계 수식과 단가 누락 확인\n합계 수식 유무도 확인"
    assert out["refineAgain"]["reviewFilename"] == "예산.xlsx"

    # 6. 실패 안내 — 서버 문구 우선(413), 한도 문구(429), 폼 방식과 동일한 문구
    assert out["fail413"]["reviewCount"] == 1
    assert "서버가 내려준 크기 상한 안내 문구" in out["fail413"]["statusText"]
    assert out["fail413"]["failedBubble"] is True
    assert out["fail413"]["outputEmpty"] is True
    assert "오늘 사용 한도를 다 썼어요" in out["fail429"]["statusText"]

    # 7. 딥링크
    assert out["deepLink"] == {"intakeVisible": True, "formHidden": True}
