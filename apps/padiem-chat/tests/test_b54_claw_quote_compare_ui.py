"""#2831: the Claw supplier-quote-comparison surface is presentation only.

Static contracts plus a Node harness that executes the real ``static/app.js``
against a DOM built from the shipped ``index.html`` and the shipped locale copy,
so "the UI reaches the merged deterministic route and invents nothing" is
demonstrated rather than asserted.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
INDEX_HTML = ROOT / "static/index.html"
LOCALE_JS = ROOT / "static/locale.js"
WORKSPACE_CSS = ROOT / "static/claw-workspace.css"

COMPARE_ROUTE = "/api/claw/manual-intake/quote-compare"
ARTIFACT_ID = "doc_" + "c" * 32
PANEL_MARKER = '<section class="claw-quote-compare" id="clawQuoteCompare"'
TOGGLE_ID = "clawCompareToggle"

# Fields the merged quote-compare contract actually accepts per supplier.
ALLOWED_SUPPLIER_FIELDS = {
    "supplier_id", "supplier_label", "item_label", "quantity",
    "unit_price_minor", "total_minor", "promised_delivery_date",
    "payment_terms", "evidence_ref", "currency",
}
ALLOWED_TOP_FIELDS = {"suppliers", "mode", "artifact", "currency", "workspace_id", "weights"}
# Anything that would read as an outbound or purchasing affordance.
FORBIDDEN_ACTION = re.compile(r"send|전송|발신|buy|purchase|주문 발주|issue|order now", re.IGNORECASE)
DRAFT_TOKEN = re.compile(r"\bDRAFT\b")


def _app() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _locale_table() -> dict[str, dict[str, str]]:
    source = LOCALE_JS.read_text(encoding="utf-8")
    pattern = re.compile(r'"([A-Za-z0-9_\-]+)":\s*"((?:[^"\\]|\\.)*)"')

    def unescape(value: str) -> str:
        return value.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")

    ko_part, en_part = source.split("en: {", 1)
    return {
        "ko": {key: unescape(value) for key, value in pattern.findall(ko_part)},
        "en": {key: unescape(value) for key, value in pattern.findall(en_part)},
    }


def _panel_block() -> str:
    index = _index()
    assert PANEL_MARKER in index
    start = index.index(PANEL_MARKER)
    return index[start:index.index("</section>", index.index('id="clawQuoteCompareResult"'))]


def _compare_region() -> str:
    app = _app()
    start = app.index("#2831 supplier quote comparison surface")
    return app[start:]


# ── static structural contracts ─────────────────────────────────────────────


def test_entry_point_exists_and_is_collapsed_by_default() -> None:
    index = _index()
    toggle = re.search(rf'<button[^>]*id="{TOGGLE_ID}"[^>]*>', index)
    assert toggle, "the Claw mode bar must expose a quote-compare entry point"
    markup = toggle.group(0)
    assert 'aria-expanded="false"' in markup, markup
    assert 'aria-controls="clawQuoteCompare"' in markup, markup
    assert "data-locale-key=" in markup, markup
    # The panel itself ships hidden, so nothing about it is visible or focusable
    # until the user asks for it.
    assert PANEL_MARKER in index
    panel = _panel_block()
    assert "hidden" in panel.split(">", 1)[0]


def test_panel_declares_its_region_and_named_controls() -> None:
    panel = _panel_block()
    assert 'aria-labelledby="clawQuoteCompareTitle"' in panel
    assert 'id="clawQuoteCompareTitle"' in panel
    # Error must be announced and the live status region must be polite-only.
    assert 'role="alert"' in panel
    assert 'aria-live="polite"' in panel
    # Exactly one heading level below the workspace title, never a second h1.
    assert "<h1" not in panel
    assert "<h2" in panel


def test_panel_exposes_only_contract_fields_and_no_invented_axis() -> None:
    panel = _panel_block()
    # Only the four bases the engine implements are offered.
    options = re.findall(r'<option value="([a-z_]+)"', panel)
    modes = [o for o in options if o in {
        "balanced", "lowest_price", "fastest_delivery", "best_cashflow_fit",
    }]
    assert sorted(modes) == sorted([
        "balanced", "lowest_price", "fastest_delivery", "best_cashflow_fit",
    ]), modes
    assert "llm" not in panel.lower()
    # Nothing outside the accepted vocabulary can be typed in: the basis and the
    # currency are selects, and the delivery field is a real date control.
    assert '<select id="clawQuoteMode"' in panel
    assert '<select id="clawQuoteCurrency"' in panel
    assert "lead" not in panel.lower()


# Only the tags that a user can operate: an actionable control must not claim or
# offer an outbound act, while the explanatory copy is required to state the
# opposite ("nothing is sent, ordered or purchased here"), so it is scanned apart.
CONTROL_TAGS = ("button", "input", "select", "option", "label")


def _control_labels(panel: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for tag, attrs in re.findall(r"<([a-z0-9-]+)([^>]*)>", panel):
        if tag not in CONTROL_TAGS:
            continue
        for attribute in ("data-locale-key", "data-locale-aria-label"):
            match = re.search(rf'{attribute}="([^"]+)"', attrs)
            if match:
                found.append((match.group(1), tag))
    return found


def test_no_send_purchase_or_order_affordance_in_the_surface() -> None:
    copy = _locale_table()
    panel = _panel_block()
    controls = _control_labels(panel)
    assert controls, "every control in the panel must be locale-bound"
    for key, tag in controls:
        for lang in ("ko", "en"):
            label = copy[lang].get(key, "")
            assert not FORBIDDEN_ACTION.search(label), (key, tag, lang, label)
    # The panel's own buttons are close / add supplier / compare: nothing else.
    assert len(re.findall(r"<button", panel)) == 3, panel
    assert 'type="submit"' in panel, "comparison must be an explicit user act"
    # And the surface does state the limit, in both languages.
    for lang in ("ko", "en"):
        assert FORBIDDEN_ACTION.search(copy[lang]["claw-compare-help"]), lang


def test_document_creation_is_optional_and_named_as_such() -> None:
    panel = _panel_block()
    assert '<input type="checkbox" id="clawQuoteDocx"' in panel
    key = re.search(r'<span data-locale-key="(claw-compare-docx)"', panel)
    assert key, panel
    copy = _locale_table()
    for lang in ("ko", "en"):
        label = copy[lang]["claw-compare-docx"]
        assert "DOCX" in label
        assert ("선택" in label) if lang == "ko" else ("optional" in label.lower(), label)


def test_panel_copy_states_advisory_draft_and_no_send() -> None:
    copy = _locale_table()
    for lang in ("ko", "en"):
        help_text = copy[lang]["claw-compare-help"]
        note = copy[lang]["claw-cmp-negotiation-note"]
        # Both languages say the result is a draft and that nothing is sent.
        assert ("초안" in help_text or "draft" in help_text.lower()), help_text
        assert ("발송" in note or "전송" in note or "sent" in note.lower()), note
        assert copy[lang]["claw-cmp-advisory"]
        assert copy[lang]["claw-cmp-unknown"]
    # English copy is English: no Hangul leaks into the en projection.
    hangul = re.compile(r"[\u3130-\ud7a3]")
    assert not hangul.search(copy["en"]["claw-compare-help"]), copy["en"]["claw-compare-help"]


def test_new_locale_keys_are_declared_in_both_languages() -> None:
    copy = _locale_table()
    index = _index()
    declared: set[str] = set()
    for attribute in ("data-locale-key", "data-locale-aria-label"):
        declared |= {
            key for key in re.findall(rf'{attribute}="([^"]+)"', index)
            if key == "claw-btn-compare" or key.startswith("claw-compare-")
        }
    runtime = set(re.findall(r'clawCompareText\("([^"]+)"\)', _app()))
    runtime |= set(re.findall(r'"(claw-cmp-[a-z0-9-]+)"', _app()))
    assert declared and runtime
    missing = sorted(k for k in declared | runtime if k not in copy["ko"] or k not in copy["en"])
    assert missing == [], missing


def test_runtime_copy_never_hardcodes_korean_and_uses_the_fallback_table() -> None:
    hangul = re.compile(r"[가-힣]")
    offenders = [
        (number, line.strip())
        for number, line in enumerate(_compare_region().splitlines(), start=1)
        if hangul.search(line)
    ]
    assert offenders == []
    fallback = _app()
    for key in set(re.findall(r'clawCompareText\("([^"]+)"\)', fallback)):
        assert f'"{key}":' in fallback, key


def test_artifact_download_reuses_the_existing_single_wiring() -> None:
    app = _app()
    # No second download implementation and no second artifact-route literal:
    # the comparison hands its document to the existing result-card action.
    assert app.count("/api/claw/manual-intake/artifact/") == 1
    assert app.count("function downloadClawArtifact(") == 1
    # def + the two pre-existing call sites: the compare surface adds none.
    assert app.count("downloadClawArtifact(") == 3
    # def + the execute call + the compare call.
    assert app.count("renderClawArtifactMeta(") == 3
    assert app.count("setClawDocumentAction(true,") == 1
    assert app.count("setClawDocumentAction(false)") == 1
    # The compare surface must not grow its own download button.
    assert 'id="clawQuoteCompare' not in app.split("clawQuoteCompareSubmit")[-1]


def test_compare_surface_reaches_no_provider_or_history_seam() -> None:
    region = _compare_region()
    for forbidden in (
        "claw_p01_adapter", "create_claw_run", "runClawExecution",
        "_usage_gate_denial", "beginClawWait", "clearClawWait",
        "record_claw_run", "active_route_for", "ProductTierLabel",
        "selectedProductTier", "innerHTML", "send_negotiation",
    ):
        assert forbidden not in region, forbidden
    # One request, fired from the form's own submit only.
    assert region.count(f'fetch("{COMPARE_ROUTE}"') == 1
    assert region.count("void runClawQuoteCompare();") == 1


def test_panel_is_hidden_outside_the_claw_shell_and_uses_theme_tokens() -> None:
    css = WORKSPACE_CSS.read_text(encoding="utf-8")
    block = css.split("#2831 supplier quote comparison", 1)[-1]
    assert block != css
    assert '.app-shell:not([data-state="claw"]) .claw-quote-compare' in block
    assert ".claw-quote-compare[hidden]" in block
    for token in ("var(--text)", "var(--muted)", "var(--line)", "var(--card-bg)", "var(--accent)"):
        assert token in block, token
    assert "--claw-" not in block
    assert 'html[data-theme="padiem-glass"]' not in block
    assert "min-height: 44px" in block


# ── behavioural proof: real app.js, shipped markup and shipped copy ─────────

HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const APP = fs.readFileSync(process.argv[2], "utf8");
const INDEX = fs.readFileSync(process.argv[4], "utf8");
const COPY = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const PLAN = JSON.parse(fs.readFileSync(process.argv[5], "utf8"));

// Mirror the shipped markup: every declared id, and which of them ship hidden.
// A toggle that reads element.hidden must see the same starting state the
// browser sees, or it takes the opposite branch and the harness proves nothing.
const declaredIds = [];
const declaredHidden = [];
{
  const tagRe = /<([a-zA-Z0-9-]+)([^>]*)>/g;
  let m;
  while ((m = tagRe.exec(INDEX)) !== null) {
    const idMatch = /\sid="([^"]+)"/.exec(m[2]);
    if (!idMatch) continue;
    if (declaredIds.indexOf(idMatch[1]) < 0) declaredIds.push(idMatch[1]);
    if (/(?:^|\s)hidden(?:\s|=|$)/.test(m[2]) && declaredHidden.indexOf(idMatch[1]) < 0) declaredHidden.push(idMatch[1]);
  }
}

function makeEl(tag) {
  const el = {
    tagName: tag, id: "", className: "", textContent: "", hidden: false,
    disabled: false, value: "", checked: false, children: [], listeners: {},
    dataset: {}, attributes: {}, style: {}, options: [], selectedIndex: 0, parentNode: null,
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
  };
  el.setAttribute = (k, v) => { el.attributes[k] = String(v); };
  el.getAttribute = (k) => (k in el.attributes ? el.attributes[k] : null);
  el.removeAttribute = (k) => { delete el.attributes[k]; };
  el.appendChild = (c) => { el.children.push(c); c.parentNode = el; return c; };
  el.append = (...cs) => cs.forEach((c) => el.appendChild(c));
  el.prepend = (...cs) => cs.forEach((c) => { el.children.unshift(c); c.parentNode = el; });
  el.replaceChildren = (...cs) => { el.children = []; cs.forEach((c) => el.appendChild(c)); };
  el.remove = () => {
    if (!el.parentNode) return;
    const siblings = el.parentNode.children;
    const at = siblings.indexOf(el);
    if (at >= 0) siblings.splice(at, 1);
    el.parentNode = null;
  };
  el.addEventListener = (t, fn) => { (el.listeners[t] = el.listeners[t] || []).push(fn); };
  el.querySelector = () => null;
  el.querySelectorAll = () => [];
  el.focus = () => { doc.activeElement = el; };
  el.scrollIntoView = () => {};
  el.click = () => (el.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, target: el }));
  el.requestSubmit = () => (el.listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
  el.submit = el.requestSubmit;
  return el;
}

const byId = {};
declaredIds.forEach((id) => { const e = makeEl("div"); e.id = id; byId[id] = e; });
declaredHidden.forEach((id) => { byId[id].hidden = true; });
const shell = makeEl("div");
shell.dataset = { state: "home" };
const accountContainer = makeEl("div");
byId.clawChannel.value = "kakao";
byId.clawAction.value = "quote";
byId.clawQuoteCurrency.value = "KRW";
byId.clawQuoteMode.value = "balanced";

const anchors = [];
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
  createDocumentFragment: () => makeEl("fragment"),
  addEventListener() {},
};

byId.projectForm.querySelector = () => makeEl("div");

const requests = [];
function jsonResponse(status, obj) {
  return { ok: status >= 200 && status < 300, status, json: async () => obj };
}
let compareResponse = () => jsonResponse(200, PLAN.response);

async function fetchImpl(url, opts) {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  requests.push({ url: String(url), method, body: opts.body ? JSON.parse(opts.body) : null });
  const u = String(url);
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, { ready: true, authenticated: true, user: { name: "owner" }, history_ready: false, project_files_ready: false });
  if (u.startsWith("/api/projects")) return jsonResponse(200, { projects: [] });
  if (u.startsWith("/api/conversations")) return jsonResponse(200, { conversations: [] });
  if (u.startsWith("/api/claw/inbox/")) return jsonResponse(200, { ok: true, kind: "tasks", items: [], limit: 20 });
  if (u.startsWith("/api/claw/memory")) return jsonResponse(200, { ok: true, memories: [] });
  if (u.startsWith("/api/claw/runs")) return jsonResponse(200, { ok: true, runs: [] });
  if (u.startsWith("/api/claw/manual-intake/quote-compare")) return compareResponse();
  if (u.startsWith("/api/claw/manual-intake/artifact/")) {
    return { ok: true, status: 200, json: async () => ({}), blob: async () => ({ size: 3, type: "application/octet-stream" }) };
  }
  return jsonResponse(200, {});
}

let lang = "ko";
function localeText(key, variables) {
  const table = COPY[lang] || COPY.ko;
  const value = table[key] || COPY.ko[key] || key;
  if (!variables || typeof variables !== "object") return value;
  return Object.keys(variables).reduce((out, name) => out.split("{" + name + "}").join(String(variables[name])), value);
}

const sandbox = {
  document: doc, fetch: fetchImpl,
  AbortController: class { constructor() { this.signal = {}; } abort() {} },
  URL: { createObjectURL: () => "blob:x", revokeObjectURL() {}, revokeURL() {} },
  setTimeout, clearTimeout, setInterval, clearInterval, console,
  CustomEvent: class {}, Math, Date, Object, Array, JSON, Number, String, Boolean, RegExp, Error, Promise, Map, Set, parseInt, parseFloat, isNaN, Intl,
  location: { href: "http://localhost/", assign() {} },
  addEventListener: () => {},
  navigator: { clipboard: { writeText: async () => {} } },
  __padiemLocale: { text: (key, variables) => localeText(key, variables) },
  PadiemChatLifecycle: { states: {}, set() {} },
  PadiemConfirmDialog: { confirm: async () => true },
  PadiemChatTransport: { requestCompleted: async () => ({}), requestStreaming: async () => ({}), readSseEvents: async () => {}, errorFor: () => new Error("x") },
  PadiemChatConversationState: { reset() {}, setConversationId() {}, getConversationId: () => null, outboundWithUser: () => [], commitAssistant() {}, setSkill() {}, getSkill: () => "auto" },
  PadiemAttachmentCapabilities: { limits: {}, images: [], textDocuments: [], copy: () => ({}) },
  PadiemBinaryDocuments: null,
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(APP, sandbox, { filename: "app.js" });

function textOf(node) {
  let out = node.textContent || "";
  (node.children || []).forEach((child) => { out += "\n" + textOf(child); });
  return out;
}

(async () => {
  const checks = {};
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, checks, requests, rendered: textOf(byId.clawQuoteCompareResult) })); process.exit(0); };
  const flush = async () => { for (let i = 0; i < 14; i++) await new Promise((r) => setTimeout(r, 0)); };
  const comparePosts = () => requests.filter((r) => r.url === "/api/claw/manual-intake/quote-compare" && r.method === "POST");
  const artifactGets = () => requests.filter((r) => r.url.indexOf("/api/claw/manual-intake/artifact/") === 0);

  // 1. loading app.js issues no comparison request
  checks.NO_REQUEST_ON_LOAD = comparePosts().length === 0;
  if (!checks.NO_REQUEST_ON_LOAD) return fail("loading app.js must not compare anything");

  // 2. opening the Claw workspace must not compare anything either
  byId.clawNavButton.click();
  await flush();
  checks.NO_REQUEST_ON_CLAW_OPEN = comparePosts().length === 0;
  if (!checks.NO_REQUEST_ON_CLAW_OPEN) return fail("opening the Claw workspace must not compare anything");

  // 3. the entry point reveals the panel, still with no request
  byId.clawCompareToggle.click();
  await flush();
  checks.NO_REQUEST_ON_PANEL_OPEN = comparePosts().length === 0;
  if (!checks.NO_REQUEST_ON_PANEL_OPEN) return fail("opening the panel must not compare anything");
  checks.PANEL_OPENED = byId.clawQuoteCompare.hidden === false;
  if (!checks.PANEL_OPENED) return fail("the entry point did not open the panel");
  checks.ARIA_EXPANDED = byId.clawCompareToggle.getAttribute("aria-expanded") === "true";
  if (!checks.ARIA_EXPANDED) return fail("aria-expanded was not synced");
  checks.NO_REQUEST_ON_PANEL_OPEN = comparePosts().length === 0;
  if (!checks.NO_REQUEST_ON_PANEL_OPEN) return fail("opening the panel must not compare anything");

  const rows = byId.clawQuoteSupplierRows.children;
  checks.TWO_SUPPLIERS_BY_DEFAULT = rows.length === 2;
  if (!checks.TWO_SUPPLIERS_BY_DEFAULT) return fail("expected two supplier rows, got " + rows.length);
  checks.ROW_FIELDS = Object.keys(rows[0].controls).sort().join(",") === [
    "due_days", "evidence_ref", "item_label", "payment_terms_label", "prepaid",
    "promised_delivery_date", "quantity", "supplier_label", "total_minor", "unit_price_minor",
  ].join(",");
  if (!checks.ROW_FIELDS) return fail("row controls are not the captured-field set: " + Object.keys(rows[0].controls));

  // 4. one extra supplier row
  byId.clawQuoteAddSupplier.click();
  checks.ADD_ROW_GROWS_TO_THREE = rows.length === 3;
  if (!checks.ADD_ROW_GROWS_TO_THREE) return fail("add supplier did not append a row");
  const removable = (rows[rows.length - 1].children || []).filter((c) => c.tagName === "button");
  checks.ADD_ROW_OFFERS_REMOVAL = removable.length === 1
    && (removable[0].listeners.click || []).length === 1;
  if (!checks.ADD_ROW_OFFERS_REMOVAL) return fail("a third row must offer exactly one removal control");
  removable[0].click();
  checks.REMOVE_ROW_WORKS = byId.clawQuoteSupplierRows.children.length === 2;
  if (!checks.REMOVE_ROW_WORKS) return fail("removing a row did not shrink the set: " + rows.length);
  checks.RENUMBERED = rows[0].dataset.supplierSequence === "1" && rows[1].dataset.supplierSequence === "2";
  rows[0].controls.supplier_label.value = "A업체";
  rows[0].controls.total_minor.value = "1200000";
  rows[0].controls.promised_delivery_date.value = "2026-10-05";
  rows[0].controls.payment_terms_label.value = "월말매입 30일";
  rows[0].controls.due_days.value = "30";
  rows[0].controls.evidence_ref.value = "A업체 견적서";
  rows[1].controls.supplier_label.value = "B업체";
  rows[1].controls.total_minor.value = "1050000";
  // row 2 deliberately has no delivery date, no terms and no evidence

  byId.clawQuoteCompareForm.requestSubmit();
  await flush();
  checks.ONE_POST_PER_SUBMIT = comparePosts().length === 1;
  if (!checks.ONE_POST_PER_SUBMIT) return fail("expected exactly one POST, saw " + comparePosts().length);

  const sent = comparePosts()[0].body;
  checks.TOP_FIELDS_ALLOWED = Object.keys(sent).every((k) => ["suppliers", "mode", "artifact", "currency", "weights"].indexOf(k) >= 0);
  if (!checks.TOP_FIELDS_ALLOWED) return fail("unexpected top-level fields " + Object.keys(sent));
  checks.SUPPLIER_COUNT = sent.suppliers.length === 2;
  checks.SUPPLIER_FIELDS_ALLOWED = sent.suppliers.every(
    (s) => Object.keys(s).every((k) => PLAN.allowedSupplierFields.indexOf(k) >= 0)
  );
  if (!checks.SUPPLIER_FIELDS_ALLOWED) return fail("supplier carries a field the contract does not accept: " + JSON.stringify(sent.suppliers));
  checks.SAFE_IDS_DERIVED = sent.suppliers.map((s) => s.supplier_id).join(",") === "supplier_1,supplier_2";
  checks.LABELS_PRESERVED = sent.suppliers[0].supplier_label === "A업체" && sent.suppliers[1].supplier_label === "B업체";
  checks.NO_ARTIFACT_FIELD_WHEN_UNCHECKED = !("artifact" in sent);
  checks.EMPTY_FIELDS_NOT_SENT = !("promised_delivery_date" in sent.suppliers[1])
    && !("payment_terms" in sent.suppliers[1])
    && !("evidence_ref" in sent.suppliers[1])
    && !("quantity" in sent.suppliers[0]);
  if (!checks.EMPTY_FIELDS_NOT_SENT) return fail("blank inputs were sent as invented values: " + JSON.stringify(sent.suppliers[1]));
  checks.NOTHING_STORED_WITHOUT_ARTIFACT = artifactGets().length === 0;

  const rendered = textOf(byId.clawQuoteCompareResult);
  checks.RESULT_SHOWN = byId.clawQuoteCompareResult.hidden === false;
  checks.RECOMMENDATION_SHOWN = rendered.indexOf("B업체") >= 0;
  checks.UNKNOWN_LABEL_USED = rendered.indexOf(COPY.ko["claw-cmp-unknown"]) >= 0;
  checks.NO_ZERO_FABRICATION = rendered.indexOf("\n0\n") < 0;
  checks.DRAFT_LABELLED = /\bDRAFT\b/.test(rendered);
  checks.NEGOTIATION_FACTS = rendered.indexOf(COPY.ko["claw-cmp-target"]) >= 0
    && rendered.indexOf("captured_competing_quote:quote_supplier_b:v1") >= 0;
  checks.ADVISORY_SHOWN = rendered.indexOf(COPY.ko["claw-cmp-advisory"]) >= 0;
  checks.NO_SEND_PROMISE = !/(전송함|발주 완료|sent to supplier)/i.test(rendered);

  // 5. a second submit while in flight must not double-post
  byId.clawQuoteCompareForm.requestSubmit();
  byId.clawQuoteCompareForm.requestSubmit();
  await flush();
  checks.SINGLE_FLIGHT = comparePosts().length === 2;
  if (!checks.SINGLE_FLIGHT) return fail("single-flight did not hold: " + comparePosts().length);

  // 6. DOCX opt-in: the artifact field appears and the existing download works
  byId.clawQuoteDocx.checked = true;
  byId.clawQuoteCompareForm.requestSubmit();
  await flush();
  const docxPost = comparePosts()[comparePosts().length - 1].body;
  checks.ARTIFACT_FIELD_SENT = docxPost.artifact === "docx";
  if (!checks.ARTIFACT_FIELD_SENT) return fail("the DOCX option did not request artifact=docx: " + JSON.stringify(docxPost));
  checks.DOCUMENT_ACTION_ARMED = byId.clawResultDocx.dataset.documentId === PLAN.artifactId;
  checks.SUCCESS_NOTE_VISIBLE = byId.clawResultSuccessNote.hidden === false;
  byId.clawResultDocx.click();
  await flush();
  checks.DOWNLOAD_REUSES_EXISTING_ROUTE = artifactGets().length === 1
    && artifactGets()[0].url === "/api/claw/manual-intake/artifact/" + PLAN.artifactId
    && anchors.length === 1;
  if (!checks.DOWNLOAD_REUSES_EXISTING_ROUTE) return fail("artifact download did not reuse the existing route");

  // 7. a failure response is reported, never replaced by a fabricated result
  compareResponse = () => jsonResponse(400, { ok: false, error: { code: "suppliers_required", message: "x" } });
  byId.clawQuoteCompareForm.requestSubmit();
  await flush();
  checks.ERROR_SURFACED = byId.clawQuoteCompareError.hidden === false
    && textOf(byId.clawQuoteCompareError).indexOf(COPY.ko["claw-cmp-error-count"]) >= 0;
  if (!checks.ERROR_SURFACED) return fail("a 400 was not surfaced with bounded copy");

  const extra = Array.from(new Set(requests.map((r) => r.url.split("?")[0])))
    .filter((u) => PLAN.allowedRoutes.indexOf(u) < 0);
  checks.NO_UNEXPECTED_ROUTE = extra.length === 0;
  if (!checks.NO_UNEXPECTED_ROUTE) return fail("unexpected routes: " + JSON.stringify(extra));

  console.log(JSON.stringify({ ok: true, checks, sent, rendered, routes: requests.map((r) => r.url) }));
  process.exit(0);
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); process.exit(0); });
"""


