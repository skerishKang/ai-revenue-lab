/* B66 CGI only: bounded authenticated-browser raster PDF exporter.
   Uses the EXACT SAME operation list as the certified DOM preview.
   No provider, PDF Worker, document compiler, or third-party HTTP call. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./quote-template-renderer.js"));
  } else {
    root.B66BrowserPdf = factory(root.QuoteTemplateRenderer);
  }
})(typeof self !== "undefined" ? self : this, function (Renderer) {
  "use strict";
  var MAX_ITEM_ROWS = Renderer.CGI_MAX_ITEM_ROWS;
  var CGI_SKILL_ID = "b66skill_2eb55d822407f626b7a75c8c88d32c40";
  var CGI_BASE_SHA256 = "462f66f6e32a7409edafef09fed5a10fd99549738df38180d430c04ef99d0de9";
  var PREVIEW_URL = "/api/padiem/b66/quote/preview-base?saved_skill_id=" + CGI_SKILL_ID;
  var WIDTH = 1190;
  var HEIGHT = 1682;
  var MAX_PNG = 512 * 1024;
  var MAX_JPEG = 4 * 1024 * 1024;
  var enc = typeof TextEncoder === "function" ? new TextEncoder() : null;

  function fail(code) {
    var error = new Error(code);
    error.code = code;
    throw error;
  }

  function sameProjection(model, preview) {
    return model && preview && model.derivedBy === "quote-core" &&
      model.template && model.template.approved === true &&
      preview.template && preview.template.approved === true &&
      !preview.template.fallbackReason &&
      preview.layoutVariant === "cgi-v2" &&
      model.template.fingerprint === preview.template.fingerprint &&
      JSON.stringify(model.facts) === JSON.stringify(preview.facts) &&
      JSON.stringify(model.items) === JSON.stringify(preview.items) &&
      JSON.stringify(model.totals) === JSON.stringify(preview.totals) &&
      model.taxReview && model.taxReview.required === false &&
      model.coreTotals && !((model.coreTotals.detailGroups || []).length);
  }

  function certifiedPreviewModel(model, skillId, approvedFingerprint) {
    // Presentation-only override for the exact owner-assigned, source-certified
    // CGI skill; NEVER alter the saved internal template or QuoteCore totals.
    if (!isCgiSkill(skillId) || !model || model.derivedBy !== "quote-core" ||
        !model.template || model.template.approved !== true ||
        model.template.fallbackReason ||
        typeof approvedFingerprint !== "string" || !approvedFingerprint ||
        model.template.fingerprint !== approvedFingerprint ||
        model.certifiedPreviewBaseUrl !== PREVIEW_URL) return model;
    return Object.assign({}, model, { layoutVariant: "cgi-v2" });
  }

  function isCgiSkill(id) { return id === CGI_SKILL_ID; }

  function project(model, preview) {
    if (!Renderer || typeof Renderer.buildCgiCertifiedDrawOps !== "function" ||
        !sameProjection(model, preview) || preview.certifiedPreviewBaseUrl !== PREVIEW_URL)
      fail("browser_pdf_projection_mismatch");
    var rows = (model.items || []).filter(function (r) { return r && r.filler !== true; });
    if (rows.length > MAX_ITEM_ROWS || !Array.isArray(model.coreTotals.effectiveItems) ||
        model.coreTotals.effectiveItems.length > MAX_ITEM_ROWS) fail("browser_pdf_unsupported_rows");
    var ops = Renderer.buildCgiCertifiedDrawOps(preview);
    if (!Array.isArray(ops) || !ops.length || ops.length > 40 ||
        ops.some(function (op) {
          return typeof op.text !== "string" || op.text.length > 240 ||
            !Number.isFinite(op.size) || op.size <= 0 || !Number.isFinite(op.baselineY);
        })) fail("browser_pdf_invalid_projection");
    return ops;
  }

  function encodeJpegPdf(jpeg) {
    if (!enc || !(jpeg instanceof Uint8Array) || jpeg.length < 4 ||
        jpeg.length > MAX_JPEG || jpeg[0] !== 255 || jpeg[1] !== 216 ||
        jpeg[jpeg.length - 2] !== 255 || jpeg[jpeg.length - 1] !== 217) {
      fail("browser_pdf_invalid_image");
    }
    var parts = [], offsets = [0], size = 0;
    function bytes(b) { parts.push(b); size += b.length; }
    function ascii(s) { bytes(enc.encode(s)); }
    function object(id, head, data, end) {
      offsets[id] = size;
      ascii(id + " 0 obj\n" + head);
      if (data) { bytes(data); ascii(end || ""); }
      ascii("\nendobj\n");
    }
    ascii("%PDF-1.4\n");
    object(1, "<< /Type /Catalog /Pages 2 0 R >>");
    object(2, "<< /Type /Pages /Count 1 /Kids [3 0 R] >>");
    object(3, "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 841] /Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>");
    var commands = enc.encode("q\n595 0 0 841 0 0 cm\n/Im0 Do\nQ\n");
    object(4, "<< /Length " + commands.length + " >>\nstream\n", commands, "endstream");
    object(5, "<< /Type /XObject /Subtype /Image /Width " + WIDTH + " /Height " + HEIGHT +
      " /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length " + jpeg.length +
      " >>\nstream\n", jpeg, "\nendstream");
    var xref = size;
    ascii("xref\n0 6\n0000000000 65535 f \n");
    for (var id = 1; id <= 5; id++) {
      ascii(String(offsets[id]).padStart(10, "0") + " 00000 n \n");
    }
    ascii("trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + xref + "\n%%EOF\n");
    var pdf = new Uint8Array(size), at = 0;
    parts.forEach(function (part) { pdf.set(part, at); at += part.length; });
    return pdf;
  }

  function drawPage(deps, img, ops) {
    var canvas = deps.document.createElement("canvas");
    canvas.width = WIDTH;
    canvas.height = HEIGHT;
    var ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) fail("browser_pdf_canvas_unavailable");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, WIDTH, HEIGHT);
    ctx.drawImage(img, 0, 0, WIDTH, HEIGHT);
    var scale = WIDTH / 595;
    ops.forEach(function (op) {
      var opts = op.options || {};
      ctx.fillStyle = "#111";
      ctx.textAlign = Number.isFinite(Number(opts.rightX)) ? "right" : "left";
      ctx.textBaseline = "alphabetic";
      var family = op.key === "written-total" ? '"GulimChe", "Gulim", monospace' :
        '"Malgun Gothic", sans-serif';
      ctx.font = (opts.bold ? "700 " : "400 ") + (op.size * scale) + "px " + family;
      var x = ctx.textAlign === "right" ? Number(opts.rightX) : Number(op.x);
      ctx.fillText(op.text, x * scale, op.baselineY * scale);
    });
    return canvas;
  }

  async function makePdf(renderModel, previewModel, deps) {
    deps = deps || (typeof window !== "undefined" ? window : null);
    if (!deps || !deps.crypto || !deps.crypto.subtle || !deps.Blob || !deps.Image ||
        !deps.URL || !deps.document || typeof deps.fetch !== "function") fail("browser_pdf_runtime_unavailable");
    var ops = project(renderModel, previewModel); // fail before private fetch
    var response = await deps.fetch(PREVIEW_URL, {
      method: "GET", cache: "no-store", credentials: "same-origin",
      headers: { Accept: "image/png" }
    });
    if (!response.ok || (response.headers.get("content-type") || "").split(";")[0].trim().toLowerCase() !== "image/png")
      fail("browser_pdf_private_asset_unavailable");
    var length = Number(response.headers.get("content-length") || "0");
    if (length > MAX_PNG) fail("browser_pdf_image_too_large");
    var buffer = await response.arrayBuffer();
    if (!buffer.byteLength || buffer.byteLength > MAX_PNG) fail("browser_pdf_image_too_large");
    var buf = new Uint8Array(buffer);
    if (buf.length < 24 || buf[0] !== 137 || buf[1] !== 80 || buf[2] !== 78 || buf[3] !== 71 ||
        buf[4] !== 13 || buf[5] !== 10 || buf[6] !== 26 || buf[7] !== 10)
      fail("browser_pdf_invalid_png");
    var shaBytes = new Uint8Array(await deps.crypto.subtle.digest("SHA-256", buffer));
    var sha = Array.from(shaBytes, function (b) { return b.toString(16).padStart(2, "0"); }).join("");
    if (sha !== CGI_BASE_SHA256) fail("browser_pdf_asset_mismatch");
    var blobUrl = deps.URL.createObjectURL(new deps.Blob([buffer], { type: "image/png" }));
    try {
      var img = new deps.Image();
      img.src = blobUrl;
      await img.decode();
      if (img.naturalWidth !== WIDTH || img.naturalHeight !== HEIGHT)
        fail("browser_pdf_dimensions_mismatch");
      var canvas = drawPage(deps, img, ops);
      var jpegBlob = await new Promise(function (resolve) {
        canvas.toBlob(resolve, "image/jpeg", 0.98);
      });
      if (!jpegBlob || jpegBlob.type !== "image/jpeg" || jpegBlob.size > MAX_JPEG)
        fail("browser_pdf_encode_failed");
      return encodeJpegPdf(new Uint8Array(await jpegBlob.arrayBuffer()));
    } finally {
      deps.URL.revokeObjectURL(blobUrl);
    }
  }

  return Object.freeze({
    CGI_SKILL_ID: CGI_SKILL_ID,
    MAX_ITEM_ROWS: MAX_ITEM_ROWS,
    CGI_BASE_SHA256: CGI_BASE_SHA256,
    PREVIEW_URL: PREVIEW_URL,
    isCgiSkill: isCgiSkill,
    certifiedPreviewModel: certifiedPreviewModel,
    project: project,
    encodeJpegPdf: encodeJpegPdf,
    makePdf: makePdf
  });
});
