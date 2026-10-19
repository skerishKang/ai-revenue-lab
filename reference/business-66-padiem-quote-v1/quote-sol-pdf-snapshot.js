/* B66 CGI #4117: one verified native Sol PDF snapshot for preview/download/Drive.
   This module does NOT render PDFs and does NOT change existing B66 routes.
   Only a future first-party authenticated native Sol endpoint may supply bytes.
   Never fall back to DOM/Canvas raster or a generic quote renderer. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.B66SolPdfSnapshot = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  var MAX_BYTES = 32 * 1024 * 1024;
  var HEX64 = /^[a-f0-9]{64}$/;
  var SKILL_ID = /^b66skill_[0-9a-f]{32}$/;
  var CERT_HEADER = "x-b66-sol-certificate-sha256";
  var PDF_HEADER = "x-b66-sol-pdf-sha256";
  var VERSION_HEADER = "x-b66-sol-renderer";
  var TEMPLATE_HEADER = "x-b66-sol-profile-fingerprint";
  var SKILL_HEADER = "x-b66-sol-skill-fingerprint";
  var PAGES_HEADER = "x-b66-sol-page-count";

  function fail(code) {
    var error = new Error(code);
    error.code = code;
    return error;
  }
  function validScope(scope, model) {
    return scope && typeof scope === "object" &&
      typeof scope.accountEpoch === "string" && scope.accountEpoch.length > 0 &&
      scope.accountEpoch.length <= 256 &&
      SKILL_ID.test(scope.savedSkillId || "") &&
      HEX64.test(scope.expectedCertificateSha256 || "") &&
      typeof scope.skillFingerprint === "string" && scope.skillFingerprint.length >= 8 &&
      scope.skillFingerprint.length <= 256 &&
      model && typeof model === "object" && !Array.isArray(model) &&
      model.derivedBy === "quote-core" &&
      model.template && model.template.approved === true &&
      typeof model.template.fingerprint === "string" &&
      model.template.fingerprint.length > 0 &&
      model.template.fingerprint === scope.profileFingerprint &&
      model.taxReview && model.taxReview.required === false &&
      model.coreTotals && typeof model.coreTotals === "object";
  }
  function bytesArePdf(data) {
    return data instanceof Uint8Array && data.length >= 8 &&
      data[0] === 37 && data[1] === 80 && data[2] === 68 &&
      data[3] === 70 && data[4] === 45;
  }
  function hex(bytes) {
    return Array.from(new Uint8Array(bytes), function (b) {
      return b.toString(16).padStart(2, "0");
    }).join("");
  }
  function create(deps) {
    if (!deps || typeof deps.fetchNativePdf !== "function" ||
        !deps.crypto || !deps.crypto.subtle ||
        typeof deps.crypto.subtle.digest !== "function" ||
        !deps.Blob || !deps.URL ||
        typeof deps.URL.createObjectURL !== "function" ||
        typeof deps.URL.revokeObjectURL !== "function") throw fail("native_pdf_runtime_unavailable");

    var activeKey = null, active = null, inflight = null;
    var generation = 0, blobUrl = null;
    function disposeUrl() {
      if (blobUrl) deps.URL.revokeObjectURL(blobUrl);
      blobUrl = null;
    }
    function invalidate() {
      generation += 1;
      activeKey = null;
      active = null;
      inflight = null;
      disposeUrl();
    }
    function keyFor(scope, model) {
      if (!validScope(scope, model)) throw fail("native_pdf_scope_invalid");
      var key = JSON.stringify([
        scope.accountEpoch, scope.savedSkillId, scope.skillFingerprint,
        scope.profileFingerprint, scope.expectedCertificateSha256, model
      ]);
      if (key.length > 32 * 1024) throw fail("native_pdf_request_too_large");
      return key;
    }
    function current(key) {
      if (key !== activeKey || !active) throw fail("native_pdf_snapshot_stale");
      return Object.freeze({
        sha256: active.sha256,
        certificateSha256: active.certificateSha256,
        pageCount: active.pageCount,
        size: active.bytes.byteLength,
        copyBytes: function () {
          if (key !== activeKey || !active) throw fail("native_pdf_snapshot_stale");
          return new Uint8Array(active.bytes);
        },
        previewUrl: function () {
          if (key !== activeKey || !active) throw fail("native_pdf_snapshot_stale");
          if (!blobUrl) blobUrl = deps.URL.createObjectURL(
            new deps.Blob([active.bytes], { type: "application/pdf" })
          );
          return blobUrl;
        }
      });
    }
    async function read(scope, model) {
      var key = keyFor(scope, model);
      if (activeKey !== key) {
        invalidate();
        activeKey = key;
      }
      if (active) return current(key);
      if (inflight) return inflight;
      var token = generation;
      var payload = JSON.parse(JSON.stringify({
        saved_skill_id: scope.savedSkillId,
        render_model: model
      }));
      inflight = (async function () {
        var response = await deps.fetchNativePdf(payload);
        if (token !== generation || key !== activeKey) throw fail("native_pdf_snapshot_stale");
        if (!response || response.ok !== true ||
            !response.headers || typeof response.headers.get !== "function")
          throw fail("native_pdf_unavailable");
        var media = String(response.headers.get("content-type") || "")
          .split(";", 1)[0].trim().toLowerCase();
        if (media !== "application/pdf" ||
            response.headers.get(VERSION_HEADER) !== "sol61-native" ||
            response.headers.get(CERT_HEADER) !== scope.expectedCertificateSha256 ||
            response.headers.get(TEMPLATE_HEADER) !== scope.profileFingerprint ||
            response.headers.get(SKILL_HEADER) !== scope.skillFingerprint)
          throw fail("native_pdf_certificate_mismatch");
        var expectedSha = String(response.headers.get(PDF_HEADER) || "");
        var pageCount = Number(response.headers.get(PAGES_HEADER));
        var lengthHeader = response.headers.get("content-length");
        if (!HEX64.test(expectedSha) || !Number.isSafeInteger(pageCount) ||
            pageCount < 1 || pageCount > 100 ||
            (lengthHeader !== null && (!/^\d+$/.test(lengthHeader) ||
            Number(lengthHeader) > MAX_BYTES)))
          throw fail("native_pdf_metadata_invalid");
        var buffer = await response.arrayBuffer();
        if (token !== generation || key !== activeKey) throw fail("native_pdf_snapshot_stale");
        if (!(buffer instanceof ArrayBuffer) ||
            buffer.byteLength < 8 || buffer.byteLength > MAX_BYTES)
          throw fail("native_pdf_bytes_invalid");
        var bytes = new Uint8Array(buffer);
        if (!bytesArePdf(bytes)) throw fail("native_pdf_bytes_invalid");
        var actual = hex(await deps.crypto.subtle.digest("SHA-256", bytes));
        if (token !== generation || key !== activeKey) throw fail("native_pdf_snapshot_stale");
        if (actual !== expectedSha) throw fail("native_pdf_sha_mismatch");
        active = { bytes: new Uint8Array(bytes), sha256: actual,
          certificateSha256: scope.expectedCertificateSha256, pageCount: pageCount };
        return current(key);
      })();
      var pending = inflight;
      try { return await pending; }
      catch (error) {
        if (token === generation && key === activeKey) invalidate();
        throw error;
      } finally {
        if (inflight === pending) inflight = null;
      }
    }
    return Object.freeze({
      read: read,
      invalidate: invalidate,
      isCurrent: function (scope, model) {
        try { return !!active && keyFor(scope, model) === activeKey; }
        catch (_) { return false; }
      }
    });
  }
  return Object.freeze({ create: create, MAX_BYTES: MAX_BYTES });
});
