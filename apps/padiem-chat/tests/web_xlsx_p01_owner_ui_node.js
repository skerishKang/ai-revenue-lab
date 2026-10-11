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
const WORK_CHAT = "chat_" + "f".repeat(32);
const REV_ID = "doc_" + "e".repeat(32);
const REV_SHA = "d".repeat(64);
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
function server({ initial = "waiting_p01", enabled = true, failPost = false, failStart = false, badSource = false, workcopy = false, forgedPreviewWrite = false, writeAvailable = false, pdfAvailable = false, followupAvailable = false, followupForged = false, readConversation = false, readConversationForged = false } = {}) {
  let stage = initial, sent = [], starts = [], previews = [], commits = [],
    writeDecisions = [], pdfPreviews = [], followupReads = [];
  global.fetch = async (url, options = {}) => {
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.cache, "no-store");
    const method = options.method || "GET";
    if (url.includes("/artifact-followup?") && method === "GET") {
      followupReads.push(url);
      return response({ok: true, followup: {
        contract_version: "claw-conversation-artifact-followup.v1",
        status: followupForged ? "not_available" : "resolved",
        source_artifact_id: REV_ID, source_integrity_ref: REV_SHA,
        read_grant_issued: false, source_material_loaded: false,
      }});
    }
    if (url.endsWith("/quote-edit/pdf") && method === "GET") {
      pdfPreviews.push(url);
      assert.equal(options.headers.Accept, "application/pdf");
      if (!pdfAvailable || !writeDecisions.includes("approve")) {
        return response({ok: false}, 404);
      }
      const bytes = Buffer.from("%PDF-1.7\n" + "mock owner quote\n".repeat(15) + "%%EOF\n");
      return {ok: true, status: 200,
        headers: {get(name) {return name === "content-type" ? "application/pdf" : null;}},
        async arrayBuffer() {return Uint8Array.from(bytes).buffer;}};
    }
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
        work_conversation: readConversation && workcopy && stage === "confirmed"
          ? { conversation_id: readConversationForged ? "conv_real_web" : WORK_CHAT }
          : null,
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
        pdf_download_available: pdfAvailable,
        followup: followupAvailable && writeDecisions.includes("approve")
          ? {conversation_id: WORK_CHAT, artifact_id: REV_ID,
            integrity_ref: followupForged ? "a".repeat(64) : REV_SHA}
          : null,
      });
    }
    if (url.endsWith("/quote-edit/approval-status") && method === "GET") {
      if (commits.length < 1) return response({ok:false},404);
      return response({
        ok: true,
        contract_version: "claw-web-xlsx-quote-write-approval-status.v1",
        selection_ref: REF,
        state: writeDecisions.length ? "confirmed" : "waiting_p01",
        edit_sha256: "a".repeat(64),
        school_name: "Gwangju University",
        supply_amount: 99200000,
        write_approved: writeDecisions.length > 0,
        revised_xlsx_created: writeDecisions.length > 0,
        pdf_exported: false,
      });
    }
    if (url.endsWith("/quote-edit/decision") && method === "POST") {
      const body = JSON.parse(options.body);
      assert.deepEqual(Object.keys(body), ["decision"]);
      assert.ok(["approve","deny"].includes(body.decision));
      writeDecisions.push(body.decision);
      if (body.decision === "deny") {
        return response({
          ok: true, contract_version: "claw-web-xlsx-quote-write-decision.v1",
          selection_ref: REF, state: "denied", revised_xlsx_created: false,
          pdf_exported: false,
        });
      }
      return response({
        ok: true, contract_version: "claw-web-xlsx-quote-write.v1",
        selection_ref: REF, state: "confirmed",
        revision_document_id: "doc_" + "e".repeat(32),
        revision_sha256: "d".repeat(64),
        edit_sha256: "a".repeat(64),
        revised_xlsx_created: true, pdf_exported: false,
        pdf_download_available: pdfAvailable,
        original_overwritten: false,
      },201);
    }
    if (url.endsWith("/quote-edit/request") && method === "POST") {
      assert.ok(writeAvailable && workcopy && stage === "confirmed");
      const body = JSON.parse(options.body);
      assert.deepEqual(Object.keys(body).sort(),
        ["edit_sha256", "school_name", "supply_amount"]);
      commits.push(body);
      return response({
        ok: true, contract_version: "claw-web-xlsx-quote-write-pause.v1",
        selection_ref: REF, state: "waiting_p01",
        edit_sha256: "a".repeat(64),
        school_name: body.school_name,
        supply_amount: body.supply_amount,
        write_approved: false,
        revised_xlsx_created: false, pdf_exported: false,
        original_overwritten: false,
      }, 202);
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
  return { sent, starts, previews, commits, writeDecisions, pdfPreviews,
    followupReads,
    get stage() { return stage; } };
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

  // #3936: restoring an already-approved selection right after a page refresh
  // is the FIRST interaction in this scenario. Opening the panel runs reload(),
  // whose setBusy(false) latches editPreviewButton.disabled = true because the
  // edit panel is still hidden at that moment. The restore handler calls
  // showSelection() without a setBusy() wrapper, so nothing recomputes the flag
  // and the edit preview stays unreachable on a refreshed page.
  const restored = await prepare({initial: "confirmed", workcopy: true});
  assert.deepEqual(restored.network.sent, [],
    "Restoring an approved selection must not re-submit a P01 decision");
  const restoredForm = restored.root.nodes.clawWebXlsxP01Panel.children.find(
    item => item.tag === "div" && item.children.some(x => x.tag === "button"));
  assert.ok(restoredForm, "Refreshed approved workcopy must expose the edit panel");
  assert.equal(restoredForm.hidden, false);
  assert.equal(restoredForm.children[2].disabled, false,
    "Restore-after-refresh must keep the edit preview reachable");

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

  const writing = await prepare({
    workcopy: true, writeAvailable: true, pdfAvailable: true,
    followupAvailable: true,
  });
  writing.root.nodes.clawWebXlsxP01Approve.handlers.click(); await settle();
  const form = writing.root.nodes.clawWebXlsxP01Panel.children.find(
    item => item.tag === "div" && item.children.some(x => x.tag === "button"));
  form.children[0].children[0].value = "Gwangju University";
  form.children[1].children[0].value = "99200000";
  form.children[2].handlers.click(); await settle();
  const commit = form.children[3], revisedLink = form.children[4];
  const pdfLink = form.children[8];
  const pdfPreviewButton = form.children[9], pdfPreviewRegion = form.children[10];
  assert.equal(pdfPreviewButton.hidden, true,
    "Before separate WRITE consent PDF preview cannot run");
  assert.equal(pdfPreviewRegion.hidden, true);
  assert.deepEqual(writing.network.pdfPreviews, [], "No implicit billable render");
  assert.equal(pdfLink.hidden,true,"No PDF before independent WRITE consent");
  assert.equal(commit.hidden, false, "Separate Engine WRITE must be enabled");
  commit.handlers.click(); commit.handlers.click(); await settle();
  assert.equal(writing.network.commits.length, 1,
    "Explicit WRITE is ONE-SHOT; never auto-repeat");
  assert.equal(writing.network.commits[0].edit_sha256, "a".repeat(64));
  assert.equal(revisedLink.hidden, true, "WRITE request is NOT approval");
  const yes = form.children[6], no = form.children[7];
  assert.equal(yes.hidden, false);
  assert.equal(no.hidden, false);
  yes.handlers.click(); yes.handlers.click(); await settle();
  assert.deepEqual(writing.network.writeDecisions, ["approve"],
    "Owner must separately authorize Core WRITE, exactly once");
  assert.equal(revisedLink.hidden, false);
  assert.equal(pdfLink.hidden, false);
  assert.match(pdfLink.textContent, /표준 견적 요약 PDF/);
  assert.equal(pdfPreviewButton.hidden, false,
    "Only confirmed independent WRITE creates PDF preview action");
  assert.equal(pdfPreviewRegion.hidden, true, "No automatic PDF render");
  pdfPreviewButton.handlers.click(); await settle();
  assert.equal(writing.network.pdfPreviews.length, 1, "Only explicit owner preview GET");
  assert.equal(pdfPreviewRegion.hidden, false);
  assert.equal(pdfPreviewRegion.children[2].hidden, false, "Bounded PDF bytes are framed");
  assert.match(pdfPreviewRegion.children[2].src, /^blob:/);
  pdfPreviewRegion.children[0].handlers.click();
  assert.equal(pdfPreviewRegion.hidden, true);
  assert.equal(pdfPreviewRegion.children[2].src, "", "Closing revokes displayed PDF");
  assert.equal(writing.network.pdfPreviews.length, 1, "Closing must not re-render");
  assert.equal(pdfLink.href, "/api/claw/office/web-selections/" + REF + "/quote-edit/pdf");
  assert.equal(revisedLink.href,
    "/api/claw/office/web-selections/" + REF + "/quote-edit/download");
  assert.ok(!revisedLink.href.includes("doc_"));
  writing.existing.handlers.click(); await settle();
  assert.equal(revisedLink.hidden, false,
    "Owner-only revised XLSX must survive D1 status refresh");
  assert.equal(pdfLink.hidden, false, "PDF link survives owner-only status refresh");
  assert.equal(pdfPreviewButton.hidden, false, "Owner-only preview survives status refresh");
  assert.equal(pdfPreviewRegion.hidden, true, "Status refresh never auto-renders PDF");
  assert.equal(writing.network.sent.length, 1,
    "WRITE cannot silently replay original READ consent");

  const openConversation = form.children[11];
  assert.match(openConversation.textContent, /작업 대화/);
  assert.equal(openConversation.hidden, false,
    "Only indexed owner revision can expose its work-conversation navigation");
  const events = [];
  global.window = {dispatchEvent(e) {events.push(e);}};
  global.CustomEvent = class {constructor(name, options) {
    this.type = name; this.detail = options.detail;
  }};
  await openConversation.click();
  assert.equal(writing.network.followupReads.length, 1,
    "Navigation must first re-check the exact owner-owned D1 artifact reference");
  assert.match(writing.network.followupReads[0], /selector=exact/);
  assert.equal(events.length, 1);
  assert.equal(events[0].type, "padiem:claw-web-work-conversation-open");
  assert.deepEqual(events[0].detail, {
    conversationId: WORK_CHAT, artifactId: REV_ID, integrityRef: REV_SHA,
  });
  assert.equal(writing.network.writeDecisions.length, 1,
    "Opening the work conversation never replays P01 WRITE or Browser PDF");

  // #3933 READ handoff: the server-verified work-conversation handle for the
  // approved workcopy exposes conversation-only navigation. It must never
  // claim an indexed revision, re-check an artifact or replay READ/WRITE/PDF.
  const readHandoff = await prepare({workcopy: true, readConversation: true});
  readHandoff.root.nodes.clawWebXlsxP01Approve.handlers.click(); await settle();
  const readButton = readHandoff.root.nodes.clawWebXlsxP01Panel.children.find(
    item => item.tag === "button" && /작업 대화/.test(item.textContent));
  assert.ok(readButton, "Verified workcopy must expose the work conversation");
  assert.equal(readButton.hidden, false);
  assert.equal(readHandoff.client.getState().workConversationReady, true);
  assert.equal(readHandoff.network.sent.length, 1);
  const readEvents = [];
  global.window = {dispatchEvent(e) {readEvents.push(e);}};
  global.CustomEvent = class {constructor(name, options) {
    this.type = name; this.detail = options.detail;
  }};
  readButton.handlers.click(); await settle();
  assert.equal(readEvents.length, 1);
  assert.equal(readEvents[0].type, "padiem:claw-web-work-conversation-open");
  assert.deepEqual(readEvents[0].detail, {conversationId: WORK_CHAT},
    "READ handoff carries the conversation handle only, no artifact claim");
  assert.deepEqual(readHandoff.network.followupReads, [],
    "READ handoff must not re-check the revision artifact index");
  assert.equal(readHandoff.network.commits.length, 0);
  assert.equal(readHandoff.network.pdfPreviews.length, 0);
  assert.equal(readHandoff.network.sent.length, 1,
    "READ handoff never replays the P01 READ approval");
  readHandoff.existing.handlers.click(); await settle();
  assert.equal(readButton.hidden, false, "Owner-only handle survives refresh");

  // A malformed conversation id invalidates the whole owner status readback
  // instead of exposing a half-verified handle.
  const forgedHandle = await prepare({
    workcopy: true, readConversation: true, readConversationForged: true,
  });
  forgedHandle.root.nodes.clawWebXlsxP01Approve.handlers.click(); await settle();
  const forgedButton = forgedHandle.root.nodes.clawWebXlsxP01Panel.children.find(
    item => item.tag === "button" && /작업 대화/.test(item.textContent));
  assert.ok(forgedButton, "The closed control must exist");
  assert.equal(forgedButton.hidden, true);
  assert.equal(forgedHandle.client.getState().workConversationReady, false,
    "A malformed conversation handle must invalidate the status readback");
  assert.deepEqual(forgedHandle.network.sent, ["approve"]);
  const forgedDispatched = [];
  global.window = {dispatchEvent(e) {forgedDispatched.push(e);}};
  forgedButton.handlers.click(); await settle();
  assert.deepEqual(forgedDispatched, []);

  // No verified handle yet (no workcopy, or a workcopy without the handle)
  // must never expose the READ handoff button or dispatch any navigation.
  for (const opts of [{workcopy: true}, {readConversation: true}]) {
    const unverified = await prepare(opts);
    assert.equal(unverified.root.nodes.clawWebXlsxP01Approve.hidden, false,
      JSON.stringify(opts));
    unverified.root.nodes.clawWebXlsxP01Approve.handlers.click(); await settle();
    const button = unverified.root.nodes.clawWebXlsxP01Panel.children.find(
      item => item.tag === "button" && /작업 대화/.test(item.textContent));
    assert.ok(button, "The closed control must exist but stay hidden");
    assert.equal(button.hidden, true, JSON.stringify(opts));
    assert.equal(unverified.client.getState().workConversationReady, false,
      JSON.stringify(opts));
    const dispatched = [];
    global.window = {dispatchEvent(e) {dispatched.push(e);}};
    button.handlers.click(); await settle();
    assert.deepEqual(dispatched, [],
      "No unverified conversation handle may ever be dispatched");
    assert.equal(unverified.network.sent.length, 1, JSON.stringify(opts));
  }
  assert.equal(
    ui.validateWorkConversation({conversation_id: WORK_CHAT}, "confirmed", true),
    true,
  );
  for (const [value, state, copy] of [
    [{conversation_id: WORK_CHAT}, "waiting_p01", false],
    [{conversation_id: WORK_CHAT}, "confirmed", false],
    [{conversation_id: "conv_real_web"}, "confirmed", true],
    [{conversation_id: WORK_CHAT, run_id: "x"}, "confirmed", true],
    [{conversation_id: WORK_CHAT}, "confirmed", "true"],
  ]) {
    assert.equal(ui.validateWorkConversation(value, state, copy), false,
      JSON.stringify([value, state, copy]));
  }
  assert.equal(ui.validateWorkConversation(null, "confirmed", false), true);

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
  console.log("WEB_XLSX_PDF_INLINE_PREVIEW_EXPLICIT_OWNER_ONLY=PASS");
  console.log("WEB_XLSX_OWNER_ONLY_PDF_AFTER_WRITE_APPROVAL=PASS");
  console.log("WEB_XLSX_EXPLICIT_CORE_WRITE_TWO_PHASE_OWNER=PASS");
  console.log("WEB_XLSX_ONE_SHOT_WRITE_REVISION_DOWNLOAD=PASS");
  console.log("WEB_XLSX_QUOTE_EDIT_PREVIEW_NO_WRITE=PASS");
  console.log("WEB_XLSX_ACTUAL_WORKCOPY_DOWNLOAD_LINK=PASS");
  console.log("WEB_XLSX_REAL_BROWSER_OWNER_DECISION=PASS");
  console.log("WEB_XLSX_ONE_SHOT_UNKNOWN_OUTCOME=PASS");
  console.log("WEB_XLSX_SERVER_STATUS_ONLY=PASS");
  console.log("WEB_XLSX_BROWSER_START_ONE_SHOT=PASS");
  console.log("WEB_XLSX_READ_WORKCOPY_CONVERSATION_HANDOFF=PASS");
})().catch(error => { console.error(error); process.exitCode = 1; });
