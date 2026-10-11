/* #3554 — offline synthetic B14 response -> QuoteExtraction -> QuoteCore -> trusted-native
 * Sol PDF SNAPSHOT contract. Mocked providers and PDF bytes; NOT a live Sol renderer.
 * This test intentionally makes zero HTTP calls and does not handle credentials.
 */
"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { createHash, webcrypto } = require("node:crypto");
const { resolve } = require("node:path");
const { readFileSync } = require("node:fs");

const ROOT = resolve(__dirname, "../../../..");
const QUOTE = resolve(ROOT, "reference/business-66-padiem-quote-v1");
const Extraction = require(resolve(QUOTE, "quote-extraction.js"));
const Core = require(resolve(QUOTE, "quote-core.js"));
const { create: createSolPdfSnapshot } = require(resolve(QUOTE, "quote-sol-pdf-snapshot.js"));
const registry = JSON.parse(readFileSync(resolve(ROOT, "apps/korean-ai-platform/app/pilot/b14_models.json"), "utf8"));
const corpus = JSON.parse(readFileSync(resolve(ROOT, ".github/fixtures/b66_quote_interpret_v1.json"), "utf8"));
const case008 = corpus.cases.find((c) => c.id === "QKR-008");
const IDS = [
  "sensenova/sensenova-6.8-flash-lite",
  "kira/qwen3.8-flash-free",
];
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const bytes = Buffer.from("%PDF-1.7\nOFFLINE CERTIFICATE-BOUNDED MOCK ONLY, NOT A NATIVE SOL PDF\n", "utf8");
const pdfSha = sha256(bytes);
const cert = "d".repeat(64);
const scope = {
  accountEpoch: "synthetic-test-session:1",
  savedSkillId: "b66skill_" + "e".repeat(32),
  skillFingerprint: "synthetic-approved-saved-skill-only",
  profileFingerprint: "synthetic-approved-template-only",
  expectedCertificateSha256: cert,
};
const noop = () => {};

function modelById(id) {
  return registry.models.find((row) => row.id === id);
}

function syntheticResponse(id) {
  const model = modelById(id);
  assert.ok(model, "exact canonical B14 registration is required");
  assert.equal(model.enabled, true);
  const raw = {
    source: { kind: "text" },
    recipient: { company: case008.expected.recipient_company },
    quote: { projectName: case008.expected.project_name, issueDate: case008.expected.issue_date },
    items: case008.expected.items.map(({ name, qty, unitPrice }) => ({ name, qty, unitPrice })),
    tax: { mode: "EXCLUSIVE" },
    warnings: [],
  };
  return {
    choices: [{ message: { role: "assistant", content: JSON.stringify(raw) }, finish_reason: "stop" }],
    business14: {
      selected_model: id,
      selected_upstream_model: model.upstream_model,
      actual_response_model: model.upstream_model,
      route_mode: "manual",
      attempt_count: 1,
      fallback_used: false,
    },
  };
}

function quoteModelFromEnvelope(id, response) {
  const entry = modelById(id);
  assert.ok(entry, "non-canonical model blocked");
  const route = response && response.business14;
  assert.ok(route &&
    route.selected_model === id &&
    route.selected_upstream_model === entry.upstream_model &&
    route.actual_response_model === entry.upstream_model &&
    route.route_mode === "manual" &&
    route.attempt_count === 1 &&
    route.fallback_used === false,
  "wrong B14 provider/model, attempts or fallback must fail before extraction");
  const content = response.choices?.[0]?.message?.content;
  assert.ok(typeof content === "string" && content.trim(), "empty answer must fail");
  assert.equal(response.choices[0].finish_reason, "stop", "unfinished answer must not be promoted");
  const extracted = JSON.parse(content);
  const result = Extraction.buildDraftCandidate(Core.createProductionDraft(), extracted);
  assert.equal(result.ok, true, "B66 extraction contract must accept exact mock fixture");
  const draft = result.value.draft;
  assert.equal(draft.recipient.company, case008.expected.recipient_company);
  assert.deepEqual(
    draft.items.map(({ name, qty, unitPrice }) => ({ name, qty, unitPrice })),
    case008.expected.items,
    "all 12 literal Korean SKU names and prices must be preserved",
  );
  const totals = Core.computeDraftTotals(draft);
  assert.ok(totals, "QuoteCore is monetary authority");
  assert.equal(totals.supply, 6500000);
  assert.equal(totals.vat, 650000);
  assert.equal(totals.grand, 7150000);
  return {
    derivedBy: "quote-core",
    template: { approved: true, fingerprint: scope.profileFingerprint },
    taxReview: { required: false },
    coreTotals: {
      subtotal: totals.subtotal, supply: totals.supply, vat: totals.vat, grand: totals.grand,
    },
    items: draft.items.map(({ name, qty, unitPrice }) => ({ name, qty, unitPrice })),
  };
}

