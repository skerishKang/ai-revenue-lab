/* #4117: isolate client PDF snapshot logic; no network, no private assets. */
"use strict";
const assert = require("node:assert/strict");
const { createHash, webcrypto } = require("node:crypto");
const { create } = require("../quote-sol-pdf-snapshot.js");
const bytes = Buffer.from("%PDF-1.7\nsynthetic native Sol PDF test only\n");
const sha = createHash("sha256").update(bytes).digest("hex");
const cert = "c".repeat(64);
const skillId = "b66skill_" + "a".repeat(32);
const scope = { accountEpoch: "signed-in-user-a:session-1", savedSkillId: skillId,
  skillFingerprint: "trusted-skill-fingerprint",
  profileFingerprint: "approved-skill-profile-fingerprint",
  expectedCertificateSha256: cert };
const model = { derivedBy: "quote-core", template: {
  approved: true, fingerprint: scope.profileFingerprint },
  coreTotals: { subtotal: 100, vat: 10, grand: 110 },
  taxReview: { required: false }, items: [{ name: "synthetic 1", qty: 1 }] };
const clone = (x) => JSON.parse(JSON.stringify(x));
const nextTick = () => new Promise((r) => setImmediate(r));
const errorCode = (c) => (err) => err && err.code === c;

function fixture(custom) {
  const state = { fetches: 0, created: [], revoked: [], payloads: [] };
  let handler = custom;
  const URL = {
    createObjectURL(blob) {
      state.created.push(blob);
      return "blob:native-pdf-" + state.created.length;
    },
    revokeObjectURL(url) { state.revoked.push(url); }
  };
  function result(opts = {}) {
    const headers = new Map([
      ["content-type", "application/pdf"],
      ["x-b66-sol-renderer", "sol61-native"],
      ["x-b66-sol-certificate-sha256", cert],
      ["x-b66-sol-pdf-sha256", sha],
      ["x-b66-sol-profile-fingerprint", scope.profileFingerprint],
      ["x-b66-sol-skill-fingerprint", scope.skillFingerprint],
      ["x-b66-sol-page-count", "2"]
    ]);
    for (const [k, v] of Object.entries(opts.headers || {})) {
      if (v === null) headers.delete(k);
      else headers.set(k, v);
    }
    return { ok: opts.ok !== false, headers: { get: (k) => headers.get(k) ?? null },
      async arrayBuffer() {
        const bin = opts.bytes || bytes;
        return Uint8Array.from(bin).buffer;
      } };
  }
  const session = create({ crypto: webcrypto, URL, Blob,
    fetchNativePdf: async (payload) => {
      state.fetches++;
      state.payloads.push(payload);
      return handler ? handler(payload, result) : result();
    } });
  return { session, state, result };
}

