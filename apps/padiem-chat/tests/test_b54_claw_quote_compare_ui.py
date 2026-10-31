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


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
MODULE = (STATIC / "claw-quote-compare.js").read_text(encoding="utf-8")
CSS = (STATIC / "claw-quote-compare.css").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")


def test_compare_surface_is_wired_as_a_separate_claw_static_module() -> None:
    assert 'id="clawQuoteCompare"' in INDEX
    assert 'id="clawQuoteCompareForm"' in INDEX
    assert 'id="clawQcSuppliers"' in INDEX
    assert 'id="clawQcCompareBtn"' in INDEX
    assert 'id="clawQcDocxBtn"' in INDEX
    assert 'id="clawQcDownloadBtn"' in INDEX
    assert '<link rel="stylesheet" href="./claw-quote-compare.css" />' in INDEX
    assert '<script src="./claw-quote-compare.js"></script>' in INDEX
    assert INDEX.count('id="clawQuoteCompare"') == 1
    assert INDEX.count('id="clawQuoteCompareForm"') == 1


def test_supplier_inputs_have_explicit_labels_and_captured_date_field() -> None:
    for field in (
        "claw-qc-field-name", "claw-qc-field-item", "claw-qc-field-unit",
        "claw-qc-field-quantity", "claw-qc-field-total", "claw-qc-field-delivery",
        "claw-qc-field-payment", "claw-qc-field-due", "claw-qc-field-prepaid",
        "claw-qc-field-evidence",
    ):
        assert field in MODULE
    assert 'node.type = type' in MODULE
    assert 'input("date", "claw-qc-delivery"' in MODULE
    assert 'promised_delivery_date = row.delivery.value' in MODULE
    assert "Lead-time text is never converted" in MODULE
    assert "리드타임" in INDEX


def test_client_requires_two_suppliers_and_preserves_missing_values() -> None:
    assert "const MIN_SUPPLIERS = 2" in MODULE
    assert "const MAX_SUPPLIERS = 10" in MODULE
    assert "entries.length < MIN_SUPPLIERS" in MODULE
    assert "supplier_price_missing" in MODULE
    assert "if (unit) entry.unit_price_minor" in MODULE
    assert "if (total) entry.total_minor" in MODULE
    assert "if (row.delivery.value) entry.promised_delivery_date" in MODULE
    assert "row.delivery.value ||" not in MODULE
    assert "new Date" not in MODULE


def test_comparison_saves_through_response_bytes_and_never_fetches_an_artifact() -> None:
    assert 'const ROUTE = "/api/claw/manual-intake/quote-compare"' in MODULE
    assert 'const DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"' in MODULE
    assert 'artifact: "docx"' in MODULE
    # #2952 follow-up ②: the document is the POST response, so nothing is stored
    # and this module must never reach the shared artifact download route again.
    assert "/api/claw/manual-intake/artifact/" not in MODULE
    assert "postDocx" in MODULE
    assert "await response.blob()" in MODULE
    assert "URL.createObjectURL(artifact.blob)" in MODULE
    assert 'anchor.download = artifact.filename' in MODULE
    assert "workspace_document_store" not in MODULE
    assert "createClawRun" not in MODULE


def test_negotiation_is_explicitly_draft_only_without_external_actions() -> None:
    assert 'negotiation.status === "draft_only"' in MODULE
    assert 'text("claw-qc-draft")' in MODULE
    assert 'text("claw-qc-no-external")' in MODULE
    assert 'id="clawQcCompareBtn"' in INDEX
    assert 'id="clawQcDocxBtn"' in INDEX
    # No actionable send, order-submit, or purchase control is present.
    assert not re.search(r'<button[^>]+>(?:[^<]*(?:send|purchase|order submit)[^<]*)</button>', INDEX, re.I)


def test_result_projection_is_text_only_and_mobile_focus_tokens_exist() -> None:
    assert "textContent" in MODULE
    assert "innerHTML" not in MODULE
    assert "replaceChildren" in MODULE
    for token in ("focus-visible", "min-height: 2.75rem", "@media (max-width: 920px)", "@media (max-width: 560px)"):
        assert token in CSS
    assert ".app-shell:not([data-state=\"claw\"]) .claw-quote-compare" in CSS


def test_claw_conversation_owns_bounded_vertical_scroll_without_changing_chat() -> None:
    workspace = (STATIC / "claw-workspace.css").read_text(encoding="utf-8")
    claw_block = workspace.split('.app-shell[data-state="claw"] .conversation {', 1)[1].split("}", 1)[0]
    # #5014/#5260: the workbench canvas no longer caps itself against the
    # viewport; the content column bounds it and the canvas owns the scroll.
    assert "max-height: calc(100vh - 96px)" not in claw_block
    assert "max-height: none" in claw_block
    assert "overflow-y: auto" in claw_block
    assert "min-height: 0" in claw_block
    assert "overscroll-behavior-y: contain" in claw_block
    bounded = workspace.split(
        '.app-shell[data-state="claw"]:not(:has(.claw-workspace[data-view="general"] ~ .conversation)) .conversation {',
        1,
    )[1].split("}", 1)[0]
    assert "flex: 1 1 0" in bounded
    # The generic Chat conversation remains governed by its existing rules.
    assert '.app-shell[data-state="chat"] .conversation' not in claw_block


def test_new_locale_keys_exist_in_both_languages() -> None:
    keys = set(re.findall(r'"(claw-qc-[^"]+)"\s*:', MODULE))
    assert keys
    ko, en = LOCALE.split("    en: {", 1)
    for key in keys:
        assert f'"{key}"' in ko, key
        assert f'"{key}"' in en, key


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
    found_ids = sorted(set(re.findall(r'id="([A-Za-z0-9]+)"', INDEX)))
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
