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
      number: 7,
      slug: "personal-meaning-map",
      title: "Personal Meaning Map",
      koreanTitle: "개인 의미 지도",
      summary: "기억 조각 사이의 반복되는 의미를 연결하고 직접 검토하는 개인 의미 필드입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b07/",
      sourcePath: "reference/business-07-personal-meaning-map-v1/"
    }),
    Object.freeze({
      number: 8,
      slug: "family-newspaper",
      title: "Family Newspaper",
      koreanTitle: "우리 가족 신문",
      summary: "사진·메모·일정을 한 호의 디지털 가족 신문으로 편집해 다시 읽는 경험입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b08/",
      sourcePath: "reference/business-08-family-newspaper-v1/"
    }),
    Object.freeze({
      number: 9,
      slug: "personalized-childrens-story",
      title: "Personalized Children's Story",
      koreanTitle: "우리 아이 이야기",
      summary: "아이의 선택에 따라 다음 장면과 질문이 달라지는 참여형 이야기 경험입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b09/",
      sourcePath: "reference/business-09-personalized-childrens-story-v1/"
    }),
    Object.freeze({
      number: 10,
      slug: "fan-magazine",
      title: "Fan Magazine",
      koreanTitle: "나만의 팬 매거진",
      summary: "다시 찾은 공개 장면과 그 이유를 한 호의 개인 팬 에디션으로 편집합니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b10/",
      sourcePath: "reference/business-10-fan-magazine-v1/"
    }),
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
      number: 60,
      slug: "ai-free-radar",
      title: "AI Free Radar",
      koreanTitle: "AI 무료 레이더",
      summary: "지금 무료로 사용할 수 있는 AI 모델·API·크레딧 기회를 빠르게 찾아 검증해 보여줍니다.",
      publicStatus: "LIVE",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b60/",
      sourcePath: "reference/business-60-ai-api-v1/"
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
