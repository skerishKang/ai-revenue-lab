/*  businesses.js  —  B1–55 derived from ARL_MANIFEST (Phase 2A)
 *
 *  This is a thin compatibility layer that exposes ARL_MANIFEST
 *  as ARL_BUSINESSES for the existing app.js consumer.
 *
 *  The sole identity source is business-manifest.js → window.ARL_MANIFEST.
 *  No Business identity data is duplicated in this file.
 *  No volatile GitHub state (Issue state, PR state, CI, SHA) here.
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
})();
