"""B54 Claw run-history copy truthfulness (#2773).

The historical artifact action itself is truthful: one bounded download of the
generated document through the route that already exists. The *copy* around it
was not — the English tagline told the owner they could "reopen the document",
and the Korean tagline said the same thing less explicitly, while the surface
only ever downloads the document again.

This contract is narrow on purpose: every `claw-runs-*` string in both
languages must describe a review of the result summary plus a download, and
must never claim an open / reopen / preview capability that B54 does not ship.

The tagline is rendered by the shared locale module from the shipped table (the
app never writes it), so a language switch cannot restore a claim unless the
shipped table contains one. The behavioral harness proves that: it resolves the
tagline through the same table for each language, and measures the one document
action the run-history card offers.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
INDEX_HTML = ROOT / "static/index.html"
LOCALE_JS = ROOT / "static/locale.js"

TAGLINE_KEY = "claw-runs-tagline"
DOWNLOAD_KEY = "claw-runs-download"
ARTIFACT_ID = "doc_" + "a" * 32

RUN_HISTORY_KEYS = (
    "claw-runs-kicker",
    "claw-runs-title",
    "claw-runs-tagline",
    "claw-runs-loading",
    "claw-runs-empty",
    "claw-runs-error",
    "claw-runs-download",
    "claw-runs-status-completed",
)

# Copy claiming the historical document can be opened, reopened or previewed.
OPEN_CLAIM = re.compile(r"reopen|re-open|open the|open document|preview|열기|열어|열람|다시 열")
# Copy that truthfully describes what the surface can do with a past document.
DOWNLOAD_CLAIM = re.compile(r"다운로드|download", re.IGNORECASE)
# Action labels may say either "download" or "receive again" in Korean; both
# describe delivery of the file, and neither may claim it is opened.
DOWNLOAD_MEANING = re.compile(r"다운로드|받기|download", re.IGNORECASE)


def _locale_source() -> str:
    return LOCALE_JS.read_text(encoding="utf-8")


def _locale_table() -> dict[str, dict[str, str]]:
    """Parse the shipped KO/EN copy out of locale.js.

    The harness resolves the tagline from THESE strings, so shipped copy and
    asserted copy cannot drift apart.
    """
    source = _locale_source()
    pattern = re.compile(r'"([A-Za-z0-9_\-]+)":\s*"((?:[^"\\]|\\.)*)"')

    def unescape(value: str) -> str:
        return value.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")

    assert "en: {" in source
    ko_part, en_part = source.split("en: {", 1)
    table = {
        "ko": {key: unescape(value) for key, value in pattern.findall(ko_part)},
        "en": {key: unescape(value) for key, value in pattern.findall(en_part)},
    }
    assert table["ko"] and table["en"]
    return table


def _tagline_fallback() -> str:
    index = INDEX_HTML.read_text(encoding="utf-8")
    marker = f'data-locale-key="{TAGLINE_KEY}">'
    assert marker in index
    return index.split(marker, 1)[1].split("</p>", 1)[0]


# ── static copy contracts ──────────────────────────────────────────────────


def test_no_run_history_copy_claims_opening_or_previewing() -> None:
    table = _locale_table()
    for language in ("ko", "en"):
        for key in RUN_HISTORY_KEYS:
            copy = table[language][key]
            assert not OPEN_CLAIM.search(copy), f"{language}/{key}: {copy}"


def test_both_taglines_describe_downloading_a_past_document() -> None:
    table = _locale_table()
    for language in ("ko", "en"):
        copy = table[language][TAGLINE_KEY]
        assert DOWNLOAD_CLAIM.search(copy), copy
        assert not OPEN_CLAIM.search(copy), copy
    # EN must say it is a *re*-download, not a first-time delivery.
    assert re.search(r"download .*again", table["en"][TAGLINE_KEY]), table["en"][TAGLINE_KEY]
    assert "다시 다운로드" in table["ko"][TAGLINE_KEY], table["ko"][TAGLINE_KEY]


def test_taglines_state_the_same_three_facts_in_both_languages() -> None:
    table = _locale_table()
    facts = {
        "ko": ("실제 실행", "요약", "문서", "다운로드"),
        "en": ("real executions", "summary", "document", "download"),
    }
    for language, tokens in facts.items():
        copy = table[language][TAGLINE_KEY]
        for token in tokens:
            assert token in copy, f"{language} tagline is missing {token!r}: {copy}"


def test_markup_fallback_matches_the_shipped_korean_copy() -> None:
    assert _tagline_fallback() == _locale_table()["ko"][TAGLINE_KEY]


def test_the_tagline_is_locale_owned_so_a_switch_cannot_restore_a_claim() -> None:
    index = INDEX_HTML.read_text(encoding="utf-8")
    # The tagline is bound to the locale table, not written by app logic.
    assert f'data-locale-key="{TAGLINE_KEY}"' in index
    app = APP_JS.read_text(encoding="utf-8")
    assert TAGLINE_KEY not in app
    # Both languages must declare it, so each renders its own truthful value.
    table = _locale_table()
    assert TAGLINE_KEY in table["ko"] and TAGLINE_KEY in table["en"]


def test_historical_artifact_action_stays_one_bounded_download() -> None:
    app = APP_JS.read_text(encoding="utf-8")
    table = _locale_table()
    # The label of the one historical document action offers the file again, in
    # KO and EN, and never claims to open it. (The KO label is deliberately
    # "문서 다시 받기": receiving the file again, which is what happens.)
    assert DOWNLOAD_MEANING.search(table["ko"][DOWNLOAD_KEY]), table["ko"][DOWNLOAD_KEY]
    assert DOWNLOAD_MEANING.search(table["en"][DOWNLOAD_KEY]), table["en"][DOWNLOAD_KEY]
    assert "다시" in table["ko"][DOWNLOAD_KEY] and "again" in table["en"][DOWNLOAD_KEY]
    assert not OPEN_CLAIM.search(table["ko"][DOWNLOAD_KEY]) and not OPEN_CLAIM.search(table["en"][DOWNLOAD_KEY])
    # Ownership did not widen: one route string and one download owner, with the
    # active result action, historical card, and validated Calendar link-back.
    assert app.count("/api/claw/manual-intake/artifact/") == 1
    assert app.count("function downloadClawArtifact(") == 1
    assert len(re.findall(r"(?<!function )\bdownloadClawArtifact\(", app)) == 3
    # The card builds exactly one button per artifact and no second control.
    card_block = app.split("claw-run-card-artifact", 1)[1].split("function fetchClawRunHistory", 1)[0]
    assert card_block.count("createElement(\"button\")") == 1
    assert "claw-run-card-download" in card_block
    assert not re.search(r"open|preview|reopen", card_block, re.IGNORECASE)


# ── behavioral proof via Node harness executing real app.js ─────────────────

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const APP = fs.readFileSync(process.argv[2], "utf8");
const COPY = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const INDEX = fs.readFileSync(process.argv[4], "utf8");
const ARTIFACT = process.argv[5];

const declaredIds = [];
{
  const tagRe = /<([a-zA-Z0-9-]+)([^>]*)>/g;
  let m;
  while ((m = tagRe.exec(INDEX)) !== null) {
    const idMatch = /\sid="([^"]+)"/.exec(m[2]);
    if (idMatch && declaredIds.indexOf(idMatch[1]) < 0) declaredIds.push(idMatch[1]);
  }
}

function makeEl(tag) {
  const el = {
    tagName: tag, id: "", className: "", textContent: "", hidden: false,
    disabled: false, value: "", children: [], listeners: {}, dataset: {},
    style: {}, scrollTop: 0, scrollHeight: 0, clientHeight: 0,
    options: [], selectedIndex: 0, files: [], parentNode: null,
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
  };
  el.setAttribute = (k, v) => { el[k] = String(v); };
  el.getAttribute = (k) => (k in el ? el[k] : null);
  el.removeAttribute = (k) => { delete el[k]; };
  el.appendChild = (c) => { el.children.push(c); c.parentNode = el; return c; };
  el.prepend = (...cs) => cs.forEach((c) => { el.children.unshift(c); c.parentNode = el; });
  el.append = (...cs) => cs.forEach((c) => el.appendChild(c));
  el.replaceChildren = (...cs) => { el.children = []; cs.forEach((c) => el.appendChild(c)); };
  el.remove = () => { if (el.parentNode) el.parentNode.children = el.parentNode.children.filter((c) => c !== el); };
  el.addEventListener = (t, fn) => { (el.listeners[t] = el.listeners[t] || []).push(fn); };
  el.querySelector = (sel) => el.children.find((c) => c.className && c.className.includes(sel.replace(/^\./, ""))) || null;
  el.querySelectorAll = (sel) => (sel && sel.indexOf("claw-chip") >= 0 ? [] : el.children);
  el.focus = () => { doc.activeElement = el; };
  el.blur = () => { if (doc.activeElement === el) doc.activeElement = null; };
  el.scrollIntoView = () => {};
  el.click = () => (el.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, target: el, key: "" }));
  el.requestSubmit = () => (el.listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
  el.matches = () => false;
  return el;
}

const byId = {};
function add(id, tag) { const e = makeEl(tag); e.id = id; byId[id] = e; return e; }
declaredIds.forEach((id) => add(id, "div"));
byId.projectForm.querySelector = () => makeEl("div");

let lang = "ko";
const shim = {
  document: null, fetch: null, console,
  AbortController: class { constructor() { this.signal = {}; } abort() {} },
  URL: { createObjectURL: () => "blob:x", revokeObjectURL() {}, revokeURL() {} },
  setTimeout, clearTimeout, setInterval, clearInterval,
  CustomEvent: class {},
  location: { href: "http://localhost/", assign() {} },
  addEventListener() {},
  __padiemLocale: { text: (key) => (COPY[lang] || COPY.ko)[key] || key },
  PadiemChatLifecycle: { states: { IDLE: "idle", STREAMING: "streaming", COMPLETED: "completed", FAILED: "failed", CANCELLED: "cancelled", TIMED_OUT: "timed_out" }, set() {} },
  PadiemConfirmDialog: { confirm: async () => true },
  PadiemChatTransport: { requestCompleted: async () => ({}), requestStreaming: async () => ({}), readSseEvents: async () => {}, errorFor: () => new Error("x") },
  PadiemChatConversationState: { reset() {}, setConversationId() {}, getConversationId() { return null; }, outboundWithUser: () => [], commitAssistant() {}, setSkill() {}, getSkill: () => "auto" },
  PadiemAttachmentCapabilities: {
    limits: { imageBytes: 4194304, textBytes: 98304, textChars: 40000 },
    images: [{ mediaTypes: ["image/jpeg", "image/png", "image/webp"] }],
    textDocuments: [{ mediaTypes: ["text/plain"], extensions: [".txt"] }],
    copy: () => ({ idleNote: "idle", unsupportedFormat: "unsupported", textTooLarge: "too large" }),
  },
  PadiemBinaryDocuments: null,
};
shim.window = shim;

const requests = [];
const anchors = [];
function jsonResponse(status, obj) {
  return { ok: status >= 200 && status < 300, status, json: async () => obj };
}
const RUN = {
  run_id: "run_1", channel: "kakao", action: "quote_draft", title: "[KAKAO] quote_draft: A업체",
  status: "completed", created_at: "2026-09-19T01:00:00Z", updated_at: "2026-09-19T01:00:00Z",
  result_summary: "견적 요약",
  artifact: { document_id: ARTIFACT, filename: "quote.docx", media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" },
};

async function fetchImpl(url, opts) {
  opts = opts || {};
  requests.push({ url: String(url), method: (opts.method || "GET").toUpperCase() });
  const u = String(url);
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, { ready: true, authenticated: true, user: { name: "owner" }, history_ready: false, project_files_ready: false });
  if (u.startsWith("/api/projects")) return jsonResponse(200, { projects: [] });
  if (u.startsWith("/api/conversations")) return jsonResponse(200, { conversations: [] });
  if (u.startsWith("/api/claw/inbox/")) return jsonResponse(200, { ok: true, kind: "tasks", items: [], limit: 20 });
  if (u.startsWith("/api/claw/memory")) return jsonResponse(200, { ok: true, memories: [] });
  if (u.startsWith("/api/claw/runs")) return jsonResponse(200, { ok: true, runs: [RUN] });
  if (u.startsWith("/api/claw/manual-intake/artifact/")) {
    return { ok: true, status: 200, json: async () => ({}), blob: async () => ({ size: 3, type: "application/octet-stream" }) };
  }
  return jsonResponse(200, {});
}

const shell = add("app-shell", "div");
shell.dataset = { state: "home" };
const accountContainer = add("sidebar-account", "div");
byId.clawChannel.options = [{ textContent: "KakaoTalk" }];
byId.clawChannel.value = "kakao";
byId.clawAction.options = [{ textContent: "quote" }];
byId.clawAction.value = "quote";
byId.clawRunHistory.hidden = true;
byId.clawResultCard.hidden = true;

const doc = {
  documentElement: { lang: "ko", classList: { add() {}, remove() {}, contains() { return false; } } },
  body: makeEl("body"),
  activeElement: null,
  getElementById: (id) => byId[id] || null,
  querySelector: (sel) => (sel === ".app-shell" ? shell : sel === ".sidebar-account" ? accountContainer : null),
  querySelectorAll: () => [],
  createElement: (tag) => {
    const el = makeEl(tag);
    if (tag === "a") el.click = () => anchors.push({ href: el.href, download: el.download });
    return el;
  },
  addEventListener() {},
};
shim.document = doc;
shim.fetch = fetchImpl;

vm.createContext(shim);
vm.runInContext(APP, shim, { filename: "app.js" });

function walk(root, out) {
  out = out || [];
  (root.children || []).forEach((c) => { out.push(c); walk(c, out); });
  return out;
}
function buttons(root) { return walk(root).filter((el) => String(el.tagName).toUpperCase() === "BUTTON"); }
function texts(root) { return walk(root).map((el) => String(el.textContent || "")).join(" "); }

(async () => {
  const checks = {};
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, checks, requests })); process.exit(0); };
  process.on("unhandledRejection", (e) => { console.log(JSON.stringify({ ok: false, error: "unhandledRejection " + String((e && e.stack) || e) })); process.exit(0); });
  process.on("uncaughtException", (e) => { console.log(JSON.stringify({ ok: false, error: "uncaughtException " + String((e && e.stack) || e) })); process.exit(0); });
  const tick = (ms) => new Promise((r) => setTimeout(r, ms));
  const openClaim = (s) => /(?:reopen|re-open|open the|open document|preview|열기|열어|열람|다시 열)/i.test(String(s));
  const downloadClaim = (s) => /(?:다운로드|download)/i.test(String(s));
  // Action labels may say "download" or "receive again" in Korean.
  const downloadMeaning = (s) => /(?:다운로드|받기|download)/i.test(String(s));
  const artifactGets = () => requests.filter((r) => r.url.indexOf("/api/claw/manual-intake/artifact/") === 0);

  await tick(40);
  byId.clawNavButton.click();
  await tick(60);
  if (shell.dataset.state !== "claw") fail("CLAW_WORKSPACE_OPEN");
  if (byId.clawRunHistory.hidden !== false) fail("RUN_HISTORY_VISIBLE");

  // The tagline is resolved the way the shipped locale module resolves it, for
  // each language the owner can switch to.
  const tagline = () => (COPY[lang] || COPY.ko)["claw-runs-tagline"] || "";
  checks.TAGLINE_TRUTHFUL_IN_KO = downloadClaim(tagline()) && !openClaim(tagline());
  if (!checks.TAGLINE_TRUTHFUL_IN_KO) fail("TAGLINE_TRUTHFUL_IN_KO: " + tagline());
  lang = "en";
  checks.LOCALE_SWITCH_TO_EN_KEEPS_COPY_TRUTHFUL = downloadClaim(tagline()) && !openClaim(tagline());
  if (!checks.LOCALE_SWITCH_TO_EN_KEEPS_COPY_TRUTHFUL) fail("LOCALE_SWITCH_TO_EN_KEEPS_COPY_TRUTHFUL: " + tagline());
  lang = "ko";
  checks.LOCALE_SWITCH_BACK_CANNOT_RESTORE_A_CLAIM = downloadClaim(tagline()) && !openClaim(tagline());
  if (!checks.LOCALE_SWITCH_BACK_CANNOT_RESTORE_A_CLAIM) fail("LOCALE_SWITCH_BACK_CANNOT_RESTORE_A_CLAIM: " + tagline());

  // No run-history string the harness can resolve claims an open capability.
  // #2916 ships exactly one session-open action: claw-runs-open-session may
  // name it; document open/preview claims stay forbidden for every key.
  const SESSION_OPEN_KEY = "claw-runs-open-session";
  const offendingKeys = Object.keys(COPY.ko)
    .filter((key) => key.indexOf("claw-runs-") === 0)
    .filter((key) => key !== SESSION_OPEN_KEY)
    .filter((key) => openClaim(COPY.ko[key]) || openClaim(COPY.en[key]));
  checks.NO_RUN_HISTORY_KEY_CLAIMS_OPENING = offendingKeys.length === 0;
  if (!checks.NO_RUN_HISTORY_KEY_CLAIMS_OPENING) fail("NO_RUN_HISTORY_KEY_CLAIMS_OPENING: " + JSON.stringify(offendingKeys));

  // The card offers exactly one document action, and it downloads.
  const cardText = texts(byId.clawRunHistoryList);
  const cardButtons = buttons(byId.clawRunHistoryList);
  checks.HISTORICAL_CARD_HAS_ONE_DOCUMENT_ACTION =
    cardButtons.length === 1 &&
    downloadMeaning(cardButtons[0].textContent) &&
    !openClaim(cardButtons[0].textContent);
  if (!checks.HISTORICAL_CARD_HAS_ONE_DOCUMENT_ACTION) {
    fail("HISTORICAL_CARD_HAS_ONE_DOCUMENT_ACTION: " + JSON.stringify(cardButtons.map((b) => b.textContent)));
  }
  checks.RENDERED_CARD_MAKES_NO_OPEN_CLAIM = !openClaim(cardText);
  if (!checks.RENDERED_CARD_MAKES_NO_OPEN_CLAIM) fail("RENDERED_CARD_MAKES_NO_OPEN_CLAIM: " + cardText);

  const before = artifactGets().length;
  cardButtons[0].click();
  await tick(40);
  checks.ONE_CLICK_IS_ONE_BOUNDED_DOWNLOAD =
    artifactGets().length === before + 1 &&
    artifactGets()[before].url === "/api/claw/manual-intake/artifact/" + ARTIFACT &&
    anchors.length === 1 && anchors[0].download === "quote.docx";
  if (!checks.ONE_CLICK_IS_ONE_BOUNDED_DOWNLOAD) fail("ONE_CLICK_IS_ONE_BOUNDED_DOWNLOAD: " + JSON.stringify({ gets: artifactGets(), anchors }));

  const allowed = new Set([
    "/api/auth/status", "/api/projects", "/api/conversations", "/api/claw/runs",
    "/api/claw/memory", "/api/claw/inbox/tasks",
    "/api/claw/manual-intake/artifact/" + ARTIFACT,
  ]);
  const extra = Array.from(new Set(requests.map((r) => r.url.split("?")[0]))).filter((u) => !allowed.has(u));
  checks.NO_NEW_ROUTE_TOUCHED = extra.length === 0;
  if (!checks.NO_NEW_ROUTE_TOUCHED) fail("NO_NEW_ROUTE_TOUCHED: " + JSON.stringify(extra));

  console.log(JSON.stringify({ ok: true, checks, requests, anchors, cardText }));
  process.exit(0);
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); process.exit(0); });
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_b54_claw_run_history_copy_harness.js"
    copy_path = ROOT / "tests" / "_b54_claw_run_history_copy.json"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    copy_path.write_text(json.dumps(_locale_table(), ensure_ascii=False), encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness_path), str(APP_JS), str(copy_path), str(INDEX_HTML), ARTIFACT_ID],
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        harness_path.unlink(missing_ok=True)
        copy_path.unlink(missing_ok=True)
    assert result.returncode == 0, f"harness exited {result.returncode}: {result.stderr}"
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
    return json.loads(line)


def test_behavioral_harness_passes() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, f"behavioral harness failed: {payload}"


def test_behavioral_run_history_copy_and_single_download() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    checks = payload["checks"]
    for name in (
        "TAGLINE_TRUTHFUL_IN_KO",
        "LOCALE_SWITCH_TO_EN_KEEPS_COPY_TRUTHFUL",
        "LOCALE_SWITCH_BACK_CANNOT_RESTORE_A_CLAIM",
        "NO_RUN_HISTORY_KEY_CLAIMS_OPENING",
        "HISTORICAL_CARD_HAS_ONE_DOCUMENT_ACTION",
        "RENDERED_CARD_MAKES_NO_OPEN_CLAIM",
        "ONE_CLICK_IS_ONE_BOUNDED_DOWNLOAD",
        "NO_NEW_ROUTE_TOUCHED",
    ):
        assert checks.get(name) is True, name
    # The rendered card carried the run summary and its artifact filename.
    assert "견적 요약" in payload["cardText"] and "quote.docx" in payload["cardText"]
    assert len(payload["anchors"]) == 1


if __name__ == "__main__":
    test_no_run_history_copy_claims_opening_or_previewing()
    test_both_taglines_describe_downloading_a_past_document()
    test_taglines_state_the_same_three_facts_in_both_languages()
    test_markup_fallback_matches_the_shipped_korean_copy()
    test_the_tagline_is_locale_owned_so_a_switch_cannot_restore_a_claim()
    test_historical_artifact_action_stays_one_bounded_download()
    test_behavioral_harness_passes()
    test_behavioral_run_history_copy_and_single_download()
    print("B54_CLAW_RUN_HISTORY_COPY_TRUTHFUL_TESTS=PASS")
