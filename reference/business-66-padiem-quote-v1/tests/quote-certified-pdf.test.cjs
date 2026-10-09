const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const Core = require("../quote-core.js");
const Template = require("../quote-template.js");
const Renderer = require("../quote-template-renderer.js");
const source = (name) => fs.readFileSync(path.join(__dirname, "..", name), "utf8");
const clone = (value) => JSON.parse(JSON.stringify(value));
const flush = () => new Promise((resolve) => setImmediate(resolve));
const SKILL_ID = "b66skill_" + "a".repeat(32);
const ASSET_ID = "b66asset_" + "b".repeat(32);
const SELECTED_MODEL_ID = "synthetic/pdf-contract";
const content = clone(Template.builtInTemplate().content);
content.slots = { logo: ASSET_ID, stamp: "" };
const profile = Template.buildProfile({
  id: "pdf-test", name: "Synthetic PDF", builtin: false, isDefault: false,
  approval: { schemaVersion: 1, status: "approved", contentFingerprint: Template.templateFingerprint(content), approvedBy: "test-owner", approvedAt: "2026-10-07T00:00:00Z" },
  createdAt: "2026-10-07T00:00:00Z", updatedAt: "2026-10-07T00:00:00Z", content
});
const draft = Core.createProductionDraft();
draft.meta.quoteNo = "PDF-20261007-001";
draft.meta.issueDate = "2026-10-07";
draft.sender.company = "Synthetic Supplier";
draft.recipient.company = "Synthetic Recipient";
draft.items = [{ id: "item-1", name: "Synthetic Item", qty: 1, unitPrice: 10015 }];
draft.calculationPolicy = { grandRounding: { mode: "FLOOR", unit: 10 } };

function verifyProjection() {
  const opts = { slotSources: { logo: { assetId: ASSET_ID, dataUrl: "data:image/png;base64,iVBORw==" } } };
  const preview = Renderer.buildRenderModel(draft, profile, opts);
  assert.equal(preview.slots.logo.rendered, true);
  const model = Renderer.buildCertifiedPdfRenderModel(draft, profile, opts);
  assert.deepEqual(model.coreTotals, Core.computeDraftTotals(Core.normalizeDraft(draft)));
  assert.equal(model.writtenWords, Core.formatKoreanMoneyWords(model.coreTotals.grand));
  assert.equal(model.coreTotals.grand, 11010);
  assert.equal(model.coreTotals.roundingAdjustment, -7);
  assert.deepEqual(model.facts, preview.facts);
  assert.deepEqual(model.items, preview.items);
  assert.deepEqual(model.totals, preview.totals);
  assert.deepEqual(Object.keys(model).sort(), ["schemaVersion", "derivedBy", "template", "facts", "items", "totals", "coreTotals", "writtenWords", "taxReview"].sort());
  assert.equal(JSON.stringify(model).includes("data:image"), false);
  assert.equal(Renderer.buildCertifiedPdfRenderModel(draft, null), null);
  assert.equal(Renderer.buildCertifiedPdfRenderModel(draft, profile, { taxReviewRequired: true }), null);
  const detailed = clone(draft);
  detailed.detailGroups = [{ id: "group-1", summaryItemId: "item-1", items: [{ id: "detail-1", name: "Detail", qty: 1, unitPrice: 2 }] }];
  assert.equal(Renderer.buildCertifiedPdfRenderModel(detailed, profile), null);
  return model;
}

