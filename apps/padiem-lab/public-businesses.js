(function (root, factory) {
  "use strict";
  var manifest = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = manifest;
  } else {
    root.PADIEM_LAB_BUSINESSES = manifest;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  return Object.freeze([
    Object.freeze({
      number: 14,
      slug: "korean-ai-platform",
      title: "Korean AI Platform",
      koreanTitle: "한국형 AI 모델 플랫폼",
      summary: "여러 AI 모델과 공급자를 한국어 중심의 하나의 모델 접근 경험으로 연결합니다.",
      publicStatus: "LIVE",
      routeKind: "EXTERNAL_RUNTIME",
      targetPath: "/b14/",
      currentPublicUrl: "https://ai-revenue-korean-ai-platform.charliekant.workers.dev/workspace"
    }),
    Object.freeze({
      number: 23,
      slug: "lovebud",
      title: "LoveBud",
      koreanTitle: "러브버드",
      summary: "사람과 관계의 맥락을 이어가는 독립 제품 프로젝트입니다.",
      publicStatus: "LIVE",
      routeKind: "EXTERNAL_RUNTIME",
      targetPath: "/b23/",
      currentPublicUrl: "https://lovebud.pages.dev/"
    }),
    Object.freeze({
      number: 24,
      slug: "lovetree-3",
      title: "LoveTree 3.0",
      koreanTitle: "러브트리 3.0",
      summary: "기억과 관계를 시각적으로 탐색하고 축적하는 LoveTree 제품 계열입니다.",
      publicStatus: "LIVE",
      routeKind: "EXTERNAL_RUNTIME",
      targetPath: "/b24/",
      currentPublicUrl: "https://lovetree3.pages.dev/"
    }),
    Object.freeze({
      number: 29,
      slug: "apartment-governance",
      title: "Apartment Governance",
      koreanTitle: "우리단지 운영실",
      summary: "회의·안건·의결·공개 기록을 하나의 운영 흐름으로 정리하는 공동주택 거버넌스 제품입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b29/",
      sourcePath: "reference/business-29-apartment-governance-tutorial/",
      currentPublicUrl: "https://ai-revenue-business-29-governance-tutorial.pages.dev/"
    }),
    Object.freeze({
      number: 60,
      slug: "ai-free-radar",
      title: "AI Free Radar",
      koreanTitle: "AI 무료 레이더",
      summary: "지금 무료로 사용할 수 있는 AI 모델·API·크레딧 기회를 빠르게 찾아 검증해 보여줍니다.",
      publicStatus: "LIVE",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b60/",
      sourcePath: "reference/business-60-ai-api-v1/",
      currentPublicUrl: "https://ai-api.pages.dev/"
    }),
    Object.freeze({
      number: 62,
      slug: "padiem-chat",
      title: "Padiem Chat",
      koreanTitle: "파디엠 챗",
      summary: "누구나 설명 없이 바로 질문하고 검색하고 파일을 다룰 수 있도록 만드는 파디엠의 기본 AI입니다.",
      publicStatus: "BUILDING",
      routeKind: "EXTERNAL_RUNTIME",
      targetPath: "/b62/"
    })
  ]);
});
