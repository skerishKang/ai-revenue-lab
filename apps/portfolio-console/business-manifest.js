/*  business-manifest.js  —  SOLE static identity source for B1-59 (Phase 2A+)
 *
 * This is the ONLY file defining Business display identity (slug, title,
 * koreanTitle, authority, lifecycle, state, workspace, surfaceUrl, priority).
 * businesses.js derives ARL_BUSINESSES from this source.
 * All volatile GitHub facts come from /api/github-status.
 *
 * Phase status values (uiStatus/uxStatus/backendStatus) are NOT defined here:
 * they are joined from the single source business-identity-core.js
 * (window.ARL_IDENTITY_CORE), which the server shares via business-identity-data.js.
 *
 * Contains NO volatile state: no Issue state, PR state, CI, SHA, updated-at.
 * B56 is an intentional numbering gap and is not represented as a Business.
 */

(function () {
  "use strict";

  var NA = {
    CANONICAL: "canonical", PROPOSED: "proposed-number", CANDIDATE: "candidate",
    EXISTING_PROJECT: "existing-project", RESERVED: "reserved", RECONCILIATION: "number-reconciliation-required",
  };

  var core = window.ARL_IDENTITY_CORE;

  function identity(data) {
    var phase = core ? core.phaseStatusFor(data.n) : { ui: "NOT_STARTED", ux: "BLOCKED_BY_UI", be: "FROZEN" };
    return {
      number: data.n, slug: data.s, title: data.t, koreanTitle: data.k,
      numberAuthority: data.a, lifecycle: data.l || "concept",
      state: data.st || "planned",
      uiStatus: phase.ui, uxStatus: phase.ux, backendStatus: phase.be,
      workspace: data.w || null, surfaceUrl: data.su || null, releaseState: data.rs || "not_released",
      portfolioClass: data.pc || "internal",
      successorTitle: data.sn || null, successorKoreanTitle: data.sk || null,
      successorRepository: data.sr || null,
      priority: data.p || 0,
    };
  }

  window.ARL_MANIFEST = [
    // ═══ 1–4: CANONICAL ═══
    identity({ n:1, s:"personal-edition", t:"Personal Edition", k:"퍼스널 에디션", a:NA.CANONICAL, l:"private_preview", st:"review", p:100, su:"https://feat-personal-edition-final.ai-revenue-personal-edition.pages.dev", w:"apps/personal-edition/" }),
    identity({ n:2, s:"living-travel", t:"Living Travel", k:"리빙 트래블", a:NA.CANONICAL, l:"private_preview", st:"running", p:35, su:"https://ops-living-travel-external-s.ai-revenue-living-travel.pages.dev", w:"apps/living-travel/" }),
    identity({ n:3, s:"living-fiction", t:"Living Fiction", k:"리빙 픽션", a:NA.CANONICAL, l:"private_preview", st:"review", p:32, w:"apps/living-fiction/" }),
    identity({ n:4, s:"living-learning", t:"Living Learning", k:"리빙 러닝", a:NA.CANONICAL, l:"private_preview", st:"running", p:30, su:"https://ai-revenue-living-learning.pages.dev/", w:"apps/living-learning/" }),
    // ═══ 5–6 ═══
    identity({ n:5, s:"neighbor-market", t:"Neighbor Market", k:"우리단지 이웃가게", a:NA.PROPOSED, l:"expanded_successor", st:"external", p:95, w:"skerishKang/02-danji-on", pc:"expanded-successor", sn:"DanjiOn", sk:"단지온", sr:"https://github.com/skerishKang/02-danji-on" }),
    identity({ n:6, s:"world-feed", t:"World Feed", k:"월드 피드", a:NA.RECONCILIATION, l:"research", st:"review", p:88, su:"https://ai-revenue-world-feed.pages.dev/", w:"apps/world-feed/" }),
    // ═══ 7–12: PROPOSED ═══
    identity({ n:7, s:"personal-meaning-map", t:"Personal Meaning Map", k:"개인 의미 지도", a:NA.PROPOSED, l:"visual_reference", st:"review", p:65, w:"reference/business-07-personal-meaning-map-v1/" }),
    identity({ n:8, s:"family-newspaper", t:"Family Newspaper", k:"우리 가족 신문", a:NA.PROPOSED, l:"visual_reference", st:"review", p:60, w:"reference/business-08-family-newspaper-v1/" }),
    identity({ n:9, s:"personalized-childrens-story", t:"Personalized Children’s Story", k:"우리 아이 이야기", a:NA.PROPOSED, l:"visual_reference", st:"review", p:58, w:"reference/business-09-personalized-childrens-story-v1/" }),
    identity({ n:10, s:"fan-magazine", t:"Fan Magazine", k:"나만의 팬 매거진", a:NA.PROPOSED, l:"visual_reference", st:"review", p:56, w:"reference/business-10-fan-magazine-v1/" }),
    identity({ n:11, s:"language-learning-magazine", t:"Language Learning Magazine", k:"나의 언어학습 매거진", a:NA.PROPOSED, l:"visual_reference", st:"review", p:54, w:"reference/business-11-language-learning-magazine-v1/" }),
    identity({ n:12, s:"creator-mini-media", t:"Creator Mini-Media", k:"크리에이터 미니미디어", a:NA.PROPOSED, l:"visual_reference", st:"review", p:52, w:"reference/business-12-creator-mini-media-v1/" }),
    // ═══ 13–14: CANONICAL ═══
    identity({ n:13, s:"personal-video-archive", t:"Personal Video Archive", k:"나의 영상 아카이브", a:NA.CANONICAL, l:"private_preview", st:"review", p:42, su:"https://ai-revenue-personal-video-archive.pages.dev/", w:"apps/personal-video-archive/" }),
    identity({ n:14, s:"korean-ai-platform", t:"Korean AI Platform", k:"한국형 AI 실행 플랫폼", a:NA.CANONICAL, l:"private_preview", st:"running", p:92, su:"https://ai-revenue-korean-ai-platform.charliekant.workers.dev/workspace", w:"apps/korean-ai-platform/" }),
    // ═══ 15–22: PROPOSED ═══
    identity({ n:15, s:"global-ai-newsroom", t:"Global AI Newsroom", k:"글로벌 AI 뉴스룸", a:NA.PROPOSED, l:"visual_reference", st:"review", p:40, w:"reference/business-15-global-ai-newsroom-v1/" }),
    identity({ n:16, s:"personal-sports", t:"Personal Sports", k:"나의 스포츠 채널", a:NA.PROPOSED, l:"visual_reference", st:"review", p:38, w:"reference/business-16-personal-sports-v1/" }),
    identity({ n:17, s:"local-shop-magazine", t:"Local Shop Magazine", k:"우리 가게 매거진", a:NA.PROPOSED, l:"visual_reference", st:"review", p:36, w:"reference/business-17-local-shop-magazine-v1/" }),
    identity({ n:18, s:"personal-audio-channel", t:"Personal Audio Channel", k:"나의 오디오 채널", a:NA.PROPOSED, l:"visual_reference", st:"review", p:34, w:"reference/business-18-personal-audio-channel-v1/" }),
    identity({ n:19, s:"personal-memory-book", t:"Personal Memory Book", k:"나의 기억책", a:NA.PROPOSED, l:"visual_reference", st:"review", p:33, w:"reference/business-19-personal-memory-book-v1/" }),
    identity({ n:20, s:"personal-memory-novel", t:"Personal Memory Novel", k:"나의 기억소설", a:NA.PROPOSED, l:"visual_reference", st:"review", p:31, w:"reference/business-20-personal-memory-novel-v1/" }),
    identity({ n:21, s:"founder-strategy-letter", t:"Founder Strategy Letter", k:"대표 전략 편지", a:NA.PROPOSED, l:"visual_reference", st:"review", p:29, w:"reference/business-21-founder-strategy-letter-v1/" }),
    identity({ n:22, s:"personal-media-studio", t:"Personal Media Studio", k:"개인 미디어 스튜디오", a:NA.PROPOSED, l:"visual_reference", st:"review", p:28, w:"reference/business-22-personal-media-studio-v1/" }),
    // ═══ 23–25: EXISTING PROJECT ═══
    identity({ n:23, s:"lovebud", t:"LoveBud", k:"러브버드", a:NA.EXISTING_PROJECT, l:"active", st:"running", p:45, su:"https://lovebud.pages.dev/", w:"skerishKang/LoveBud" }),
    identity({ n:24, s:"lovetree-3", t:"LoveTree 3.0", k:"러브트리 3.0", a:NA.EXISTING_PROJECT, l:"active", st:"running", p:25, su:"https://lovetree3.pages.dev/", w:"skerishKang/lovetree3.0" }),
    identity({ n:25, s:"love-matchmaking", t:"Love Matchmaking", k:"러브 매치메이킹", a:NA.EXISTING_PROJECT, l:"concept", st:"planning", p:15, w:"skerishKang/401-love-match-making" }),
    // ═══ 26–35: PROPOSED ═══
    identity({ n:26, s:"company-memory", t:"Company Memory", k:"회사 기억", a:NA.PROPOSED, l:"visual_reference", st:"review", p:27, w:"reference/business-26-company-memory-v1/" }),
    identity({ n:27, s:"evidence-studio", t:"Evidence Studio", k:"사건 기록실", a:NA.PROPOSED, l:"visual_reference", st:"review", p:26, w:"reference/business-27-evidence-studio-v1/" }),
    identity({ n:28, s:"decision-archive", t:"Decision Archive", k:"회의·결정 기록실", a:NA.PROPOSED, l:"visual_reference", st:"review", p:24, w:"reference/business-28-decision-archive-v1/" }),
    identity({ n:29, s:"apartment-governance", t:"Apartment Governance", k:"우리단지 운영실", a:NA.PROPOSED, l:"visual_reference", st:"review", p:22, su:"https://ai-revenue-business-29-governance-tutorial.pages.dev/", w:"reference/business-29-apartment-governance-tutorial/" }),
    identity({ n:30, s:"civic-ai-navigator", t:"Civic AI Navigator", k:"시민 AI 내비게이터", a:NA.PROPOSED, l:"visual_reference", st:"review", p:20, w:"reference/business-30-civic-ai-navigator-v1/" }),
    identity({ n:31, s:"public-procedure-experience-data", t:"Public Procedure Experience Data", k:"공공절차 경험 데이터", a:NA.PROPOSED, l:"visual_reference", st:"review", p:18, w:"reference/business-31-public-procedure-data-v1/" }),
    identity({ n:32, s:"ai-skill-studio", t:"AI Skill Studio", k:"AI 업무 실습실", a:NA.PROPOSED, l:"visual_reference", st:"review", p:16, w:"reference/business-32-ai-skill-studio-ux/" }),
    identity({ n:33, s:"research-memory", t:"Research Memory", k:"연구 기억실", a:NA.PROPOSED, l:"visual_reference", st:"review", p:14, w:"reference/business-33-research-memory-v1/" }),
    identity({ n:34, s:"ai-dubbing-studio", t:"AI Dubbing Studio", k:"AI 더빙 스튜디오", a:NA.PROPOSED, l:"visual_reference", st:"review", p:12, w:"reference/business-34-ai-dubbing-studio-v1/" }),
    identity({ n:35, s:"ai-media-education-dx", t:"AI Media Education & DX", k:"AI 미디어 교육·DX", a:NA.PROPOSED, l:"visual_reference", st:"review", p:11, w:"reference/business-35-ai-media-education-dx-v3/" }),
    // ═══ 36–43: PROPOSED ═══
    identity({ n:36, s:"ai-women-safety", t:"AI Women Safety", k:"AI 여성안전 서비스", a:NA.PROPOSED, l:"visual_reference", st:"review", p:50, w:"reference/business-36-ai-women-safety-v1/" }),
    identity({ n:37, s:"ai-safe-route", t:"AI Safe Route", k:"AI 안전경로", a:NA.PROPOSED, l:"visual_reference", st:"review", p:48, w:"reference/business-37-ai-safe-route-v1/" }),
    identity({ n:38, s:"ai-exercise-coach", t:"AI Exercise Coach", k:"AI 운동 코치", a:NA.PROPOSED, l:"visual_reference", st:"review", p:46, w:"reference/business-38-ai-exercise-coach-v1/" }),
    identity({ n:39, s:"112-real-time-interpretation", t:"112 Real-Time Interpretation", k:"112 실시간 AI 통역", a:NA.PROPOSED, l:"visual_reference", st:"review", p:44, w:"reference/business-39-112-real-time-interpretation-v1/" }),
    identity({ n:40, s:"emergency-urgency-ai", t:"Emergency Urgency AI", k:"긴급도 판단 AI", a:NA.PROPOSED, l:"visual_reference", st:"review", p:24, w:"reference/business-40-emergency-urgency-ai-v1/" }),
    identity({ n:41, s:"foreign-emergency-assistant", t:"Foreign Emergency Assistant", k:"외국인 긴급신고 도우미", a:NA.PROPOSED, l:"visual_reference", st:"review", p:22, w:"reference/business-41-foreign-emergency-assistant-v1/" }),
    identity({ n:42, s:"ai-development-control-tower", t:"AI Development Control Tower", k:"AI 개발 관제탑", a:NA.PROPOSED, l:"visual_reference", st:"review", p:20, w:"reference/business-42-ai-development-control-tower-v1/" }),
    identity({ n:43, s:"ai-software-factory", t:"AI Software Factory", k:"AI 소프트웨어 공장", a:NA.PROPOSED, l:"visual_reference", st:"review", p:18, w:"reference/business-43-ai-software-factory-v1/" }),
    // ═══ 44: EXISTING PROJECT ═══
    identity({ n:44, s:"portfolio-console", t:"Portfolio Console", k:"포트폴리오 콘솔", a:NA.EXISTING_PROJECT, l:"active", st:"running", p:10, su:"https://ai-revenue-portfolio-console.pages.dev/", w:"apps/portfolio-console/" }),
    // ═══ 45–55: CANDIDATE ═══
    identity({ n:45, s:"ai-content-engine", t:"AI Content Engine", k:"AI 콘텐츠 엔진", a:NA.CANDIDATE, l:"visual_reference", st:"review", p:5, w:"reference/business-45-ai-content-engine-v1/" }),
    identity({ n:46, s:"ai-personalization-engine", t:"AI Personalization Engine", k:"AI 개인화 엔진", a:NA.CANDIDATE, l:"visual_reference", st:"review", p:5, w:"reference/business-46-ai-personalization-engine-v1/" }),
    identity({ n:47, s:"real-time-feedback-engine", t:"Real-Time Feedback Engine", k:"실시간 반응 엔진", a:NA.CANDIDATE, l:"visual_reference", st:"review", p:5, w:"reference/business-47-real-time-feedback-engine-v1/" }),
    identity({ n:48, s:"ai-verification-engine", t:"AI Verification Engine", k:"AI 검증·승인 엔진", a:NA.CANDIDATE, l:"visual_reference", st:"review", p:5, w:"reference/business-48-ai-verification-engine-v1/" }),
    identity({ n:49, s:"public-data-connector-hub", t:"Public Data Connector Hub", k:"공공데이터 커넥터 허브", a:NA.CANDIDATE, l:"visual_reference", st:"review", p:5, w:"reference/business-49-public-data-connector-hub-v1/" }),
    identity({ n:50, s:"private-data-connector-hub", t:"Private Data Connector Hub", k:"사내자료 커넥터 허브", a:NA.CANDIDATE, l:"concept", st:"planning", p:5 }),
    identity({ n:51, s:"ai-workflow-marketplace", t:"AI Workflow Marketplace", k:"AI 워크플로우 마켓", a:NA.CANDIDATE, l:"visual_reference", st:"review", p:5, w:"reference/business-51-ai-workflow-marketplace-v1/" }),
    identity({ n:52, s:"scheduled-agent-operations", t:"Scheduled Agent Operations", k:"예약형 AI 운영", a:NA.CANDIDATE, l:"visual_reference", st:"review", p:5, w:"reference/business-52-scheduled-agent-operations-v1/" }),
    identity({ n:53, s:"embedded-ai-sdk", t:"Embedded AI SDK", k:"임베드 AI SDK", a:NA.CANDIDATE, l:"visual_reference", st:"review", p:5, w:"reference/business-53-embedded-ai-sdk-v1/" }),
    identity({ n:54, s:"korean-ai-code-agent", t:"Korean AI Code Agent", k:"한국형 AI 코드 에이전트", a:NA.CANDIDATE, l:"mvp_vertical_slice", st:"review", p:5, w:"apps/korean-ai-code-agent/" }),
    identity({ n:55, s:"local-ai-fleet", t:"Local AI Fleet", k:"로컬 AI 플릿", a:NA.CANDIDATE, l:"visual_reference", st:"review", p:5, w:"reference/business-55-local-ai-fleet-v1/" }),
    // B56 is intentionally unused.
    identity({ n:57, s:"classic-literature-translation-studio", t:"Classic Literature Translation Studio", k:"고전문학 번역 스튜디오", a:NA.CANDIDATE, l:"visual_reference", st:"review", p:5, w:"reference/business-57-classic-literature-translation-studio-v1/" }),
    identity({ n:58, s:"personal-writing-voice-studio", t:"Personal Writing Voice Studio", k:"개인 문체 스튜디오", a:NA.CANDIDATE, l:"visual_reference", st:"review", p:5, w:"reference/business-58-personal-writing-voice-studio-v1/" }),
    identity({ n:59, s:"living-archive", t:"Living Archive", k:"나의 기록서재", a:NA.CANDIDATE, l:"mvp_vertical_slice", st:"review", p:5, w:"reference/business-59-living-archive-v1/" }),
  ];

  // Generate summary counts
  (function () {
    var total = window.ARL_MANIFEST.length;
    var numberAuthority = {};
    for (var i = 0; i < total; i++) {
      var key = window.ARL_MANIFEST[i].numberAuthority;
      numberAuthority[key] = (numberAuthority[key] || 0) + 1;
    }
    window.ARL_MANIFEST_SUMMARY = { total: total, sum: total, numberAuthority: numberAuthority };
  })();
})();