function accountHarness({ authenticated = true, withSkill = true, cgiExport = false } = {}) {
  const elements = new Map();
  const calls = [];
  const downloads = [];
  const blobs = [];
  const revoked = [];
  const handlers = new Map();
  let responseFactory = () => new Response("%PDF-1.7\nsynthetic", { headers: { "Content-Type": "application/pdf", "Content-Disposition": "attachment; filename*=UTF-8''%ED%85%8C%EC%8A%A4%ED%8A%B8.pdf" } });
  const makeElement = (tag) => ({
    value: "", children: [], dataset: {}, hidden: false,
    addEventListener(type, fn) { handlers.set(tag + ":" + type, fn); },
    append(...children) { this.children.push(...children); if (!this.value && children.length) this.value = children[0].value; },
    appendChild(child) { this.children.push(child); },
    replaceChildren() { this.children = []; this.value = ""; },
    click() { if (tag === "a") downloads.push({ filename: this.download, href: this.href }); },
    remove() {}, setAttribute() {}, removeAttribute() {}, focus() {}, scrollIntoView() {}
  });
  const getElement = (id) => { if (!elements.has(id)) elements.set(id, makeElement(id)); return elements.get(id); };
  const skill = { id: "synthetic-skill", name: "Synthetic Skill", approved: true, fingerprint: "synthetic-skill-fingerprint", internalTemplate: profile, variableSchema: { recipient: true, items: true } };
  const rowId = cgiExport ? "b66skill_2eb55d822407f626b7a75c8c88d32c40" : SKILL_ID;
  const row = { saved_skill_id: rowId, skill_name: skill.name, skill, skill_fingerprint: skill.fingerprint };
  const browserCalls = [];
  const json = (data) => new Response(JSON.stringify(data), { headers: { "Content-Type": "application/json" } });
  const context = vm.createContext({
    Blob, Uint8Array, setTimeout, clearTimeout,
    URL: { createObjectURL(blob) { blobs.push(blob); return "blob:synthetic"; }, revokeObjectURL(url) { revoked.push(url); } },
    btoa: (value) => Buffer.from(value, "binary").toString("base64"),
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    SavedQuoteSkill: { normalizeSkill: (value) => value },
    B66QuoteAppBridge: { createFreshDraft: () => Core.createProductionDraft() },
    B66BrowserPdf: cgiExport ? {
      isCgiSkill: (id) => id === rowId,
      async makePdf(renderModel, previewModel) {
        browserCalls.push({ renderModel, previewModel });
        return new Uint8Array(Buffer.from("%PDF-1.4\nCI browser proof"));
      }
    } : undefined,
    B66QuoteSkillBridge: { setServerSkill: () => true, clearServerSkill() {} },
    document: { readyState: "complete", body: makeElement("body"), getElementById: getElement, createElement: makeElement, dispatchEvent() {}, addEventListener() {} },
    fetch: async (url, opts = {}) => {
      calls.push({ url: String(url), opts });
      if (String(url).endsWith("/auth/status")) return json({ authenticated, session_state: authenticated ? "signed_in" : "signed_out", user: {}, methods: {} });
      if (String(url).includes("/saved-skills?")) return json({ skills: withSkill ? [row] : [] });
      if (String(url).endsWith("/saved-skills/" + rowId)) return json({ saved_skill: row });
      if (String(url).endsWith("/company-profile")) return json({ company_profile: { company: "Synthetic Supplier" } });
      if (String(url).includes("/assets/")) return new Response(new Uint8Array([137, 80, 78, 71]), { headers: { "Content-Type": "image/png" } });
      if (String(url).endsWith("/quote/models")) return json({
        ok: true, models: [{ model_id: SELECTED_MODEL_ID, name: "Synthetic PDF Contract Model" }],
        default_model_id: null
      });
      if (String(url).endsWith("/quote/pdf")) return responseFactory();
      if (String(url).endsWith("/quote/interpret")) return json({ ok: true, candidate: { recipient: { company: "Synthetic Recipient" }, items: [{ name: "Synthetic Item", qty: 1, unitPrice: null }], missing: ["unitPrice"] } });
      throw new Error("unexpected test endpoint");
    }
  });
  context.window = context;
  new vm.Script(source("padiem-account.js")).runInContext(context);
  return { bridge: context.B66QuoteRuntimeBridge, calls, downloads, blobs, revoked, elements, browserCalls, setResponse: (fn) => { responseFactory = fn; } };
}

