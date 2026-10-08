const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const Renderer = require("../quote-template-renderer.js");
const Browser = require("../quote-browser-pdf.js");
const clone = (x) => JSON.parse(JSON.stringify(x));
const base = {
  schemaVersion: 1, derivedBy: "quote-core",
  template: { id: "approved", approved: true, fingerprint: "a".repeat(64) },
  facts: {
    meta: { quoteNo: "CGI-20261008-1", issueDate: "2026-10-08", projectName: "배관 공사" },
    recipient: { company: "대한건설" }, taxRateText: "10%"
  },
  items: [{ filler: false, values: { name: "배관", qty: "100", unitPrice: "₩18,000", amount: "₩1,800,000" } }],
  totals: { subtotalText: "₩1,800,000", vatText: "₩180,000", grandText: "₩1,980,000" },
  coreTotals: { effectiveItems: [{ name: "배관", qty: 100, unitPrice: 18000 }],
    amounts: [1800000], supply: 1800000, vat: 180000, grand: 1980000, detailGroups: [] },
  writtenWords: "일백구십팔만원", taxReview: { required: false }
};
const preview = Object.assign({}, clone(base), {
  layoutVariant: "cgi-v2", certifiedPreviewBaseUrl: Browser.PREVIEW_URL,
  writtenTotalText: "합계금액 : 일금 일백구십팔만원정"
});
function rejection(modify, expected) {
  const model = clone(base), shown = clone(preview);
  modify(model, shown);
  assert.throws(() => Browser.project(model, shown),
    (err) => err.code === expected, expected);
}
function verifyOwnerSkillPersistence() {
  const src = fs.readFileSync(path.join(__dirname, "..", "app.js"), "utf8");
  const start = src.indexOf("  function applySkillToForm(skill) {");
  const end = src.indexOf("\n  function setServerSkill(", start + 15);
  assert.ok(start >= 0 && end > start);
  const source = src.slice(start, end).trim();
  function probe(skillId, requested) {
    const protectedSkill = { id: "semantic-skill-internal", approved: true };
    const privateSlots = { logo: { rendered: true } };
    const status = {
      serverSkill: protectedSkill,
      serverSavedSkillId: skillId,
      serverSlotSources: privateSlots,
      activeSkillId: skillId
    };
    let rendered = 0, toasted = 0;
    const ctx = {
      skillUiState: status,
      window: { B66BrowserPdf: Browser },
      SkillUi: { formValuesFromSkill() { throw new Error("owner selection unexpectedly called local UI"); } },
      render() { rendered++; },
      toast() { toasted++; }
    };
    const apply = vm.runInNewContext("(" + source + ")", ctx);
    const response = apply(requested);
    return { response, status, protectedSkill, privateSlots, rendered, toasted };
  }
  const unchanged = probe(Browser.CGI_SKILL_ID, null);
  assert.equal(unchanged.response, true);
  assert.equal(unchanged.status.serverSkill, unchanged.protectedSkill);
  assert.equal(unchanged.status.serverSlotSources, unchanged.privateSlots);
  assert.equal(unchanged.status.activeSkillId, Browser.CGI_SKILL_ID);
  assert.equal(unchanged.status.serverSavedSkillId, Browser.CGI_SKILL_ID);
  assert.notEqual(unchanged.status.serverSkill.id, unchanged.status.serverSavedSkillId);
  assert.equal(unchanged.rendered, 0, "no transient fallback render");
  assert.equal(unchanged.toasted, 0, "no confusing local-skill toast");
  const blocked = probe(Browser.CGI_SKILL_ID, { id: "b66skill_" + "d".repeat(32) });
  assert.equal(blocked.status.serverSkill, blocked.protectedSkill, "foreign local skill cannot replace active CGI");
  const other = probe("b66skill_" + "d".repeat(32), null);
  assert.equal(other.status.serverSkill, null, "non-CGI still follows existing local reset semantics");
  assert.equal(other.status.serverSavedSkillId, null);
  console.log("CGI_ASSIGNED_SKILL_STICKY_WHILE_SIGNED_IN=PASS");
  console.log("NON_CGI_LOCAL_SKILL_RESET_UNCHANGED=PASS");
}

