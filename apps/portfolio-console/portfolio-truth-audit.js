/* portfolio-truth-audit.js
 *
 * Owner-facing truth layer for Portfolio Console.
 *
 * Separates historical technical phase evidence from final owner visual review,
 * and applies the #396 external / successor boundary without modifying any
 * external repository or product implementation.
 */
(function (root) {
  "use strict";

  var OWNER = Object.freeze({
    APPROVED: "OWNER_APPROVED",
    REJECTED: "OWNER_REJECTED",
    REVIEW_REQUIRED: "OWNER_REVIEW_REQUIRED",
    NOT_APPLICABLE: "NOT_APPLICABLE"
  });

  // #396 hard exclusions. Repository links are supplied only where an
  // authoritative source is recorded. Missing links remain intentionally null.
  var BOUNDARIES = Object.freeze({
    3:  { kind:"external-parallel",       title:"External / Parallel Track", korean:"외부·병렬 작업", repository:null },
    5:  { kind:"expanded-successor",      title:"DanjiOn", korean:"단지온", repository:"https://github.com/skerishKang/02-danji-on" },
    23: { kind:"external-implementation", title:"LoveBud", korean:"LoveBud", repository:"https://github.com/skerishKang/LoveBud" },
    24: { kind:"external-implementation", title:"LoveTree 3.0", korean:"LoveTree 3.0", repository:"https://github.com/skerishKang/lovetree3.0" },
    25: { kind:"external-implementation", title:"Love Matchmaking", korean:"러브 매치메이킹", repository:"https://github.com/skerishKang/401-love-match-making" },
    26: { kind:"integrated-successor",     title:"Ieeon", korean:"이어온", repository:null },
    27: { kind:"integrated-successor",     title:"Sasillo", korean:"사실로", repository:null },
    28: { kind:"integrated-successor",     title:"Ieeon", korean:"이어온", repository:null },
    30: { kind:"expanded-successor",       title:"400 AI Finder", korean:"400-ai-finder", repository:"https://github.com/skerishKang/400-ai-finder" },
    31: { kind:"integrated-successor",     title:"Sasillo", korean:"사실로", repository:null },
    50: { kind:"integrated-successor",     title:"Ieeon", korean:"이어온", repository:null }
  });

  function boundaryFor(number) {
    return BOUNDARIES[Number(number)] || null;
  }

  function ownerUiStatusFor(number) {
    var n = Number(number);
    if (boundaryFor(n)) return OWNER.NOT_APPLICABLE;
    if (n === 1) return OWNER.REJECTED;
    // No historical machine/CTO validation is promoted to owner acceptance.
    // Explicit future owner decisions may add OWNER.APPROVED entries here.
    return OWNER.REVIEW_REQUIRED;
  }

  function applyIdentityTruth() {
    var list = Array.isArray(root.ARL_BUSINESSES) ? root.ARL_BUSINESSES : [];
    list.forEach(function (business) {
      business.ownerUiStatus = ownerUiStatusFor(business.number);
      var boundary = boundaryFor(business.number);
      if (!boundary) return;

      // Reuse the launcher's existing lineage presentation contract. This is a
      // presentation class only; the exact boundary kind remains separately set.
      business.portfolioClass = "expanded-successor";
      business.boundaryKind = boundary.kind;
      business.lifecycle = boundary.kind === "integrated-successor"
        ? "integrated_successor"
        : boundary.kind === "expanded-successor"
          ? "expanded_successor"
          : "external_implementation";
      business.state = "external";
      business.uiStatus = "NOT_APPLICABLE";
      business.uxStatus = "NOT_APPLICABLE";
      business.backendStatus = "NOT_APPLICABLE";
      business.successorTitle = boundary.title;
      business.successorKoreanTitle = boundary.korean;
      business.successorRepository = boundary.repository;

      if (boundary.repository) {
        business.workspace = boundary.repository.replace("https://github.com/", "");
      } else {
        business.workspace = "외부 원본 · 링크 확인 필요";
      }
    });
  }

  function language() {
    return document.documentElement.lang === "en" ? "en" : "ko";
  }

  function businessForRow(row) {
    if (!row) return null;
    var n = Number(row.dataset.bizNumber);
    return (root.ARL_BUSINESSES || []).find(function (item) { return item.number === n; }) || null;
  }

  function ownerUiCopy(business) {
    var lang = language();
    if (!business) return "";
    if (business.ownerUiStatus === OWNER.REJECTED) return lang === "en" ? "UI · REDESIGN" : "UI · 재설계";
    if (business.ownerUiStatus === OWNER.APPROVED) return lang === "en" ? "UI · OWNER APPROVED" : "UI · 사용자 승인";
    if (business.ownerUiStatus === OWNER.REVIEW_REQUIRED && business.uiStatus === "UI_APPROVED") {
      return lang === "en" ? "UI · OWNER REVIEW" : "UI · 검토 필요";
    }
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
      return lang === "en" ? "External / parallel expansion · internal work excluded" : "외부·병렬 확장 · 내부 개발 제외";
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
        firstBadge.title = business.ownerUiStatus === OWNER.REJECTED
          ? (language() === "en" ? "Owner rejected current visual UI; redesign required" : "현재 UI 사용자 미승인 · 재설계 필요")
          : (language() === "en" ? "Technical UI evidence exists; final owner visual review is still required" : "기술 UI 검증 이력 있음 · 사용자 최종 시각 검토 필요");
      }
    }

    var boundary = boundaryFor(business.number);
    if (!boundary) return;

    row.dataset.portfolioClass = "expanded-successor";
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

    // Existing external live sites remain directly reviewable. The detail dialog
    // continues to expose the authoritative repository link when one is known.
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
      // Observe direct row replacement only. Badge text mutations are descendants
      // and therefore cannot feed back into this observer.
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
    BOUNDARIES: BOUNDARIES,
    boundaryFor: boundaryFor,
    ownerUiStatusFor: ownerUiStatusFor
  });

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", startDomTruth);
    else startDomTruth();
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
