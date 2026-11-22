"""#2831 Claw supplier quote comparison UI contracts.

The backend comparison route is covered by ``test_claw_quote_compare_http``.
This file guards the static UI wiring and the product-safety boundary around
that existing route: captured facts only, at least two suppliers, draft-only
negotiation, and the response-bytes document handoff (#2952 follow-up).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from _support.settings_dialog_source import index_elements

# #8060 56차: 원문 읽기는 _support(quote_compare_source)가 담당하고 시험은
# 파싱된 HTML 요소·JS 토큰·CSS 선언·로케일 맵·하네스 실행 값으로 단언한다.
from _support.quote_compare_source import (  # noqa: E402
    compare_rules,
    has_locale_text,
    index_ids,
    locale_map,
    media_conditions,
    module_const,
    module_has,
    module_identifiers,
    module_lacks,
    module_qc_keys,
    module_strings,
    rule_for,
    rule_value,
    selectors_of,
    workspace_rules,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def test_compare_surface_is_wired_as_a_separate_claw_static_module() -> None:
    elements = index_elements()
    ids = [el.attrs.get("id") for el in elements]
    for element_id in (
        "clawQuoteCompare", "clawQuoteCompareForm", "clawQcSuppliers",
        "clawQcCompareBtn", "clawQcDocxBtn", "clawQcDownloadBtn",
    ):
        assert element_id in ids
    links = [el.attrs for el in elements if el.tag == "link"]
    assert any(
        attrs.get("rel") == "stylesheet" and attrs.get("href") == "./claw-quote-compare.css"
        for attrs in links
    )
    scripts = [el.attrs for el in elements if el.tag == "script"]
    assert any(attrs.get("src") == "./claw-quote-compare.js" for attrs in scripts)
    assert ids.count("clawQuoteCompare") == 1
    assert ids.count("clawQuoteCompareForm") == 1


def test_supplier_inputs_have_explicit_labels_and_captured_date_field() -> None:
    strings = module_strings()
    for field in (
        "claw-qc-field-name", "claw-qc-field-item", "claw-qc-field-unit",
        "claw-qc-field-quantity", "claw-qc-field-total", "claw-qc-field-delivery",
        "claw-qc-field-payment", "claw-qc-field-due", "claw-qc-field-prepaid",
        "claw-qc-field-evidence",
    ):
        assert field in strings
    assert module_has("node.type = type")
    assert module_has('input("date", "claw-qc-delivery"')
    assert module_has("promised_delivery_date = row.delivery.value")
    assert module_has("Lead-time text is never converted")
    assert has_locale_text("리드타임")


def test_client_requires_two_suppliers_and_preserves_missing_values() -> None:
    assert module_const("MIN_SUPPLIERS") == "2"
    assert module_const("MAX_SUPPLIERS") == "10"
    assert module_has("entries.length < MIN_SUPPLIERS")
    assert "supplier_price_missing" in module_identifiers()
    assert module_has("if (unit) entry.unit_price_minor")
    assert module_has("if (total) entry.total_minor")
    assert module_has("if (row.delivery.value) entry.promised_delivery_date")
    assert module_lacks("row.delivery.value ||")
    assert module_lacks("new Date")


def test_comparison_saves_through_response_bytes_and_never_fetches_an_artifact() -> None:
    assert module_const("ROUTE") == '"/api/claw/manual-intake/quote-compare"'
    assert module_const("DOCX_MEDIA_TYPE") == (
        '"application/vnd.openxmlformats-officedocument.wordprocessingml.document"'
    )
    assert module_has('artifact: "docx"')
    # #2952 follow-up ②: the document is the POST response, so nothing is stored
    # and this module must never reach the shared artifact download route again.
    assert not any("/api/claw/manual-intake/artifact/" in value for value in module_strings())
    assert "postDocx" in module_identifiers()
    assert module_has("await response.blob()")
    assert module_has("URL.createObjectURL(artifact.blob)")
    assert module_has("anchor.download = artifact.filename")
    assert module_lacks("workspace_document_store")
    assert module_lacks("createClawRun")


def test_negotiation_is_explicitly_draft_only_without_external_actions() -> None:
    assert module_has('negotiation.status === "draft_only"')
    assert module_has('text("claw-qc-draft")')
    assert module_has('text("claw-qc-no-external")')
    ids = [el.attrs.get("id") for el in index_elements()]
    assert "clawQcCompareBtn" in ids and "clawQcDocxBtn" in ids
    # No actionable send, order-submit, or purchase control is present.
    assert not [
        el for el in index_elements()
        if el.tag == "button"
        and any(word in el.text.lower() for word in ("send", "purchase", "order submit"))
    ]


def test_result_projection_is_text_only_and_mobile_focus_tokens_exist() -> None:
    assert "textContent" in module_identifiers()
    assert "innerHTML" not in module_identifiers()
    assert "replaceChildren" in module_identifiers()
    rules = compare_rules()
    assert any("focus-visible" in selector for selector in selectors_of(rules))
    assert rule_value(rules, ".claw-qc-control select", "min-height") == "2.75rem"
    media = media_conditions(rules)
    assert "(max-width: 920px)" in media
    assert "(max-width: 560px)" in media
    assert rule_for(rules, '.app-shell:not([data-state="claw"]) .claw-quote-compare')


def test_claw_conversation_owns_bounded_vertical_scroll_without_changing_chat() -> None:
    rules = workspace_rules()
    claw = '.app-shell[data-state="claw"] .conversation'
    # #5014/#5260: the workbench canvas no longer caps itself against the
    # viewport; the content column bounds it and the canvas owns the scroll.
    assert rule_value(rules, claw, "max-height") == "none"
    assert rule_value(rules, claw, "overflow-y") == "auto"
    assert rule_value(rules, claw, "min-height") == "0"
    assert rule_value(rules, claw, "overscroll-behavior-y") == "contain"
    bounded = (
        '.app-shell[data-state="claw"]:not('
        ':has(.claw-workspace[data-view="general"] ~ .conversation)) .conversation'
    )
    assert rule_value(rules, bounded, "flex") == "1 1 0"
    # The generic Chat conversation remains governed by its existing rules.
    assert not rule_for(rules, '.app-shell[data-state="chat"] .conversation')


def test_new_locale_keys_exist_in_both_languages() -> None:
    keys = module_qc_keys()
    assert keys
    ko = locale_map("ko")
    en = locale_map("en")
    for key in keys:
        assert key in ko, key
        assert key in en, key


_HARNESS = r"""
const fs = require("fs");
const MODULE_PATH = process.argv[2];

