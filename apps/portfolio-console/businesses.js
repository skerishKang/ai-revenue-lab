/*  businesses.js  —  B1–59 derived from ARL_MANIFEST (Phase 2A+)
 *
 *  This is a thin compatibility layer that exposes ARL_MANIFEST
 *  as ARL_BUSINESSES for the existing app.js consumer.
 *
 *  The sole identity source is business-manifest.js → window.ARL_MANIFEST.
 *  Review deployment metadata is loaded from review-surfaces-396.js.
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

  // index.html loads businesses.js immediately before app.js. Keep the review
  // registry parser-blocking so app.js sees the attached reviewSurface fields.
  if (typeof document !== "undefined" && document.readyState === "loading") {
    document.write('<script src="./review-surfaces-396.js?v=review-surfaces-20260809-1"><\/script>');
  }
})();
