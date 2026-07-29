/*
 * AI Revenue Lab — Business Authority Registry
 *
 * This file is the single repository-local source of truth for
 * Business 1–55. Every Business has a normalized record with
 * separate UI / UX / Backend phase states and a clear
 * number-authority classification.
 *
 * Last verified against origin/main SHA: b24e2452928d8181f5f3f5ee7b5d2aee66ab1538
 * Last updated: 2026-07-29
 *
 * See docs/BUSINESS_AUTHORITY_AUDIT_2026-07-29.md for full audit.
 */

window.ARL_BUSINESSES = (function () {
  "use strict";

  // ── canonical vocabulary ──
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

  return [
    // ═══════════════════════════════════════════════════════════
    // 1–4: CANONICAL — verified in BUSINESS_REGISTRY.md
    // ═══════════════════════════════════════════════════════════
    rec({
      n: 1, s: "personal-edition", t: "Personal Edition", k: "퍼스널 에디션",
      a: NUMBER_AUTHORITY.CANONICAL, l: "private_preview", st: "review",
      ui: UI_STATUS.IN_PROGRESS, ux: UX_STATUS.BLOCKED_BY_UI, be: BACKEND_STATUS.FROZEN,
      pdi: 108, ci: 108, pr: 111,
      w: "apps/personal-edition/",
      sty: "Cloudflare Pages branch preview",
      su: "https://feat-personal-edition-final.ai-revenue-personal-edition.pages.dev",
      d: "Preview deployed; CTO changes required",
      rs: "preview_draft",
      gl: "Draft PR #111",
      gu: "https://github.com/skerishKang/ai-revenue-lab/pull/111",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/108",
      ca: "Fix visual and clickable-flow blockers",
      na: "Re-review PR #111 after fixes",
      kl: "PR #111 remains Draft; CTO review pending",
      src: "BUSINESS_REGISTRY.md; Issue #108; PR #111",
      lv: "2026-07-24", p: 100
    }),
    rec({
      n: 2, s: "living-travel", t: "Living Travel", k: "리빙 트래블",
      a: NUMBER_AUTHORITY.CANONICAL, l: "private_preview", st: "running",
      ui: UI_STATUS.APPROVED, ux: UX_STATUS.NOT_STARTED, be: BACKEND_STATUS.IMPLEMENTED,
      pdi: 43, ci: 107, pr: 88,
      w: "apps/living-travel/",
      sty: "External staging",
      su: "https://ops-living-travel-external-s.ai-revenue-living-travel.pages.dev",
      d: "Cloudflare Pages + Modal + Neon",
      rs: "staging",
      gl: "Merged PR #88",
      gu: "https://github.com/skerishKang/ai-revenue-lab/pull/88",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/107",
      ca: "Issue #107 Phase 3B live-provider activation",
      na: "Prepare resettable traveler/operator demo sequence",
      kl: "Remote PR/commit for Phase 3B not yet published",
      src: "BUSINESS_REGISTRY.md; Issues #32, #43, #69, #74, #86, #107; PR #88",
      lv: "2026-07-24", p: 35
    }),
    rec({
      n: 3, s: "living-fiction", t: "Living Fiction", k: "리빙 픽션",
      a: NUMBER_AUTHORITY.CANONICAL, l: "private_preview", st: "review",
      ui: UI_STATUS.APPROVED, ux: UX_STATUS.NOT_STARTED, be: BACKEND_STATUS.IMPLEMENTED,
      pdi: 55, ci: 75, pr: 85,
      w: "apps/living-fiction/",
      sty: "Modal production workflow (404 as of 2026-07-26)",
      su: null,
      d: "Modal + Neon — deployment unreachable",
      rs: "degraded",
      gl: "Merged PR #85",
      gu: "https://github.com/skerishKang/ai-revenue-lab/pull/85",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/75",
      ca: "Verify deployment and restore access",
      na: "Document synthetic invite credentials and demo-data reset procedure",
      kl: "Existing Modal URL returns 404 — deployment re-verification required",
      src: "BUSINESS_REGISTRY.md; Issues #34, #55, #75, #77; PR #85",
      lv: "2026-07-26", p: 32
    }),
    rec({
      n: 4, s: "living-learning", t: "Living Learning", k: "리빙 러닝",
      a: NUMBER_AUTHORITY.CANONICAL, l: "private_preview", st: "running",
      ui: UI_STATUS.APPROVED, ux: UX_STATUS.NOT_STARTED, be: BACKEND_STATUS.NOT_APPLICABLE,
      pdi: 37, ci: 37, pr: 94,
      w: "apps/living-learning/",
      sty: "Cloudflare Pages static demo",
      su: "https://ai-revenue-living-learning.pages.dev/",
      d: "Static preview available",
      rs: "static_preview",
      gl: "Merged PR #94",
      gu: "https://github.com/skerishKang/ai-revenue-lab/pull/94",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/37",
      ca: "Standardize adaptive-lesson demo narration",
      na: "Standardize first-lesson to adapted-lesson demo flow",
      kl: "Static demo only; no adaptive runtime",
      src: "BUSINESS_REGISTRY.md; Issue #37; PR #94",
      lv: "2026-07-24", p: 30
    }),

    // ═══════════════════════════════════════════════════════════
    // 5: PROPOSED-NUMBER — Issue #99 open, registry update pending
    // ═══════════════════════════════════════════════════════════
    rec({
      n: 5, s: "neighbor-market", t: "Neighbor Market", k: "우리단지 이웃가게",
      a: NUMBER_AUTHORITY.PROPOSED, l: "concept", st: "review",
      ui: UI_STATUS.IN_PROGRESS, ux: UX_STATUS.BLOCKED_BY_UI, be: BACKEND_STATUS.FROZEN,
      pdi: 99, ci: 99, pr: 109,
      w: "reference/business-05-neighbor-market-v2/",
      sty: "Static demo in Draft PR",
      su: null,
      d: "Assignment pending; no production deployment",
      rs: "not_released",
      gl: "Draft PR #109",
      gu: "https://github.com/skerishKang/ai-revenue-lab/pull/109",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/99",
      ca: "Pending canonical Business 5 assignment",
      na: "Accept canonical B05 assignment and complete static-demo review",
      kl: "Issue #99 (canonical assignment) remains OPEN; BUSINESS_REGISTRY.md still shows reserved-05",
      src: "Issue #99; Draft PR #109; reference/business-05-neighbor-market-v2/",
      lv: "2026-07-24", p: 95
    }),

    // ═══════════════════════════════════════════════════════════
    // 6: NUMBER-RECONCILIATION-REQUIRED — conflicting sources
    //    Registry says reserved, candidate backlog says proposed-number
    // ═══════════════════════════════════════════════════════════
    rec({
      n: 6, s: "world-feed", t: "World Feed", k: "월드 피드",
      a: NUMBER_AUTHORITY.RECONCILIATION, l: "research", st: "planning",
      ui: UI_STATUS.IN_PROGRESS, ux: UX_STATUS.BLOCKED_BY_UI, be: BACKEND_STATUS.FROZEN,
      pdi: 98, ci: 98, pr: null,
      w: "apps/world-feed/",
      sty: "Research workspace",
      su: null,
      d: "Not assigned as canonical Business 6",
      rs: "not_released",
      gl: "Issue #98",
      gu: "https://github.com/skerishKang/ai-revenue-lab/issues/98",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/98",
      ca: "Resolve numbering conflict",
      na: "Approve, reject, or revise proposed B06 mapping",
      kl: "BUSINESS_REGISTRY.md reserves 06; candidate backlog proposes world-feed as B06; Issue #98 open",
      src: "BUSINESS_REGISTRY.md (reserved-06); BUSINESS_CANDIDATE_BACKLOG.md (proposed); Issue #98",
      lv: "2026-07-24", p: 88
    }),

    // ═══════════════════════════════════════════════════════════
    // 7–12: PROPOSED-NUMBER — PR #185 merged as canonical but
    //       BUSINESS_REGISTRY.md still shows reserved
    //       Conservative: proposed-number until registry doc is updated
    // ═══════════════════════════════════════════════════════════
    rec({
      n: 7, s: "personal-meaning-map", t: "Personal Meaning Map", k: "개인 의미 지도",
      a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", st: "review",
      ui: UI_STATUS.IN_PROGRESS, ux: UX_STATUS.BLOCKED_BY_UI, be: BACKEND_STATUS.FROZEN,
      pdi: 166, ci: 166, pr: 174,
      w: "reference/business-07-personal-meaning-map-v1/",
      sty: "Visual reference in Draft PR",
      su: null, d: "Not deployed", rs: "not_released",
      gl: "Draft PR #174",
      gu: "https://github.com/skerishKang/ai-revenue-lab/pull/174",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/166",
      ca: "Complete Phase 1 UI review",
      na: "Obtain exact-head CTO approval",
      kl: "PR #185 merged 7–12 as canonical, but BUSINESS_REGISTRY.md remains reserved; conservative classification",
      src: "PR #185; Issues #166, #168, #170, #171, #172, #173; Draft PRs #174, #176, #175, #177, #179, #178",
      lv: "2026-07-26", p: 65
    }),
    rec({
      n: 8, s: "family-newspaper", t: "Family Newspaper", k: "우리 가족 신문",
      a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", st: "review",
      ui: UI_STATUS.IN_PROGRESS, ux: UX_STATUS.BLOCKED_BY_UI, be: BACKEND_STATUS.FROZEN,
      pdi: 168, ci: 168, pr: 176,
      w: "reference/business-08-family-newspaper-v1/",
      sty: "Visual reference in Draft PR",
      su: null, d: "Not deployed", rs: "not_released",
      gl: "Draft PR #176",
      gu: "https://github.com/skerishKang/ai-revenue-lab/pull/176",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/168",
      ca: "Complete Phase 1 UI review",
      na: "Obtain exact-head CTO approval",
      kl: "PR #185 merged as canonical; registry doc conflict",
      src: "PR #185; Issue #168; Draft PR #176",
      lv: "2026-07-26", p: 60
    }),
    rec({
      n: 9, s: "personalized-childrens-story", t: "Personalized Children\u2019s Story", k: "우리 아이 이야기",
      a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", st: "review",
      ui: UI_STATUS.APPROVED, ux: UX_STATUS.NOT_STARTED, be: BACKEND_STATUS.FROZEN,
      pdi: 170, ci: 170, pr: 175,
      w: "reference/business-09-personalized-childrens-story-v1/",
      sty: "Approved visual reference in Draft PR",
      su: null, d: "Not deployed", rs: "not_released",
      gl: "UI_APPROVED \u00b7 Draft PR #175",
      gu: "https://github.com/skerishKang/ai-revenue-lab/pull/175",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/170",
      ca: "Keep PR #175 Draft pending separate Ready/merge authorization",
      na: "Open Phase 2 UX only through a separately authorized issue",
      kl: "Phase 2 UX requires a separately authorized issue; UI_APPROVED does not imply merge or UX approval",
      src: "PR #185; Issue #170; Draft PR #175 (UI_APPROVED)",
      lv: "2026-07-26", p: 58
    }),
    rec({
      n: 10, s: "fan-magazine", t: "Fan Magazine", k: "나만의 팬 매거진",
      a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", st: "review",
      ui: UI_STATUS.IN_PROGRESS, ux: UX_STATUS.BLOCKED_BY_UI, be: BACKEND_STATUS.FROZEN,
      pdi: 171, ci: 171, pr: 177,
      w: "reference/business-10-fan-magazine-v1/",
      sty: "Visual reference in Draft PR",
      su: null, d: "Not deployed", rs: "not_released",
      gl: "Draft PR #177",
      gu: "https://github.com/skerishKang/ai-revenue-lab/pull/177",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/171",
      ca: "Complete Phase 1 UI review",
      na: "Obtain exact-head CTO approval",
      kl: "PR #185 merged as canonical; registry doc conflict",
      src: "PR #185; Issue #171; Draft PR #177",
      lv: "2026-07-26", p: 56
    }),
    rec({
      n: 11, s: "language-learning-magazine", t: "Language Learning Magazine", k: "나의 언어학습 매거진",
      a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", st: "review",
      ui: UI_STATUS.IN_PROGRESS, ux: UX_STATUS.BLOCKED_BY_UI, be: BACKEND_STATUS.FROZEN,
      pdi: 172, ci: 172, pr: 179,
      w: "reference/business-11-language-learning-magazine-v1/",
      sty: "Visual reference in Draft PR",
      su: null, d: "Not deployed", rs: "not_released",
      gl: "Draft PR #179",
      gu: "https://github.com/skerishKang/ai-revenue-lab/pull/179",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/172",
      ca: "Complete Phase 1 UI review",
      na: "Obtain exact-head CTO approval",
      kl: "PR #185 merged as canonical; registry doc conflict",
      src: "PR #185; Issue #172; Draft PR #179",
      lv: "2026-07-26", p: 54
    }),
    rec({
      n: 12, s: "creator-mini-media", t: "Creator Mini-Media", k: "크리에이터 미니미디어",
      a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", st: "review",
      ui: UI_STATUS.IN_PROGRESS, ux: UX_STATUS.BLOCKED_BY_UI, be: BACKEND_STATUS.FROZEN,
      pdi: 173, ci: 173, pr: 178,
      w: "reference/business-12-creator-mini-media-v1/",
      sty: "Visual reference in Draft PR",
      su: null, d: "Not deployed", rs: "not_released",
      gl: "Draft PR #178",
      gu: "https://github.com/skerishKang/ai-revenue-lab/pull/178",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/173",
      ca: "Complete Phase 1 UI review",
      na: "Obtain exact-head CTO approval",
      kl: "PR #185 merged as canonical; registry doc conflict",
      src: "PR #185; Issue #173; Draft PR #178",
      lv: "2026-07-26", p: 52
    }),

    // ═══════════════════════════════════════════════════════════
    // 13–14: CANONICAL — verified in BUSINESS_REGISTRY.md
    // ═══════════════════════════════════════════════════════════
    rec({
      n: 13, s: "personal-video-archive", t: "Personal Video Archive", k: "나의 영상 아카이브",
      a: NUMBER_AUTHORITY.CANONICAL, l: "private_preview", st: "review",
      ui: UI_STATUS.APPROVED, ux: UX_STATUS.NOT_STARTED, be: BACKEND_STATUS.DECISION_PENDING,
      pdi: 76, ci: 76, pr: 78,
      w: "apps/personal-video-archive/",
      sty: "Cloudflare Pages branch preview",
      su: "https://feat-personal-video-archive.ai-revenue-personal-video-archive.pages.dev",
      d: "Merged product preview",
      rs: "preview_draft",
      gl: "Merged PR #78",
      gu: "https://github.com/skerishKang/ai-revenue-lab/pull/78",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/76",
      ca: "Verify merged preview",
      na: "Decide next production-infrastructure scope",
      kl: "Branch preview only; no fixed Production URL",
      src: "BUSINESS_REGISTRY.md; Issues #60, #62, #72, #76; PR #78",
      lv: "2026-07-24", p: 42
    }),
    rec({
      n: 14, s: "korean-ai-platform", t: "Korean AI Platform", k: "한국형 AI 실행 플랫폼",
      a: NUMBER_AUTHORITY.CANONICAL, l: "private_preview", st: "running",
      ui: UI_STATUS.APPROVED, ux: UX_STATUS.NOT_STARTED, be: BACKEND_STATUS.IN_PROGRESS,
      pdi: 80, ci: 138, pr: 142,
      w: "apps/korean-ai-platform/",
      sty: "Cloudflare Worker",
      su: "https://ai-revenue-korean-ai-platform.charliekant.workers.dev/workspace",
      d: "PR #142 merged — dedicated Worker deployed",
      rs: "staging",
      gl: "PR #142 merged",
      gu: "https://github.com/skerishKang/ai-revenue-lab/pull/142",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/138",
      ca: "Configure Provider registry",
      na: "Activate real BYOK chat",
      kl: "Provider registry not yet configured; real chat not yet active",
      src: "BUSINESS_REGISTRY.md; Issue #80, #138; PR #79, #142",
      lv: "2026-07-25", p: 92
    }),

    // ═══════════════════════════════════════════════════════════
    // 15: RESERVED — Business 15 not yet assigned
    //     Candidate backlog suggests "Global AI Newsroom" but no product-decision issue exists
    //     Conservative: keep reserved
    // ═══════════════════════════════════════════════════════════
    rec({
      n: 15, s: "unassigned-15", t: "Unassigned", k: "미배정",
      a: NUMBER_AUTHORITY.RESERVED, l: "reserved", st: "reserved",
      ui: UI_STATUS.NOT_APPLICABLE, ux: UX_STATUS.NOT_APPLICABLE, be: BACKEND_STATUS.NOT_APPLICABLE,
      w: null, sty: null, su: null,
      d: "Open slot", rs: "not_released",
      gl: null, gu: null, iu: null,
      ca: "Define Business 15 only when a product decision is documented",
      na: "Product decision required before assignment",
      kl: "Candidate backlog suggests Global AI Newsroom but no product-decision Issue exists",
      src: "BUSINESS_REGISTRY.md (implicitly reserved); BUSINESS_CANDIDATE_BACKLOG.md (candidate: Global AI Newsroom)",
      lv: "2026-07-24", p: 0
    }),

    // ═══════════════════════════════════════════════════════════
    // 16–22: CANDIDATE — from candidate backlog
    //        No product-decision Issues, no UI/UX/backend work authorized
    // ═══════════════════════════════════════════════════════════
    rec({ n: 16, s: "personal-sports", t: "Personal Sports", k: "나의 스포츠 채널", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 17, s: "local-shop-magazine", t: "Local Shop Magazine", k: "우리 가게 매거진", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 18, s: "personal-audio-channel", t: "Personal Audio Channel", k: "나의 오디오 채널", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 19, s: "personal-memory-book", t: "Personal Memory Book", k: "나의 기억책", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 20, s: "personal-memory-novel", t: "Personal Memory Novel", k: "나의 기억소설", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 21, s: "founder-strategy-letter", t: "Founder Strategy Letter", k: "대표 전략 편지", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 22, s: "personal-media-studio", t: "Personal Media Studio", k: "개인 미디어 스튜디오", a: NUMBER_AUTHORITY.CANDIDATE }),

    // ═══════════════════════════════════════════════════════════
    // 23–25: EXISTING-PROJECT — separate repos exist, no canonical number
    // ═══════════════════════════════════════════════════════════
    rec({
      n: 23, s: "lovebud", t: "LoveBud", k: "러브버드",
      a: NUMBER_AUTHORITY.EXISTING_PROJECT, l: "active", st: "running",
      ui: UI_STATUS.APPROVED, ux: UX_STATUS.IN_PROGRESS, be: BACKEND_STATUS.IMPLEMENTED,
      ci: 3425, pr: 3531,
      w: "skerishKang/LoveBud",
      sty: "Cloudflare Pages",
      su: "https://lovebud.pages.dev/",
      d: "Live Cloudflare Pages deployment",
      rs: "live",
      gl: "Separate repository · LoveBud",
      gu: "https://github.com/skerishKang/LoveBud",
      iu: "https://github.com/skerishKang/LoveBud/issues/3425",
      ca: "Architecture audit (#3425)",
      na: "Migration ledger and provenance gate (#3458)",
      kl: "Not assigned a canonical Business number; separate repository",
      src: "BUSINESS_CANDIDATE_BACKLOG.md; skerishKang/LoveBud repository",
      lv: "2026-07-26", p: 45
    }),
    rec({
      n: 24, s: "lovetree-3", t: "LoveTree 3.0", k: "러브트리 3.0",
      a: NUMBER_AUTHORITY.EXISTING_PROJECT, l: "active", st: "running",
      ui: UI_STATUS.APPROVED, ux: UX_STATUS.NOT_STARTED, be: BACKEND_STATUS.IMPLEMENTED,
      w: "skerishKang/lovetree3.0",
      sty: "Cloudflare Pages",
      su: "https://lovetree3.pages.dev/",
      d: "Live Cloudflare Pages deployment",
      rs: "live",
      gl: "Separate repository · lovetree3.0",
      gu: "https://github.com/skerishKang/lovetree3.0",
      ca: "Current work not defined (no verified milestone)",
      na: "Define feature expansion plan",
      kl: "Not assigned a canonical Business number; separate repository",
      src: "BUSINESS_CANDIDATE_BACKLOG.md; skerishKang/lovetree3.0 repository",
      lv: "2026-07-26", p: 25
    }),
    rec({
      n: 25, s: "love-matchmaking", t: "Love Matchmaking", k: "러브 매치메이킹",
      a: NUMBER_AUTHORITY.EXISTING_PROJECT, l: "concept", st: "planning",
      ui: UI_STATUS.NOT_STARTED, ux: UX_STATUS.BLOCKED_BY_UI, be: BACKEND_STATUS.FROZEN,
      w: "skerishKang/401-love-match-making",
      sty: null, su: null,
      d: "Repository exists; no implementation or deployment evidence",
      rs: "not_released",
      gl: "Separate repository · 401-love-match-making",
      gu: "https://github.com/skerishKang/401-love-match-making",
      ca: "No current work",
      na: "Define implementation scope",
      kl: "Not assigned a canonical Business number; separate repository; no deployed UI",
      src: "BUSINESS_CANDIDATE_BACKLOG.md; skerishKang/401-love-match-making",
      lv: "2026-07-26", p: 15
    }),

    // ═══════════════════════════════════════════════════════════
    // 26–35: CANDIDATE (including spin-outs mapped to candidate)
    // ═══════════════════════════════════════════════════════════
    rec({ n: 26, s: "company-memory", t: "Company Memory", k: "회사 기억", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 27, s: "evidence-studio", t: "Evidence Studio", k: "사건 기록실", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 28, s: "decision-archive", t: "Decision Archive", k: "회의\u00b7결정 기록실", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 29, s: "apartment-governance", t: "Apartment Governance", k: "우리단지 운영실", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 30, s: "civic-ai-navigator", t: "Civic AI Navigator", k: "시민 AI 내비게이터", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 31, s: "public-procedure-experience-data", t: "Public Procedure Experience Data", k: "공공절차 경험 데이터", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 32, s: "ai-skill-studio", t: "AI Skill Studio", k: "AI 업무 실습실", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 33, s: "research-memory", t: "Research Memory", k: "연구 기억실", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 34, s: "ai-dubbing-studio", t: "AI Dubbing Studio", k: "AI 더빙 스튜디오", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 35, s: "ai-media-education-dx", t: "AI Media Education & DX", k: "AI 미디어 교육\u00b7DX", a: NUMBER_AUTHORITY.CANDIDATE }),

    // ═══════════════════════════════════════════════════════════
    // 36: PROPOSED-NUMBER — Issue #266 (product decision), Draft PR #279 (Phase 1 UI)
    // ═══════════════════════════════════════════════════════════
    rec({
      n: 36, s: "ai-women-safety", t: "AI Women Safety", k: "AI 여성안전 서비스",
      a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", st: "review",
      ui: UI_STATUS.IN_PROGRESS, ux: UX_STATUS.BLOCKED_BY_UI, be: BACKEND_STATUS.FROZEN,
      pdi: 266, ci: 268, pr: 279,
      w: "reference/business-36-ai-women-safety-v1/",
      sty: "Phase 1 UI visual reference in Draft PR",
      su: null, d: "Not deployed", rs: "not_released",
      gl: "Draft PR #279",
      gu: "https://github.com/skerishKang/ai-revenue-lab/pull/279",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/268",
      ca: "Phase 1 UI review pending",
      na: "Obtain exact-head CTO approval",
      kl: "Product-decision Issue #266 open; Draft PR #279 not yet UI_APPROVED",
      src: "BUSINESS_CANDIDATE_BACKLOG.md; Issues #266, #268; Draft PR #279",
      lv: "2026-07-29", p: 50
    }),

    // ═══════════════════════════════════════════════════════════
    // 37: CANDIDATE — spin-out in backlog, no product-decision issue
    // ═══════════════════════════════════════════════════════════
    rec({ n: 37, s: "ai-safe-route", t: "AI Safe Route", k: "AI 안전경로", a: NUMBER_AUTHORITY.CANDIDATE }),

    // ═══════════════════════════════════════════════════════════
    // 38: PROPOSED-NUMBER — Issues #267, #269 (product decision), Draft PR #278 (Phase 1 UI)
    // ═══════════════════════════════════════════════════════════
    rec({
      n: 38, s: "ai-exercise-coach", t: "AI Exercise Coach", k: "AI 운동 코치",
      a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", st: "review",
      ui: UI_STATUS.IN_PROGRESS, ux: UX_STATUS.BLOCKED_BY_UI, be: BACKEND_STATUS.FROZEN,
      pdi: 267, ci: 269, pr: 278,
      w: "reference/business-38-ai-exercise-coach-v1/",
      sty: "Phase 1 UI visual reference in Draft PR",
      su: null, d: "Not deployed", rs: "not_released",
      gl: "Draft PR #278",
      gu: "https://github.com/skerishKang/ai-revenue-lab/pull/278",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/269",
      ca: "Phase 1 UI review pending",
      na: "Obtain exact-head CTO approval",
      kl: "Product-decision Issues #267, #269 open; Draft PR #278 not yet UI_APPROVED",
      src: "BUSINESS_CANDIDATE_BACKLOG.md; Issues #267, #269; Draft PR #278",
      lv: "2026-07-29", p: 48
    }),

    // ═══════════════════════════════════════════════════════════
    // 39: CANDIDATE — spin-out, no product-decision issue
    // ═══════════════════════════════════════════════════════════
    rec({ n: 39, s: "112-real-time-interpretation", t: "112 Real-Time Interpretation", k: "112 실시간 AI 통역", a: NUMBER_AUTHORITY.CANDIDATE }),

    // ═══════════════════════════════════════════════════════════
    // 40: CANDIDATE — branch exists (feat/business-40-emergency-urgency-ai-ui) but no PR yet
    //     Conservative: candidate until product-decision issue confirmed
    // ═══════════════════════════════════════════════════════════
    rec({
      n: 40, s: "emergency-urgency-ai", t: "Emergency Urgency AI", k: "긴급도 판단 AI",
      a: NUMBER_AUTHORITY.CANDIDATE, l: "concept", st: "planning",
      ui: UI_STATUS.NOT_STARTED, ux: UX_STATUS.BLOCKED_BY_UI, be: BACKEND_STATUS.FROZEN,
      w: null,
      kl: "Branch feat/business-40-emergency-urgency-ai-ui exists on origin but no Issue or PR confirmed",
      src: "BUSINESS_CANDIDATE_BACKLOG.md (spin-out); origin branch only",
      lv: "2026-07-29", p: 10
    }),

    // ═══════════════════════════════════════════════════════════
    // 41: CANDIDATE — branch exists (feat/business-41-foreign-emergency-assistant-ui) but no PR yet
    //     Conservative: candidate until product-decision issue confirmed
    // ═══════════════════════════════════════════════════════════
    rec({
      n: 41, s: "foreign-emergency-assistant", t: "Foreign Emergency Assistant", k: "외국인 긴급신고 도우미",
      a: NUMBER_AUTHORITY.CANDIDATE, l: "concept", st: "planning",
      ui: UI_STATUS.NOT_STARTED, ux: UX_STATUS.BLOCKED_BY_UI, be: BACKEND_STATUS.FROZEN,
      w: null,
      kl: "Branch feat/business-41-foreign-emergency-assistant-ui exists on origin but no Issue or PR confirmed",
      src: "BUSINESS_CANDIDATE_BACKLOG.md; origin branch only",
      lv: "2026-07-29", p: 8
    }),

    // ═══════════════════════════════════════════════════════════
    // 42–43: CANDIDATE — spin-out in backlog
    // ═══════════════════════════════════════════════════════════
    rec({ n: 42, s: "ai-development-control-tower", t: "AI Development Control Tower", k: "AI 개발 관제실", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 43, s: "ai-software-factory", t: "AI Software Factory", k: "AI 소프트웨어 공장", a: NUMBER_AUTHORITY.CANDIDATE }),

    // ═══════════════════════════════════════════════════════════
    // 44: EXISTING-PROJECT — this IS the Portfolio Console itself
    // ═══════════════════════════════════════════════════════════
    rec({
      n: 44, s: "portfolio-operations-console", t: "Portfolio Operations Console", k: "포트폴리오 운영 콘솔",
      a: NUMBER_AUTHORITY.EXISTING_PROJECT, l: "active", st: "running",
      ui: UI_STATUS.APPROVED, ux: UX_STATUS.NOT_STARTED, be: BACKEND_STATUS.NOT_APPLICABLE,
      w: "apps/portfolio-console/",
      sty: "Cloudflare Pages",
      su: "https://ai-revenue-portfolio-console.pages.dev",
      d: "Cloudflare Pages deployment (Access-protected)",
      rs: "live",
      gl: "This console",
      gu: "https://github.com/skerishKang/ai-revenue-lab",
      iu: "https://github.com/skerishKang/ai-revenue-lab/issues/117",
      ca: "This Business IS the Portfolio Console running now",
      na: "GitHub live-sync activation (#163); ongoing improvements",
      kl: "Not a canonical numbered Business; this is the console itself",
      src: "BUSINESS_CANDIDATE_BACKLOG.md (existing-project); Portfolio Console application",
      lv: "2026-07-29", p: 5
    }),

    // ═══════════════════════════════════════════════════════════
    // 45–55: CANDIDATE — spin-outs and candidates from backlog
    // ═══════════════════════════════════════════════════════════
    rec({ n: 45, s: "ai-content-engine", t: "AI Content Engine", k: "AI 콘텐츠 엔진", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 46, s: "ai-personalization-engine", t: "AI Personalization Engine", k: "AI 개인화 엔진", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 47, s: "real-time-feedback-engine", t: "Real-Time Feedback Engine", k: "실시간 반응 엔진", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 48, s: "ai-verification-engine", t: "AI Verification Engine", k: "AI 검증\u00b7승인 엔진", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 49, s: "public-data-connector-hub", t: "Public Data Connector Hub", k: "공공데이터 커넥터 허브", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 50, s: "private-data-connector-hub", t: "Private Data Connector Hub", k: "사내자료 커넥터 허브", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 51, s: "ai-workflow-marketplace", t: "AI Workflow Marketplace", k: "AI 워크플로우 마켓", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 52, s: "scheduled-agent-operations", t: "Scheduled Agent Operations", k: "예약형 AI 운영", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 53, s: "embedded-ai-sdk", t: "Embedded AI SDK", k: "임베드 AI SDK", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 54, s: "ai-model-router", t: "AI Model Router", k: "AI 모델 라우터", a: NUMBER_AUTHORITY.CANDIDATE }),
    rec({ n: 55, s: "local-ai-fleet", t: "Local AI Fleet", k: "로컬 AI 플릿", a: NUMBER_AUTHORITY.CANDIDATE })
  ];
})();
