/* #4117: authenticated native Sol transport; inert until a server-owned
 * release exists. NO historical certificate, Canvas, JPEG or legacy fallback.
 * This module cannot activate customer UI by itself.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.B66SolPdfRuntimeBridge = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const HEX = /^[a-f0-9]{64}$/;
  const ID = /^b66skill_[0-9a-f]{32}$/;
  const API = "/api/b66/quote/";
  function fail(code) {
    const e = new Error(code);
    e.code = code;
    return e;
  }
  function create(deps) {
    if (!deps || typeof deps.fetch !== "function" ||
        !deps.snapshotModule || typeof deps.snapshotModule.create !== "function" ||
        !deps.outputsModule || typeof deps.outputsModule.create !== "function") {
      throw fail("native_sol_bridge_unavailable");
    }
    let serial = 0, scoped = null, scopedKey = null;
    const snapshot = deps.snapshotModule.create({
      crypto: deps.crypto, Blob: deps.Blob, URL: deps.URL,
      fetchNativePdf: payload => deps.fetch(API + "native-sol-pdf", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Content-Type": "application/json", "Accept": "application/pdf" },
        body: JSON.stringify(payload)
      })
    });
    const outputs = deps.outputsModule.create({
      snapshots: snapshot, saveFile: deps.saveFile
    });
    function invalidate() {
      serial++;
      scoped = null;
      scopedKey = null;
      outputs.invalidate();
    }
    async function trustedScope(accountEpoch, savedSkillId, model) {
      if (typeof accountEpoch !== "string" || !accountEpoch ||
          !ID.test(savedSkillId || "") || !model || !model.template ||
          model.template.approved !== true || !model.coreTotals ||
          !Array.isArray(model.coreTotals.effectiveItems) ||
          !model.taxReview || model.taxReview.required !== false) {
        throw fail("native_sol_scope_invalid");
      }
      const count = model.coreTotals.effectiveItems.length;
      if (!Number.isInteger(count) || count < 1 || count > 100) {
        throw fail("native_sol_scope_invalid");
      }
      const key = JSON.stringify([accountEpoch, savedSkillId,
        model.template.fingerprint, count]);
      if (key !== scopedKey) {
        invalidate();
        scopedKey = key;
      }
      const current = serial;
      if (scoped) return scoped;
      const query = "saved_skill_id=" + encodeURIComponent(savedSkillId) +
        "&item_count=" + count;
      const response = await deps.fetch(API + "native-sol-scope?" + query, {
        method: "GET", credentials: "same-origin", cache: "no-store",
        headers: { "Accept": "application/json" }
      });
      if (current !== serial) throw fail("native_sol_scope_stale");
      if (!response || !response.ok) throw fail("native_sol_release_not_certified");
      const data = await response.json();
      if (current !== serial) throw fail("native_sol_scope_stale");
      if (!data || data.schemaVersion !== 1 || data.available !== true ||
          data.renderer !== "sol61-native" || data.savedSkillId !== savedSkillId ||
          data.itemCount !== count ||
          !HEX.test(data.certificateSha256 || "") ||
          !HEX.test(data.skillFingerprint || "") ||
          !HEX.test(data.profileFingerprint || "") ||
          data.profileFingerprint !== model.template.fingerprint ||
          !Number.isInteger(data.minItems) || !Number.isInteger(data.maxItems) ||
          data.minItems > count || data.maxItems < count) {
        throw fail("native_sol_scope_untrusted");
      }
      scoped = Object.freeze({
        accountEpoch, savedSkillId, skillFingerprint: data.skillFingerprint,
        profileFingerprint: data.profileFingerprint,
        expectedCertificateSha256: data.certificateSha256
      });
      return scoped;
    }
    async function withScope(accountEpoch, savedSkillId, model, call) {
      const scope = await trustedScope(accountEpoch, savedSkillId, model);
      return call(scope, model);
    }
    return Object.freeze({
      preview: (epoch, id, model, frame) =>
        withScope(epoch, id, model, (scope, m) => outputs.showPreview(scope, m, frame)),
      download: (epoch, id, model, name) =>
        withScope(epoch, id, model, (scope, m) => outputs.download(scope, m, name)),
      driveBytes: (epoch, id, model) =>
        withScope(epoch, id, model, (scope, m) => outputs.driveBytes(scope, m)),
      invalidate, hasTrustedScope: () => !!scoped
    });
  }
  return Object.freeze({ create });
});
