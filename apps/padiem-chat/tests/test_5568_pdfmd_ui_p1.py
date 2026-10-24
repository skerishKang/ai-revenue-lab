"""#5568 P1 UI/UX: upload affordance, status chips, preview height, empty states.

Four production complaints were reproduced on chat.padiem.net:

1. The drop zone only advertised drag-and-drop, which does not help on a
   phone. It is now one large keyboard-operable picker target with a visible
   ``파일 선택`` action.
2. Work history rows rendered the raw message string, so the state was buried
   in text. Each row now carries a themed status chip.
3. The original-PDF iframe was 260px tall on mobile. Panes now use a viewport
   clamp and stack to one column below 768px.
4. The first screen and an empty job had no guidance. Both render an explicit
   empty state with the next action.

The Node harness executes the real ``util-pdfmd.js`` against a minimal DOM
shim and a recording fetch. It is load-bearing for the ``modeLabel`` helper:
an earlier revision shadowed that helper with a local ``<label>`` element and
history rendering silently fell through to the failure state.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import json
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PDFMD_JS = ROOT / "static/util-pdfmd.js"
UTIL_MENU_CSS = ROOT / "static/util-menu.css"


# --------------------------------------------------------------------------
# static structural contracts
# --------------------------------------------------------------------------


def test_upload_zone_is_one_keyboard_operable_picker_target() -> None:
    js = PDFMD_JS.read_text(encoding="utf-8")
    assert 'drop.setAttribute("role", "button")' in js
    assert "drop.tabIndex = 0" in js
    assert "PDF 파일을 선택하세요" in js
    assert "pdfmd-drop-cta" in js
    assert '"파일 선택"' in js
    assert 'drop.setAttribute("aria-describedby", "pdfmdDropHint")' in js
    assert 'e.key === "Enter" || e.key === " "' in js
    # The hidden input must stay outside the clickable zone so the synthetic
    # click from openPicker() cannot re-enter the zone's own click handler.
    drop_start = js.index("const drop = el(\"div\", \"pdfmd-drop\")")
    input_start = js.index("const fileInput = document.createElement(\"input\")")
    assert input_start > drop_start
    assert "drop.appendChild(fileInput)" not in js


def test_history_rows_use_status_chips_and_localized_labels() -> None:
    js = PDFMD_JS.read_text(encoding="utf-8")
    for status, label in (
        ("queued", "준비중"),
        ("working", "변환중"),
        ("reviewed", "검토중"),
        ("done", "완료"),
        ("failed", "실패"),
    ):
        assert f'{status}: "{label}"' in js
    assert 'el("button", "pdfmd-history-item")' in js
    assert 'statusChip(job.status)' in js
    assert 'btn.setAttribute("aria-current", "true")' in js
    # Regression: the local <label> must not reuse the helper's name.
    assert 'const modeField = el("label", null, "변환 방식 ")' in js
    assert "const modeLabel = el(" not in js


def test_error_codes_map_to_friendly_korean_messages() -> None:
    js = PDFMD_JS.read_text(encoding="utf-8")
    for code, message in (
        ("unauthorized", "로그인이 필요합니다."),
        ("pdf_magic_mismatch", "PDF 형식이 아니거나 손상된 파일입니다."),
        ("invalid_archive", "ZIP 파일을 열 수 없습니다."),
        ("document_too_large", "파일이 너무 큽니다."),
        ("convert_failed", "변환에 실패했습니다. 다시 시도해 주세요."),
    ):
        assert f'{code}: "{message}"' in js
    assert "이력 조회 실패" not in js
    assert "innerHTML" not in js
    assert "insertAdjacentHTML" not in js


def test_empty_states_guide_the_next_action() -> None:
    js = PDFMD_JS.read_text(encoding="utf-8")
    assert '"첫 PDF를 변환해 보세요."' in js
    assert '"이 작업에는 아직 파일이 없습니다."' in js
    assert '"아직 작업 이력이 없습니다."' in js
    assert '"로그인하면 작업 이력을 볼 수 있습니다."' in js
    assert '"목록에서 \'변환 실행\'을 누릅니다."' in js


def test_preview_panes_are_labelled_and_tall_enough_on_mobile() -> None:
    js = PDFMD_JS.read_text(encoding="utf-8")
    css = UTIL_MENU_CSS.read_text(encoding="utf-8")
    assert 'el("span", "pdfmd-pane-label", "원본 PDF")' in js
    assert 'el("span", "pdfmd-pane-label", "Markdown 변환본")' in js
    assert "mdView.tabIndex = 0" in js
    assert "height: clamp(480px, 62vh, 760px)" in css
    assert "height: 70vh; min-height: 420px; max-height: 720px" in css
    assert "height: 260px" not in css
    assert "grid-template-columns: 1fr 1fr" in css


def test_status_chips_and_controls_reuse_theme_tokens() -> None:
    css = UTIL_MENU_CSS.read_text(encoding="utf-8")
    assert ".pdfmd-shell" in css
    assert "var(--card-bg" in css
    assert "backdrop-filter: blur(24px)" in css
    assert '.pdfmd-status-chip[data-status="done"]' in css
    assert '.pdfmd-status-chip[data-status="failed"]' in css
    assert "min-height: 44px" in css
    assert "min-height: 56px" in css
    # The old flat white PDF controls are replaced by token-driven surfaces.
    assert ".pdfmd-item { border: 1px solid #e5e7eb" not in css
    assert ".pdfmd-btn { padding: 8px 14px" not in css


# --------------------------------------------------------------------------
# behavioral harness: real util-pdfmd.js, minimal DOM, recording fetch
# --------------------------------------------------------------------------

_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");

const pdfmdPath = process.argv[2];

class N {
  constructor(tag) {
    this.tagName = String(tag || "div").toUpperCase();
    this.children = [];
    this.attrs = {};
    this.dataset = {};
    this.style = {};
    this.value = "";
    this.textContent = "";
    this.hidden = false;
    this.type = "";
    this.title = "";
    this.id = "";
    this.tabIndex = -1;
    this.disabled = false;
    this._cls = "";
    this._listeners = {};
    const set = new Set();
    this.classList = {
      add: (...c) => c.forEach((x) => set.add(x)),
      remove: (...c) => c.forEach((x) => set.delete(x)),
      contains: (c) => set.has(c),
    };
  }
  set className(v) { this._cls = String(v || ""); }
  get className() { return this._cls || ""; }
  setAttribute(k, v) {
    this.attrs[k] = String(v);
    if (k === "class") this._cls = String(v);
  }
  getAttribute(k) {
    return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null;
  }
  removeAttribute(k) { delete this.attrs[k]; }
  appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
  append(...children) { children.forEach((child) => this.appendChild(child)); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  removeEventListener() {}
  async dispatch(type, event) {
    for (const fn of this._listeners[type] || []) await fn.call(this, event || { preventDefault() {} });
  }
  focus() {}
  click() { return this.dispatch("click"); }
  querySelector(sel) { return this.findAll(sel)[0] || null; }
  querySelectorAll(sel) { return this.findAll(sel); }
  _descendants() {
    const out = [];
    for (const child of this.children) { out.push(child); out.push(...child._descendants()); }
    return out;
  }
  findAll(sel) {
    const parts = String(sel).split(/\s+/);
    let scope = [this, ...this.children];
    parts.forEach((part, index) => {
      const next = [];
      for (const node of scope) {
        if (index === 0 && simpleMatch(node, part)) next.push(node);
        for (const descendant of node._descendants()) {
          if (simpleMatch(descendant, part)) next.push(descendant);
        }
      }
      scope = Array.from(new Set(next));
    });
    return scope;
  }
}

function simpleMatch(node, sel) {
  let rest = String(sel);
  const idMatch = /^#([\w-]+)/.exec(rest);
  if (idMatch) {
    if (node.id !== idMatch[1]) return false;
    rest = rest.slice(idMatch[0].length);
  }
  const tagMatch = /^([\w-]+)/.exec(rest);
  if (tagMatch) {
    if (tagMatch[1].toUpperCase() !== node.tagName) return false;
    rest = rest.slice(tagMatch[0].length);
  }
  const classes = rest.split(".").filter(Boolean);
  if (classes.length && !classes.every((c) => String(node._cls || "").split(/\s+/).includes(c))) {
    return false;
  }
  return true;
}

function text(node) {
  return String(node.textContent || "") + node.children.map(text).join("");
}

const root = new N("html");
const panel = new N("div");
panel.id = "utilPdfmdPanel";
root.appendChild(panel);

const jobs = [
  { id: "dcj_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", mode: "fast", status: "done", item_count: 2, created_at: "2026-10-24T05:12:00Z" },
  { id: "dcj_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", mode: "verify", status: "reviewed", item_count: 1, created_at: "2026-10-23T23:40:00Z" },
  { id: "dcj_cccccccccccccccccccccccccccccccc", mode: "fast", status: "failed", item_count: 3, created_at: "2026-10-23T22:10:00Z" },
  { id: "dcj_dddddddddddddddddddddddddddddddd", mode: "fast", status: "working", item_count: 1, created_at: "2026-10-23T21:00:00Z" },
  { id: "dcj_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", mode: "verify", status: "queued", item_count: 1, created_at: "2026-10-23T20:00:00Z" },
];
const items = [
  { id: "dci_11111111111111111111111111111111", job_id: jobs[0].id, name: "sample-one.pdf", status: "reviewed", page_count: 1, character_count: 275, has_markdown: true, has_original: true, report: null, error_code: null },
  { id: "dci_22222222222222222222222222222222", job_id: jobs[0].id, name: "damaged.pdf", status: "failed", page_count: 0, character_count: 0, has_markdown: false, has_original: true, report: null, error_code: "pdf_magic_mismatch" },
];

const requests = [];
let historyMode = "jobs";
function json(data, status) {
  const code = status || 200;
  return {
    ok: code < 400,
    status: code,
    headers: { get: () => "application/json" },
    json: async () => data,
  };
}
async function fetch(url) {
  const target = String(url);
  requests.push(target);
  if (target.indexOf("/api/document-conversions?limit=") !== -1) {
    if (historyMode === "unauthorized") return json({ error: { code: "unauthorized" } }, 401);
    return json({ jobs: jobs });
  }
  if (/\/markdown\?display=inline$/.test(target)) {
    return {
      ok: true,
      status: 200,
      headers: { get: () => "text/markdown" },
      text: async () => "# 변환 결과\n\n본문 텍스트",
    };
  }
  if (/^\/api\/document-conversions\/dcj_[a-z]+$/.test(target)) return json({ items: items });
  return json({ error: { code: "not_found" } }, 404);
}

const ctx = {
  document: {
    body: new N("body"),
    documentElement: root,
    getElementById: (id) => (id === "utilPdfmdPanel" ? panel : null),
    querySelector: (sel) => root.findAll(sel)[0] || null,
    querySelectorAll: (sel) => root.findAll(sel),
    createElement: (tag) => new N(tag),
    addEventListener() {},
  },
  window: {},
  fetch: fetch,
  console: console,
  setTimeout: () => 0,
  URL: { createObjectURL: () => "blob:fixture", revokeObjectURL() {} },
};

vm.createContext(ctx);
vm.runInContext(fs.readFileSync(pdfmdPath, "utf8"), ctx, { filename: "util-pdfmd.js" });

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function fail(label, extra) {
  console.log(JSON.stringify({ ok: false, fail: label, extra: extra || null, requests: requests }));
  process.exit(1);
}

function buttonByText(label) {
  return root.findAll("button").find((b) => text(b).trim() === label) || null;
}

(async () => {
  ctx.window.initPdfMdUtility(panel);
  await flush();
  await flush();

  // 0) #5711: new work is paused; the COM2 notice replaces the picker action.
  const noticeText = root.findAll(".pdfmd-status").map(text).join(" ");
  if (!noticeText.includes("서비스 준비 중 · 신규 업로드 및 변환 일시 중단")) fail("PAUSE_NOTICE_MISSING", noticeText);
  const drop = root.findAll(".pdfmd-drop")[0];
  if (!drop) fail("DROP_ZONE_MISSING");
  if (drop.getAttribute("role") !== null) fail("PAUSED_DROP_STILL_BUTTON");
  const dropCta = drop.querySelector(".pdfmd-drop-cta");
  if (!dropCta || !text(dropCta).includes("업로드 일시 중단")) fail("PAUSED_DROP_COPY_MISSING", dropCta && text(dropCta));

  // 1) History rows render one localized chip each.
  const rows = root.findAll(".pdfmd-history-item");
  if (rows.length !== 5) fail("HISTORY_NOT_RENDERED", rows.length);
  const chips = root.findAll(".pdfmd-history-list .pdfmd-status-chip");
  const chipPairs = chips.map((c) => c.dataset.status + ":" + text(c));
  const expected = ["done:완료", "reviewed:검토중", "failed:실패", "working:변환중", "queued:준비중"];
  if (JSON.stringify(chipPairs) !== JSON.stringify(expected)) fail("STATUS_CHIP_MISMATCH", chipPairs);
  const meta = root.findAll(".pdfmd-history-meta").map(text);
  if (meta[0] !== "2개 파일 · 빠른 변환") fail("HISTORY_META_MISMATCH", meta[0]);
  if (!rows[0].getAttribute("aria-label").includes("상태 완료")) fail("HISTORY_ARIA_MISSING_STATUS");

  // 2) First screen explains the next action instead of showing nothing.
  const onboarding = text(panel.querySelector(".pdfmd-items"));
  if (!onboarding.includes("첫 PDF를 변환해 보세요.")) fail("ONBOARDING_MISSING");
  if (!onboarding.includes("변환 실행")) fail("ONBOARDING_MISSING_STEP");

  // 3) Selecting a job renders item chips, friendly failure copy, retry label.
  await rows[0].dispatch("click");
  await flush();
  await flush();
  const cards = root.findAll(".pdfmd-item");
  if (cards.length !== 2) fail("ITEMS_NOT_RENDERED", cards.length);
  const cardChips = root.findAll(".pdfmd-item .pdfmd-status-chip").map((c) => c.dataset.status + ":" + text(c));
  if (JSON.stringify(cardChips) !== JSON.stringify(["reviewed:검토중", "failed:실패"])) {
    fail("ITEM_STATUS_CHIP_MISMATCH", cardChips);
  }
  const warn = text(panel.querySelector(".pdfmd-warn"));
  if (warn !== "PDF 형식이 아니거나 손상된 파일입니다.") fail("RAW_ERROR_LEAKED", warn);
  const actions = root.findAll(".pdfmd-item-actions").map(text);
  if (!actions[0].includes("비교 보기") || actions[0].includes("변환 실행")) fail("PRIMARY_ACTION_WRONG", actions[0]);
  if (actions[1].includes("다시 변환") || actions[1].includes("변환 실행")) fail("PAUSED_RETRY_RENDERED", actions[1]);
  if (!actions[1].includes("삭제")) fail("PAUSED_DELETE_MISSING", actions[1]);
  if (rows[0].getAttribute("aria-current") !== "true") fail("ACTIVE_ROW_NOT_MARKED");

  // 4) Preview shows labelled panes, a real markdown body and a taller frame.
  await buttonByText("비교 보기").dispatch("click");
  await flush();
  await flush();
  if (panel.querySelector(".pdfmd-preview").hidden !== false) fail("PREVIEW_NOT_SHOWN");
  const labels = root.findAll(".pdfmd-pane-label").map(text);
  if (JSON.stringify(labels) !== JSON.stringify(["원본 PDF", "Markdown 변환본"])) fail("PANE_LABELS_WRONG", labels);
  const md = panel.querySelector(".pdfmd-md");
  if (!text(md).includes("변환 결과")) fail("MARKDOWN_NOT_LOADED", text(md));
  if (md.tabIndex !== 0) fail("MARKDOWN_NOT_FOCUSABLE");
  const frame = panel.querySelector(".pdfmd-iframe");
  if (!String(frame.src).includes("/original?display=inline")) fail("IFRAME_SRC_NOT_SET", frame.src);

  // 5) Paused: the new-work control stays hidden.
  const newJob = buttonByText("새 작업");
  if (!newJob) fail("NEW_JOB_BUTTON_MISSING");
  if (newJob.hidden !== true) fail("NEW_JOB_VISIBLE_WHILE_PAUSED");

  // 6) Guests get a login explanation, not a raw unauthorized string.
  historyMode = "unauthorized";
  ctx.window.initPdfMdUtility(panel);
  await flush();
  await flush();
  const historyText = text(panel.querySelector(".pdfmd-history"));
  if (!historyText.includes("로그인하면 작업 이력을 볼 수 있습니다.")) fail("GUEST_STATE_MISSING", historyText);
  if (historyText.includes("unauthorized")) fail("RAW_UNAUTHORIZED_LEAKED", historyText);

  console.log(JSON.stringify({
    ok: true,
    historyRows: rows.length,
    chips: chipPairs,
    meta: meta[0],
    itemActions: actions,
    paneLabels: labels,
    markdownLoaded: true,
    pauseNotice: noticeText.trim(),
    dropCta: dropCta ? text(dropCta) : "",
    newJobHidden: newJob ? newJob.hidden === true : null,
    guestState: historyText.trim(),
  }));
})().catch((error) => {
  console.log(JSON.stringify({ ok: false, error: String((error && error.stack) || error) }));
});
"""