async function verifyAccountDownload(model) {
  const signedOut = accountHarness({ authenticated: false });
  await flush();
  const before = signedOut.calls.length;
  assert.equal((await signedOut.bridge.downloadPdf(model)).code, "auth_required");
  assert.equal(signedOut.calls.length, before);
  const noSkill = accountHarness({ withSkill: false });
  await flush();
  assert.equal((await noSkill.bridge.downloadPdf(model)).code, "skill_not_ready");
  const harness = accountHarness();
  await flush();
  assert.equal(harness.bridge.readiness().ready, true);
  const badFingerprint = clone(model);
  badFingerprint.template.fingerprint = "wrong";
  const initial = harness.calls.length;
  assert.equal((await harness.bridge.downloadPdf(badFingerprint)).code, "pdf_skill_mismatch");
  assert.equal(harness.calls.length, initial);
  const detailed = clone(model);
  detailed.coreTotals.detailGroups = [{}];
  assert.equal((await harness.bridge.downloadPdf(detailed)).code, "invalid_pdf_model");
  const oversized = clone(model);
  oversized.facts.meta.projectName = "x".repeat(33 * 1024);
  assert.equal((await harness.bridge.downloadPdf(oversized)).code, "pdf_request_too_large");
  assert.equal(harness.calls.length, initial);
  const success = await harness.bridge.downloadPdf(model);
  assert.equal(success.ok, true);
  assert.equal(success.filename, "테스트.pdf");
  const request = harness.calls.at(-1);
  assert.equal(request.url, "/api/padiem/b66/quote/pdf");
  assert.equal(request.opts.credentials, "same-origin");
  assert.equal(request.opts.cache, "no-store");
  assert.deepEqual(JSON.parse(request.opts.body), { saved_skill_id: SKILL_ID, render_model: model });
  assert.equal(harness.blobs[0].type, "application/pdf");
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.deepEqual(harness.revoked, ["blob:synthetic"]);
  assert.equal(harness.downloads.length, 1);
  const errors = [
    [() => new Response('{"error":{"message":"PDF 양식 준비 중"}}', { status: 503, headers: { "Content-Type": "application/json" } }), "pdf_render_failed"],
    [() => new Response("%PDF-1.7", { headers: { "Content-Type": "text/html" } }), "pdf_media_invalid"],
    [() => new Response("", { headers: { "Content-Type": "application/pdf" } }), "pdf_bytes_invalid"],
    [() => new Response("<html>error</html>", { headers: { "Content-Type": "application/pdf" } }), "pdf_bytes_invalid"]
  ];
  for (const [response, code] of errors) {
    harness.setResponse(response);
    assert.equal((await harness.bridge.downloadPdf(model)).code, code);
    assert.equal(harness.downloads.length, 1);
  }
  harness.setResponse(() => new Response("%PDF-1.7", { headers: { "Content-Type": "application/pdf" } }));
  assert.equal((await harness.bridge.downloadPdf(model)).filename, draft.meta.quoteNo + ".pdf");
  harness.elements.get("padiemSavedSkillSelect").value = "";
  const selectedBefore = harness.calls.length;
  assert.equal((await harness.bridge.downloadPdf(model)).code, "pdf_skill_mismatch");
  assert.equal(harness.calls.length, selectedBefore);
  harness.elements.get("padiemSavedSkillSelect").value = SKILL_ID;
  // #3760: registered does not mean implicitly selected. No model => no POST,
  // no pending quote and no change to the existing certified PDF path.
  const unselectedBefore = harness.calls.length;
  const unselected = await harness.bridge.interpret("Synthetic partial quote");
  assert.equal(unselected.code, "model_selection_required");
  assert.equal(harness.calls.length, unselectedBefore);
  assert.equal(harness.bridge.pendingQuote(), null);
  harness.elements.get("padiemQuoteModelSelect").value = SELECTED_MODEL_ID;
  const pending = await harness.bridge.interpret("Synthetic partial quote");
  assert.equal(pending.code, "incomplete_request");
  assert.ok(harness.bridge.pendingQuote());
  const interpreted = harness.calls.slice(unselectedBefore);
  assert.equal(interpreted.length, 1, "one selected-model request, no retry");
  assert.equal(interpreted[0].url, "/api/padiem/b66/quote/interpret");
  assert.equal(JSON.parse(interpreted[0].opts.body).model_id, SELECTED_MODEL_ID);
  const pendingBefore = harness.calls.length;
  assert.equal((await harness.bridge.downloadPdf(model)).code, "pending_quote");
  assert.equal(harness.calls.length, pendingBefore);
  harness.bridge.clearPending();
  const racing = accountHarness();
  await flush();
  racing.setResponse(() => {
    racing.elements.get("padiemSavedSkillSelect").value = "";
    return new Response("%PDF-1.7", { headers: { "Content-Type": "application/pdf" } });
  });
  assert.equal((await racing.bridge.downloadPdf(model)).code, "pdf_skill_changed");
  assert.equal(racing.downloads.length, 0);
}