function verifyAssignedRowIdentity() {
  const src = fs.readFileSync(path.join(__dirname, "..", "app.js"), "utf8");
  const start = src.indexOf("  function setServerSkill(");
  const end = src.indexOf("\n  function clearServerSkill()", start);
  assert.ok(start > 0 && end > start, "actual setServerSkill source required");
  const target = src.slice(start, end).trim();
  function probe(savedId) {
    const semantic = { id: "approved-cgi-semantic-id", approved: true,
      fingerprint: "sha-owned-skill", internalTemplate: { approved:true, fingerprint:"approved-profile-fp" } };
    const state = { serverSkill:null, serverSavedSkillId:null, activeSkillId:null,
      serverSlotSources: {} };
    const suppliedSlots = { logo: "private-reference-only" };
    let renders = 0;
    const sandbox = {
      skillUiState:state,
      window:{ B66BrowserPdf:Browser },
      SavedSkill:{ normalizeSkill(v){return v;} },
      Template:{ normalizeTemplate(v){return v;}, isApprovedProfile(v){return v.approved === true;} },
      renderTemplateUi(){}, render(){renders++;}
    };
    const fn=vm.runInNewContext("(" + target + ")", sandbox);
    assert.equal(fn(semantic,suppliedSlots,savedId),true);
    return {state,semantic,suppliedSlots,renders};
  }
  const cgi=probe(Browser.CGI_SKILL_ID);
  assert.equal(cgi.state.serverSavedSkillId,Browser.CGI_SKILL_ID);
  assert.equal(cgi.state.activeSkillId,Browser.CGI_SKILL_ID);
  assert.equal(cgi.state.serverSkill,cgi.semantic);
  assert.equal(cgi.semantic.id,"approved-cgi-semantic-id","semantic ID must remain intact");
  assert.equal(cgi.state.serverSlotSources,cgi.suppliedSlots);
  assert.equal(cgi.renders,1);
  const other=probe("b66skill_" + "e".repeat(32));
  assert.equal(other.state.activeSkillId,other.semantic.id,"non-CGI remains on established legacy semantic ID");
  assert.equal(other.state.serverSavedSkillId,other.semantic.id);
  const account=fs.readFileSync(path.join(__dirname, "..", "padiem-account.js"),"utf8");
  assert.ok(account.includes("bridge.setServerSkill(skill, slotSources, savedSkillId)"));
  assert.ok(account.includes("row.saved_skill_id !== savedSkillId"));
  console.log("B66_CGI_ROW_ID_NE_SEMANTIC_SKILL_ID=PASS");
  console.log("B66_CGI_OWNER_ID_USED_END_TO_END=PASS");
}