@lru_cache(maxsize=1)
def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the util-pdfmd behavioral harness"
    harness_path = ROOT / "tests" / "_5568_pdfmd_ui_harness.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness_path), str(PDFMD_JS)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ},
            timeout=60,
            cwd=str(ROOT),
        )
    finally:
        harness_path.unlink(missing_ok=True)
    stdout = result.stdout.strip()
    assert result.returncode == 0 and stdout, f"harness crashed: stdout={stdout!r} stderr={result.stderr!r}"
    payload = json.loads(stdout.splitlines()[-1])
    assert payload.get("ok"), f"harness failed: {payload!r}"
    return payload


def test_history_renders_every_status_chip() -> None:
    payload = _run_harness()
    assert payload["historyRows"] == 5
    assert payload["chips"] == [
        "done:완료",
        "reviewed:검토중",
        "failed:실패",
        "working:변환중",
        "queued:준비중",
    ]
    assert payload["meta"] == "2개 파일 · 빠른 변환"


def test_item_cards_show_friendly_errors_and_correct_actions() -> None:
    payload = _run_harness()
    assert "비교 보기" in payload["itemActions"][0]
    assert "변환 실행" not in payload["itemActions"][0]
    # #5711: retry is paused; only the existing delete action remains.
    assert "다시 변환" not in payload["itemActions"][1]
    assert "삭제" in payload["itemActions"][1]
    assert "신규 업로드 및 변환 일시 중단" in payload["pauseNotice"]
    assert "업로드 일시 중단" in payload["dropCta"]
    assert payload["newJobHidden"] is True


def test_preview_labels_markdown_and_guest_state() -> None:
    payload = _run_harness()
    assert payload["paneLabels"] == ["원본 PDF", "Markdown 변환본"]
    assert payload["markdownLoaded"] is True
    assert "로그인하면 작업 이력을 볼 수 있습니다." in payload["guestState"]
