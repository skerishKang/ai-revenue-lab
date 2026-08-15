/* portfolio-truth-audit.js
 *
 * Owner-facing truth layer for Portfolio Console.
 *
 * Stable external/successor identity is owned by business-manifest.js.
 * This layer only applies owner-review and phase-presentation semantics.
 */
(function (root) {
  "use strict";

  var OWNER = Object.freeze({
    APPROVED: "OWNER_APPROVED",
    REJECTED: "OWNER_REJECTED",
    REVIEW_REQUIRED: "OWNER_REVIEW_REQUIRED",
    NOT_APPLICABLE: "NOT_APPLICABLE"
  });

  var HARD_EXCLUSIONS = Object.freeze({
    3:true, 5:true, 23:true, 24:true, 25:true,
    26:true, 27:true, 28:true, 30:true, 31:true, 50:true
  });

  var OWNER_APPROVED = Object.freeze({
    6: {
      source: "PR #158 issuecomment-5082096357",
      date: "2026-07-26",
      exactHead: "cde6677e71172125cb3a0406f6ba6a79e0467d36"
    }
  });

  var OWNER_REVIEW_READY = Object.freeze({
    1: {
      source: "PR #456",
      mergedCommit: "dc129b0a2768ec8aaae0d7517e182311d7b80422",
      surfaceUrl: "https://ai-revenue-final-review-b01.pages.dev/"
    },
    2: {
      source: "PR #460",
      mergedCommit: "d2fcd03dc696c451fa1ab31a690249fa37c82a21",
      surfaceUrl: "https://ai-revenue-final-review-b02.pages.dev/"
    }
  });

  function businessByNumber(number) {
    var n = Number(number);
    return (root.ARL_BUSINESSES || []).find(function (item) {
      return Number(item.number) === n;
    }) || null;
  }

  function boundaryFor(number) {
    var n = Number(number);
    if (!HARD_EXCLUSIONS[n]) return null;
    var business = businessByNumber(n);
    if (!business || !business.boundaryKind) return null;
    return {
      kind: business.boundaryKind,
      title: business.successorTitle,
      korean: business.successorKoreanTitle,
      repository: business.successorRepository || null
    };
  }

  function ownerUiStatusFor(number) {
    var n = Number(number);
    if (boundaryFor(n) || n === 54) return OWNER.NOT_APPLICABLE;
    if (OWNER_APPROVED[n]) return OWNER.APPROVED;
    if (OWNER_REVIEW_READY[n]) return OWNER.REVIEW_REQUIRED;
    return OWNER.REVIEW_REQUIRED;
  }

  function applyIdentityTruth() {
    var list = Array.isArray(root.ARL_BUSINESSES) ? root.ARL_BUSINESSES : [];
    list.forEach(function (business) {
      business.ownerUiStatus = ownerUiStatusFor(business.number);
      if (OWNER_APPROVED[business.number]) {
        business.ownerUiDecision = OWNER_APPROVED[business.number];
      }
      if (OWNER_REVIEW_READY[business.number]) {
        business.ownerUiDecision = OWNER_REVIEW_READY[business.number];
        business.surfaceUrl = OWNER_REVIEW_READY[business.number].surfaceUrl;
      }

      // Stable lineage, workspace, lifecycle, state and successor metadata are
      // already authoritative in business-manifest.js. Only phase presentation
      // becomes not-applicable for hard-excluded external/successor Businesses.
      if (boundaryFor(business.number)) {
        business.uiStatus = "NOT_APPLICABLE";
        business.uxStatus = "NOT_APPLICABLE";
        business.backendStatus = "NOT_APPLICABLE";
      }
    });
  }

  function language() {
    return document.documentElement.lang === "en" ? "en" : "ko";
  }

  function businessForRow(row) {
    if (!row) return null;
    return businessByNumber(Number(row.dataset.bizNumber));
  }

  function ownerUiCopy(business) {
    var lang = language();
    if (!business) return "";
    if (business.ownerUiStatus === OWNER.REJECTED) return lang === "en" ? "UI · REDESIGN" : "UI · 재설계";
    if (business.ownerUiStatus === OWNER.APPROVED) return lang === "en" ? "UI · OWNER APPROVED" : "UI · 사용자 승인";
    if (business.ownerUiStatus === OWNER.REVIEW_REQUIRED) return lang === "en" ? "UI · OWNER REVIEW" : "UI · 검토 필요";
    return null;
  }

  function lineageCopy(boundary) {
    if (!boundary) return "";
    var lang = language();
    if (boundary.kind === "integrated-successor") {
      return lang === "en"
        ? "Integrated into " + boundary.title + " · external development"
        : "통합 → " + boundary.korean + " · 외부 개발";
    }
    if (boundary.kind === "external-implementation") {
      return lang === "en"
        ? "External implementation · " + boundary.title
        : "외부 개발 · " + boundary.korean;
    }
    if (boundary.kind === "external-parallel") {
      return lang === "en"
        ? "External / parallel expansion · internal work excluded"
        : "외부·병렬 확장 · 내부 개발 제외";
    }
    return lang === "en"
      ? "Expanded to " + boundary.title + " · external development"
      : "확장 → " + boundary.korean + " · 외부 개발";
  }

  function decorateRow(row) {
    var business = businessForRow(row);
    if (!business) return;
    row.dataset.ownerUiStatus = business.ownerUiStatus;

    var ownerCopy = ownerUiCopy(business);
    if (ownerCopy) {
      var firstBadge = row.querySelector(".biz-phase-badge");
      if (firstBadge && firstBadge.textContent !== ownerCopy) firstBadge.textContent = ownerCopy;
      if (firstBadge) {
        if (business.ownerUiStatus === OWNER.REJECTED) {
          firstBadge.title = language() === "en"
            ? "Owner rejected current visual UI; redesign required"
            : "현재 UI 사용자 미승인 · 재설계 필요";
        } else if (business.ownerUiStatus === OWNER.APPROVED) {
          firstBadge.title = language() === "en"
            ? "Explicit owner visual approval is recorded"
            : "사용자 직접 시각 승인 기록 있음";
        } else {
          firstBadge.title = language() === "en"
            ? "A review surface exists; final owner visual review is still required"
            : "검토 가능한 화면 있음 · 사용자 최종 시각 검토 필요";
        }
      }
    }

    var boundary = boundaryFor(business.number);
    if (!boundary) return;

    row.dataset.portfolioClass = business.portfolioClass || "expanded-successor";
    row.dataset.boundaryKind = boundary.kind;

    var authority = row.querySelector(".biz-auth");
    if (authority) {
      var authorityText = language() === "en" ? "EXTERNAL" : "외부/확장";
      if (authority.textContent !== authorityText) authority.textContent = authorityText;
    }

    var lineage = row.querySelector(".biz-expanded-lineage");
    if (lineage) {
      var nextLineage = lineageCopy(boundary);
      if (lineage.textContent !== nextLineage) lineage.textContent = nextLineage;
    }

    var action = row.querySelector(".biz-launch-external");
    var state = row.querySelector(".biz-launch-state");
    if (business.surfaceUrl && action) {
      action.href = business.surfaceUrl;
      action.textContent = language() === "en" ? "Open site ↗" : "사이트 열기 ↗";
    } else if (!boundary.repository && state) {
      state.textContent = language() === "en" ? "EXTERNAL" : "외부 작업";
    }
  }

  function decorateAll() {
    document.querySelectorAll("#biz-list .biz-item").forEach(decorateRow);
  }

  function startDomTruth() {
    decorateAll();
    var list = document.querySelector("#biz-list");
    if (list) {
      new MutationObserver(decorateAll).observe(list, { childList: true });
    }
    new MutationObserver(decorateAll).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["lang"]
    });
  }

  applyIdentityTruth();

  root.ARL_PORTFOLIO_TRUTH = Object.freeze({
    OWNER: OWNER,
    HARD_EXCLUSIONS: HARD_EXCLUSIONS,
    OWNER_APPROVED: OWNER_APPROVED,
    OWNER_REVIEW_READY: OWNER_REVIEW_READY,
    boundaryFor: boundaryFor,
    ownerUiStatusFor: ownerUiStatusFor
  });

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", startDomTruth);
    else startDomTruth();
  }
})(typeof globalThis !== "undefined" ? globalThis : this);