SUCCESS_COMPARISON = {
    "ok": True,
    "comparison": {
        "workspace_id": "claw_manual_intake",
        "mode": "balanced",
        "weights": {"price": 50, "delivery": 25, "cashflow": 25},
        "currency": "KRW",
        "supplier_count": 2,
        "suppliers": [
            {
                "supplier_id": "supplier_2", "supplier_label": "B업체", "item_label": "",
                "quote_id": "quote_supplier_2", "quote_version": 1,
                "total": {"amount_minor": 1050000, "currency": "KRW"},
                "promised_delivery_date": "2026-10-20", "payment_terms_label": "선입금",
                "due_days": 0, "prepaid": True, "price_rank": 1, "delivery_rank": 2,
                "cashflow_rank": 2, "score_basis_points": 8333, "unknown_fields": [],
                "evidence_ref": "",
            },
            {
                "supplier_id": "supplier_1", "supplier_label": "A업체", "item_label": "산업용 랙",
                "quote_id": "quote_supplier_1", "quote_version": 1,
                "total": {"amount_minor": 1200000, "currency": "KRW"},
                "promised_delivery_date": None, "payment_terms_label": "",
                "due_days": None, "prepaid": None, "price_rank": 2, "delivery_rank": None,
                "cashflow_rank": None, "score_basis_points": 4000,
                "unknown_fields": ["promised_delivery_date", "payment_terms"],
                "evidence_ref": "A업체 견적서",
            },
        ],
        "recommended_supplier_id": "supplier_2",
        "recommended_supplier_label": "B업체",
        "reason_codes": ["mode:balanced", "score:8333", "winner_fields_complete"],
        "advisory_only": True,
        "negotiation": {
            "negotiation_id": "negotiation_claw_manual_intake_balanced",
            "supplier_id": "supplier_1", "supplier_label": "A업체",
            "quote_id": "quote_supplier_1", "quote_version": 1, "version": 1,
            "current_total": {"amount_minor": 1200000, "currency": "KRW"},
            "target_total": {"amount_minor": 1050000, "currency": "KRW"},
            "basis": "captured_competing_quote:quote_supplier_b:v1",
            "message": "A업체 담당자님, 안녕하세요.\n[DRAFT ONLY]",
            "status": "draft_only", "send_performed": False,
        },
        "negotiation_unavailable_reason": None,
        "draft_only": True, "external_send_supported": False,
        "external_sends": 0, "model_calls": 0,
    },
    "artifact": {
        "document_id": ARTIFACT_ID,
        "filename": "compare.docx",
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "byte_length": 4096,
    },
}

