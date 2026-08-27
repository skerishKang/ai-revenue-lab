"use strict";

const routes = [
  {
    number: 1,
    route: "b01",
    sourcePath: "apps/personal-edition",
    mode: "GENERATED_APP_PREVIEW_ALLOWLIST",
    marker: "Personal Edition",
    generatorModule: "scripts.build_static_production",
    generatorOutputOverride: "preview._OUTPUT_DIR",
    includeFiles: [
      "index.html",
      "robots.txt",
      "preview/participant/index.html"
    ],
    includeDirs: [
      "static",
      "guide",
      "preview/participant/empty",
      "preview/participant/input-received",
      "preview/participant/editing",
      "preview/participant/published",
      "preview/participant/feedback",
      "preview/participant/input",
      "preview/participant/editions",
      "preview/participant/history",
      "preview/participant/not-found",
      "preview/participant/transformation"
    ],
    privateLinkSegments: ["admin", "preview-states"],
    rewriteRootRelative: true,
    neutralizeForms: true,
    aggregateHeaders: [
      "X-Robots-Tag: noindex, nofollow",
      "Referrer-Policy: no-referrer",
      "X-Content-Type-Options: nosniff",
      "X-Frame-Options: DENY",
      "Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; script-src 'none'; connect-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'self'; object-src 'none'"
    ]
  },
  {
    number: 2,
    route: "b02",
    sourcePath: "apps/living-travel/pages-preview/site",
    mode: "STATIC_APP_PREVIEW_ALLOWLIST",
    marker: "Living Travel",
    includeFiles: ["index.html", "guide.html", "robots.txt"],
    includeDirs: ["assets", "demo", "traveler"],
    privateLinkSegments: ["operator", "staging"],
    rewriteRootRelative: true,
    aggregateHeaders: [
      "X-Robots-Tag: noindex, nofollow",
      "Referrer-Policy: no-referrer",
      "X-Content-Type-Options: nosniff",
      "X-Frame-Options: DENY",
      "Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; script-src 'self' 'unsafe-inline'; connect-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'self'; object-src 'none'"
    ]
  },
  {
    number: 4,
    route: "b04",
    sourcePath: "apps/living-learning/pages-preview",
    mode: "STATIC_APP_PREVIEW",
    marker: "Living Learning",
    includeFiles: [],
    includeDirs: [],
    excludeRootFiles: ["_headers", "_redirects"],
    rewriteRootRelative: true
  },
  {
    number: 6,
    route: "b06",
    sourcePath: "reference/business-06-world-feed-v1",
    mode: "STATIC_REFERENCE",
    marker: "World Feed",
    includeFiles: ["index.html", "guide.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
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
    number: 11,
    route: "b11",
    sourcePath: "reference/business-11-language-learning-magazine-v1",
    mode: "STATIC_REFERENCE",
    marker: "Language Field Journal",
    includeFiles: ["index.html", "guide.html", "ux.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 12,
    route: "b12",
    sourcePath: "reference/business-12-creator-mini-media-v1",
    mode: "STATIC_REFERENCE",
    marker: "Creator Release Room",
    includeFiles: ["index.html", "guide.html", "ux.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 13,
    route: "b13",
    sourcePath: "apps/personal-video-archive",
    mode: "GENERATED_APP_PREVIEW",
    marker: "Business 13",
    generatorModule: "scripts.build_static_preview",
    excludeRootFiles: ["_headers"],
    rewriteRootRelative: true,
    aggregateHeaders: [
      "X-Robots-Tag: noindex, nofollow",
      "Referrer-Policy: no-referrer",
      "X-Content-Type-Options: nosniff",
      "X-Frame-Options: DENY",
      "Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' https://i.ytimg.com; script-src 'none'; connect-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'self'"
    ]
  },
  {
    number: 15,
    route: "b15",
    sourcePath: "reference/business-15-global-ai-newsroom-v1",
    mode: "STATIC_REFERENCE",
    marker: "Verification Desk",
    includeFiles: ["index.html", "guide.html", "ux.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 16,
    route: "b16",
    sourcePath: "reference/business-16-personal-sports-v1",
    mode: "STATIC_REFERENCE",
    marker: "Matchday Live Journal",
    includeFiles: ["index.html", "guide.html", "ux.html"],
    includeDirs: ["assets", "styles"],
    excludePaths: ["app.js", "docs"]
  },
  {
    number: 17,
    route: "b17",
    sourcePath: "reference/business-17-local-shop-magazine-v1",
    mode: "STATIC_REFERENCE",
    marker: "Counter Journal",
    includeFiles: ["index.html", "guide.html", "ux.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 18,
    route: "b18",
    sourcePath: "reference/business-18-personal-audio-channel-v1",
    mode: "STATIC_REFERENCE",
    marker: "Listening Room",
    includeFiles: ["index.html", "guide.html", "ux.html"],
    includeDirs: ["assets", "styles"],
    excludePaths: ["app.js", "docs"]
  },
  {
    number: 19,
    route: "b19",
    sourcePath: "reference/business-19-personal-memory-book-v1",
    mode: "STATIC_REFERENCE",
    marker: "Memory Binding Table",
    includeFiles: ["index.html", "guide.html", "ux.html"],
    includeDirs: ["assets", "styles"],
    excludePaths: ["app.js", "docs"]
  },
  {
    number: 20,
    route: "b20",
    sourcePath: "reference/business-20-personal-memory-novel-v1",
    mode: "STATIC_REFERENCE",
    marker: "Memory Manuscript Studio",
    includeFiles: ["index.html", "guide.html", "ux.html"],
    includeDirs: ["assets", "styles"],
    excludePaths: ["app.js", "docs"]
  },
  {
    number: 21,
    route: "b21",
    sourcePath: "reference/business-21-founder-strategy-letter-v1",
    mode: "STATIC_REFERENCE",
    marker: "Decision Corridor",
    includeFiles: ["index.html", "guide.html", "ux.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 22,
    route: "b22",
    sourcePath: "reference/business-22-personal-media-studio-v1",
    mode: "STATIC_REFERENCE",
    marker: "Story Spine Loom",
    includeFiles: ["index.html", "guide.html", "ux.html"],
    includeDirs: ["assets", "styles"],
    excludePaths: ["app.js", "docs"]
  },
  {
    number: 32,
    route: "b32",
    sourcePath: "reference/business-32-ai-skill-studio-ux",
    mode: "STATIC_REFERENCE",
    marker: "AI 업무 실습실",
    includeFiles: ["index.html", "guide.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 35,
    route: "b35",
    sourcePath: "reference/business-35-ai-media-education-dx-v3",
    mode: "STATIC_REFERENCE",
    marker: "AI 미디어 업무전환",
    includeFiles: ["index.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 36,
    route: "b36",
    sourcePath: "reference/business-36-ai-women-safety-v1",
    mode: "STATIC_REFERENCE",
    marker: "AI 여성안전 서비스",
    includeFiles: ["index.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 37,
    route: "b37",
    sourcePath: "reference/business-37-ai-safe-route-v1",
    mode: "STATIC_REFERENCE",
    marker: "AI 안전경로",
    includeFiles: ["index.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 39,
    route: "b39",
    sourcePath: "reference/business-39-112-real-time-interpretation-v1",
    mode: "STATIC_REFERENCE",
    marker: "112 실시간 AI 통역",
    includeFiles: ["index.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 48,
    route: "b48",
    sourcePath: "reference/business-48-ai-verification-engine-v1",
    mode: "STATIC_REFERENCE",
    marker: "AI 검증·승인 엔진",
    includeFiles: ["index.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 52,
    route: "b52",
    sourcePath: "reference/business-52-scheduled-agent-operations-v1",
    mode: "STATIC_REFERENCE",
    marker: "예약형 AI 운영",
    includeFiles: ["index.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 53,
    route: "b53",
    sourcePath: "reference/business-53-embedded-ai-sdk-v1",
    mode: "STATIC_REFERENCE",
    marker: "임베드 AI SDK",
    includeFiles: ["index.html"],
    includeDirs: ["assets", "scripts", "styles"]
  },
  {
    number: 59,
    route: "b59",
    sourcePath: "reference/business-59-living-archive-v1",
    mode: "STATIC_REFERENCE",
    marker: "나의 기록서재",
    includeFiles: ["index.html"],
    includeDirs: ["scripts", "styles"]
  },
  {
    number: 60,
    route: "b60",
    sourcePath: "reference/business-60-ai-api-v1",
    mode: "B60_PUBLIC_ALLOWLIST",
    marker: "AI",
    includeDirs: ["assets", "data"]
  }
];

module.exports = Object.freeze(routes.map(route => Object.freeze({
  ...route,
  includeFiles: route.includeFiles ? Object.freeze(route.includeFiles.slice()) : undefined,
  includeDirs: route.includeDirs ? Object.freeze(route.includeDirs.slice()) : undefined,
  excludePaths: route.excludePaths ? Object.freeze(route.excludePaths.slice()) : undefined,
  excludeRootFiles: route.excludeRootFiles ? Object.freeze(route.excludeRootFiles.slice()) : undefined,
  privateLinkSegments: route.privateLinkSegments ? Object.freeze(route.privateLinkSegments.slice()) : undefined,
  aggregateHeaders: route.aggregateHeaders ? Object.freeze(route.aggregateHeaders.slice()) : undefined
})));