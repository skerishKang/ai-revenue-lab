/*  business-manifest.js  —  B1–55 static identity manifest (Phase 2A)
 *
 *  Contains only slow-changing data:
 *    - Business number, slug, Korean/English title
 *    - Number-authority classification
 *    - Product boundary / lifecycle
 *    - Workspace / reference workspace
 *    - Portfolio priority where explicitly authorized
 *    - Static fallback phase verdict where necessary
 *
 *  Contains NO volatile state:
 *    - No Issue state, PR state, CI result, SHA, updated-at
 *    - No currentPr, currentAction, nextAction
 *    - No deployment currentness
 *    - No lastVerified timestamp from manual audit
 *
 *  This is the sole client-side source of truth for identity/authority.
 *  All volatile GitHub facts come from /api/github-status (Phase 2A).
 */

(function () {
  "use strict";

  /* ── Number-authority vocabulary ── */
  var NUMBER_AUTHORITY = {
    CANONICAL: "canonical",
    PROPOSED: "proposed-number",
    CANDIDATE: "candidate",
    EXISTING_PROJECT: "existing-project",
    RESERVED: "reserved",
    RECONCILIATION: "number-reconciliation-required",
  };

  /* ── Helpers ── */
  function identity(data) {
    return {
      number: data.n,
      slug: data.s,
      title: data.t,
      koreanTitle: data.k,
      numberAuthority: data.a,
      lifecycle: data.l || "concept",
      priority: data.p || 0,
      workspace: data.w || null,
    };
  }

  /* ── Static identity records (B1–55) ── */
  window.ARL_MANIFEST = [
    // ═══ 1–4: CANONICAL ═══
    identity({ n: 1,  s: "personal-edition", t: "Personal Edition", k: "퍼스널 에디션",           a: NUMBER_AUTHORITY.CANONICAL, l: "private_preview", p: 100, w: "apps/personal-edition/" }),
    identity({ n: 2,  s: "living-travel",     t: "Living Travel",     k: "리빙 트래블",            a: NUMBER_AUTHORITY.CANONICAL, l: "private_preview", p: 35,  w: "apps/living-travel/" }),
    identity({ n: 3,  s: "living-fiction",     t: "Living Fiction",    k: "리빙 픽션",              a: NUMBER_AUTHORITY.CANONICAL, l: "private_preview", p: 32,  w: "apps/living-fiction/" }),
    identity({ n: 4,  s: "living-learning",    t: "Living Learning",   k: "리빙 러닝",              a: NUMBER_AUTHORITY.CANONICAL, l: "private_preview", p: 30,  w: "apps/living-learning/" }),
    // ═══ 5–6: PROPOSED / RECONCILIATION ═══
    identity({ n: 5,  s: "neighbor-market",          t: "Neighbor Market",         k: "우리단지 이웃가게",    a: NUMBER_AUTHORITY.PROPOSED,       l: "concept",    p: 95, w: "reference/business-05-neighbor-market-v2/" }),
    identity({ n: 6,  s: "world-feed",               t: "World Feed",              k: "월드 피드",           a: NUMBER_AUTHORITY.RECONCILIATION, l: "research",   p: 88, w: "apps/world-feed/" }),
    // ═══ 7–12: PROPOSED ═══
    identity({ n: 7,  s: "personal-meaning-map",         t: "Personal Meaning Map",         k: "개인 의미 지도",        a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 65, w: "reference/business-07-personal-meaning-map-v1/" }),
    identity({ n: 8,  s: "family-newspaper",              t: "Family Newspaper",             k: "우리 가족 신문",         a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 60, w: "reference/business-08-family-newspaper-v1/" }),
    identity({ n: 9,  s: "personalized-childrens-story",  t: "Personalized Children\u2019s Story", k: "우리 아이 이야기", a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 58, w: "reference/business-09-personalized-childrens-story-v1/" }),
    identity({ n: 10, s: "fan-magazine",                 t: "Fan Magazine",                k: "나만의 팬 매거진",      a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 56, w: "reference/business-10-fan-magazine-v1/" }),
    identity({ n: 11, s: "language-learning-magazine",    t: "Language Learning Magazine",   k: "나의 언어학습 매거진",  a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 54, w: "reference/business-11-language-learning-magazine-v1/" }),
    identity({ n: 12, s: "creator-mini-media",            t: "Creator Mini-Media",          k: "크리에이터 미니미디어", a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 52, w: "reference/business-12-creator-mini-media-v1/" }),
    // ═══ 13–14: CANONICAL ═══
    identity({ n: 13, s: "personal-video-archive", t: "Personal Video Archive", k: "나의 영상 아카이브",    a: NUMBER_AUTHORITY.CANONICAL, l: "private_preview", p: 42, w: "apps/personal-video-archive/" }),
    identity({ n: 14, s: "korean-ai-platform",     t: "Korean AI Platform",     k: "한국형 AI 실행 플랫폼", a: NUMBER_AUTHORITY.CANONICAL, l: "private_preview", p: 92, w: "apps/korean-ai-platform/" }),
    // ═══ 15–22: PROPOSED ═══
    identity({ n: 15, s: "global-ai-newsroom",              t: "Global AI Newsroom",              k: "글로벌 AI 뉴스룸",       a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 40, w: "reference/business-15-global-ai-newsroom-v1/" }),
    identity({ n: 16, s: "personal-sports",                 t: "Personal Sports",                 k: "나의 스포츠 채널",      a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 38, w: "reference/business-16-personal-sports-v1/" }),
    identity({ n: 17, s: "local-shop-magazine",             t: "Local Shop Magazine",             k: "우리 가게 매거진",      a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 36, w: "reference/business-17-local-shop-magazine-v1/" }),
    identity({ n: 18, s: "personal-audio-channel",          t: "Personal Audio Channel",          k: "나의 오디오 채널",      a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 34, w: "reference/business-18-personal-audio-channel-v1/" }),
    identity({ n: 19, s: "personal-memory-book",            t: "Personal Memory Book",            k: "나의 기억책",           a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 33, w: "reference/business-19-personal-memory-book-v1/" }),
    identity({ n: 20, s: "personal-memory-novel",           t: "Personal Memory Novel",           k: "나의 기억소설",         a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 31, w: "reference/business-20-personal-memory-novel-v1/" }),
    identity({ n: 21, s: "founder-strategy-letter",         t: "Founder Strategy Letter",         k: "대표 전략 편지",        a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 29, w: "reference/business-21-founder-strategy-letter-v1/" }),
    identity({ n: 22, s: "personal-media-studio",           t: "Personal Media Studio",           k: "개인 미디어 스튜디오", a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 28, w: "reference/business-22-personal-media-studio-v1/" }),
    // ═══ 23–25: EXISTING PROJECT ═══
    identity({ n: 23, s: "lovebud",              t: "LoveBud",          k: "러브버드",         a: NUMBER_AUTHORITY.EXISTING_PROJECT, l: "active", p: 45, w: "skerishKang/LoveBud" }),
    identity({ n: 24, s: "lovetree-3",           t: "LoveTree 3.0",     k: "러브트리 3.0",     a: NUMBER_AUTHORITY.EXISTING_PROJECT, l: "active", p: 25, w: "skerishKang/lovetree3.0" }),
    identity({ n: 25, s: "love-matchmaking",     t: "Love Matchmaking", k: "러브 매치메이킹",   a: NUMBER_AUTHORITY.EXISTING_PROJECT, l: "concept", p: 15, w: "skerishKang/401-love-match-making" }),
    // ═══ 26–35: PROPOSED ═══
    identity({ n: 26, s: "company-memory",              t: "Company Memory",           k: "회사 기억",            a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 27, w: "reference/business-26-company-memory-v1/" }),
    identity({ n: 27, s: "evidence-studio",             t: "Evidence Studio",          k: "사건 기록실",          a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 26, w: "reference/business-27-evidence-studio-v1/" }),
    identity({ n: 28, s: "decision-archive",            t: "Decision Archive",         k: "회의\u00b7결정 기록실", a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 24, w: "reference/business-28-decision-archive-v1/" }),
    identity({ n: 29, s: "apartment-governance",        t: "Apartment Governance",     k: "우리단지 운영실",       a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 22, w: "reference/business-29-apartment-governance-v1/" }),
    identity({ n: 30, s: "civic-ai-navigator",          t: "Civic AI Navigator",       k: "시민 AI 내비게이터",    a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 20, w: "reference/business-30-civic-ai-navigator-v1/" }),
    identity({ n: 31, s: "public-procedure-experience-data", t: "Public Procedure Experience Data", k: "공공절차 경험 데이터", a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 18, w: "reference/business-31-public-procedure-data-v1/" }),
    identity({ n: 32, s: "ai-skill-studio",            t: "AI Skill Studio",          k: "AI 업무 실습실",        a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 16, w: "reference/business-32-ai-skill-studio-v1/" }),
    identity({ n: 33, s: "research-memory",            t: "Research Memory",          k: "연구 기억실",           a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 14, w: "reference/business-33-research-memory-v1/" }),
    identity({ n: 34, s: "ai-dubbing-studio",          t: "AI Dubbing Studio",        k: "AI 더빙 스튜디오",      a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 12, w: "reference/business-34-ai-dubbing-studio-v1/" }),
    identity({ n: 35, s: "ai-media-education-dx",      t: "AI Media Education & DX",  k: "AI 미디어 교육\u00b7DX", a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 11, w: "reference/business-35-ai-media-education-dx-v1/" }),
    // ═══ 36–43: PROPOSED ═══
    identity({ n: 36, s: "ai-women-safety",              t: "AI Women Safety",             k: "AI 여성안전 서비스",  a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 50, w: "reference/business-36-ai-women-safety-v1/" }),
    identity({ n: 37, s: "ai-safe-route",                t: "AI Safe Route",               k: "AI 안전경로",         a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 48, w: "reference/business-37-ai-safe-route-v1/" }),
    identity({ n: 38, s: "ai-learning-tutor",            t: "AI Learning Tutor",           k: "AI 학습 튜터",        a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 46, w: "reference/business-38-ai-learning-tutor-v1/" }),
    identity({ n: 39, s: "ai-fact-check-dashboard",      t: "AI Fact Check Dashboard",     k: "AI 팩트체크 대시보드", a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 44, w: "reference/business-39-ai-fact-check-dashboard-v1/" }),
    identity({ n: 40, s: "ai-automated-classification",  t: "AI Automated Classification",  k: "AI 자동 분류 서비스",  a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 24, w: "reference/business-40-ai-automated-classification-v1/" }),
    identity({ n: 41, s: "ai-customer-consultation",     t: "AI Customer Consultation",    k: "AI 고객 상담 서비스",  a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 22, w: "reference/business-41-ai-customer-consultation-v1/" }),
    identity({ n: 42, s: "ai-development-control-tower", t: "AI Development Control Tower", k: "AI 개발 관제탑",       a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 20, w: "reference/business-42-ai-development-control-tower-v1/" }),
    identity({ n: 43, s: "ai-neural-commerce",           t: "AI Neural Commerce",          k: "AI 신경망 커머스",     a: NUMBER_AUTHORITY.PROPOSED, l: "visual_reference", p: 18, w: "reference/business-43-ai-neural-commerce-v1/" }),
    // ═══ 44: EXISTING PROJECT ═══
    identity({ n: 44, s: "portfolio-console", t: "Portfolio Console", k: "포트폴리오 콘솔", a: NUMBER_AUTHORITY.EXISTING_PROJECT, l: "active", p: 10, w: "apps/portfolio-console/" }),
    // ═══ 45–55: CANDIDATE ═══
    identity({ n: 45, s: "ai-content-engine",           t: "AI Content Engine",           k: "AI 콘텐츠 엔진",          a: NUMBER_AUTHORITY.CANDIDATE, l: "concept", p: 5 }),
    identity({ n: 46, s: "ai-personalization-engine",   t: "AI Personalization Engine",   k: "AI 개인화 엔진",          a: NUMBER_AUTHORITY.CANDIDATE, l: "concept", p: 5 }),
    identity({ n: 47, s: "real-time-feedback-engine",   t: "Real-Time Feedback Engine",   k: "실시간 반응 엔진",        a: NUMBER_AUTHORITY.CANDIDATE, l: "concept", p: 5 }),
    identity({ n: 48, s: "ai-verification-engine",      t: "AI Verification Engine",      k: "AI 검증\u00b7승인 엔진",   a: NUMBER_AUTHORITY.CANDIDATE, l: "concept", p: 5 }),
    identity({ n: 49, s: "public-data-connector-hub",   t: "Public Data Connector Hub",   k: "공공데이터 커넥터 허브",  a: NUMBER_AUTHORITY.CANDIDATE, l: "concept", p: 5 }),
    identity({ n: 50, s: "private-data-connector-hub",  t: "Private Data Connector Hub",  k: "사내자료 커넥터 허브",    a: NUMBER_AUTHORITY.CANDIDATE, l: "concept", p: 5 }),
    identity({ n: 51, s: "ai-workflow-marketplace",     t: "AI Workflow Marketplace",     k: "AI 워크플로우 마켓",      a: NUMBER_AUTHORITY.CANDIDATE, l: "concept", p: 5 }),
    identity({ n: 52, s: "scheduled-agent-operations",  t: "Scheduled Agent Operations",  k: "예약형 AI 운영",          a: NUMBER_AUTHORITY.CANDIDATE, l: "concept", p: 5 }),
    identity({ n: 53, s: "embedded-ai-sdk",             t: "Embedded AI SDK",             k: "임베드 AI SDK",           a: NUMBER_AUTHORITY.CANDIDATE, l: "concept", p: 5 }),
    identity({ n: 54, s: "ai-model-router",             t: "AI Model Router",             k: "AI 모델 라우터",           a: NUMBER_AUTHORITY.CANDIDATE, l: "concept", p: 5 }),
    identity({ n: 55, s: "local-ai-fleet",              t: "Local AI Fleet",              k: "로컬 AI 플릿",            a: NUMBER_AUTHORITY.CANDIDATE, l: "concept", p: 5 }),
  ].sort(function (a, b) { return a.number - b.number; });

  /* ── Generated summary counts ── */
  window.ARL_MANIFEST_SUMMARY = (function () {
    var total = window.ARL_MANIFEST.length;
    var numberAuthority = {};
    for (var i = 0; i < total; i++) {
      var key = window.ARL_MANIFEST[i].numberAuthority;
      numberAuthority[key] = (numberAuthority[key] || 0) + 1;
    }
    var sum = 0;
    for (var k in numberAuthority) sum += numberAuthority[k];
    return { total: total, sum: sum, numberAuthority: numberAuthority };
  })();
})();
