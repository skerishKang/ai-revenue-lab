/*  business-live-facts.js  —  client-side live fact adapter (Phase 2A)
 *
 *  Extends the existing github-live-status.js with Phase 2A
 *  phase-discovery and phase-verdict rendering.
 *
 *  Static identity manifest (ARL_MANIFEST) is never overwritten.
 *  Live facts are displayed alongside static data.
 *  CONFIGURATION_MISSING still shows the full static list.
 */

(function () {
  "use strict";

  /* ── Phase state labels (reuse existing vocabulary) ── */
  var PHASE_LABELS = {
    ko: {
      discovered: "발견됨",
      conflict: "충돌",
      unavailable: "사용 불가",
      verified: "검증됨",
      unverified: "미검증",
      invalid: "무효",
      pending: "대기",
      /* discovery methods */
      refs: "Refs",
      related_to: "Related to",
      marker: "마커",
      branch: "브랜치",
      fallback: "대체",
      /* mapping status */
      configuration_missing: "설정 없음",
      cache_configuration_missing: "캐시 설정 없음",
      upstream_unavailable: "GitHub 연결 불가",
      upstream_rate_limited: "GitHub 속도 제한",
      mapping_conflict: "매핑 충돌",
      verdict_unverified: "검증되지 않은 판정",
      stale: "오래된 정보",
    },
    en: {
      discovered: "DISCOVERED",
      conflict: "CONFLICT",
      unavailable: "UNAVAILABLE",
      verified: "VERIFIED",
      unverified: "UNVERIFIED",
      invalid: "INVALID",
      pending: "PENDING",
      refs: "REFS",
      related_to: "RELATED TO",
      marker: "MARKER",
      branch: "BRANCH",
      fallback: "FALLBACK",
      configuration_missing: "CONFIG MISSING",
      cache_configuration_missing: "CACHE CONFIG MISSING",
      upstream_unavailable: "UPSTREAM UNAVAILABLE",
      upstream_rate_limited: "RATE LIMITED",
      mapping_conflict: "MAPPING CONFLICT",
      verdict_unverified: "UNVERIFIED VERDICT",
      stale: "STALE",
    },
  };

  function lang() {
    return document.documentElement.lang === "en" ? "en" : "ko";
  }

  function l(key) {
    return PHASE_LABELS[lang()][key] || key;
  }

  /* ── Exported API ── */
  var api = {
    decorateDiscovery: decorateDiscovery,
    decorateVerdict: decorateVerdict,
    phaseLabel: phaseLabel,
    discoveryLabel: discoveryLabel,
    verdictLabel: verdictLabel,
  };

  /* ── Phase state badge CSS class ── */
  function phaseStateClass(state) {
    switch (state) {
      case "pass": return "phase-ap";
      case "fail": return "phase-nr";
      case "pending": return "phase-ip";
      default: return "phase-ns";
    }
  }

  /* ── Discovery method label ── */
  function discoveryLabel(method) {
    if (!method) return "—";
    return l(method);
  }

  /* ── Verdict status label ── */
  function verdictLabel(verdict) {
    if (!verdict) return "—";
    if (typeof verdict === "object") {
      return verdict.status === "verified"
        ? (verdict.verdict || "—")
        : l(verdict.status);
    }
    return String(verdict);
  }

  function phaseLabel(state) {
    var s = String(state || "").toLowerCase();
    switch (s) {
      case "pass": return "\u2713 PASS";
      case "fail": return "\u2717 FAIL";
      case "pending": return "\u25CB PENDING";
      default: return "\u2014";
    }
  }

  /* ── Decorate business rows with phase discovery info ── */
  function decorateDiscovery(payload) {
    if (!payload?.ok || !Array.isArray(payload.businesses)) return;
    var items = document.querySelectorAll(".biz-item[data-biz-number]");
    for (var i = 0; i < items.length; i++) {
      var row = items[i];
      var num = Number(row.dataset.bizNumber);
      var live = payload.businesses.find(function (b) { return b.number === num; });
      if (!live) continue;

      var discovery = live.phaseDiscovery;
      if (!discovery) continue;

      var target = row.querySelector("[data-live-discovery]");
      if (!target) continue;

      var parts = [];
      if (discovery.ui && discovery.ui.status === "discovered") {
        parts.push("UI:" + l(discovery.ui.method || "discovered"));
      }
      if (discovery.ui && discovery.ui.status === "conflict") {
        parts.push("UI:" + l("conflict"));
      }
      target.textContent = parts.length ? parts.join(" ") : "";
    }
  }

  /* ── Decorate business detail dialog with verdict info ── */
  function decorateVerdict(payload, dialogBody) {
    if (!payload?.ok || !dialogBody) return;
    var numEl = dialogBody.querySelector(".dialog-biznumber");
    if (!numEl) return;
    var num = Number((numEl.textContent || "").replace(/\D/g, ""));
    var live = (payload.businesses || []).find(function (b) { return b.number === num; });
    if (!live) return;

    var verdictBlock = dialogBody.querySelector("[data-verdict-block]");
    if (verdictBlock) {
      // Already decorated
      return;
    }

    var verdicts = live.phaseVerdicts;
    if (!verdicts) return;

    var container = document.createElement("div");
    container.dataset.verdictBlock = "true";
    container.className = "dialog-section";

    var html = '<hr class="dialog-divider">';
    html += '<span class="dialog-section-label" data-label-ko="단계 판정" data-label-en="PHASE VERDICT">PHASE VERDICT</span>';

    if (verdicts.ui) {
      html += '<div class="dialog-section"><span class="dialog-section-label">UI</span>';
      html += '<span class="dialog-section-value">' + verdictLabel(verdicts.ui) + '</span></div>';
    }
    if (verdicts.ux) {
      html += '<div class="dialog-section"><span class="dialog-section-label">UX</span>';
      html += '<span class="dialog-section-value">' + verdictLabel(verdicts.ux) + '</span></div>';
    }
    if (verdicts.backend) {
      html += '<div class="dialog-section"><span class="dialog-section-label">BACKEND</span>';
      html += '<span class="dialog-section-value">' + verdictLabel(verdicts.backend) + '</span></div>';
    }

    container.innerHTML = html;
    dialogBody.appendChild(container);

    // Update language labels
    var labels = container.querySelectorAll("[data-label-ko]");
    for (var i = 0; i < labels.length; i++) {
      labels[i].textContent = labels[i].dataset[lang() === "en" ? "labelEn" : "labelKo"];
    }
  }

  /* ── Expose API ── */
  window.ARLLiveFacts = api;
})();