function verifyLiveRenderAuthority() {
  const app = fs.readFileSync(path.join(__dirname, "..", "app.js"), "utf8");
  const begin = app.indexOf("  function render() {");
  const end = app.indexOf("\n  /*", begin + 20);
  assert.ok(begin > 0 && end > begin, "actual render() source must be extractable");
  const renderSource = app.slice(begin, end).trim();
  const cgiProfile = { id: "assigned-approved", fingerprint: "fingerprint-assigned", approved: true };
  const genericProfile = { id: "previous-generic", fingerprint: "fingerprint-generic", approved: true };
  const profilePreview = { id: "management-preview", fingerprint: "fingerprint-preview", approved: true };
  function probe({ skillId, serverSkillId, previewMode = false }) {
    const selected = [], applied = [];
    const ctx = {
      $: () => null,
      previewTemplateProfile: () => previewMode ? profilePreview : null,
      renderTemplateAuthority: () => genericProfile,
      skillUiState: { activeSkillId: skillId, serverSavedSkillId: serverSkillId,
        serverSkill: { id: "internal-skill-is-not-a-db-row-id" }, serverSlotSources: {} },
      activeSkillProfile: () => cgiProfile,
      TemplateRenderer: {
        buildRenderModel: (_draft, authority, options) => {
          selected.push(authority);
          return { derivedBy: "quote-core", template: authority, certifiedPreviewBaseUrl: options.certifiedPreviewBaseUrl };
        },
        applyRenderModel: (_doc, model) => applied.push(model)
      },
      draft: {}, taxReviewRequired: false,
      window: {
        B66BrowserPdf: {
          isCgiSkill: (id) => id === Browser.CGI_SKILL_ID,
          certifiedPreviewModel: (model, _id, fp) => ({ ...model, layoutVariant: "cgi-v2", boundFingerprint: fp })
        },
        B66QuoteRuntimeBridge: { certifiedPreviewBaseUrl: (id) => id }
      },
      document: { querySelectorAll: () => [] },
      Core: { computeDraftTotals: () => null },
      saveDraft() {}
    };
    vm.runInNewContext("(" + renderSource + ")", ctx)();
    return { selected, applied };
  }
  const owner = probe({ skillId: Browser.CGI_SKILL_ID, serverSkillId: Browser.CGI_SKILL_ID });
  assert.equal(owner.selected[0].id, cgiProfile.id, "authenticated CGI must use assigned approved profile");
  assert.equal(owner.applied[0].layoutVariant, "cgi-v2");
  assert.equal(owner.applied[0].boundFingerprint, cgiProfile.fingerprint);
  const other = probe({ skillId: "b66skill_" + "e".repeat(32), serverSkillId: "b66skill_" + "e".repeat(32) });
  assert.equal(other.selected[0].id, genericProfile.id, "other templates must keep existing precedence");
  const notServer = probe({ skillId: Browser.CGI_SKILL_ID, serverSkillId: "b66skill_" + "e".repeat(32) });
  assert.equal(notServer.selected[0].id, genericProfile.id, "browser may not assert nonassigned skill");
  const management = probe({ skillId: Browser.CGI_SKILL_ID, serverSkillId: Browser.CGI_SKILL_ID, previewMode: true });
  assert.equal(management.selected[0].id, profilePreview.id, "intentional template management preview stays isolated");
  console.log("B66_CGI_ACTUAL_RENDER_AUTHORITY=PASS");
}

