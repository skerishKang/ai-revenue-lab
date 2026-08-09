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

  // index.html loads businesses.js immediately before app.js. Keep the portfolio
  // truth layer and review registry parser-blocking so app.js sees corrected
  // owner-review / external-lineage fields before it captures ARL_BUSINESSES.
  // The launcher registers a deferred DOMContentLoaded enhancement and therefore
  // can be loaded here before app.js without racing app initialization.
  if (typeof document !== "undefined" && document.readyState === "loading") {
    document.write('<script src="./portfolio-truth-audit.js?v=portfolio-truth-20260809-1"><\/script>');
    document.write('<link rel="stylesheet" href="./business-launcher.css?v=business-launcher-20260809-1">');
    document.write('<script src="./review-surfaces-396.js?v=review-surfaces-20260809-2"><\/script>');
    document.write('<script src="./business-launcher.js?v=business-launcher-20260809-1"><\/script>');
  }
})();
