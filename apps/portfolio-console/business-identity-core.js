/*  business-identity-core.js  —  SINGLE SOURCE for B1–59 phase authority (Phase 2A+)
 *
 * Static portfolio phase status only. Volatile Issue/PR/CI/SHA facts remain
 * outside this file. B56 is an intentional numbering gap.
 */

(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ARL_IDENTITY_CORE = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var BUSINESS_PHASE_AUTHORITY = Object.freeze([
    // n, ui, ux, be
    { n:1,  ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
    { n:2,  ui:"UI_APPROVED",   ux:"NOT_STARTED",    be:"IMPLEMENTED" },
    { n:3,  ui:"UI_APPROVED",   ux:"NOT_STARTED",    be:"IMPLEMENTED" },
    { n:4,  ui:"UI_APPROVED",   ux:"NOT_STARTED",    be:"NOT_APPLICABLE" },
    { n:5,  ui:"NOT_APPLICABLE",ux:"NOT_APPLICABLE", be:"NOT_APPLICABLE" },
    { n:6,  ui:"UI_APPROVED",   ux:"UX_NOT_READY",   be:"FROZEN" },
    { n:7,  ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:8,  ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:9,  ui:"UI_APPROVED",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:10, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:11, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:12, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:13, ui:"UI_APPROVED",   ux:"NOT_STARTED",    be:"DECISION_PENDING" },
    { n:14, ui:"UI_APPROVED",   ux:"NOT_STARTED",    be:"IN_PROGRESS" },
    { n:15, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:16, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:17, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:18, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:19, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:20, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:21, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:22, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:23, ui:"UI_APPROVED",   ux:"IN_PROGRESS",    be:"IMPLEMENTED" },
    { n:24, ui:"UI_APPROVED",   ux:"NOT_STARTED",    be:"IMPLEMENTED" },
    { n:25, ui:"NOT_STARTED",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
    { n:26, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
    { n:27, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
    { n:28, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
    { n:29, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
    { n:30, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
    { n:31, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
    { n:32, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:33, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:34, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:35, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:36, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:37, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:38, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:39, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:40, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:41, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:42, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:43, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:44, ui:"UI_APPROVED",   ux:"NOT_STARTED",    be:"IMPLEMENTED" },
    { n:45, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:46, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:47, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:48, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:49, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:50, ui:"NOT_STARTED",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
    { n:51, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:52, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:53, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:54, ui:"NOT_APPLICABLE",ux:"IN_PROGRESS",    be:"IN_PROGRESS" },
    { n:55, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:57, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:58, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"FROZEN" },
    { n:59, ui:"IN_PROGRESS",   ux:"IN_PROGRESS",    be:"NOT_APPLICABLE" }
  ]);

  var byNumber = {};
  for (var i = 0; i < BUSINESS_PHASE_AUTHORITY.length; i++) {
    byNumber[BUSINESS_PHASE_AUTHORITY[i].n] = BUSINESS_PHASE_AUTHORITY[i];
  }

  function phaseStatusFor(number) {
    var entry = byNumber[Number(number)];
    if (!entry) return { ui: "NOT_STARTED", ux: "BLOCKED_BY_UI", be: "FROZEN" };
    return { ui: entry.ui, ux: entry.ux, be: entry.be };
  }

  function buildIdentitySource() {
    var map = {};
    for (var i = 0; i < BUSINESS_PHASE_AUTHORITY.length; i++) {
      var entry = BUSINESS_PHASE_AUTHORITY[i];
      map[entry.n] = { uiStatus: entry.ui, uxStatus: entry.ux, backendStatus: entry.be };
    }
    return map;
  }

  return {
    BUSINESS_PHASE_AUTHORITY: BUSINESS_PHASE_AUTHORITY,
    phaseStatusFor: phaseStatusFor,
    buildIdentitySource: buildIdentitySource
  };
});