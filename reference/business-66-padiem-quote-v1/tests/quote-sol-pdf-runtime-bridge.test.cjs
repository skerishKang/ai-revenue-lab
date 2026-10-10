/* B66 #4117 synthetic transport: GET owner release -> POST native PDF -> 3 outputs. */
"use strict";
const assert = require("node:assert/strict");
const { webcrypto, createHash } = require("node:crypto");
const fs = require("node:fs");
const { create } = require("../quote-sol-pdf-runtime-bridge.js");
const snapshotModule = require("../quote-sol-pdf-snapshot.js");
const outputsModule = require("../quote-sol-pdf-outputs.js");
const id = "b66skill_" + "c".repeat(32);
const skill = "1".repeat(64), profile = "2".repeat(64), cert = "a".repeat(64);
const realFile = process.env.B66_NATIVE_SOL_TEST_PDF_PATH;
const pdf = realFile ? fs.readFileSync(realFile) : Buffer.from("%PDF-1.7\nsynthetic signed-scope unit fixture\n%%EOF\n");
const sha = createHash("sha256").update(pdf).digest("hex");
const model = {
  schemaVersion: 1, derivedBy: "quote-core",
  template: { approved: true, fingerprint: profile },
  coreTotals: { effectiveItems: [{ name: "test", qty: 1, unitPrice: 100 }] },
  taxReview: { required: false }
};
const clone = obj => JSON.parse(JSON.stringify(obj));
const code = name => error => error && error.code === name;
function setup(tamper) {
  const stats = { scope: 0, pdf: 0, downloads: [], blobs: [], revoked: [] };
  const URL = {
    createObjectURL: blob => {
      stats.blobs.push(blob);
      return "blob:client-" + stats.blobs.length;
    },
    revokeObjectURL: value => stats.revoked.push(value)
  };
  const scopeBody = { schemaVersion: 1, available: true, renderer: "sol61-native",
    savedSkillId: id, itemCount: 1, certificateSha256: cert,
    skillFingerprint: skill, profileFingerprint: profile, minItems: 1, maxItems: 3 };
  const bridge = create({
    snapshotModule, outputsModule, Blob, URL, crypto: webcrypto,
    saveFile: async (bytes, filename) => {
      stats.downloads.push({ bytes: Uint8Array.from(bytes), filename });
    },
    fetch: async (url, args) => {
      assert.equal(args.credentials, "same-origin");
      assert.equal(args.cache, "no-store");
      if (url.includes("/native-sol-scope?")) {
        stats.scope++;
        assert.equal(args.method, "GET");
        assert.ok(url.includes("item_count=1"));
        return { ok: !tamper?.scopeUnavailable, json: async () =>
          Object.assign({}, scopeBody, tamper?.scope || {}) };
      }
      if (url.endsWith("/native-sol-pdf")) {
        stats.pdf++;
        assert.equal(args.method, "POST");
        assert.equal(JSON.parse(args.body).saved_skill_id, id);
        return {
          ok: true,
          headers: { get: key => ({
            "content-type": "application/pdf",
            "x-b66-sol-renderer": "sol61-native",
            "x-b66-sol-pdf-sha256": sha,
            "x-b66-sol-certificate-sha256": cert,
            "x-b66-sol-skill-fingerprint": skill,
            "x-b66-sol-profile-fingerprint": profile,
            "x-b66-sol-page-count": realFile ? "2" : "1"
          })[key] ?? null },
          arrayBuffer: async () => Uint8Array.from(pdf).buffer
        };
      }
      throw new Error("Unexpected route " + url);
    }
  });
  const frame = {
    src: "", hidden: true,
    setAttribute(key, value) { assert.equal(key, "src"); this.src = value; },
    removeAttribute(key) { assert.equal(key, "src"); this.src = ""; }
  };
  return { bridge, stats, frame };
}
(async () => {
  const { bridge, stats, frame } = setup();
  const first = await bridge.preview("owner-a:session-1", id, model, frame);
  assert.equal(first.sha256, sha);
  assert.equal(frame.src, "blob:client-1");
  assert.deepEqual(Buffer.from(await stats.blobs[0].arrayBuffer()), pdf);
  const saved = await bridge.download("owner-a:session-1", id, model, "quote.pdf");
  assert.equal(saved.sha256, sha);
  assert.deepEqual(Buffer.from(stats.downloads[0].bytes), pdf);
  const drive = await bridge.driveBytes("owner-a:session-1", id, model);
  assert.equal(drive.sha256, sha);
  assert.deepEqual(Buffer.from(drive.bytes), pdf);
  assert.equal(stats.pdf, 1, "all outputs reuse one verified POST PDF");
  assert.equal(stats.scope, 1, "scope fetched from real owner contract once");
  bridge.invalidate();
  assert.equal(frame.src, "");
  assert.deepEqual(stats.revoked, ["blob:client-1"]);
  assert.equal(bridge.hasTrustedScope(), false);

  const unavailable = setup({ scopeUnavailable: true });
  await assert.rejects(
    unavailable.bridge.driveBytes("owner-a:session-1", id, model),
    code("native_sol_release_not_certified"));
  assert.equal(unavailable.stats.pdf, 0, "No fallback to Canvas/legacy renderer");

  const forged = setup({ scope: { profileFingerprint: "0".repeat(64) } });
  await assert.rejects(
    forged.bridge.driveBytes("owner-a:session-1", id, model),
    code("native_sol_scope_untrusted"));
  assert.equal(forged.stats.pdf, 0);

  const broken = setup();
  await assert.rejects(
    broken.bridge.driveBytes("", id, model), code("native_sol_scope_invalid"));
  assert.equal(broken.stats.scope, 0);

  const changed = setup();
  await changed.bridge.driveBytes("owner-a:session-1", id, model);
  await changed.bridge.driveBytes("owner-b:session-2", id, clone(model));
  assert.equal(changed.stats.scope, 2);
  assert.equal(changed.stats.pdf, 2, "account epoch must refresh the PDF");
  console.log("NATIVE_SOL_RUNTIME_TRANSPORT_BYTES=" +
    (realFile ? "REAL_WINDOWS_SOL_PDF_PASS" : "SYNTHETIC_FIXTURE_PASS"));
  console.log("AUTHENTICATED_NATIVE_RELEASE_SCOPE=PASS");
  console.log("NATIVE_SOL_SCOPE_TO_PREVIEW_DOWNLOAD_DRIVE=PASS " + sha);
  console.log("UNAVAILABLE_FORGED_STALE_SCOPE_FAIL_CLOSED=PASS");
})().catch(error => { console.error(error); process.exitCode = 1; });
