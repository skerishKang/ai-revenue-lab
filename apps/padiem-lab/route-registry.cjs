"use strict";

const routes = [
  {
    number: 7,
    route: "b07",
    sourcePath: "reference/business-07-personal-meaning-map-v1",
    mode: "STATIC_REFERENCE",
    marker: "개인 의미 지도",
    includeFiles: ["index.html", "guide.html", "ux.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 8,
    route: "b08",
    sourcePath: "reference/business-08-family-newspaper-v1",
    mode: "STATIC_REFERENCE",
    marker: "우리 가족 신문",
    includeFiles: ["index.html", "guide.html", "ux.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 9,
    route: "b09",
    sourcePath: "reference/business-09-personalized-childrens-story-v1",
    mode: "STATIC_REFERENCE",
    marker: "우리 아이 이야기",
    includeFiles: ["index.html", "guide.html", "ux.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 10,
    route: "b10",
    sourcePath: "reference/business-10-fan-magazine-v1",
    mode: "STATIC_REFERENCE",
    marker: "Fandom Edition",
    includeFiles: ["index.html", "guide.html", "ux.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 60,
    route: "b60",
    sourcePath: "reference/business-60-ai-api-v1",
    mode: "B60_PUBLIC_ALLOWLIST",
    marker: "AI 무료 레이더",
    includeDirs: ["assets", "data"]
  }
];

module.exports = Object.freeze(routes.map(route => Object.freeze({
  ...route,
  includeFiles: route.includeFiles ? Object.freeze(route.includeFiles.slice()) : undefined,
  includeDirs: Object.freeze(route.includeDirs.slice())
})));
