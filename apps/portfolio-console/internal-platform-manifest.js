/*
 * Internal Platform manifest — shared infrastructure is intentionally separate
 * from Business numbering. Source paths remain authoritative in ai-revenue-lab.
 */
(function () {
  "use strict";

  function freeze(value) {
    if (Array.isArray(value)) value.forEach(freeze);
    if (value && typeof value === "object" && !Object.isFrozen(value)) {
      Object.keys(value).forEach(function (key) { freeze(value[key]); });
      Object.freeze(value);
    }
    return value;
  }

  var platforms = [
    {
      id: "IP-CORE",
      name: "Padiem AI Core",
      koreanName: "파디엠 AI 코어",
      repository: "skerishKang/ai-revenue-lab",
      sourcePath: "packages/padiem-ai-core/",
      sourceUrl: "https://github.com/skerishKang/ai-revenue-lab/tree/main/packages/padiem-ai-core",
      authorityDoc: "packages/padiem-ai-core/BOUNDARY.md",
      authorityDocUrl: "https://github.com/skerishKang/ai-revenue-lab/blob/main/packages/padiem-ai-core/BOUNDARY.md",
      businessNumber: null,
      status: "active-development",
      runtime: "Shared Python package / AI runtime library",
      roleKo: "제품 중립 AI 계약과 공통 실행 런타임",
      roleEn: "Product-neutral AI contracts and shared execution runtimes",
      owns: ["Execution", "Evidence / Grounding", "Streaming", "Tool Runtime", "Web / Research", "Retrieval / Memory", "Context Permission", "Orchestration"],
      doesNotOwn: ["Product domain semantics", "Cross-runtime service identity", "Provider/model selection", "Provider credentials"],
      dependencies: ["B14 Korean AI Platform"],
      consumers: ["B61 StoryMemory", "B62 Padiem Chat", "LoveBud Scout via IP-ENGINE"],
      currentWorkKo: "공통 AI 기능 재사용·확장 경계 유지",
      currentWorkEn: "Maintain reusable shared AI runtime boundaries",
      currentIssue: null
    },
    {
      id: "IP-ENGINE",
      name: "Padiem AI Engine",
      koreanName: "파디엠 AI 엔진",
      repository: "skerishKang/ai-revenue-lab",
      sourcePath: "apps/padiem-ai-engine/",
      sourceUrl: "https://github.com/skerishKang/ai-revenue-lab/tree/main/apps/padiem-ai-engine",
      authorityDoc: "docs/internal-platform/engine/README.md",
      authorityDocUrl: "https://github.com/skerishKang/ai-revenue-lab/blob/main/docs/internal-platform/engine/README.md",
      businessNumber: null,
      status: "active-development",
      runtime: "Cloudflare Worker — padiem-ai-engine",
      roleKo: "제품과 Core 사이의 cross-runtime 실행·인증·Service Binding 관문",
      roleEn: "Cross-runtime execution, identity, and Service Binding boundary around Core",
      owns: ["Internal execute/stream transport", "Service Binding hosting", "First-party caller identity", "Core runtime service projection"],
      doesNotOwn: ["Product domain semantics", "Core generic AI semantics", "B14 provider routing", "Product credentials"],
      dependencies: ["IP-CORE", "B14 Korean AI Platform"],
      consumers: ["B61 StoryMemory", "LoveBud Scout — runtime activation pending"],
      currentWorkKo: "#1698 독립 제품용 multi-caller service identity registry",
      currentWorkEn: "#1698 multi-caller service identity registry for independent products",
      currentIssue: {
        label: "#1698",
        url: "https://github.com/skerishKang/ai-revenue-lab/issues/1698"
      }
    },
    {
      id: "IP-CONTROL",
      name: "Padiem Control Plane",
      koreanName: "파디엠 컨트롤 플레인",
      repository: "skerishKang/ai-revenue-lab",
      sourcePath: "packages/padiem-control-plane/",
      sourceUrl: "https://github.com/skerishKang/ai-revenue-lab/tree/main/packages/padiem-control-plane",
      authorityDoc: "docs/internal-platform/control-plane/README.md",
      authorityDocUrl: "https://github.com/skerishKang/ai-revenue-lab/blob/main/docs/internal-platform/control-plane/README.md",
      businessNumber: null,
      status: "active-development",
      runtime: "Shared control-plane / policy package",
      roleKo: "여러 제품에서 재사용하는 플랫폼 제어·정책 계약",
      roleEn: "Reusable platform control-plane and policy contracts",
      owns: ["Shared control-plane contracts", "Reusable platform governance state"],
      doesNotOwn: ["Product-local authorization", "Product records", "Core runtime semantics", "Engine service identity", "B14 provider credentials"],
      dependencies: [],
      consumers: ["Padiem platform components as explicitly integrated"],
      currentWorkKo: "공통 제어·정책 경계 유지",
      currentWorkEn: "Maintain reusable control-plane and policy boundaries",
      currentIssue: null
    }
  ];

  window.ARL_INTERNAL_PLATFORMS = freeze(platforms);
  window.ARL_INTERNAL_PLATFORM_SUMMARY = freeze({
    count: platforms.length,
    idPrefix: "IP-",
    businessNumberAuthority: "NONE",
    registryPath: "docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md",
    adoptionPlaybookPath: "docs/internal-platform/AI_ADOPTION_PLAYBOOK.md"
  });
})();