(async () => {
  // One trusted native PDF byte snapshot is simultaneously the preview and
  // source bytes for download and Drive. Copy protects internal cache.
  {
    const { session, state } = fixture();
    const snap = await session.read(scope, model);
    assert.equal(snap.sha256, sha);
    assert.equal(snap.certificateSha256, cert);
    assert.equal(snap.pageCount, 2);
    assert.deepEqual(Buffer.from(snap.copyBytes()), bytes);
    const u1 = snap.previewUrl();
    assert.equal(snap.previewUrl(), u1);
    assert.equal(state.created.length, 1);
    const mutated = snap.copyBytes();
    mutated[0] = 0;
    assert.deepEqual(Buffer.from(snap.copyBytes()), bytes, "Drive/downloader cannot edit cached PDF");
    const also = await session.read(clone(scope), clone(model));
    assert.equal(also.sha256, snap.sha256);
    assert.equal(state.fetches, 1, "same authenticated approved snapshot only one Sol invocation");
    assert.equal(state.payloads[0].saved_skill_id, skillId);
    assert.deepEqual(state.payloads[0].render_model.coreTotals, model.coreTotals);
    session.invalidate();
    assert.deepEqual(state.revoked, [u1], "logout/edit revokes local preview URL");
    assert.throws(() => snap.copyBytes(), errorCode("native_pdf_snapshot_stale"));
    assert.throws(() => snap.previewUrl(), errorCode("native_pdf_snapshot_stale"));
    assert.equal(session.isCurrent(scope, model), false);
  }

  // Editing must not return the previous native PDF, even if an async request
  // settles late. Repeated identical in-flight reads coalesce.
  {
    const resolvers = [];
    const { session, state } = fixture(() => new Promise((r) => { resolvers.push(r); }));
    const first = session.read(scope, model);
    const duplicate = session.read(scope, model);
    assert.equal(state.fetches, 1);
    await nextTick();
    const updated = clone(model);
    updated.items[0].qty = 2;
    const second = session.read(scope, updated);
    assert.equal(state.fetches, 2);
    resolvers[0](fixture().result());
    resolvers[1](fixture().result());
    await assert.rejects(first, errorCode("native_pdf_snapshot_stale"));
    await assert.rejects(duplicate, errorCode("native_pdf_snapshot_stale"));
    const newSnapshot = await second;
    assert.equal(newSnapshot.sha256, sha);
    assert.equal(session.isCurrent(scope, updated), true);
    assert.equal(session.isCurrent(scope, model), false);
  }

  // A late reply from account A may not repopulate account B's PDF view.
  {
    const resolvers = [];
    const { session } = fixture(() => new Promise((r) => resolvers.push(r)));
    const accountA = session.read(scope, model);
    const accountB = session.read({ ...scope, accountEpoch: "signed-in-user-b:session-2" }, model);
    assert.equal(resolvers.length, 2);
    resolvers[0](fixture().result());
    await assert.rejects(accountA, errorCode("native_pdf_snapshot_stale"));
    resolvers[1](fixture().result());
    const snap = await accountB;
    assert.equal(snap.sha256, sha);
    assert.equal(snap.pageCount, 2);
  }

  // A PDF with missing native certificate headers, incorrect SHA,
  // inappropriate content-type or forged untrusted response fails closed.
  const bad = [
    [{ headers: { "x-b66-sol-renderer": "canvas-jpeg" } }, "native_pdf_certificate_mismatch"],
    [{ headers: { "x-b66-sol-certificate-sha256": "f".repeat(64) } }, "native_pdf_certificate_mismatch"],
    [{ headers: { "x-b66-sol-profile-fingerprint": "other-profile" } }, "native_pdf_certificate_mismatch"],
    [{ headers: { "x-b66-sol-skill-fingerprint": "another-skill" } }, "native_pdf_certificate_mismatch"],
    [{ headers: { "content-type": "image/png" } }, "native_pdf_certificate_mismatch"],
    [{ headers: { "x-b66-sol-pdf-sha256": "0".repeat(64) } }, "native_pdf_sha_mismatch"],
    [{ headers: { "x-b66-sol-page-count": "0" } }, "native_pdf_metadata_invalid"],
    [{ headers: { "x-b66-sol-page-count": "101" } }, "native_pdf_metadata_invalid"],
    [{ headers: { "content-length": String(33 * 1024 * 1024) } }, "native_pdf_metadata_invalid"],
    [{ bytes: Buffer.from("<html>fake PDF") }, "native_pdf_bytes_invalid"],
    [{ ok: false }, "native_pdf_unavailable"]
  ];
  for (const [overrides, code] of bad) {
    const { session, state } = fixture((_, result) => result(overrides));
    await assert.rejects(session.read(scope, model), errorCode(code), code);
    assert.equal(state.created.length, 0);
    assert.equal(session.isCurrent(scope, model), false);
  }

  // Reject anything less than a real approved account/skill/core contract.
  const invalid = [
    [{ ...scope, savedSkillId: "bad" }, model],
    [{ ...scope, expectedCertificateSha256: "unsigned" }, model],
    [{ ...scope, accountEpoch: "" }, model],
    [{ ...scope, profileFingerprint: "another" }, model],
    [scope, { ...model, derivedBy: "browser-only" }],
    [scope, { ...model, template: { approved: false, fingerprint: scope.profileFingerprint } }],
    [scope, { ...model, taxReview: { required: true } }],
    [scope, { ...model, coreTotals: null }]
  ];
  for (const [s, m] of invalid) {
    const { session, state } = fixture();
    await assert.rejects(session.read(s, m), errorCode("native_pdf_scope_invalid"));
    assert.equal(state.fetches, 0);
  }

  // Fetch failures may be retried but only for the original snapshot key.
  {
    let attempts = 0;
    const { session } = fixture((_, result) => {
      if (++attempts === 1) return result({ ok: false });
      return result();
    });
    await assert.rejects(session.read(scope, model), errorCode("native_pdf_unavailable"));
    const second = await session.read(scope, model);
    assert.equal(second.sha256, sha);
    assert.equal(attempts, 2);
  }
  console.log("B66_NATIVE_SOL_PDF_SNAPSHOT_PARITY=PASS");
  console.log("PDF_PREVIEW_DOWNLOAD_DRIVE_SHARED_VERIFIED_BYTES=PASS");
  console.log("ACCOUNT_SWITCH_AND_EDIT_STALE_ASYNC_FAIL_CLOSED=PASS");
  console.log("BROWSER_CANVAS_OR_WORKER_PDF_ACCEPTED=NO");
})().catch((error) => { console.error(error); process.exitCode = 1; });
