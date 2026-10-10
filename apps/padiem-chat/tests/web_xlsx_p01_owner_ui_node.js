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
    "clawWebXlsxP01Refresh", "clawWebXlsxP01Approve", "clawWebXlsxP01Deny",
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
function server({ initial = "waiting_p01", enabled = true, failPost = false, badSource = false } = {}) {
  let stage = initial, sent = [];
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
        processing_started: false, workcopy_created: false,
      });
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
        selection_ref: REF, status: stage, owner_intent_only: true,
        processing_started: false, workcopy_created: false,
      });
    }
    throw Error("UNEXPECTED_REQUEST " + method + " " + url);
  };
  return { sent, get stage() { return stage; } };
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
  console.log("WEB_XLSX_REAL_BROWSER_OWNER_DECISION=PASS");
  console.log("WEB_XLSX_ONE_SHOT_UNKNOWN_OUTCOME=PASS");
  console.log("WEB_XLSX_SERVER_STATUS_ONLY=PASS");
})().catch(error => { console.error(error); process.exitCode = 1; });
