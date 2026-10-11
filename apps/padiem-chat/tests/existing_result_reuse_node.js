"use strict";
/* #3933 existing-result reuse: the REAL connection between the two shipped
 * modules. The read-only conversation context card delegates to the web Excel
 * panel, which performs the ONE owner-scoped adopt call, then selects the NEW
 * document identity so only a brand-new P01 READ approval can start work.
 * Both modules are the real shipped files; only the transport is stubbed. */
const assert = require("node:assert/strict");
const { join } = require("node:path");
const STATIC = join(__dirname, "..", "static");
const panelApi = require(join(STATIC, "claw-web-xlsx-sources.js"));
const contextApi = require(join(STATIC, "claw-conversation-artifact-context.js"));

const CHAT = "chat_" + "a".repeat(32);
const SRC = {
  document_id: "doc_" + "b".repeat(32),
  filename: "hark-quote.xlsx",
  size_bytes: 4096,
  source_sha256: "1".repeat(64),
  original_immutable: true,
  processing_authorized: false,
};
const SRC_REF = "sel_" + "2".repeat(32);
const ARTIFACT = "doc_" + "c".repeat(32);
const ARTIFACT_SHA = "3".repeat(64);
const ADOPTED = {
  document_id: "doc_" + "d".repeat(32),
  filename: "hark-revised-quote.xlsx",
  size_bytes: 1856,
  source_sha256: ARTIFACT_SHA,
  original_immutable: true,
  processing_authorized: false,
};
const ADOPTED_REF = "sel_" + "4".repeat(32);
const RESULT_NAME = "hark-revised-quote.xlsx";

class FakeNode {
  constructor(tag = "div") {
    this.tag = tag; this.hidden = false; this.disabled = false; this.open = false;
    this.textContent = ""; this.className = ""; this.type = "";
    this.children = []; this.handlers = {}; this.value = ""; this.files = null;
  }
  addEventListener(name, callback) { this.handlers[name] = callback; }
  append(...elements) { this.children.push(...elements); }
  appendChild(node) { this.children.push(node); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this[name] = value; }
  querySelector() { return null; }
  scrollIntoView() { this.scrolled = true; }
  async click() { return this.handlers.click?.(); }
}

const PANEL_IDS = [
  "clawWebOfficeDetails", "clawWebXlsxInput", "clawWebXlsxSave",
  "clawWebXlsxRefresh", "clawWebXlsxNotice", "clawWebXlsxList",
  "clawWebXlsxP01Panel", "clawWebXlsxP01Selected", "clawWebXlsxP01Status",
  "clawWebXlsxP01Refresh", "clawWebXlsxP01Start",
  "clawWebXlsxP01Approve", "clawWebXlsxP01Deny",
];

function fakeDocument() {
  const nodes = Object.fromEntries(PANEL_IDS.map((id) => [id, new FakeNode()]));
  nodes.clawWebXlsxP01Panel.hidden = true;
  return {
    nodes,
    getElementById(id) { return nodes[id] || null; },
    createElement(tag) { return new FakeNode(tag); },
  };
}

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300, status,
    async json() { return body; },
  };
}

