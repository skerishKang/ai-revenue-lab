"use strict";
/* Execute actual shipped Hark web XLSX UI with network-free minimal DOM. */
const assert = require("node:assert/strict");
const { join } = require("node:path");
const ui = require(join(__dirname, "..", "static", "claw-web-xlsx-sources.js"));
const SRC = {
  document_id: "doc_" + "a".repeat(32),
  filename: "test-owner.xlsx",
  size_bytes: 321,
  source_sha256: "b".repeat(64),
  original_immutable: true,
  processing_authorized: false,
};
const REF = "sel_" + "c".repeat(32);
const COPY_ID = "doc_" + "d".repeat(32);
const SELECTION = {
  selection_ref: REF, document_id: SRC.document_id, filename: SRC.filename,
  size_bytes: SRC.size_bytes, source_sha256: SRC.source_sha256,
  status: "source_selected_p01_not_started",
  p01_approval_started: false, processing_started: false,
};

class FakeNode {
  constructor(tag = "div") {
    this.tag = tag; this.hidden = false; this.disabled = false; this.open = false;
    this.textContent = ""; this.children = []; this.handlers = {};
    this.files = null; this.value = "";
  }
  addEventListener(name, callback) { this.handlers[name] = callback; }
  append(...elements) { this.children.push(...elements); }
  appendChild(node) { this.children.push(node); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, val) { this[name] = val; }
  async click() { return this.handlers.click?.(); }
}

