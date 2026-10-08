const assert = require("node:assert/strict");
const fs = require("node:fs");
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
async function verify() {
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
