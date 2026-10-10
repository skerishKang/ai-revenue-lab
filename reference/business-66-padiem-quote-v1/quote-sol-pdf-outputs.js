/* B66 #4117 — fan out ONE verified Sol PDF snapshot to its three outputs.
 * Does not render, certify, fetch, or upload a PDF. The caller owns the
 * authenticated Saved Skill scope and an independently certified release.
 * No browser/Canvas/legacy-PDF fallback is permitted once this path is used.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.B66SolPdfOutputs = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  function fail(code) {
    var error = new Error(code);
    error.code = code;
    return error;
  }
  function create(options) {
    var opts = options || {};
    var snapshots = opts.snapshots;
    if (!snapshots || typeof snapshots.read !== "function" ||
        typeof snapshots.invalidate !== "function" ||
        typeof snapshots.isCurrent !== "function" ||
        typeof opts.saveFile !== "function") throw fail("native_pdf_outputs_unavailable");
    var version = 0;
    var frame = null;
    function isLive(token, scope, model) {
      return token === version && snapshots.isCurrent(scope, model);
    }
    function clearPreview() {
      if (!frame) return;
      frame.removeAttribute("src");
      frame.hidden = true;
      frame = null;
    }
    function invalidate() {
      version++;
      clearPreview();
      snapshots.invalidate();
    }
    async function read(scope, model) {
      var token = version;
      var pdf = await snapshots.read(scope, model);
      if (!isLive(token, scope, model)) throw fail("native_pdf_outputs_stale");
      return { pdf: pdf, token: token };
    }
    async function showPreview(scope, model, target) {
      if (!target || typeof target.setAttribute !== "function" ||
          typeof target.removeAttribute !== "function") {
        throw fail("native_pdf_preview_target_invalid");
      }
      // Editing must hide the previous quote immediately, not keep an old PDF
      // visible while an asynchronous native Sol render is in flight.
      clearPreview();
      var state = await read(scope, model);
      if (!isLive(state.token, scope, model)) throw fail("native_pdf_outputs_stale");
      target.setAttribute("src", state.pdf.previewUrl());
      target.hidden = false;
      frame = target;
      return Object.freeze({
        sha256: state.pdf.sha256, pageCount: state.pdf.pageCount,
        certificateSha256: state.pdf.certificateSha256
      });
    }
    async function download(scope, model, fileName) {
      if (typeof fileName !== "string" || !fileName.trim() ||
          !/\.pdf$/i.test(fileName) || /[\\/:*?"<>|\u0000-\u001f]/.test(fileName)) {
        throw fail("native_pdf_filename_invalid");
      }
      var state = await read(scope, model);
      if (!isLive(state.token, scope, model)) throw fail("native_pdf_outputs_stale");
      await opts.saveFile(state.pdf.copyBytes(), fileName);
      if (!isLive(state.token, scope, model)) throw fail("native_pdf_outputs_stale");
      return Object.freeze({ sha256: state.pdf.sha256, fileName: fileName });
    }
    async function driveBytes(scope, model) {
      var state = await read(scope, model);
      if (!isLive(state.token, scope, model)) throw fail("native_pdf_outputs_stale");
      return {
        bytes: state.pdf.copyBytes(), sha256: state.pdf.sha256,
        certificateSha256: state.pdf.certificateSha256,
        pageCount: state.pdf.pageCount
      };
    }
    return Object.freeze({
      showPreview: showPreview, download: download,
      driveBytes: driveBytes, invalidate: invalidate,
      isCurrent: snapshots.isCurrent,
      // Explicit read-only proof; neither the URL nor the blob is a new PDF.
      current: function (scope, model) { return snapshots.isCurrent(scope, model); }
    });
  }
  return Object.freeze({ create: create });
});