async function settle() {
  for (let index = 0; index < 16; ++index) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

function textOf(node) {
  return [node.textContent, ...node.children.map(textOf)].join(" ");
}

/* One shared stub transport for BOTH modules. It records every call so the
 * test can prove which module made which request. */
function stubServer() {
  const log = [];
  let adopted = null;
  let selections = [{
    selection_ref: SRC_REF, document_id: SRC.document_id,
    filename: SRC.filename, size_bytes: SRC.size_bytes,
    source_sha256: SRC.source_sha256,
    status: "source_selected_p01_not_started",
    p01_approval_started: false, processing_started: false,
  }];
  global.fetch = async (url, options = {}) => {
    const method = options.method || "GET";
    log.push({ url, method });
    if (url.endsWith("/artifact-followup?kind=xlsx&selector=latest")) {
      return response({ ok: true, followup: {
        contract_version: "claw-conversation-artifact-followup.v1",
        status: "resolved",
        source_artifact_id: ARTIFACT, source_integrity_ref: ARTIFACT_SHA,
        source_run_ref: "run_reuse_1", source_filename: RESULT_NAME,
        choices: [],
        read_grant_issued: false, source_material_loaded: false,
        memory_restored: false, provider_write_authorized: false,
      }});
    }
    if (url.endsWith("/artifact-followup/adopt") && method === "POST") {
      assert.equal(url, "/api/claw/conversations/" + CHAT
        + "/artifact-followup/adopt");
      const body = JSON.parse(options.body);
      assert.deepEqual(Object.keys(body).sort(), ["artifact_id", "integrity_ref"]);
      assert.equal(body.artifact_id, ARTIFACT);
      assert.equal(body.integrity_ref, ARTIFACT_SHA);
      adopted = ADOPTED;
      return response({
        ok: true, contract_version: "claw-web-xlsx-source-adopt.v1",
        file: ADOPTED, source: "previous_completed_result",
        adopted_from_artifact_id: ARTIFACT,
        p01_approval_started: false, processing_started: false,
        p01_approved: false, drive_uploaded: false, workcopy_created: false,
        previous_approval_reused: false, read_grant_issued: false,
        source_material_loaded: false, provider_write_authorized: false,
        memory_restored: false,
      }, 201);
    }
    if (url === "/api/claw/office/web-sources" && method === "GET") {
      return response({
        ok: true, contract_version: "claw-web-xlsx-source.v1",
        source: "browser_upload", read_authorized_for_processing: false,
        requires_p01_for_processing: true,
        files: adopted === null ? [SRC] : [SRC, adopted],
      });
    }
    if (url === "/api/claw/office/web-selections" && method === "GET") {
      return response({
        ok: true, contract_version: "claw-web-xlsx-selection.v1",
        selections, p01_approval_started: false, processing_started: false,
      });
    }
    if (url === "/api/claw/office/web-selections" && method === "POST") {
      const body = JSON.parse(options.body);
      assert.deepEqual(Object.keys(body), ["document_id"]);
      assert.equal(body.document_id, ADOPTED.document_id,
        "Only the adopted NEW identity may be selected");
      selections = [{
        selection_ref: ADOPTED_REF, document_id: ADOPTED.document_id,
        filename: ADOPTED.filename, size_bytes: ADOPTED.size_bytes,
        source_sha256: ADOPTED.source_sha256,
        status: "source_selected_p01_not_started",
        p01_approval_started: false, processing_started: false,
      }];
      return response({
        ok: true, contract_version: "claw-web-xlsx-selection.v1",
        selection: selections[0], p01_approval_started: false,
        processing_started: false, workcopy_created: false,
        drive_uploaded: false,
      }, 201);
    }
    if (url.endsWith("/p01-status") && method === "GET") {
      assert.ok(url.includes(ADOPTED_REF),
        "Only the brand-new selection may be status-checked");
      return response({
        ok: true, contract_version: "claw-web-xlsx-p01-status.v1",
        selection_ref: ADOPTED_REF, document_id: ADOPTED.document_id,
        filename: ADOPTED.filename, size_bytes: ADOPTED.size_bytes,
        source_sha256: ADOPTED.source_sha256,
        status: "not_requested", owner_decision_enabled: false,
        owner_request_enabled: true,
        processing_started: false, workcopy_created: false,
        workcopy_document_id: null, work_conversation: null,
      });
    }
    // No revision exists for the brand-new source yet.
    return response({ ok: false, error: { code: "web_xlsx_write_not_found" } }, 404);
  };
  return {
    log,
    urls: () => log.map((entry) => entry.url),
    count: (fragment) => log.filter(
      (entry) => entry.url.includes(fragment)).length,
  };
}

(async () => {
  const doc = fakeDocument();
  const server = stubServer();
  // The context module resolves the panel through the same window global the
  // shipped page uses; the panel module owns the single adopt call.
  global.window = { PadiemClawWebXlsxSources: panelApi };
  try {
    const panel = panelApi.init(doc);
    assert.ok(panel, "the real panel module must bind");
    const host = {
      hidden: true, children: [], ownerDocument: doc, attributes: {},
      append(...elements) { this.children.push(...elements); },
      replaceChildren(...nodes) { this.children = nodes; },
      setAttribute(name, value) { this.attributes[name] = value; },
    };
    const context = contextApi.init(host);
    assert.ok(context, "the real context module must bind");

    // 1. The owner's completed result is shown as a verified reference.
    await context.show(CHAT);
    await settle();
    assert.equal(host.hidden, false);
    assert.match(textOf({ textContent: "", children: host.children }),
      new RegExp(RESULT_NAME.replace(".", "\\.")));
    assert.equal(server.count("/artifact-followup?"), 1);
    assert.equal(server.count("/artifact-followup/adopt"), 0,
      "Showing the reference must never adopt it");

    // 2. Clicking "continue" delegates to the panel: exactly one adopt call.
    const resume = host.children.find(
      (node) => node.tag === "button" && /이어서 작업/.test(node.textContent));
    assert.ok(resume, "the resolved card must offer the continue action");
    await resume.click();
    await settle();
    assert.equal(server.count("/artifact-followup/adopt"), 1,
      "The panel performs the ONE owner-scoped adopt call");
    assert.equal(doc.nodes.clawWebOfficeDetails.open, true,
      "The new source is shown where it will be worked on");

    // 3. The adopted NEW identity is listed and selected, which is a NEW
    //    selection with NO approval history at all.
    assert.equal(doc.nodes.clawWebXlsxList.children.length, 2,
      "The adopted result appears beside the original upload");
    assert.equal(panel.getState().selectedDocumentId, ADOPTED.document_id);
    assert.equal(panel.getState().selectedSelectionRef, ADOPTED_REF);
    assert.equal(server.count("/p01-status"), 1,
      "The brand-new selection is the only one status-checked");

    // 4. The only possible next step is a NEW P01 READ request; the previous
    //    approval, workcopy and WRITE receipt are all absent.
    assert.equal(panel.getState().ownerRequestReady, true);
    assert.equal(panel.getState().ownerDecisionReady, false);
    assert.equal(doc.nodes.clawWebXlsxP01Start.hidden, false);
    assert.equal(doc.nodes.clawWebXlsxP01Start.disabled, false);
    assert.equal(doc.nodes.clawWebXlsxP01Approve.hidden, true);
    assert.equal(doc.nodes.clawWebXlsxP01Deny.hidden, true);
    assert.equal(server.count("/p01-decision"), 0, "No decision is replayed");
    assert.equal(server.count("/quote-edit/request"), 0, "No WRITE is replayed");
    assert.equal(server.count("/quote-edit/pdf"), 0, "No billable PDF render");
    assert.equal(server.count("/start-p01"), 0,
      "Processing is NOT started automatically; the owner must approve first");
    const workcopy = doc.nodes.clawWebXlsxP01Panel.children.find(
      (node) => node.tag === "a" && /작업 사본/.test(node.textContent));
    assert.ok(workcopy);
    assert.equal(workcopy.hidden, true,
      "The previous workcopy must never carry over to the new source");
    assert.match(doc.nodes.clawWebXlsxNotice.textContent, /새 P01 읽기 승인/);

    // 5. The owner now explicitly starts and approves the NEW READ request.
    doc.nodes.clawWebXlsxP01Start.handlers.click();
    await settle();
    assert.equal(server.count("/start-p01"), 1);
    assert.equal(server.count("/artifact-followup/adopt"), 1,
      "Starting the new approval must not re-adopt the result");

    console.log("EXISTING_RESULT_REUSE_CONTEXT_TO_PANEL_CONNECTION=PASS");
    console.log("EXISTING_RESULT_REUSE_ADOPT_MINTS_NEW_IDENTITY=PASS");
    console.log("EXISTING_RESULT_REUSE_NEW_READ_APPROVAL_REQUIRED=PASS");
  } finally {
    delete global.window;
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
