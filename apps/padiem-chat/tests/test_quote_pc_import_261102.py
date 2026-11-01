"""#6460 3장 — 견적서 양식 화면이 "내 PC에서 가져오기"에 이어진다 (클레이 웹 엑셀).

공용 부품(static/pc-file-exchange.js, #6012)은 **쓰기만** 하고 고치지 않는다:
부품에는 확장자 필터가 없으므로 이 화면이 엑셀 양식(.xlsx·.xls·.xlsm)만 거르고,
고른 파일은 브라우저 선택과 **같은 save() 흐름**(10MB 초과는 #6584의 tus)으로
그대로 넘어간다. 새 업로드 경로는 없다.

시험은 두 층이다:
- 정적 계약: 버튼·안내 노드, 단일 업로드 경로, 필터 상수, 연결 상태 표시 규칙.
- 행위 헤널스(실제 모듈 실행): 연결됨/미연결/필터/타계정 네 장면을 recording
  fetch + 모의 부품으로 돌려 실제 네트워크 모양을 증명한다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
SOURCES_JS = STATIC / "claw-web-xlsx-sources.js"
INDEX_HTML = STATIC / "index.html"
EXCHANGE_JS = STATIC / "pc-file-exchange.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── 정적 계약 ────────────────────────────────────────────────────────────────


def test_html_places_the_pc_button_beside_the_untouched_direct_picker() -> None:
    html = _read(INDEX_HTML)
    actions = html[html.index('id="clawWebXlsxInput"') - 400: html.index("clawWebXlsxNotice") + 200]
    assert 'id="clawWebXlsxPcPick" hidden' in actions
    assert "내 PC에서 가져오기" in actions
    assert 'id="clawWebXlsxPcNote" role="status" hidden' in actions
    # 기존 직접 업로드는 그대로다.
    assert 'id="clawWebXlsxInput"' in actions
    assert 'id="clawWebXlsxSave">원본 보관</button>' in actions
    assert '<label for="clawWebXlsxInput">XLSX 파일 선택</label>' in actions


def test_the_shared_part_is_consumed_not_modified_and_opened_in_import_half() -> None:
    js = _read(SOURCES_JS)
    assert 'const PC_EXCHANGE_SCRIPT = "./pc-file-exchange.js"' in js
    assert 'script.src = PC_EXCHANGE_SCRIPT' in js
    assert 'const PC_EXCHANGE_CSS = "./pc-file-exchange.css"' in js
    assert 'mode: "import"' in js
    assert "onSelect" in js
    assert "loadPcExchange()" in js
    # 부품 자체에는 이 변경이 요구하는 것이 없다: open({mode, onSelect})과
    # /api/pc/file이면 충분하다(필터는 이 화면이 거른다).
    exchange = _read(EXCHANGE_JS)
    assert "settings.startFolder" in exchange  # 부품의 계약은 그대로


def test_imported_file_rides_the_existing_save_flow_only() -> None:
    js = _read(SOURCES_JS)
    assert "await save(new window.File([blob], name, { type: XLSX_MEDIA_TYPE }));" in js
    assert "async function save(fileOverride)" in js
    assert "const file = fileOverride || input.files?.[0];" in js
    # 새 업로드 경로를 만들지 않았다: tus endpoint 구성은 기존 한 곳뿐이다.
    assert js.count('ENDPOINT + "/tus"') == 1
    assert "/api/pc/fetch" not in js  # 바이트는 pc/file 한 번으로 읽는다
    assert 'PC_FILE_FETCH + "?dispatch_id=" + encodeURIComponent(picked.fileId)' in js


def test_picker_filters_excel_forms_before_any_byte_moves() -> None:
    js = _read(SOURCES_JS)
    assert r"/\.(?:xlsx|xls|xlsm)$/i" in js
    assert 'report(PC_COPY.notExcel);' in js
    # 필터는 네트워크보다 먼저다: 가져오기 본문이 필터 뒤에 온다.
    assert js.index("PC_PICK_RE.test(name)") < js.index("PC_FILE_FETCH + \"?dispatch_id=\"")


def test_pc_button_shows_only_with_a_server_answered_link() -> None:
    js = _read(SOURCES_JS)
    # 서버의 pairings 기록만이 내민다/접는다를 말한다: true면 내리고,
    # false면 접어 공용 문구(pc-exchange-no-pc)와 연결 안내로 바꾼다.
    assert "void pcLinked().then((linked) => {" in js
    assert "if (linked === true) {" in js and "pcPick.hidden = false;" in js
    assert "pcPick.hidden = true;" in js
    # 미연결: 직접 업로드는 그대로, 안내는 공용 문구 키(pc-exchange-no-pc)로.
    assert 'pcExchangeCopy("pc-exchange-no-pc", PC_COPY.noPcFallback)' in js
    assert "PC_COPY.connect" in js
    # 확인 실패(null)는 조용히 머문다 — 추측 안내는 두 번째 거짓말이다.
    assert "else if (linked === false) {" in js
    # HTML 기본값도 숨김이다: 확인 전까지 아무것도 내밀지 않는다.
    assert 'id="clawWebXlsxPcPick" hidden' in _read(INDEX_HTML)


# ── 행위 헤널스: 실제 모듈을 실행해 네트워크 모양을 증명한다 ────────────────

_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");

const SOURCES = fs.readFileSync(process.argv[2], "utf8");
const TUSLIB = fs.readFileSync(process.argv[3], "utf8");
const SCENE = process.argv[4] || "linked";

const XLSX_BYTES_SMALL = Uint8Array.from([0x50, 0x4b, 0x03, 0x04, 0x00, 0x00]);
// >10MB — the quote form's own split point sends it through the shared tus lane.
const BIG = new Uint8Array(10000001);
BIG[0] = 0x50; BIG[1] = 0x4b;

function makeEl(tag) {
  const el = {
    tagName: tag, id: "", className: "", textContent: "", hidden: false, open: false,
    disabled: false, value: "", children: [], listeners: {}, dataset: {},
    style: {}, files: [], parentNode: null, accept: "",
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
  };
  el.setAttribute = (k, v) => { el[k] = String(v); };
  el.getAttribute = (k) => (k in el ? el[k] : null);
  el.removeAttribute = (k) => { delete el[k]; };
  el.appendChild = (c) => { el.children.push(c); c.parentNode = el; return c; };
  el.append = (...cs) => cs.forEach((c) => el.appendChild(c));
  el.replaceChildren = (...cs) => { el.children = []; cs.forEach((c) => el.appendChild(c)); };
  el.removeChild = (node) => { el.children = el.children.filter((c) => c !== node); return node; };
  el.addEventListener = (t, fn) => { (el.listeners[t] = el.listeners[t] || []).push(fn); };
  el.querySelector = () => null;
  el.querySelectorAll = () => [];
  el.focus = () => {};
  el.blur = () => {};
  el.scrollIntoView = () => {};
  el.click = () => (el.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, target: el }));
  return el;
}

const byId = {};
function add(id, tag) { const e = makeEl(tag); e.id = id; byId[id] = e; return e; }
[
  "clawWebOfficeDetails", "clawWebXlsxInput", "clawWebXlsxPcPick", "clawWebXlsxPcNote",
  "clawWebXlsxSave", "clawWebXlsxRefresh", "clawWebXlsxNotice", "clawWebXlsxList",
  "clawWebXlsxP01Panel", "clawWebXlsxP01Selected", "clawWebXlsxP01Status",
  "clawWebXlsxP01Refresh", "clawWebXlsxP01Start", "clawWebXlsxP01Approve",
  "clawWebXlsxP01Deny",
].forEach((id) => add(id, /Input/.test(id) ? "input" : "div"));
// index.html의 두 노드는 기본 hidden이다 — 시로도 언제나 그 모양에서 시작한다.
byId.clawWebXlsxPcPick.hidden = true;
byId.clawWebXlsxPcNote.hidden = true;
byId.clawWebOfficeDetails.appendChild(byId.clawWebXlsxInput);
byId.clawWebOfficeDetails.appendChild(byId.clawWebXlsxPcPick);
byId.clawWebOfficeDetails.appendChild(byId.clawWebXlsxSave);
byId.clawWebOfficeDetails.open = false;

const doc = {
  documentElement: { lang: "ko" },
  body: makeEl("body"),
  head: makeEl("head"),
  activeElement: null,
  getElementById: (id) => byId[id] || null,
  querySelector: () => null,
  querySelectorAll: () => [],
  createElement: (tag) => makeEl(tag),
  addEventListener() {},
};

const XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const requests = [];
const tusCreates = [];
const tusPatches = [];
let pcFileFetches = [];
let pairingsAnswer = SCENE === "notLinked"
  ? { status: 200, links: [] }
  : { status: 200, links: [{ state: "active" }] };
let pcFileAnswer = { status: 200, bytes: BIG };
const uploads = new Map();
let uploadSeq = 0;
let listed = 0;

function headerMap(values) {
  const lower = {};
  Object.keys(values || {}).forEach((k) => { lower[String(k).toLowerCase()] = String(values[k]); });
  return { get: (k) => (Object.prototype.hasOwnProperty.call(lower, String(k).toLowerCase())
    ? lower[String(k).toLowerCase()] : null) };
}
function decodeMetadata(raw) {
  const out = {};
  String(raw || "").split(",").forEach((pair) => {
    const at = pair.indexOf(" ");
    if (at < 0) return;
    out[pair.slice(0, at)] = Buffer.from(pair.slice(at + 1), "base64").toString("utf8");
  });
  return out;
}
function bodyBytes(body) {
  if (!body) return 0;
  if (body._bytes) return body._bytes.length;
  if (typeof body.length === "number") return body.length;
  return 0;
}

async function fetchImpl(url, opts) {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  const u = String(url);
  requests.push({ url: u, method });
  if (u.startsWith("/api/pc/pairings")) {
    return { ok: pairingsAnswer.status < 400, status: pairingsAnswer.status,
      json: async () => ({ links: pairingsAnswer.links }) };
  }
  if (u.startsWith("/api/pc/file")) {
    pcFileFetches.push(u);
    if (pcFileAnswer.status !== 200) {
      return { ok: false, status: pcFileAnswer.status, json: async () => ({ error: { code: "not_found" } }) };
    }
    return { ok: true, status: 200,
      blob: async () => ({ _bytes: pcFileAnswer.bytes }) };
  }
  if (method === "GET" && u === "/api/claw/office/web-sources") {
    listed += 1;
    return { ok: true, status: 200, json: async () => ({
      ok: true, contract_version: "claw-web-xlsx-source.v1", source: "browser_upload",
      read_authorized_for_processing: false, requires_p01_for_processing: true,
      files: [] }) };
  }
  if (method === "OPTIONS" && /\/tus$/.test(u)) {
    return { ok: true, status: 204, json: async () => ({}),
      headers: headerMap({ "tus-max-size": "1073741824", "x-padiem-tus-chunk-max": "94371840" }) };
  }
  if (method === "POST" && /\/tus$/.test(u)) {
    const meta = decodeMetadata(opts.headers && opts.headers["Upload-Metadata"]);
    const length = Number(opts.headers && opts.headers["Upload-Length"]);
    const location = "/api/claw/office/web-sources/tus/stub-" + (++uploadSeq);
    tusCreates.push({ length, filename: meta.filename, media_type: meta.filetype });
    uploads.set(location, { offset: 0, total: length });
    return { ok: true, status: 201, json: async () => ({ upload_id: "stub-" + uploadSeq }),
      headers: headerMap({ location }) };
  }
  if (method === "PATCH" && /\/tus\//.test(u)) {
    const state = uploads.get(String(u).replace(/^[a-z]+:\/\/[^/]+/i, ""));
    const bytes = bodyBytes(opts.body);
    if (state) state.offset += bytes;
    tusPatches.push({ offset: Number(opts.headers["Upload-Offset"]), bytes });
    return { ok: true, status: 204, json: async () => ({}),
      headers: headerMap({ "upload-offset": String(state ? state.offset : 0) }) };
  }
  if (method === "HEAD" && /\/tus\//.test(u)) {
    const state = uploads.get(String(u).replace(/^[a-z]+:\/\/[^/]+/i, ""));
    return { ok: true, status: 200, json: async () => ({}),
      headers: headerMap({ "upload-offset": String(state ? state.offset : 0) }) };
  }
  if (method === "POST" && u === "/api/claw/office/web-sources") {
    const bytes = bodyBytes(opts.body);
    return { ok: true, status: 201, json: async () => ({
      ok: true, processing_started: false, p01_approved: false, drive_uploaded: false,
      file: { document_id: "doc_" + "0".repeat(32), filename: "가져온양식.xlsx",
        size_bytes: bytes, source_sha256: "0".repeat(64), original_immutable: true,
        processing_authorized: false } }) };
  }
  return { ok: false, status: 404, json: async () => ({}) };
}

function makeFile(name, bytes) {
  return {
    name, type: XLSX_MEDIA, size: bytes.length, _bytes: bytes,
    slice(start, end) {
      const from = start || 0;
      const to = end === undefined ? bytes.length : Math.min(end, bytes.length);
      return { length: Math.max(0, to - from), _bytes: bytes.slice(from, to) };
    },
  };
}

const pcPicks = [];
const exchange = {
  open(settings) {
    pcPicks.push({ mode: settings.mode, hasOnSelect: typeof settings.onSelect === "function" });
    if (SCENE === "filter") settings.onSelect({ fileId: "d-2", name: "메모.pdf", folder: "." });
    else if (SCENE === "foreign") {
      // 다른 계정의 dispatch는 서버가 404로 흩어낸다(소유권 계약).
      pcFileAnswer = { status: 404, bytes: new Uint8Array(0) };
      settings.onSelect({ fileId: "foreign-dispatch", name: "가져온양식.xlsx", folder: "." });
    }
    else settings.onSelect({ fileId: "d-1", name: "견적양식.xlsx", folder: "." });
  },
};

const window = {
  document: doc,
  fetch: fetchImpl,
  File: class { constructor(parts, name, opts) { const p = parts[0] || {}; this.name = name;
    this.type = (opts && opts.type) || ""; this._bytes = p._bytes || new Uint8Array(0);
    this.size = this._bytes.length;
    this.slice = (s, e) => { const from = s || 0; const to = e === undefined
      ? this._bytes.length : Math.min(e, this._bytes.length);
      return { length: Math.max(0, to - from), _bytes: this._bytes.slice(from, to) }; }; } },
  PadiemPcFileExchange: exchange,
};
window.window = window;
const context = vm.createContext({ window, document: doc, fetch: fetchImpl, setTimeout, clearTimeout,
  setInterval, clearInterval, URLSearchParams, URL, console, Buffer, TextEncoder, btoa, atob,
  module: { exports: {} } });
context.globalThis = context;

(async () => {
  vm.runInContext(TUSLIB, context);
  vm.runInContext(SOURCES, context);
  const pause = (ms) => new Promise((r) => setTimeout(r, ms));
  const waitUntil = async (check, ms) => {
    for (let waited = 0; waited < ms; waited += 10) {
      if (check()) return true;
      await pause(10);
    }
    return check();
  };

  if (SCENE === "linked" || SCENE === "filter" || SCENE === "foreign") {
    // 연결 확인이 끝나 단추가 내려오는지부터 확인한다.
    await waitUntil(() => byId.clawWebXlsxPcPick.hidden === false, 2000);
    const pickVisible = byId.clawWebXlsxPcPick.hidden === false && byId.clawWebXlsxPcNote.hidden === true;
    const beforeFetches = pcFileFetches.length;
    const beforeCreates = tusCreates.length;

    // 단추 클릭이 공용 부품을 import 반쪽으로 연다.
    (byId.clawWebXlsxPcPick.listeners.click || []).forEach((fn) => fn({ preventDefault() {} }));
    await pause(30);
    const opened = pcPicks.length === 1 && pcPicks[0].mode === "import" && pcPicks[0].hasOnSelect;

    if (SCENE === "filter") {
      await waitUntil(() => byId.clawWebXlsxNotice.textContent.includes("엑셀 양식"), 2000);
      return {
        ok: opened && pickVisible,
        pickVisible, opened,
        pcFileFetches: pcFileFetches.length - beforeFetches,
        tusCreates: tusCreates.length - beforeCreates,
        notice: byId.clawWebXlsxNotice.textContent,
      };
    }
    if (SCENE === "foreign") {
      const done = await waitUntil(() =>
        byId.clawWebXlsxNotice.textContent.includes("PC에서 가져온 파일"), 2000);
      return {
        ok: done && pcFileFetches.length - beforeFetches === 1
          && tusCreates.length - beforeCreates === 0,
        pickVisible, opened, notice: byId.clawWebXlsxNotice.textContent,
        pcFileFetches: pcFileFetches.length - beforeFetches,
        tusCreates: tusCreates.length - beforeCreates,
      };
    }
    // linked: PC 파일이 기존 흐름으로 이어진다 — pc/file 1회 + tus create·patch,
    // 그리고 저장 뒤 목록 재조회까지( 실패 문구가 끝이 아님을 증명한다).
    const finished = await waitUntil(() =>
      tusCreates.length - beforeCreates >= 1 && listed >= 1, 5000);
    const create = tusCreates[tusCreates.length - 1] || {};
    const patchedBytes = tusPatches.reduce((sum, p) => sum + p.bytes, 0);
    const notice = byId.clawWebXlsxNotice.textContent;
    return {
      ok: finished && opened && pickVisible,
      pickVisible, opened,
      pcFileFetches: pcFileFetches.length - beforeFetches,
      tusCreates: tusCreates.length - beforeCreates,
      tusLength: create.length, tusFilename: create.filename, tusMediaType: create.media_type,
      patchedBytes, listed,
      noFailureNotice: !notice.includes("실패했습니다") && !notice.includes("하지 못했습니다"),
      notice,
      inputStillEnabled: byId.clawWebXlsxInput.disabled === false,
    };
  }

  if (SCENE === "notLinked") {
    // 연결 확인이 끝나 안내가 채워질 때까지 기다린다(자식 노드가 붙는 순간).
    const settled = await waitUntil(() => byId.clawWebXlsxPcNote.children.length >= 1, 2000);
    return {
      ok: settled && byId.clawWebXlsxPcPick.hidden === true && byId.clawWebXlsxPcNote.hidden === false,
      pickHidden: byId.clawWebXlsxPcPick.hidden,
      noteShown: byId.clawWebXlsxPcNote.hidden === false,
      noteText: (byId.clawWebXlsxPcNote.children[0] || {}).textContent || "",
      connectText: (byId.clawWebXlsxPcNote.children[1] || {}).textContent || "",
      directPickerIntact: byId.clawWebXlsxInput.disabled === false
        && byId.clawWebXlsxSave.disabled === false
        && byId.clawWebXlsxInput.parentNode === byId.clawWebOfficeDetails,
    };
  }
  return { ok: false, error: "unknown scene" };
})().then((payload) => { console.log(JSON.stringify(payload)); })
  .catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); });
"""


