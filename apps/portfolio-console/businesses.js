/*  businesses.js  —  B1–55 Business authority registry (Phase 2A)
 *
 *  Contains static identity, phase status, and authority data.
 *  Contains NO volatile GitHub state (no Issue state, PR state, CI, SHA, updated-at).
 *  Volatile facts come from /api/github-status (Phase 2A) via github-live-status.js.
 *
 *  Fields:
 *    number          - Business number (1-55)
 *    slug            - URL-safe identifier
 *    title           - English title
 *    koreanTitle     - Korean title
 *    numberAuthority - "canonical" | "proposed-number" | "candidate" | "existing-project" | "reserved" | "number-reconciliation-required"
 *    lifecycle       - lifecycle stage
 *    uiStatus        - UI phase state
 *    uxStatus        - UX phase state
 *    backendStatus   - Backend phase state
 *    workspace       - workspace path
 *    surfaceUrl      - verified surface URL or null
 *    releaseState    - release state
 *    priority        - portfolio priority (0-100)
 *    state           - display state (for backward compatibility)
 *    progress        - removed (arbitrary percentage no longer used; use phase states)
 */

window.ARL_BUSINESSES = (function () {
  "use strict";

  var NA = {
    canonical: "canonical",
    proposed: "proposed-number",
    candidate: "candidate",
    existing: "existing-project",
    reserved: "reserved",
    reconciliation: "number-reconciliation-required",
  };

  var UI = {
    ns: "NOT_STARTED",
    ip: "IN_PROGRESS",
    nr: "UI_NOT_READY",
    cr: "UI_CONDITIONALLY_READY",
    ap: "UI_APPROVED",
    na: "NOT_APPLICABLE",
  };

  var UX = {
    bu: "BLOCKED_BY_UI",
    ns: "NOT_STARTED",
    ip: "IN_PROGRESS",
    nr: "UX_NOT_READY",
    cr: "UX_CONDITIONALLY_READY",
    ap: "UX_APPROVED",
    na: "NOT_APPLICABLE",
  };

  var BE = {
    fr: "FROZEN",
    dp: "DECISION_PENDING",
    df: "DEFERRED",
    au: "AUTHORIZED",
    ip: "IN_PROGRESS",
    im: "IMPLEMENTED",
    na: "NOT_APPLICABLE",
  };

  function biz(n, s, t, k, a, l, ui, ux, be, opts) {
    opts = opts || {};
    return {
      number: n, slug: s, title: t, koreanTitle: k,
      numberAuthority: a, lifecycle: l || "concept",
      state: opts.state || "planned",
      uiStatus: ui || UI.ns, uxStatus: ux || UX.bu, backendStatus: be || BE.fr,
      workspace: opts.w || null,
      surfaceUrl: opts.su || null,
      releaseState: opts.rs || "not_released",
      priority: opts.p || 0,
    };
  }

  return [
    // ═══ 1–4: CANONICAL ═══
    biz(1, "personal-edition", "Personal Edition", "퍼스널 에디션", NA.canonical, "private_preview", UI.ip, UX.bu, BE.fr, { state: "review", su: "https://feat-personal-edition-final.ai-revenue-personal-edition.pages.dev", p: 100, w: "apps/personal-edition/" }),
    biz(2, "living-travel", "Living Travel", "리빙 트래블", NA.canonical, "private_preview", UI.ap, UX.ns, BE.im, { state: "running", su: "https://ops-living-travel-external-s.ai-revenue-living-travel.pages.dev", p: 35, w: "apps/living-travel/" }),
    biz(3, "living-fiction", "Living Fiction", "리빙 픽션", NA.canonical, "private_preview", UI.ap, UX.ns, BE.im, { state: "review", p: 32, w: "apps/living-fiction/" }),
    biz(4, "living-learning", "Living Learning", "리빙 러닝", NA.canonical, "private_preview", UI.ap, UX.ns, BE.na, { state: "running", su: "https://ai-revenue-living-learning.pages.dev/", p: 30, w: "apps/living-learning/" }),
    // ═══ 5–6: PROPOSED / RECONCILIATION ═══
    biz(5, "neighbor-market", "Neighbor Market", "우리단지 이웃가게", NA.proposed, "concept", UI.ip, UX.bu, BE.fr, { state: "review", p: 95, w: "reference/business-05-neighbor-market-v2/" }),
    biz(6, "world-feed", "World Feed", "월드 피드", NA.reconciliation, "research", UI.ip, UX.bu, BE.fr, { state: "planning", p: 88, w: "apps/world-feed/" }),
    // ═══ 7–12: PROPOSED ═══
    biz(7, "personal-meaning-map", "Personal Meaning Map", "개인 의미 지도", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 65, w: "reference/business-07-personal-meaning-map-v1/" }),
    biz(8, "family-newspaper", "Family Newspaper", "우리 가족 신문", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 60, w: "reference/business-08-family-newspaper-v1/" }),
    biz(9, "personalized-childrens-story", "Personalized Children\u2019s Story", "우리 아이 이야기", NA.proposed, "visual_reference", UI.ap, UX.ns, BE.fr, { state: "review", p: 58, w: "reference/business-09-personalized-childrens-story-v1/" }),
    biz(10, "fan-magazine", "Fan Magazine", "나만의 팬 매거진", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 56, w: "reference/business-10-fan-magazine-v1/" }),
    biz(11, "language-learning-magazine", "Language Learning Magazine", "나의 언어학습 매거진", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 54, w: "reference/business-11-language-learning-magazine-v1/" }),
    biz(12, "creator-mini-media", "Creator Mini-Media", "크리에이터 미니미디어", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 52, w: "reference/business-12-creator-mini-media-v1/" }),
    // ═══ 13–14: CANONICAL ═══
    biz(13, "personal-video-archive", "Personal Video Archive", "나의 영상 아카이브", NA.canonical, "private_preview", UI.ap, UX.ns, BE.dp, { state: "review", su: "https://feat-personal-video-archive.ai-revenue-personal-video-archive.pages.dev", p: 42, w: "apps/personal-video-archive/" }),
    biz(14, "korean-ai-platform", "Korean AI Platform", "한국형 AI 실행 플랫폼", NA.canonical, "private_preview", UI.ap, UX.ns, BE.ip, { state: "running", su: "https://ai-revenue-korean-ai-platform.charliekant.workers.dev/workspace", p: 92, w: "apps/korean-ai-platform/" }),
    // ═══ 15–22: PROPOSED ═══
    biz(15, "global-ai-newsroom", "Global AI Newsroom", "글로벌 AI 뉴스룸", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 40, w: "reference/business-15-global-ai-newsroom-v1/" }),
    biz(16, "personal-sports", "Personal Sports", "나의 스포츠 채널", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 38, w: "reference/business-16-personal-sports-v1/" }),
    biz(17, "local-shop-magazine", "Local Shop Magazine", "우리 가게 매거진", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 36, w: "reference/business-17-local-shop-magazine-v1/" }),
    biz(18, "personal-audio-channel", "Personal Audio Channel", "나의 오디오 채널", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 34, w: "reference/business-18-personal-audio-channel-v1/" }),
    biz(19, "personal-memory-book", "Personal Memory Book", "나의 기억책", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 33, w: "reference/business-19-personal-memory-book-v1/" }),
    biz(20, "personal-memory-novel", "Personal Memory Novel", "나의 기억소설", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 31, w: "reference/business-20-personal-memory-novel-v1/" }),
    biz(21, "founder-strategy-letter", "Founder Strategy Letter", "대표 전략 편지", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 29, w: "reference/business-21-founder-strategy-letter-v1/" }),
    biz(22, "personal-media-studio", "Personal Media Studio", "개인 미디어 스튜디오", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 28, w: "reference/business-22-personal-media-studio-v1/" }),
    // ═══ 23–25: EXISTING PROJECT ═══
    biz(23, "lovebud", "LoveBud", "러브버드", NA.existing, "active", UI.ap, UX.ip, BE.im, { state: "running", su: "https://lovebud.pages.dev/", p: 45, w: "skerishKang/LoveBud" }),
    biz(24, "lovetree-3", "LoveTree 3.0", "러브트리 3.0", NA.existing, "active", UI.ap, UX.ns, BE.im, { state: "running", su: "https://lovetree3.pages.dev/", p: 25, w: "skerishKang/lovetree3.0" }),
    biz(25, "love-matchmaking", "Love Matchmaking", "러브 매치메이킹", NA.existing, "concept", UI.ns, UX.bu, BE.fr, { state: "planning", p: 15, w: "skerishKang/401-love-match-making" }),
    // ═══ 26–35: PROPOSED ═══
    biz(26, "company-memory", "Company Memory", "회사 기억", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 27, w: "reference/business-26-company-memory-v1/" }),
    biz(27, "evidence-studio", "Evidence Studio", "사건 기록실", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 26, w: "reference/business-27-evidence-studio-v1/" }),
    biz(28, "decision-archive", "Decision Archive", "회의\u00b7결정 기록실", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 24, w: "reference/business-28-decision-archive-v1/" }),
    biz(29, "apartment-governance", "Apartment Governance", "우리단지 운영실", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 22, w: "reference/business-29-apartment-governance-v1/" }),
    biz(30, "civic-ai-navigator", "Civic AI Navigator", "시민 AI 내비게이터", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 20, w: "reference/business-30-civic-ai-navigator-v1/" }),
    biz(31, "public-procedure-experience-data", "Public Procedure Experience Data", "공공절차 경험 데이터", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 18, w: "reference/business-31-public-procedure-data-v1/" }),
    biz(32, "ai-skill-studio", "AI Skill Studio", "AI 업무 실습실", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 16, w: "reference/business-32-ai-skill-studio-v1/" }),
    biz(33, "research-memory", "Research Memory", "연구 기억실", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 14, w: "reference/business-33-research-memory-v1/" }),
    biz(34, "ai-dubbing-studio", "AI Dubbing Studio", "AI 더빙 스튜디오", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 12, w: "reference/business-34-ai-dubbing-studio-v1/" }),
    biz(35, "ai-media-education-dx", "AI Media Education & DX", "AI 미디어 교육\u00b7DX", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 11, w: "reference/business-35-ai-media-education-dx-v1/" }),
    // ═══ 36–43: PROPOSED ═══
    biz(36, "ai-women-safety", "AI Women Safety", "AI 여성안전 서비스", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 50, w: "reference/business-36-ai-women-safety-v1/" }),
    biz(37, "ai-safe-route", "AI Safe Route", "AI 안전경로", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 48, w: "reference/business-37-ai-safe-route-v1/" }),
    biz(38, "ai-learning-tutor", "AI Learning Tutor", "AI 학습 튜터", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 46, w: "reference/business-38-ai-learning-tutor-v1/" }),
    biz(39, "ai-fact-check-dashboard", "AI Fact Check Dashboard", "AI 팩트체크 대시보드", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 44, w: "reference/business-39-ai-fact-check-dashboard-v1/" }),
    biz(40, "ai-automated-classification", "AI Automated Classification", "AI 자동 분류 서비스", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 24, w: "reference/business-40-ai-automated-classification-v1/" }),
    biz(41, "ai-customer-consultation", "AI Customer Consultation", "AI 고객 상담 서비스", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 22, w: "reference/business-41-ai-customer-consultation-v1/" }),
    biz(42, "ai-development-control-tower", "AI Development Control Tower", "AI 개발 관제탑", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 20, w: "reference/business-42-ai-development-control-tower-v1/" }),
    biz(43, "ai-neural-commerce", "AI Neural Commerce", "AI 신경망 커머스", NA.proposed, "visual_reference", UI.ip, UX.bu, BE.fr, { state: "review", p: 18, w: "reference/business-43-ai-neural-commerce-v1/" }),
    // ═══ 44: EXISTING PROJECT ═══
    biz(44, "portfolio-console", "Portfolio Console", "포트폴리오 콘솔", NA.existing, "active", UI.ap, UX.ns, BE.im, { state: "running", p: 10, w: "apps/portfolio-console/" }),
    // ═══ 45–55: CANDIDATE ═══
    biz(45, "ai-content-engine", "AI Content Engine", "AI 콘텐츠 엔진", NA.candidate, "concept", UI.ns, UX.bu, BE.fr, { state: "planning", p: 5 }),
    biz(46, "ai-personalization-engine", "AI Personalization Engine", "AI 개인화 엔진", NA.candidate, "concept", UI.ns, UX.bu, BE.fr, { state: "planning", p: 5 }),
    biz(47, "real-time-feedback-engine", "Real-Time Feedback Engine", "실시간 반응 엔진", NA.candidate, "concept", UI.ns, UX.bu, BE.fr, { state: "planning", p: 5 }),
    biz(48, "ai-verification-engine", "AI Verification Engine", "AI 검증\u00b7승인 엔진", NA.candidate, "concept", UI.ns, UX.bu, BE.fr, { state: "planning", p: 5 }),
    biz(49, "public-data-connector-hub", "Public Data Connector Hub", "공공데이터 커넥터 허브", NA.candidate, "concept", UI.ns, UX.bu, BE.fr, { state: "planning", p: 5 }),
    biz(50, "private-data-connector-hub", "Private Data Connector Hub", "사내자료 커넥터 허브", NA.candidate, "concept", UI.ns, UX.bu, BE.fr, { state: "planning", p: 5 }),
    biz(51, "ai-workflow-marketplace", "AI Workflow Marketplace", "AI 워크플로우 마켓", NA.candidate, "concept", UI.ns, UX.bu, BE.fr, { state: "planning", p: 5 }),
    biz(52, "scheduled-agent-operations", "Scheduled Agent Operations", "예약형 AI 운영", NA.candidate, "concept", UI.ns, UX.bu, BE.fr, { state: "planning", p: 5 }),
    biz(53, "embedded-ai-sdk", "Embedded AI SDK", "임베드 AI SDK", NA.candidate, "concept", UI.ns, UX.bu, BE.fr, { state: "planning", p: 5 }),
    biz(54, "ai-model-router", "AI Model Router", "AI 모델 라우터", NA.candidate, "concept", UI.ns, UX.bu, BE.fr, { state: "planning", p: 5 }),
    biz(55, "local-ai-fleet", "Local AI Fleet", "로컬 AI 플릿", NA.candidate, "concept", UI.ns, UX.bu, BE.fr, { state: "planning", p: 5 }),
  ];
})();