async function verify() {
  verifyAssignedRowIdentity();
  verifyOwnerSkillPersistence();
  verifyLiveRenderAuthority();
  assert.equal(Browser.isCgiSkill(Browser.CGI_SKILL_ID), true);
  assert.equal(Browser.isCgiSkill("b66skill_" + "a".repeat(32)), false);
  assert.equal(Browser.CGI_BASE_SHA256.length, 64);
  const oldScreen = { ...clone(preview), layoutVariant: "" };
  const approvedScreen = Browser.certifiedPreviewModel(oldScreen, Browser.CGI_SKILL_ID, base.template.fingerprint);
  assert.equal(approvedScreen.layoutVariant, "cgi-v2");
  assert.equal(oldScreen.layoutVariant, "", "source approved profile is never mutated");
  assert.equal(approvedScreen.template.fingerprint, base.template.fingerprint);
  assert.equal(Browser.certifiedPreviewModel(oldScreen, "b66skill_" + "a".repeat(32),
    base.template.fingerprint), oldScreen, "other skills must not switch layout");
  assert.equal(Browser.certifiedPreviewModel(oldScreen, Browser.CGI_SKILL_ID,
    "forged-fingerprint"), oldScreen, "template fingerprint is required");
  assert.equal(Browser.certifiedPreviewModel({ ...oldScreen, certifiedPreviewBaseUrl: "/evil" },
    Browser.CGI_SKILL_ID, base.template.fingerprint).layoutVariant, "",
    "invalid preview source cannot enter certified mode");
  assert.equal(Browser.certifiedPreviewModel({ ...oldScreen,
    template: { ...oldScreen.template, approved: false } },
    Browser.CGI_SKILL_ID, base.template.fingerprint).layoutVariant, "",
    "unapproved profile must never enter certified mode");
  // Regression: a prior generic template is a *different fingerprint*.
  // CGI preview must select the approved assigned source profile, not this
  // unrelated template; the owner fingerprint gate remains fail-closed.
  const genericSelected = { id:"generic", approved:true, fingerprint:"generic-other" };
  // The opt-in must not magically validate a mismatched generic profile.
  assert.equal(Browser.certifiedPreviewModel({ ...oldScreen, template:genericSelected },
    Browser.CGI_SKILL_ID, base.template.fingerprint).layoutVariant, "");
  const appSource = fs.readFileSync(require("node:path").join(__dirname, "..", "app.js"), "utf8");
  assert.ok(appSource.includes("const authority = ownerCgi ? cgiProfile : (previewProfile || renderTemplateAuthority());"),
    "CGI must bypass unrelated previously selected generic authority");
  assert.ok(appSource.includes("cgiProfile.fingerprint"),
    "certified preview must retain owner-assigned fingerprint gate");
  const ops = Browser.project(base, approvedScreen);
  assert.ok(ops.length >= 14 && ops.length <= 40);
  const get = (key) => ops.find((op) => op.key === key);
  assert.equal(get("recipient").text, "대한건설");
  assert.equal(get("item-name-0").text, "배관");
  assert.equal(get("item-qty-0").text, "100");
  assert.equal(get("subtotal").text, "1,800,000");
  assert.equal(get("grand").text, "1,980,000");
  assert.equal(get("item-unit-price-0").options.rightX, 426.62);
  assert.ok(get("written-total").text.includes("1,980,000"));
  rejection((m, p) => { p.certifiedPreviewBaseUrl = "/evil"; }, "browser_pdf_projection_mismatch");
  rejection((m) => { m.facts.recipient.company = "modified after projection"; }, "browser_pdf_projection_mismatch");
  rejection((m) => { m.template.approved = false; }, "browser_pdf_projection_mismatch");
  rejection((m) => { m.taxReview.required = true; }, "browser_pdf_projection_mismatch");
  rejection((m, p) => { m.coreTotals.effectiveItems = new Array(4).fill({name:"extra"}); },
    "browser_pdf_unsupported_rows");
  rejection((m, p) => { m.facts.meta.projectName = "x".repeat(1000);
    p.facts.meta.projectName = m.facts.meta.projectName; }, "browser_pdf_invalid_projection");
  assert.throws(() => Browser.encodeJpegPdf(new Uint8Array([0, 1, 2])), /browser_pdf_invalid_image/);
  const fakeJpeg = Uint8Array.from([255, 216, 255, 217]);
  const bytes = Browser.encodeJpegPdf(fakeJpeg);
  assert.equal(Buffer.from(bytes.subarray(0, 8)).toString(), "%PDF-1.4");
  assert.ok(Buffer.from(bytes).includes(Buffer.from("/MediaBox [0 0 595 841]")));
  assert.ok(Buffer.from(bytes).includes(Buffer.from("xref\n0 6")));
  let count = 0, assetMethod = null;
  const png = Uint8Array.from([137,80,78,71,13,10,26,10,...new Array(20).fill(0)]);
  const deps = {
    fetch: async (url, options) => { count++; assetMethod = options;
      assert.equal(url, Browser.PREVIEW_URL);
      return new Response(png, { headers: { "content-type": "image/png" } });
    },
    crypto: { subtle: { digest: async () => new Uint8Array(32) } },
    Image: class {}, Blob, URL, document: {}
  };
  await assert.rejects(Browser.makePdf(base, preview, deps),
    (err) => err.code === "browser_pdf_asset_mismatch");
  assert.equal(count, 1);
  assert.equal(assetMethod.credentials, "same-origin");
  assert.equal(assetMethod.cache, "no-store");
  await assert.rejects(Browser.makePdf(base, { ...preview, certifiedPreviewBaseUrl: "/evil" }, deps),
    (err) => err.code === "browser_pdf_projection_mismatch");
  assert.equal(count, 1, "invalid quote must not fetch private image");
  console.log("B66_CGI_CLIENT_OPS_PARITY=PASS");
  console.log("B66_CGI_BROWSER_PDF_VALIDATION=PASS");
  console.log("B66_CGI_PRIVATE_PNG_HASH_FAIL_CLOSED=PASS");
  console.log("B66_CGI_CLOUD_PDF_FALLBACK=0");
}
verify().catch((error) => { console.error(error); process.exitCode = 1; });