function fakeRoot() {
  const ids = [
    "clawWebOfficeDetails", "clawWebXlsxInput", "clawWebXlsxSave",
    "clawWebXlsxRefresh", "clawWebXlsxNotice", "clawWebXlsxList",
    "clawWebXlsxP01Panel", "clawWebXlsxP01Selected", "clawWebXlsxP01Status",
    "clawWebXlsxP01Refresh", "clawWebXlsxP01Start",
    "clawWebXlsxP01Approve", "clawWebXlsxP01Deny",
  ];
  const elements = Object.fromEntries(ids.map(id => [id, new FakeNode()]));
  elements.clawWebXlsxP01Panel.hidden = true;
  return {
    nodes: elements,
    getElementById(id) { return elements[id] || null; },
    createElement(tag) { return new FakeNode(tag); },
  };
}
function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, async json() { return body; } };
}
async function settle() {
  for (let i = 0; i < 12; ++i) await new Promise(resolve => setImmediate(resolve));
}
function server({ initial = "waiting_p01", enabled = true, failPost = false, failStart = false, badSource = false, workcopy = false, forgedPreviewWrite = false, writeAvailable = false } = {}) {
  let stage = initial, sent = [], starts = [], previews = [], commits = [];
  global.fetch = async (url, options = {}) => {
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.cache, "no-store");
    const method = options.method || "GET";
    if (url === "/api/claw/office/web-sources" && method === "GET") {
      return response({
        ok: true, contract_version: "claw-web-xlsx-source.v1",
        source: "browser_upload", read_authorized_for_processing: false,
        requires_p01_for_processing: true, files: [SRC],
      });
    }
    if (url === "/api/claw/office/web-selections" && method === "GET") {
      return response({
        ok: true, contract_version: "claw-web-xlsx-selection.v1",
        selections: [SELECTION], p01_approval_started: false,
        processing_started: false,
      });
    }
    if (url.endsWith("/p01-status") && method === "GET") {
      return response({
        ok: true, contract_version: "claw-web-xlsx-p01-status.v1",
        selection_ref: REF, document_id: SRC.document_id,
        filename: SRC.filename, size_bytes: SRC.size_bytes,
        source_sha256: badSource ? "f".repeat(64) : SRC.source_sha256,
        status: stage, owner_decision_enabled: enabled && stage === "waiting_p01",
        owner_request_enabled: enabled && stage === "not_requested",
        processing_started: workcopy && stage === "confirmed",
        workcopy_created: workcopy && stage === "confirmed",
        workcopy_document_id: workcopy && stage === "confirmed" ? COPY_ID : null,
      });
    }
    if (url.endsWith("/quote-edit/status") && method === "GET") {
      if (commits.length < 1) return response({ok: false}, 404);
      return response({
        ok: true, contract_version: "claw-web-xlsx-quote-write-status.v1",
        selection_ref: REF, state: "confirmed",
        revision_document_id: "doc_" + "e".repeat(32),
        revision_sha256: "d".repeat(64), revised_xlsx_created: true,
        pdf_exported: false,
      });
    }
    if (url.endsWith("/quote-edit/commit") && method === "POST") {
      assert.ok(writeAvailable && workcopy && stage === "confirmed");
      const body = JSON.parse(options.body);
      assert.deepEqual(Object.keys(body).sort(),
        ["edit_sha256", "school_name", "supply_amount"]);
      commits.push(body);
      return response({
        ok: true, contract_version: "claw-web-xlsx-quote-write.v1",
        selection_ref: REF, state: "confirmed",
        revision_document_id: "doc_" + "e".repeat(32),
        revision_sha256: "d".repeat(64),
        edit_sha256: "a".repeat(64),
        revised_xlsx_created: true, pdf_exported: false,
        original_overwritten: false,
      }, 201);
    }
    if (url.endsWith("/quote-edit/preview") && method === "POST") {
      assert.equal(workcopy && stage === "confirmed", true,
        "Quote preview requires owner-approved existing workcopy");
      const body = JSON.parse(options.body);
      assert.deepEqual(Object.keys(body).sort(), ["school_name", "supply_amount"]);
      previews.push(body);
      const vat = body.supply_amount / 10;
      return response({
        ok: true, contract_version: "claw-web-xlsx-quote-edit-preview.v1",
        selection_ref: REF, original_workcopy_sha256: "b".repeat(64),
        edit_sha256: "a".repeat(64), revision_preview_sha256: "d".repeat(64),
        school_name: body.school_name, supply_amount: body.supply_amount,
        vat_amount: vat, total_amount: body.supply_amount + vat,
        preview_only: true, write_approved: forgedPreviewWrite,
        revised_xlsx_created: false, pdf_exported: false,
        pdf_unsupported: true, requires_independent_p01_write: true,
        write_request_available: writeAvailable,
      });
    }
    if (url.endsWith("/start-p01") && method === "POST") {
      assert.deepEqual(JSON.parse(options.body), {});
      starts.push("start");
      stage = failStart ? "request_unknown" : "waiting_p01";
      if (failStart) return response({ ok: false }, 503);
      return response({ ok: true, contract_version: "claw-web-xlsx-p01-start.v1",
        selection_ref: REF, status: stage, processing_started: false,
        workcopy_created: false }, 202);
    }
    if (url.endsWith("/p01-decision") && method === "POST") {
      const body = JSON.parse(options.body);
      assert.deepEqual(Object.keys(body), ["decision"]);
      assert.ok(["approve", "deny"].includes(body.decision));
      sent.push(body.decision);
      if (failPost) {
        stage = "decision_unknown";
        return response({ ok: false, error: { code: "unknown" } }, 503);
      }
      stage = body.decision === "approve" ? "confirmed" : "denied";
      return response({
        ok: true, contract_version: "claw-web-xlsx-p01-owner-decision.v1",
        selection_ref: REF, status: stage,
        owner_intent_only: !(workcopy && stage === "confirmed"),
        processing_started: workcopy && stage === "confirmed",
        workcopy_created: workcopy && stage === "confirmed",
        workcopy_document_id: workcopy && stage === "confirmed" ? COPY_ID : null,
      });
    }
    throw Error("UNEXPECTED_REQUEST " + method + " " + url);
  };
  return { sent, starts, previews, commits, get stage() { return stage; } };
}
async function prepare(config) {
  const network = server(config);
  const root = fakeRoot();
  const client = ui.init(root);
  assert.ok(client);
  root.nodes.clawWebOfficeDetails.open = true;
  root.nodes.clawWebOfficeDetails.handlers.toggle();
  await settle();
  assert.equal(root.nodes.clawWebXlsxList.children.length, 1);
  const existing = root.nodes.clawWebXlsxList.children[0].children[2];
  assert.ok(existing, "Existing source selection must be visible after page reload");
  existing.handlers.click();
  await settle();
  return { root, client, network, existing };
}
(async () => {
  const ready = await prepare();
  assert.equal(ready.root.nodes.clawWebXlsxP01Panel.hidden, false);
  assert.equal(ready.root.nodes.clawWebXlsxP01Approve.hidden, false);
  assert.equal(ready.root.nodes.clawWebXlsxP01Approve.disabled, false);
  ready.root.nodes.clawWebXlsxP01Approve.handlers.click();
  ready.root.nodes.clawWebXlsxP01Deny.handlers.click();
  await settle();
  assert.deepEqual(ready.network.sent, ["approve"]);
  assert.equal(ready.client.getState().decisionAttempted, true);
  assert.equal(ready.root.nodes.clawWebXlsxP01Approve.hidden, true);
  assert.match(ready.root.nodes.clawWebXlsxP01Status.textContent, /승인/);
  ready.existing.handlers.click(); await settle();
  assert.equal(ready.root.nodes.clawWebXlsxP01Approve.disabled, true);
  ready.root.nodes.clawWebXlsxP01Approve.handlers.click(); await settle();
  assert.deepEqual(ready.network.sent, ["approve"]);

  // A genuine server-generated copy receipt must be accepted and expose ONLY
  // the owner-scoped selection download, never arbitrary R2/object references.
  const copied = await prepare({workcopy: true});
  copied.root.nodes.clawWebXlsxP01Approve.handlers.click(); await settle();
  assert.deepEqual(copied.network.sent, ["approve"]);
  const link = copied.root.nodes.clawWebXlsxP01Panel.children.find(
    item => item.tag === "a" && /작업 사본/.test(item.textContent));
  assert.ok(link);
  assert.equal(link.hidden, false);
  assert.equal(link.href,
    "/api/claw/office/web-selections/" + REF + "/workcopy/download");
  assert.ok(!link.href.includes(COPY_ID));
  copied.existing.handlers.click(); await settle();
  assert.equal(link.hidden, false, "Owner-scoped server readback survives refresh");

  const editForm = copied.root.nodes.clawWebXlsxP01Panel.children.find(
    item => item.tag === "div" && item.children.some(x => x.tag === "button"));
  assert.ok(editForm, "Visible edit preview requires server-approved original");
  assert.equal(editForm.hidden, false);
  const school = editForm.children[0].children[0];
  const supply = editForm.children[1].children[0];
  const previewButton = editForm.children[2];
  const previewStatus = editForm.children[5];
  school.value = "Gwangju University";
  supply.value = "99200000";
  previewButton.handlers.click(); await settle();
  assert.deepEqual(copied.network.previews, [{
    school_name: "Gwangju University", supply_amount: 99_200_000,
  }]);
  assert.match(previewStatus.textContent, /99,200,000/);
  assert.match(previewStatus.textContent, /109,120,000/);
  assert.match(previewStatus.textContent, /PDF/);
  assert.equal(copied.network.sent.length, 1,
    "Preview cannot re-submit the P01 READ approval");
  copied.root.nodes.clawWebXlsxP01Panel.hidden = true;
  copied.existing.handlers.click(); await settle();

  const forged = await prepare({workcopy: true, forgedPreviewWrite: true});
  forged.root.nodes.clawWebXlsxP01Approve.handlers.click(); await settle();
  const forgedForm = forged.root.nodes.clawWebXlsxP01Panel.children.find(
    item => item.tag === "div" && item.children.some(x => x.tag === "button"));
  forgedForm.children[0].children[0].value = "Gwangju University";
  forgedForm.children[1].children[0].value = "99200000";
  forgedForm.children[2].handlers.click(); await settle();
  assert.equal(forged.network.previews.length, 1);
  assert.ok(!/109,120,000/.test(forgedForm.children[5].textContent),
    "Browser must reject forged WRITE-approved preview response");

  const writing = await prepare({workcopy: true, writeAvailable: true});
  writing.root.nodes.clawWebXlsxP01Approve.handlers.click(); await settle();
  const form = writing.root.nodes.clawWebXlsxP01Panel.children.find(
    item => item.tag === "div" && item.children.some(x => x.tag === "button"));
  form.children[0].children[0].value = "Gwangju University";
  form.children[1].children[0].value = "99200000";
  form.children[2].handlers.click(); await settle();
  const commit = form.children[3], revisedLink = form.children[4];
  assert.equal(commit.hidden, false, "Separate Engine WRITE must be enabled");
  commit.handlers.click(); commit.handlers.click(); await settle();
  assert.equal(writing.network.commits.length, 1,
    "Explicit WRITE is ONE-SHOT; never auto-repeat");
  assert.equal(writing.network.commits[0].edit_sha256, "a".repeat(64));
  assert.equal(revisedLink.hidden, false);
  assert.equal(revisedLink.href,
    "/api/claw/office/web-selections/" + REF + "/quote-edit/download");
  assert.ok(!revisedLink.href.includes("doc_"));
  writing.existing.handlers.click(); await settle();
  assert.equal(revisedLink.hidden, false,
    "Owner-only revised XLSX must survive D1 status refresh");
  assert.equal(writing.network.sent.length, 1,
    "WRITE cannot silently replay original READ consent");

  const fresh = await prepare({initial: "not_requested"});
  assert.equal(fresh.root.nodes.clawWebXlsxP01Start.hidden, false);
  fresh.root.nodes.clawWebXlsxP01Start.handlers.click();
  fresh.root.nodes.clawWebXlsxP01Start.handlers.click();
  await settle();
  assert.deepEqual(fresh.network.starts, ["start"]);
  assert.equal(fresh.root.nodes.clawWebXlsxP01Start.disabled, true);
  assert.equal(fresh.root.nodes.clawWebXlsxP01Approve.hidden, false);
  fresh.existing.handlers.click(); await settle();
  assert.equal(fresh.root.nodes.clawWebXlsxP01Start.disabled, true);
  assert.deepEqual(fresh.network.starts, ["start"]);

  const unknownStart = await prepare({ initial: "not_requested", failStart: true });
  unknownStart.root.nodes.clawWebXlsxP01Start.handlers.click(); await settle();
  unknownStart.root.nodes.clawWebXlsxP01Refresh.handlers.click(); await settle();
  unknownStart.existing.handlers.click(); await settle();
  assert.deepEqual(unknownStart.network.starts, ["start"], "uncertain P01 start NEVER retried");

  const denied = await prepare();
  denied.root.nodes.clawWebXlsxP01Deny.handlers.click(); await settle();
  assert.deepEqual(denied.network.sent, ["deny"]);
  assert.match(denied.root.nodes.clawWebXlsxP01Status.textContent, /거절/);

  const unknown = await prepare({ failPost: true });
  unknown.root.nodes.clawWebXlsxP01Approve.handlers.click(); await settle();
  assert.deepEqual(unknown.network.sent, ["approve"]);
  assert.equal(unknown.root.nodes.clawWebXlsxP01Approve.hidden, true);
  unknown.root.nodes.clawWebXlsxP01Refresh.handlers.click(); await settle();
  unknown.existing.handlers.click(); await settle();
  unknown.root.nodes.clawWebXlsxP01Approve.handlers.click(); await settle();
  assert.deepEqual(unknown.network.sent, ["approve"], "uncertain dispatch NEVER retried");

  for (const opts of [
    { initial: "not_requested" }, { initial: "request_unknown" },
    { initial: "expired" }, { initial: "manual_review" },
    { initial: "confirmed" }, { initial: "denied" },
    { initial: "waiting_p01", enabled: false },
    { initial: "waiting_p01", badSource: true },
  ]) {
    const x = await prepare(opts);
    assert.equal(x.root.nodes.clawWebXlsxP01Approve.hidden, true, JSON.stringify(opts));
    assert.equal(x.root.nodes.clawWebXlsxP01Deny.hidden, true, JSON.stringify(opts));
    assert.equal(x.client.getState().ownerDecisionReady, false);
    assert.deepEqual(x.network.sent, []);
  }

  assert.equal(
    ui.validateP01Status(
      { ok: true, contract_version: "claw-web-xlsx-p01-status.v1",
        selection_ref: REF, document_id: SRC.document_id, source_sha256: SRC.source_sha256,
        filename: SRC.filename, size_bytes: SRC.size_bytes,
        status: "waiting_p01", owner_decision_enabled: true,
        processing_started: true, workcopy_created: false }, SRC, REF,
    ), false,
  );
  console.log("WEB_XLSX_ONE_SHOT_WRITE_REVISION_DOWNLOAD=PASS");
  console.log("WEB_XLSX_QUOTE_EDIT_PREVIEW_NO_WRITE=PASS");
  console.log("WEB_XLSX_ACTUAL_WORKCOPY_DOWNLOAD_LINK=PASS");
  console.log("WEB_XLSX_REAL_BROWSER_OWNER_DECISION=PASS");
  console.log("WEB_XLSX_ONE_SHOT_UNKNOWN_OUTCOME=PASS");
  console.log("WEB_XLSX_SERVER_STATUS_ONLY=PASS");
  console.log("WEB_XLSX_BROWSER_START_ONE_SHOT=PASS");
})().catch(error => { console.error(error); process.exitCode = 1; });