@lru_cache(maxsize=None)
def _run_scene(scene: str) -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_quote_pc_import_harness.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness_path), str(SOURCES_JS), str(STATIC / "tus-upload.js"), scene],
            capture_output=True, text=True, timeout=60,
        )
    finally:
        harness_path.unlink(missing_ok=True)
    assert result.returncode == 0, f"harness exited {result.returncode}: {result.stderr}"
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
    return json.loads(line)


def test_linked_pc_import_rides_the_existing_tus_flow() -> None:
    payload = _run_scene("linked")
    assert payload.get("ok") is True, payload
    assert payload["opened"] is True and payload["pickVisible"] is True
    # PC 파일 바이트는 pc/file로 한 번 읽힌다.
    assert payload["pcFileFetches"] == 1
    # 기존 양식 업로드 경로(이제 tus)로 그대로 넘어간다: 길이·이름·미디어 타입.
    assert payload["tusCreates"] == 1
    assert payload["tusLength"] == 10000001
    assert payload["tusFilename"] == "견적양식.xlsx"
    assert payload["tusMediaType"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert payload["patchedBytes"] == 10000001
    # 저장 뒤 목록 재조회까지 끝났고 실패 문구는 없다.
    assert payload["listed"] == 1
    assert payload["noFailureNotice"] is True
    assert payload["inputStillEnabled"] is True


def test_non_excel_pick_is_refused_before_any_byte_moves() -> None:
    payload = _run_scene("filter")
    assert payload.get("ok") is True, payload
    assert payload["opened"] is True
    assert payload["pcFileFetches"] == 0
    assert payload["tusCreates"] == 0
    assert "엑셀 양식(.xlsx·.xls·.xlsm)" in payload["notice"]


def test_foreign_account_pc_file_is_refused_without_an_upload() -> None:
    payload = _run_scene("foreign")
    assert payload.get("ok") is True, payload
    assert payload["pcFileFetches"] == 1  # 읽기는 시도되지만
    assert payload["tusCreates"] == 0     # 거부되면 업로드는 없다
    assert "PC에서 가져온 파일" in payload["notice"]


def test_unlinked_owner_keeps_the_direct_picker_and_gets_the_shared_words() -> None:
    payload = _run_scene("notLinked")
    assert payload.get("ok") is True, payload
    assert payload["pickHidden"] is True
    assert payload["noteShown"] is True
    assert "아직 연결된 PC가 없어요" in payload["noteText"]
    assert payload["connectText"] == "이 PC 연결"
    assert payload["directPickerIntact"] is True
