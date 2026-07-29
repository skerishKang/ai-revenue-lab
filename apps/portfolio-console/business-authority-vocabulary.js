/*
 * AI Revenue Lab — Business Authority Vocabulary
 *
 * Canonical vocabulary for number-authority classification and
 * UI / UX / Backend phase states. Also provides the compact
 * record factory `rec()` used by businesses.js.
 *
 * This file is the single source for all vocabulary constants.
 * It must be loaded before businesses.js.
 *
 * Last verified against origin/main SHA: b24e2452928d8181f5f3f5ee7b5d2aee66ab1538
 * Last updated: 2026-07-29
 */

window.ARL_VOCABULARY = (function () {
  "use strict";

  var NUMBER_AUTHORITY = {
    CANONICAL: "canonical",
    PROPOSED: "proposed-number",
    CANDIDATE: "candidate",
    EXISTING_PROJECT: "existing-project",
    RESERVED: "reserved",
    RECONCILIATION: "number-reconciliation-required"
  };

  var UI_STATUS = {
    NOT_STARTED: "NOT_STARTED",
    IN_PROGRESS: "IN_PROGRESS",
    NOT_READY: "UI_NOT_READY",
    CONDITIONALLY_READY: "UI_CONDITIONALLY_READY",
    APPROVED: "UI_APPROVED",
    NOT_APPLICABLE: "NOT_APPLICABLE"
  };

  var UX_STATUS = {
    BLOCKED_BY_UI: "BLOCKED_BY_UI",
    NOT_STARTED: "NOT_STARTED",
    IN_PROGRESS: "IN_PROGRESS",
    NOT_READY: "UX_NOT_READY",
    CONDITIONALLY_READY: "UX_CONDITIONALLY_READY",
    APPROVED: "UX_APPROVED",
    NOT_APPLICABLE: "NOT_APPLICABLE"
  };

  var BACKEND_STATUS = {
    FROZEN: "FROZEN",
    DECISION_PENDING: "DECISION_PENDING",
    DEFERRED: "DEFERRED",
    AUTHORIZED: "AUTHORIZED",
    IN_PROGRESS: "IN_PROGRESS",
    IMPLEMENTED: "IMPLEMENTED",
    NOT_APPLICABLE: "NOT_APPLICABLE"
  };

  // ── helper: compact record factory ──
  function rec(data) {
    return {
      number: data.n,
      slug: data.s,
      title: data.t,
      koreanTitle: data.k,
      numberAuthority: data.a,
      lifecycle: data.l || "concept",
      state: data.st || "planned",
      uiStatus: data.ui || UI_STATUS.NOT_STARTED,
      uxStatus: data.ux || UX_STATUS.BLOCKED_BY_UI,
      backendStatus: data.be || BACKEND_STATUS.FROZEN,
      productDecisionIssue: data.pdi || null,
      currentIssue: data.ci || null,
      currentPr: data.pr || null,
      acceptedVisualHead: data.avh || null,
      acceptedUxHead: data.auh || null,
      workspace: data.w || null,
      surfaceType: data.sty || null,
      surfaceUrl: data.su || null,
      deployment: data.d || null,
      releaseState: data.rs || "not_released",
      githubLabel: data.gl || null,
      githubUrl: data.gu || null,
      issueUrl: data.iu || null,
      currentAction: data.ca || null,
      nextAction: data.na || null,
      knownLimitation: data.kl || null,
      sources: data.src || null,
      lastVerified: data.lv || "2026-07-29",
      priority: data.p || 0
    };
  }

  // ── summary generator ──
  function generateSummary(businesses) {
    if (!Array.isArray(businesses) || businesses.length === 0) {
      return null;
    }
    var authCounts = {};
    var uiCounts = {};
    var uxCounts = {};
    var beCounts = {};

    for (var i = 0; i < businesses.length; i++) {
      var b = businesses[i];
      authCounts[b.numberAuthority] = (authCounts[b.numberAuthority] || 0) + 1;
      uiCounts[b.uiStatus] = (uiCounts[b.uiStatus] || 0) + 1;
      uxCounts[b.uxStatus] = (uxCounts[b.uxStatus] || 0) + 1;
      beCounts[b.backendStatus] = (beCounts[b.backendStatus] || 0) + 1;
    }

    var total = businesses.length;
    var authSum = 0; for (var k in authCounts) authSum += authCounts[k];
    var uiSum = 0; for (var k in uiCounts) uiSum += uiCounts[k];
    var uxSum = 0; for (var k in uxCounts) uxSum += uxCounts[k];
    var beSum = 0; for (var k in beCounts) beSum += beCounts[k];

    return {
      total: total,
      authSum: authSum,
      uiSum: uiSum,
      uxSum: uxSum,
      beSum: beSum,
      numberAuthority: authCounts,
      uiStatus: uiCounts,
      uxStatus: uxCounts,
      backendStatus: beCounts
    };
  }

  return {
    NUMBER_AUTHORITY: NUMBER_AUTHORITY,
    UI_STATUS: UI_STATUS,
    UX_STATUS: UX_STATUS,
    BACKEND_STATUS: BACKEND_STATUS,
    rec: rec,
    generateSummary: generateSummary
  };
})();