function createOfflineSolContract() {
  let fetches = 0;
  let payload;
  const blobs = [];
  const fakeUrls = [];
  const session = createSolPdfSnapshot({
    crypto: webcrypto,
    Blob,
    URL: {
      createObjectURL(blob) { blobs.push(blob); return "blob:sol-native-fixture-" + blobs.length; },
      revokeObjectURL(url) { fakeUrls.push(url); },
    },
    async fetchNativePdf(body) {
      fetches += 1;
      payload = body;
      const headers = new Map([
        ["content-type", "application/pdf"],
        ["x-b66-sol-renderer", "sol61-native"],
        ["x-b66-sol-certificate-sha256", cert],
        ["x-b66-sol-pdf-sha256", pdfSha],
        ["x-b66-sol-profile-fingerprint", scope.profileFingerprint],
        ["x-b66-sol-skill-fingerprint", scope.skillFingerprint],
        ["x-b66-sol-page-count", "1"],
      ]);
      return {
        ok: true, headers: { get: (key) => headers.get(key) ?? null },
        async arrayBuffer() { return Uint8Array.from(bytes).buffer; },
      };
    },
  });
  return { session, blobs, fakeUrls, get fetches() { return fetches; }, get payload() { return payload; } };
}

for (const modelId of IDS) {
  test("#3554 " + modelId + ": synthetic 12-item B14 -> real B66 normalize/core -> mock native Sol snapshot", async () => {
    const response = syntheticResponse(modelId);
    const model = quoteModelFromEnvelope(modelId, response);
    const transport = createOfflineSolContract();
    const snap = await transport.session.read(scope, model);
    assert.equal(transport.fetches, 1, "one fake trusted PDF source request");
    assert.equal(transport.payload.saved_skill_id, scope.savedSkillId);
    assert.deepEqual(transport.payload.render_model.coreTotals, model.coreTotals);
    assert.deepEqual(transport.payload.render_model.items, model.items);
    assert.equal(snap.sha256, pdfSha);
    assert.equal(snap.certificateSha256, cert);
    const url = snap.previewUrl(); // UI preview receives this exact byte-backed blob
    assert.match(url, /^blob:/);
    const previewBytes = Buffer.from(await transport.blobs[0].arrayBuffer());
    const downloadBytes = Buffer.from(snap.copyBytes());
    const driveBytes = Buffer.from(snap.copyBytes());
    for (const payload of [previewBytes, downloadBytes, driveBytes]) {
      assert.equal(sha256(payload), snap.sha256, "same exact PDF byte digest for all 3 destinations");
      assert.deepEqual(payload, bytes);
    }
    await transport.session.read(scope, model);
    assert.equal(transport.fetches, 1, "same approved snapshot reused");
    transport.session.invalidate();
    assert.deepEqual(transport.fakeUrls, [url]);
    assert.throws(() => snap.copyBytes(), { code: "native_pdf_snapshot_stale" });
    assert.equal(transport.session.isCurrent(scope, model), false);
  });
}

test("model substitution, extra attempts and blank/truncated answers fail before QuoteCore/PDF", () => {
  for (const modelId of IDS) {
    const base = syntheticResponse(modelId);
    for (const modify of [
      (x) => { x.business14.selected_model = "google/gemini-3.1-flash-lite"; },
      (x) => { x.business14.actual_response_model = "other-model"; },
      (x) => { x.business14.attempt_count = 2; },
      (x) => { x.business14.fallback_used = true; },
      (x) => { x.choices[0].message.content = "   "; },
      (x) => { x.choices[0].finish_reason = "length"; },
    ]) {
      const bad = structuredClone(base);
      modify(bad);
      assert.throws(() => quoteModelFromEnvelope(modelId, bad));
    }
  }
});

test("offline synthetic PDF must not be represented as an actual Sol-rendered customer PDF", () => {
  assert.match(bytes.toString("utf8"), /MOCK ONLY/);
  assert.equal(corpus.provider_calls_authorized, false);
  assert.equal(corpus.data_policy, "synthetic_non_sensitive_only");
  for (const id of IDS) assert.ok(modelById(id)?.enabled);
});

console.log("B14_3554_REAL_QUOTE_CONTRACT_WITH_MOCK_SOL_PDF=OFFLINE_ONLY");
console.log("REAL_PROVIDER_POST=0 NATIVE_SOL_RENDER=0 CUSTOMER_PDF_ATTESTED=NO");
