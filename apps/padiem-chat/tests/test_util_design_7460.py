"""#7460 — 유틸 디자인 1단계 계약 및 동작 시험.

검증 범위:
1. 상단 Chat | Claw | 유틸 탭(#appSwitch) 제거 및 왼쪽 사이드바 메뉴 일원화.
2. 단일 도구 등록부(static/util-manifest.js)에서 카드·칩·왼쪽 메뉴를 모두 렌더하고,
   도구마다 id, 이름, 아이콘, 분류, 주소(#util/…), 필요 등급, 서버 경로,
   2단계(#7461 대화 방식) 호환 입력 칸 정의(필드·필수 여부·물어볼 문장)를 가짐.
3. 도구 화면 재구성: 큰 "Padiem Util / 유틸" 머리말은 첫 화면(#util)에만 표시,
   도구 화면(#util/<id>) 맨 위 = "‹ 유틸" 뒤로가기 + standalone-views.css 공통 큰 제목 +
   한 줄 설명 + 6개 도구 칩 줄(축사·인사말 | SNS 홍보 | 회의정리 | PDF→MD | 견적서 | Excel),
   현재 도구 강조, 칩으로 바로 이동, "더 자세히" 기본 접힘, 좌입력·우결과 2패널 구조.
4. 옛 #util 주소 호환(#util, #util/, #util-<id>, #util/claw-quote, #util?tool=<id>),
   Chat·Claw 회귀 없음, app.js 로직 추가 금지.
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
MANIFEST_PATH = STATIC / "util-manifest.js"
APP_PATH = STATIC / "util-app.js"
MENU_PATH = STATIC / "util-menu.js"
TOOLS_PATH = STATIC / "util-tools.js"
QUOTE_PATH = STATIC / "util-quote.js"
CONTRACT_PATH = STATIC / "util-tools-contract.js"
MARKDOWN_PATH = STATIC / "util-tools-markdown.js"
UTIL_APP_CSS = (STATIC / "util-app.css").read_text(encoding="utf-8")
UTIL_TOOLS_CSS = (STATIC / "util-tools.css").read_text(encoding="utf-8")
CHAT_APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")

EXPECTED_CHIPS = ["축사·인사말", "SNS 홍보", "회의정리", "PDF→MD", "견적서", "Excel"]
EXPECTED_IDS = ["speech", "sns", "meeting", "pdfmd", "quote", "excel"]


def test_file_boundary_and_top_tab_removal() -> None:
    assert 'id="appSwitch"' not in INDEX
    assert 'class="app-switch"' not in INDEX
    assert ".app-switch" not in UTIL_APP_CSS
    assert 'id="utilNavButton"' in INDEX
    assert 'id="utilSubmenu"' in INDEX
    assert '<script src="./util-manifest.js" defer></script>' in INDEX
    for forbidden in ("PadiemUtilManifest", "util-tool-chip", "util-pane-input"):
        assert forbidden not in CHAT_APP_JS
    assert len(CHAT_APP_JS.splitlines()) <= 5865


def test_layout_css_pins_pc_two_columns_phone_stacked_and_standalone_heading() -> None:
    app_rules = parse_rules(UTIL_APP_CSS)
    workbench = [r for r in app_rules if r.media is None and ".util-tool-workbench" in r.selectors]
    assert workbench and declaration(workbench[0], "display") == "grid"
    assert "minmax(0, 1fr) minmax(0, 1fr)" in (declaration(workbench[0], "grid-template-columns") or "")
    phone_workbench = [r for r in app_rules if r.media == "(max-width: 920px)" and ".util-tool-workbench" in r.selectors]
    assert phone_workbench and declaration(phone_workbench[0], "grid-template-columns") == "1fr"

    tool_rules = parse_rules(UTIL_TOOLS_CSS)
    form_grid = [r for r in tool_rules if r.media is None and ".util-tool-form" in r.selectors]
    assert form_grid and declaration(form_grid[0], "display") == "grid"
    assert "minmax(0, 1fr) minmax(0, 1fr)" in (declaration(form_grid[0], "grid-template-columns") or "")
    phone_form = [r for r in tool_rules if r.media == "(max-width: 920px)" and ".util-tool-form" in r.selectors]
    assert phone_form and declaration(phone_form[0], "grid-template-columns") == "1fr"

    active_chip = find_rules_with_selector(app_rules, '.util-tool-chip[aria-current="page"]')
    assert active_chip and declaration(active_chip[0], "background") == "var(--primary-bg)"
    assert declaration(active_chip[0], "color") == "#fff"


NODE_HARNESS = r'''
const fs = require("node:fs");
const vm = require("node:vm");

const [manifestFile, markdownFile, contractFile, toolsFile, quoteFile, appFile, menuFile] = process.argv.slice(2);

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
    rows: 0,
    maxLength: 0,
    required: false,
    disabled: false,
    hidden: false,
    open: false,
    focused: false,
    noValidate: false,
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
      if (k === "open") this.open = true;
    },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    appendChild(child) { this.children.push(child); child.parentElement = this; return child; },
    replaceChildren(...nodes) { this.children = []; nodes.forEach((n) => this.appendChild(n)); },
    focus() { this.focused = true; },
    click() { (this.listeners.click || []).slice().forEach((fn) => fn({ target: this, preventDefault() {} })); },
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
function fullText(el) { let out = ""; walk(el, (e) => { if (e.tagName === "#TEXT" || (!e.children.length && e.textContent)) out += e.textContent; }); return out; }

const shell = El("div"); shell.className = "app-shell"; shell.dataset.state = "home";
const utilNav = El("button"); utilNav.id = "utilNavButton"; utilNav.setAttribute("aria-current", "false"); registry.push(utilNav);
const chevron = El("span"); chevron.className = "side-chevron"; chevron.textContent = "›"; utilNav.appendChild(chevron);
const utilSubmenu = El("div"); utilSubmenu.id = "utilSubmenu"; utilSubmenu.hidden = true; registry.push(utilSubmenu);
const newChat = El("button"); newChat.id = "newChatButton"; newChat.setAttribute("aria-current", "page"); registry.push(newChat);
const clawNav = El("button"); clawNav.id = "clawNavButton"; clawNav.setAttribute("aria-current", "false"); registry.push(clawNav);

const utilView = El("section"); utilView.id = "utilView"; utilView.hidden = true; registry.push(utilView);
const utilHeader = El("header"); utilHeader.className = "util-header"; utilView.appendChild(utilHeader);
const utilKicker = El("p"); utilKicker.id = "utilKicker"; utilHeader.appendChild(utilKicker); registry.push(utilKicker);
const utilTitle = El("h2"); utilTitle.id = "utilTitle"; utilHeader.appendChild(utilTitle); registry.push(utilTitle);
const utilTagline = El("p"); utilTagline.id = "utilTagline"; utilHeader.appendChild(utilTagline); registry.push(utilTagline);
const root = El("div"); root.id = "utilAppRoot"; utilView.appendChild(root); registry.push(root);
const meetingHost = El("div"); meetingHost.id = "meetingCaptureHost"; meetingHost.hidden = true; registry.push(meetingHost);
const meetingEntry = El("button"); meetingEntry.id = "meetingNavButton"; meetingHost.appendChild(meetingEntry); registry.push(meetingEntry);

const observers = [];
class FakeMutationObserver {
  constructor(cb) { this.cb = cb; observers.push(this); }
  observe(target) { this.target = target; }
  trigger() { this.cb([]); }
}

const listeners = {};
const historyStack = [""];
const loc = {
  _hash: "",
  pathname: "/index.html",
  search: "",
  get hash() { return this._hash; },
  set hash(v) {
    this._hash = String(v || "");
    historyStack.push(this._hash);
    (listeners.hashchange || []).forEach((fn) => fn());
  },
};
const history = {
  state: null,
  replaceState(_s, _t, url) {
    const idx = String(url).indexOf("#");
    loc._hash = idx >= 0 ? String(url).slice(idx) : "";
    historyStack[historyStack.length - 1] = loc._hash;
  },
  back() {
    if (historyStack.length > 1) {
      historyStack.pop();
      loc._hash = historyStack[historyStack.length - 1];
      (listeners.hashchange || []).forEach((fn) => fn());
    }
  },
};

const switchCalls = [];
const windowObj = {
  location: loc,
  history: history,
  addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
  dispatchEvent(ev) { (listeners[ev.type] || []).forEach((fn) => fn(ev)); },
  PadiemAuthSession: { get: () => ({ authenticated: true }) },
  PadiemAppSwitch: {
    openChat() { shell.dataset.state = "home"; switchCalls.push("chat"); },
    openClaw() { shell.dataset.state = "claw"; switchCalls.push("claw"); },
  },
  initPdfMdUtility(panel) {
    const a = El("div"); a.setAttribute("data-util-pane", "input");
    const b = El("div"); b.setAttribute("data-util-pane", "result");
    panel.appendChild(a); panel.appendChild(b);
  },
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
  MutationObserver: FakeMutationObserver,
  CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
  console,
  setTimeout: () => 0,
  clearTimeout: () => {},
};
ctx.globalThis = ctx;
vm.createContext(ctx);
[manifestFile, markdownFile, contractFile, toolsFile, quoteFile, appFile, menuFile].forEach((file) => {
  vm.runInContext(fs.readFileSync(file, "utf8"), ctx, { filename: file });
});

const manifest = windowObj.PadiemUtilManifest;
const app = windowObj.PadiemUtilApp;

// 1. Manifest completeness & Stage 2 (#7461) conversational question helpers
const manifestReport = manifest.TOOLS.map((t) => ({
  id: t.id,
  hasName: Boolean(t.name && t.name.ko && t.name.en),
  hasChip: Boolean(t.chip && t.chip.ko && t.chip.en),
  chipKo: t.chip.ko,
  hasIcon: Boolean(t.icon),
  hasCategory: Boolean(t.category),
  route: t.route,
  requiredTier: t.requiredTier,
  hasServerPathKey: Object.prototype.hasOwnProperty.call(t, "serverPath"),
  fieldCount: t.fields.length,
  requiredCount: t.fields.filter((f) => f.required).length,
  allFieldsHaveQuestions: t.fields.every((f) => Boolean(f.key && typeof f.required === "boolean" && f.question && f.question.ko && f.question.en)),
}));

const speechNextEmpty = manifest.nextQuestion("speech", {}, "ko");
const speechNextFilled = manifest.nextQuestion("speech", { event: "광복절 기념식" }, "ko");
const snsNextPartial = manifest.nextQuestion("sns", { event: "정원 설명회" }, "ko");

// 2. Left menu click -> #util first screen (cards rendered, big header shown)
utilNav.click();
const firstScreenHeaderVisible = utilHeader.hidden === false && utilView.dataset.utilScreen === "list";
const cardButtons = findAll(root, ".util-card");
const cardRoutes = cardButtons.map((b) => b.getAttribute("data-util-route"));
const menuIds = utilSubmenu.children.map((b) => b.dataset.util);

// 3. Open #util/speech -> big header hidden, ‹ 유틸 back link, standalone heading, 6 chips, more collapsed, 2 panes
loc.hash = "#util/speech";
const speechScreen = find(root, ".util-tool-screen");
const speechHeaderHidden = utilHeader.hidden === true && utilView.dataset.utilScreen === "tool";
const speechBackText = fullText(find(speechScreen, ".util-tool-back")).trim();
const speechHeading = find(speechScreen, "#utilToolHeading");
const speechDesc = find(speechScreen, ".util-tool-desc");
const chips = findAll(speechScreen, ".util-tool-chip");
const chipLabels = chips.map((c) => c.textContent);
const speechActiveChips = chips.filter((c) => c.getAttribute("aria-current") === "page").map((c) => c.getAttribute("data-util-chip"));
const speechMore = find(speechScreen, ".util-more");
const speechMoreCollapsed = Boolean(speechMore) && speechMore.open === false;
const speechPanes = [
  Boolean(find(speechScreen, '[data-util-pane="input"]')),
  Boolean(find(speechScreen, '[data-util-pane="result"]')),
];

// 4. Chip click -> direct switch to #util/quote without returning to #util list; Back returns to #util/speech
const quoteChip = chips.find((c) => c.getAttribute("data-util-chip") === "quote");
root.listeners.click[0]({ target: quoteChip, preventDefault() {} });
const afterChipHash = loc.hash;
const quoteActiveMenu = utilSubmenu.children.filter((b) => b.classList.contains("active")).map((b) => b.dataset.util);
const quoteHeadingText = find(root, "#utilToolHeading").textContent;
history.back();
const afterBackHash = loc.hash;
const afterBackHeading = find(root, "#utilToolHeading").textContent;

// 5. All 6 tools mount both input & result panes
const panesByTool = {};
manifest.TOOL_IDS.forEach((id) => {
  loc.hash = "#util/" + id;
  const scr = find(root, ".util-tool-screen");
  panesByTool[id] = Boolean(find(scr, '[data-util-pane="input"]') && find(scr, '[data-util-pane="result"]'));
});

// 6. Legacy #util URL aliases
loc.hash = "#util-sns";
const legacyHyphen = { hash: loc.hash, tool: find(root, ".util-tool-screen").getAttribute("data-util-tool") };
loc.hash = "#util/claw-quote";
const legacyClawQuote = { hash: loc.hash, tool: find(root, ".util-tool-screen").getAttribute("data-util-tool") };
loc.hash = "#util?tool=pdfmd";
const legacyQuery = { hash: loc.hash, tool: find(root, ".util-tool-screen").getAttribute("data-util-tool") };

// 7. Leaving Util via Chat / Claw sidebar clears Util view and stale #util hash without app.js changes
shell.dataset.state = "home";
observers.forEach((o) => { if (o.target === shell) o.trigger(); });
const exitedToChat = { utilHidden: utilView.hidden === true, hash: loc.hash };

console.log(JSON.stringify({
  manifestReport,
  speechNextEmpty: speechNextEmpty && { fieldKey: speechNextEmpty.fieldKey, hasQuestion: Boolean(speechNextEmpty.question) },
  speechNextFilled,
  snsNextPartial: snsNextPartial && snsNextPartial.fieldKey,
  firstScreenHeaderVisible,
  cardRoutes,
  menuIds,
  speechHeaderHidden,
  speechBackText,
  speechHeadingClasses: speechHeading.className,
  speechHeadingText: speechHeading.textContent,
  speechDescClasses: speechDesc.className,
  chipLabels,
  speechActiveChips,
  speechMoreCollapsed,
  speechPanes,
  afterChipHash,
  quoteActiveMenu,
  quoteHeadingText,
  afterBackHash,
  afterBackHeading,
  panesByTool,
  legacyHyphen,
  legacyClawQuote,
  legacyQuery,
  exitedToChat,
}));
'''


def _run_suite() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required"
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "harness_7460.cjs"
        script.write_text(NODE_HARNESS, encoding="utf-8")
        completed = subprocess.run(
            [
                node,
                str(script),
                str(MANIFEST_PATH),
                str(MARKDOWN_PATH),
                str(CONTRACT_PATH),
                str(TOOLS_PATH),
                str(QUOTE_PATH),
                str(APP_PATH),
                str(MENU_PATH),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout.strip())


def test_single_manifest_drives_cards_chips_menu_and_stage2_questions() -> None:
    out = _run_suite()
    ids = [entry["id"] for entry in out["manifestReport"]]
    assert ids == EXPECTED_IDS
    for entry in out["manifestReport"]:
        assert entry["hasName"] is True
        assert entry["hasChip"] is True
        assert entry["hasIcon"] is True
        assert entry["hasCategory"] is True
        assert entry["route"] == f"#util/{entry['id']}"
        assert entry["requiredTier"] == "free"
        assert entry["hasServerPathKey"] is True
        assert entry["fieldCount"] >= 2
        assert entry["requiredCount"] >= 1
        assert entry["allFieldsHaveQuestions"] is True

    # Stage 2 (#7461) conversational question contract
    assert out["speechNextEmpty"] == {"fieldKey": "event", "hasQuestion": True}
    assert out["speechNextFilled"] is None
    assert out["snsNextPartial"] == "content"

    # Cards, chips and left menu all match the manifest
    assert out["cardRoutes"] == [f"#util/{tid}" for tid in EXPECTED_IDS]
    assert out["menuIds"] == EXPECTED_IDS
    assert out["chipLabels"] == EXPECTED_CHIPS


def test_tool_screen_header_chips_collapsed_details_panes_and_legacy_routes() -> None:
    out = _run_suite()
    assert out["firstScreenHeaderVisible"] is True
    assert out["speechHeaderHidden"] is True
    assert out["speechBackText"] == "‹ 유틸"
    assert "standalone-view-title" in out["speechHeadingClasses"]
    assert out["speechHeadingText"] == "축사·인사말"
    assert "standalone-view-tagline" in out["speechDescClasses"]
    assert out["speechActiveChips"] == ["speech"]
    assert out["speechMoreCollapsed"] is True
    assert out["speechPanes"] == [True, True]
    assert all(out["panesByTool"].values()), out["panesByTool"]

    # Chip navigation + Back
    assert out["afterChipHash"] == "#util/quote"
    assert out["quoteActiveMenu"] == ["quote"]
    assert out["quoteHeadingText"] == "견적서 초안"
    assert out["afterBackHash"] == "#util/speech"
    assert out["afterBackHeading"] == "축사·인사말"

    # Legacy #util URL compatibility & clean exit to Chat
    assert out["legacyHyphen"] == {"hash": "#util/sns", "tool": "sns"}
    assert out["legacyClawQuote"] == {"hash": "#util/quote", "tool": "quote"}
    assert out["legacyQuery"] == {"hash": "#util/pdfmd", "tool": "pdfmd"}
    assert out["exitedToChat"] == {"utilHidden": True, "hash": ""}
