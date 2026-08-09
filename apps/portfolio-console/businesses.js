/*  businesses.js  —  B1–59 derived from ARL_MANIFEST (Phase 2A+)
 *
 *  This is a thin compatibility layer that exposes ARL_MANIFEST
 *  as ARL_BUSINESSES for the existing app.js consumer.
 *
 *  The sole identity source is business-manifest.js → window.ARL_MANIFEST.
 *  Review deployment metadata is loaded from review-surfaces-396.js.
 *  Business launcher behavior is layered on top without changing app.js.
 */

(function () {
  "use strict";
  var manifest = window.ARL_MANIFEST;
  if (!manifest || !Array.isArray(manifest)) {
    window.ARL_BUSINESSES = [];
    return;
  }
  window.ARL_BUSINESSES = manifest;
  window.ARL_SUMMARY = window.ARL_MANIFEST_SUMMARY || null;

  // index.html loads businesses.js immediately before app.js. All dynamically
  // written scripts remain parser-blocking, so the truth layer still mutates the
  // Business data before app.js captures ARL_BUSINESSES. Load the launcher first
  // only so its DOMContentLoaded decorator is registered before the audit's final
  // owner/external presentation pass; the audit therefore owns the final labels.
  if (typeof document !== "undefined" && document.readyState === "loading") {
    document.write('<link rel="stylesheet" href="./business-launcher.css?v=business-launcher-20260809-1">');
    document.write('<script src="./review-surfaces-396.js?v=review-surfaces-20260809-2"><\/script>');
    document.write('<script src="./business-launcher.js?v=business-launcher-20260809-1"><\/script>');
    document.write('<script src="./portfolio-truth-audit.js?v=portfolio-truth-20260809-1"><\/script>');
  }
})();
