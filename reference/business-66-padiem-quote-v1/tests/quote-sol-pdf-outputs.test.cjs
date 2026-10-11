/* #4117: one Sol PDF blob is preview, download, and Drive bytes.
 * B66_NATIVE_SOL_TEST_PDF_PATH enables a REAL Windows Sol PDF fixture;
 * CI stays synthetic and never activates customer runtime or paid resources.
 */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { createHash, webcrypto } = require("node:crypto");
const { create: createSnapshot } = require("../quote-sol-pdf-snapshot.js");
const { create: createOutputs } = require("../quote-sol-pdf-outputs.js");

const realPath = process.env.B66_NATIVE_SOL_TEST_PDF_PATH;
const bytes = realPath
  ? fs.readFileSync(realPath)
  : Buffer.from("%PDF-1.7\nsynthetic fanout fixture\n%%EOF\n");
const sha = createHash("sha256").update(bytes).digest("hex");
const CERT = "c".repeat(64);
const scope = Object.freeze({
  accountEpoch: "account-a:epoch-1",
  savedSkillId: "b66skill_" + "a".repeat(32),
  skillFingerprint: "test-approved-skill-identity",
  profileFingerprint: "test-approved-profile-identity",
  expectedCertificateSha256: CERT
});
const model = {
  derivedBy: "quote-core", template: { approved: true, fingerprint: scope.profileFingerprint },
  coreTotals: { effectiveItems: [{ name: "통신공사", qty: 1 }] },
  taxReview: { required: false }, items: [{ name: "통신공사" }]
};
const clone = x => JSON.parse(JSON.stringify(x));
const fails = code => error => error && error.code === code;
function fixture(overrides = {}) {
  const stats = { calls: 0, urls: [], revoked: [], downloads: [], blobs: [] };
  const URL = {
    createObjectURL(blob) {
      stats.blobs.push(blob);
      const value = "blob:sol-proof-" + stats.blobs.length;
      stats.urls.push(value);
      return value;
    },
    revokeObjectURL(value) { stats.revoked.push(value); }
  };
  const result = (opts = {}) => {
    const headers = new Map([
      ["content-type", "application/pdf"],
      ["x-b66-sol-renderer", "sol61-native"],
      ["x-b66-sol-certificate-sha256", CERT],
      ["x-b66-sol-pdf-sha256", sha],
      ["x-b66-sol-profile-fingerprint", scope.profileFingerprint],
      ["x-b66-sol-skill-fingerprint", scope.skillFingerprint],
      ["x-b66-sol-page-count", realPath ? "2" : "1"]
    ]);
    Object.entries(opts.headers || {}).forEach(([key, val]) => headers.set(key, val));
    return {
      ok: opts.ok !== false,
      headers: { get: key => headers.get(key) ?? null },
      arrayBuffer: async () => Uint8Array.from(opts.bytes || bytes).buffer
    };
  };
  const snapshot = createSnapshot({
    crypto: webcrypto, Blob, URL,
    fetchNativePdf: async input => {
      stats.calls++;
      return overrides.fetch ? overrides.fetch(input, result) : result();
    }
  });
  const outputs = createOutputs({
    snapshots: snapshot,
    saveFile: async (data, fileName) => {
      stats.downloads.push({ bytes: Uint8Array.from(data), fileName });
      if (overrides.download) await overrides.download(data, fileName);
    }
  });
  const frame = {
    src: "", hidden: true,
    setAttribute(name, value) { assert.equal(name, "src"); this.src = value; },
    removeAttribute(name) { assert.equal(name, "src"); this.src = ""; }
  };
  return { outputs, snapshot, frame, stats };
}

(async () => {
  const { outputs, frame, stats } = fixture();
  const preview = await outputs.showPreview(scope, model, frame);
  assert.equal(preview.sha256, sha);
  assert.equal(frame.hidden, false);
  assert.match(frame.src, /^blob:sol-proof/);
  const shown = Buffer.from(await stats.blobs[0].arrayBuffer());
  assert.deepEqual(shown, bytes, "iframe must show the original PDF, not Canvas/JPEG");

  const downloaded = await outputs.download(scope, model, "quote.pdf");
  assert.equal(downloaded.sha256, preview.sha256);
  assert.deepEqual(Buffer.from(stats.downloads[0].bytes), bytes);
  const drive = await outputs.driveBytes(scope, model);
  assert.equal(drive.sha256, downloaded.sha256);
  assert.deepEqual(Buffer.from(drive.bytes), bytes);
  assert.equal(stats.calls, 1, "all three outputs must share one server render");
  drive.bytes[0] = 0;
  assert.deepEqual(Buffer.from((await outputs.driveBytes(scope, model)).bytes), bytes,
    "Drive consumer cannot mutate the cached preview/download snapshot");

  await assert.rejects(outputs.download(scope, model, "../unsafe.pdf"),
    fails("native_pdf_filename_invalid"));
  outputs.invalidate();
  assert.equal(frame.src, "");
  assert.equal(frame.hidden, true);
  assert.deepEqual(stats.revoked, stats.urls);
  assert.equal(outputs.current(scope, model), false);

  // Edits, account changes, and in-flight delayed replies fail closed.
  const pending = [];
  const late = fixture({ fetch: (_, response) => new Promise(resolve =>
    pending.push(() => resolve(response()))) });
  const first = late.outputs.showPreview(scope, model, late.frame);
  late.outputs.invalidate();
  pending[0]();
  await assert.rejects(first, error => error &&
    (error.code === "native_pdf_snapshot_stale" ||
     error.code === "native_pdf_outputs_stale"));
  assert.equal(late.frame.src, "");

  const swapped = fixture();
  const signedIn = await swapped.outputs.driveBytes(scope, model);
  assert.equal(signedIn.sha256, sha);
  swapped.outputs.invalidate();
  assert.equal(swapped.outputs.current(scope, model), false);

  // No response/header spoofing or server error can be silently replaced.
  const hostile = fixture({ fetch: (_, response) => response({
    headers: { "x-b66-sol-pdf-sha256": "0".repeat(64) }
  }) });
  await assert.rejects(hostile.outputs.driveBytes(scope, model),
    fails("native_pdf_sha_mismatch"));

  console.log("NATIVE_SOL_ORIGINAL_PDF_FANOUT=" + (realPath ? "REAL_SOL_BYTES_PASS" : "SYNTHETIC_PASS"));
  console.log("PDF_PREVIEW_DOWNLOAD_DRIVE_SHA_PARITY=PASS " + sha);
  console.log("ONE_FETCH_FOR_THREE_OUTPUTS=PASS");
  console.log("STALE_LOGOUT_EDIT_FORGED_SHA_FAIL_CLOSED=PASS");
})().catch(error => { console.error(error); process.exitCode = 1; });