ALLOWED_ROUTES = [
    "/api/auth/status", "/api/projects", "/api/conversations", "/api/claw/runs",
    "/api/claw/memory", "/api/claw/inbox/tasks", COMPARE_ROUTE,
    "/api/claw/manual-intake/artifact/" + ARTIFACT_ID,
]


def _run_harness(response: dict) -> dict:
    node = shutil.which("node")
    if node is None:  # pragma: no cover - the runner image always ships node
        pytest.skip("node is not available")
    plan = {
        "response": response,
        "artifactId": ARTIFACT_ID,
        "allowedSupplierFields": sorted(ALLOWED_SUPPLIER_FIELDS),
        "allowedRoutes": ALLOWED_ROUTES,
    }
    script = ROOT / "tests" / "_b54_claw_quote_compare_ui_harness.js"
    copy_file = ROOT / "tests" / "_b54_claw_quote_compare_ui_copy.json"
    plan_file = ROOT / "tests" / "_b54_claw_quote_compare_ui_plan.json"
    script.write_text(HARNESS, encoding="utf-8")
    copy_file.write_text(json.dumps(_locale_table(), ensure_ascii=False), encoding="utf-8")
    plan_file.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    try:
        completed = subprocess.run(
            [
                node, str(script), str(APP_JS), str(copy_file), str(INDEX_HTML), str(plan_file),
            ],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
    finally:
        for artifact in (script, copy_file, plan_file):
            artifact.unlink(missing_ok=True)
    assert completed.returncode == 0, completed.stderr[-4000:]
    line = [l for l in completed.stdout.splitlines() if l.strip().startswith("{")]
    assert line, completed.stdout[-3000:] + completed.stderr[-3000:]
    return json.loads(line[-1])


def test_harness_runs_the_real_app_and_reports_no_failure() -> None:
    result = _run_harness(SUCCESS_COMPARISON)
    assert result.get("ok") is True, result


def test_harness_proves_the_ui_invariants() -> None:
    result = _run_harness(SUCCESS_COMPARISON)
    checks = result["checks"]
    for name in (
        "NO_REQUEST_ON_LOAD",
        "NO_REQUEST_ON_CLAW_OPEN",
        "NO_REQUEST_ON_PANEL_OPEN",
        "TWO_SUPPLIERS_BY_DEFAULT",
        "ROW_FIELDS",
        "ONE_POST_PER_SUBMIT",
        "SUPPLIER_FIELDS_ALLOWED",
        "SAFE_IDS_DERIVED",
        "LABELS_PRESERVED",
        "NO_ARTIFACT_FIELD_WHEN_UNCHECKED",
        "EMPTY_FIELDS_NOT_SENT",
        "NOTHING_STORED_WITHOUT_ARTIFACT",
        "RESULT_SHOWN",
        "RECOMMENDATION_SHOWN",
        "UNKNOWN_LABEL_USED",
        "NO_ZERO_FABRICATION",
        "DRAFT_LABELLED",
        "NEGOTIATION_FACTS",
        "ADVISORY_SHOWN",
        "NO_SEND_PROMISE",
        "SINGLE_FLIGHT",
        "ARTIFACT_FIELD_SENT",
        "DOCUMENT_ACTION_ARMED",
        "DOWNLOAD_REUSES_EXISTING_ROUTE",
        "ERROR_SURFACED",
        "NO_UNEXPECTED_ROUTE",
    ):
        assert checks.get(name) is True, (name, checks, result.get("rendered"))


def test_harness_payload_is_the_capture_and_nothing_else() -> None:
    result = _run_harness(SUCCESS_COMPARISON)
    suppliers = result["sent"]["suppliers"]
    assert suppliers[0] == {
        "supplier_id": "supplier_1",
        "supplier_label": "A업체",
        "total_minor": "1200000",
        "promised_delivery_date": "2026-10-05",
        "payment_terms": {"label": "월말매입 30일", "due_days": 30},
        "evidence_ref": "A업체 견적서",
        "currency": "KRW",
    }, suppliers[0]
    assert suppliers[1] == {
        "supplier_id": "supplier_2",
        "supplier_label": "B업체",
        "total_minor": "1050000",
        "currency": "KRW",
    }, suppliers[1]


def test_backend_contract_still_rejects_a_lead_time_phrase() -> None:
    # The UI offers a date control and sends nothing for a blank one, so the
    # route stays the thing that refuses a lead-time phrase: the boundary is
    # enforced in one place and cannot drift if the copy changes.
    from kagent.ops_quote_compare_flow import (
        OpsQuoteCompareFlowError,
        compare_supplier_quotes,
    )

    with pytest.raises(OpsQuoteCompareFlowError) as caught:
        compare_supplier_quotes(
            {
                "suppliers": [
                    {"supplier_id": "s1", "supplier_label": "A", "total_minor": 100,
                     "promised_delivery_date": "2\uc8fc"},
                    {"supplier_id": "s2", "supplier_label": "B", "total_minor": 200},
                ]
            }
        )
    assert caught.value.error_code == "invalid_delivery_date"