async function verifyCgiBrowserPath(model) {
  const harness = accountHarness({ cgiExport: true });
  await flush();
  const view = { layoutVariant: "cgi-v2", template: model.template };
  const result = await harness.bridge.downloadPdf(model, view);
  assert.equal(result.ok, true);
  assert.equal(harness.browserCalls.length, 1);
  assert.equal(harness.browserCalls[0].previewModel, view);
  assert.equal(harness.downloads.length, 1);
  assert.equal(harness.blobs[0].type, "application/pdf");
  assert.equal(harness.calls.some((call) => call.url.endsWith("/quote/pdf")), false,
    "CGI must NEVER silently call old Worker");
  const invalid = clone(model);
  invalid.template.fingerprint = "tampered";
  const count = harness.browserCalls.length;
  assert.equal((await harness.bridge.downloadPdf(invalid, view)).code, "pdf_skill_mismatch");
  assert.equal(harness.browserCalls.length, count);
  assert.equal(harness.downloads.length, 1);
  console.log("CGI_BROWSER_ACCOUNT_DOWNLOAD=PASS");
  console.log("CGI_OLD_PDF_ENDPOINT_CALLS=0");
}

async function verifyAppButton(model) {
  const app = source("app.js");
  assert.equal(app.includes("window.print()"), false);
  const action = app.slice(app.indexOf("  let pdfDownloadPending = false;"), app.indexOf('  $("emailFuture").addEventListener'));
  let handler;
  let readinessFailure = { code: "tax_review", message: "VAT required" };
  let downloads = 0;
  let taxFocused = 0;
  let release;
  const button = { disabled: false, addEventListener(type, fn) { handler = fn; } };
  const context = vm.createContext({
    draft, taxReviewRequired: false,
    $: (id) => id === "printPdf" ? button : { addEventListener() {} },
    printReadinessFailure: () => readinessFailure,
    focusTaxReview: () => { taxFocused++; }, focusReadinessTarget() {}, toast() {},
    activeSkillProfile: () => profile,
    TemplateRenderer: { buildCertifiedPdfRenderModel: () => model },
    window: { B66QuoteRuntimeBridge: { downloadPdf: () => { downloads++; return new Promise((resolve) => { release = resolve; }); } } }
  });
  new vm.Script(action).runInContext(context);
  await handler();
  assert.equal(downloads, 0);
  assert.equal(taxFocused, 1);
  readinessFailure = null;
  const running = handler();
  assert.equal(button.disabled, true);
  await handler();
  assert.equal(downloads, 1);
  release({ ok: true });
  await running;
  assert.equal(button.disabled, false);
}

(async () => {
  const model = verifyProjection();
  await verifyAccountDownload(model);
  await verifyCgiBrowserPath(model);
  await verifyAppButton(model);
  console.log("CERTIFIED_PDF_FRONTEND_CONTRACT=PASS");
  console.log("QUOTE_CORE_FINAL_VALUES_PRESERVED=PASS");
  console.log("PRIVATE_PREVIEW_ASSETS_OMITTED=PASS");
  console.log("HTML_PRINT_PDF_FALLBACK=0");
})().catch((error) => { console.error(error); process.exitCode = 1; });