const cases = [];
function ok(name, cond, extra) { cases.push({ name, ok: !!cond, extra: extra === undefined ? undefined : String(extra) }); }

class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = []; this.listeners = {}; this.dataset = {}; this.attrs = {};
    this.hidden = false; this.disabled = false; this.checked = false;
    this.className = ""; this.type = ""; this.textContent = ""; this.htmlFor = "";
    this._innerHTML = ""; this._value = "";
    this.style = { setProperty() {} };
  }
  get value() { return this._value; }
  set value(v) { this._value = v === undefined || v === null ? "" : String(v); }
  get innerHTML() { return this._innerHTML; }
  set innerHTML(v) { this._innerHTML = String(v); if (v === "") this.children = []; }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(n) { this.children.push(n); return n; }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  remove() {}
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  dispatch(type, event) { (this.listeners[type] || []).forEach((fn) => fn(event || {})); }
  querySelector(sel) {
    const className = sel.startsWith(".") ? sel.slice(1) : null;
    if (!className) return null;
    const walk = (node) => {
      for (const child of node.children || []) {
        if (child.className === className) return child;
        const found = walk(child);
        if (found) return found;
      }
      return null;
    };
    return walk(this);
  }
  getBoundingClientRect() { return { height: 0 }; }
  focus() {}
  click() { this.dispatch("click", { preventDefault() {} }); }
}

// Only ids that really exist in static/index.html get an element; others are null.
const IDS = fs.readFileSync(process.argv[3], "utf-8").trim().split("\n");
const byId = new Map(IDS.map((id) => [id, new El(id === "clawQuoteCompareForm" ? "form" : "div")]));
const body = new El("body");
const created = [];
global.document = {
  readyState: "complete",
  body,
  createElement: (tag) => { const node = new El(tag); created.push(node); return node; },
  getElementById: (id) => byId.get(id) || null,
  querySelector: () => null,
  addEventListener() {},
};

const form = byId.get("clawQuoteCompareForm");
form.addEventListener("submit", () => {});
byId.get("clawQcMode").value = "balanced";
byId.get("clawQcCurrency").value = "KRW";
const login = byId.get("loginButton");
login.dataset.authenticated = "true";
login.disabled = false;

const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const FILENAME = "견적 비교.docx";
const calls = [];
let comparisonResponses = 0;

global.fetch = async (url, options) => {
  calls.push({ url, options });
  if (String(url).startsWith("/api/claw/manual-intake/artifact/")) {
    return { ok: false, status: 404, json: async () => ({ ok: false, error: { code: "artifact_not_found" } }) };
  }
  if (options && String(options.body || "").includes('"artifact":"docx"')) {
    return {
      ok: true, status: 200,
      headers: { get: (name) => (String(name).toLowerCase() === "content-disposition"
        ? "attachment; filename*=UTF-8''" + encodeURIComponent(FILENAME) : null) },
      blob: async () => ({ size: 4096, kind: DOCX }),
      json: async () => ({ ok: false }),
    };
  }
  comparisonResponses += 1;
  return {
    ok: true, status: 200,
    json: async () => ({
      ok: true,
      comparison: {
        mode: "balanced", currency: "KRW", supplier_count: 2, recommended_supplier_label: "갑",
        unknown_fields: [], rows: [], weights: {}, negotiation: null, entries: [],
      },
    }),
  };
};

global.window = {
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  addEventListener() {},
};
const objectUrls = [];
global.URL = { createObjectURL: (blob) => { objectUrls.push(blob); return "blob:generated"; }, revokeObjectURL() {} };

require(MODULE_PATH);

const wait = () => new Promise((resolve) => setTimeout(resolve, 30));
const docx = byId.get("clawQcDocxBtn");
const download = byId.get("clawQcDownloadBtn");
const status = byId.get("clawQcStatus");

(async () => {
  const fill = (id, value) => {
    const node = created.find((c) => c.id === id);
    if (!node) throw new Error("missing element id " + id);
    node.value = value;
  };
  fill("clawQcName1", "갑상사"); fill("clawQcUnit1", "1200000");
  fill("clawQcName2", "을상사"); fill("clawQcUnit2", "1500000");
  form.dispatch("submit", { preventDefault() {} });
  await wait();
  ok("comparison rendered and save enabled", docx.disabled === false, "status=" + status.dataset.state);

  docx.dispatch("click", { preventDefault() {} });
  await wait();
  const saveCall = calls.find((c) => String(c.options && c.options.body || "").includes('"artifact":"docx"'));
  ok("save posts to the comparison route only", Boolean(saveCall) && saveCall.url === "/api/claw/manual-intake/quote-compare");
  ok("save asks for the document media type", Boolean(saveCall) && saveCall.options.headers.Accept === DOCX);
  ok("download enabled after the bytes answer", download.disabled === false, "status=" + status.dataset.state);
  ok("no second artifact fetch happened", !calls.some((c) => String(c.url).startsWith("/api/claw/manual-intake/artifact/")));

  download.dispatch("click", { preventDefault() {} });
  await wait();
  const anchor = body.children.find((node) => node.tagName === "A");
  ok("blob came from the response bytes", objectUrls.length === 1 && objectUrls[0].kind === DOCX && objectUrls[0].size === 4096);
  ok("download name is the server filename", Boolean(anchor) && anchor.download === FILENAME, anchor && anchor.download);

  console.log(JSON.stringify({ cases, callCount: calls.length }));
})();
"""


def test_real_quote_compare_download_runs_on_response_bytes() -> None:
    """The REAL module, driven through the ids that exist in index.html.

    #2952 follow-up ②: the comparison document is the POST response, so the
    module must save and download from those bytes and never call the shared
    artifact route again.
    """
    if shutil.which("node") is None:
        pytest.skip("Node unavailable locally; required B62 Linux CI browser test")

    directory = Path(tempfile.mkdtemp(prefix="claw-quote-compare-"))
    harness = directory / "harness.cjs"
    ids = directory / "ids.txt"
    harness.write_text(_HARNESS, encoding="utf-8", newline="\n")
    found_ids = sorted(i for i in index_ids() if re.fullmatch(r"[A-Za-z0-9]+", i))
    ids.write_text("\n".join(found_ids) + "\n", encoding="utf-8", newline="\n")

    result = subprocess.run(
        ["node", str(harness), str(STATIC / "claw-quote-compare.js"), str(ids)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    failed = [case for case in payload["cases"] if not case.get("ok")]
    assert not failed, json.dumps(failed, ensure_ascii=False)
    assert [case["name"] for case in payload["cases"]] == [
        "comparison rendered and save enabled",
        "save posts to the comparison route only",
        "save asks for the document media type",
        "download enabled after the bytes answer",
        "no second artifact fetch happened",
        "blob came from the response bytes",
        "download name is the server filename",
    ]
    # Two calls total: the comparison and the save. Nothing re-fetches an artifact.
    assert payload["callCount"] == 2
