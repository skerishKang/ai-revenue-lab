(() => {
  "use strict";

  const state = {
    view: "start",
    preset: "code",
    mode: "auto",
    scope: "preferred",
    optimize: "balanced",
    allowFallback: true,
    selectedManualModel: "Kanana Code",
  };

  const taskPresets = {
    code: "이 저장소의 로그인 오류 원인을 찾고 수정 계획을 한국어로 정리해줘.",
    korean: "이 회의록을 핵심 쟁점, 결정사항, 후속 조치로 나눠 정리해줘.",
    batch: "고객 문의 300건을 유형별로 분류하고 반복되는 불만을 요약해줘.",
  };

  const codeSamples = {
    quick: {
      python: `from openai import OpenAI\n\nclient = OpenAI(\n    base_url="https://api.business14.kr/v1",\n    api_key=os.environ["BUSINESS14_API_KEY"]\n)\n\nresponse = client.chat.completions.create(\n    model="b14/auto",\n    messages=[{"role": "user", "content": task}]\n)`,
      node: `import OpenAI from "openai";\n\nconst client = new OpenAI({\n  baseURL: "https://api.business14.kr/v1",\n  apiKey: process.env.BUSINESS14_API_KEY\n});\n\nconst response = await client.chat.completions.create({\n  model: "b14/auto",\n  messages: [{ role: "user", content: task }]\n});`,
      curl: `curl https://api.business14.kr/v1/chat/completions \\\n  -H "Authorization: Bearer $BUSINESS14_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model":"b14/auto","messages":[{"role":"user","content":"한국어 문서를 요약해줘"}]}'`,
    },
    developer: {
      python: `from openai import OpenAI\nimport os\n\nclient = OpenAI(\n    base_url="https://api.business14.kr/v1",\n    api_key=os.environ["BUSINESS14_API_KEY"]\n)\n\nresponse = client.chat.completions.create(\n    model="b14/auto",\n    messages=[{\n        "role": "user",\n        "content": "한국어 계약서를 핵심 쟁점별로 정리해줘"\n    }],\n    extra_body={\n        "business14": {\n            "route_scope": "domestic_preferred",\n            "optimize_for": "balanced"\n        }\n    }\n)\n\nprint(response.model)\nprint(response.business14.selected_provider)`,
      typescript: `import OpenAI from "openai";\n\nconst client = new OpenAI({\n  baseURL: "https://api.business14.kr/v1",\n  apiKey: process.env.BUSINESS14_API_KEY\n});\n\nconst response = await client.chat.completions.create({\n  model: "b14/auto",\n  messages: [{\n    role: "user",\n    content: "한국어 계약서를 핵심 쟁점별로 정리해줘"\n  }],\n  business14: {\n    route_scope: "domestic_preferred",\n    optimize_for: "balanced"\n  }\n});\n\nconsole.log(response.model);`,
      curl: `curl https://api.business14.kr/v1/chat/completions \\\n  -H "Authorization: Bearer $BUSINESS14_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '{\n    "model": "b14/auto",\n    "messages": [{"role":"user","content":"한국어 계약서를 정리해줘"}],\n    "business14": {\n      "route_scope": "domestic_preferred",\n      "optimize_for": "balanced"\n    }\n  }'`,
    },
  };

  const routeCatalog = {
    kanana: {
      model: "Kanana Code",
      provider: "Kakao · 국내",
      reason: "한국어·코드 적합성, 국내 처리",
      basis: "한국어 + 코드 · 국내 우선",
      cost: "설정값 · 약 ₩0.42",
      initial: "K",
      tone: "tone-red",
    },
    qwen: {
      model: "Qwen Coder 32B",
      provider: "내 PC · 로컬",
      reason: "로컬 전용, 코드 작업 가능",
      basis: "코드 + 로컬 전용",
      cost: "API 비용 ₩0",
      initial: "Q",
      tone: "tone-ink",
    },
    hcx: {
      model: "HyperCLOVA X Seed",
      provider: "Naver · 국내",
      reason: "한국어 문서 적합성, 국내 처리",
      basis: "한국어 문서 · 국내 우선",
      cost: "공개 단가 · 약 ₩1.16",
      initial: "H",
      tone: "tone-green",
    },
    gemini: {
      model: "Gemini Flash",
      provider: "Google · 외부",
      reason: "대량 처리 속도와 낮은 설정 비용",
      basis: "대량 분류 · 비용/속도 우선",
      cost: "최근 측정 · 약 ₩0.31",
      initial: "G",
      tone: "tone-gold",
    },
    claude: {
      model: "Claude Sonnet",
      provider: "Anthropic · 외부",
      reason: "복잡한 구현과 긴 코드 검토",
      basis: "복잡한 코드 · 품질 우선",
      cost: "공개 단가 · 약 ₩7.84",
      initial: "C",
      tone: "tone-blue",
    },
  };

  const routeCandidateLayouts = {
    code: ["kanana", "qwen", "claude"],
    korean: ["hcx", "kanana", "gemini"],
    batch: ["gemini", "qwen", "hcx"],
  };

  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function setView(viewName, options = {}) {
    const target = qs(`[data-view="${viewName}"]`);
    if (!target) return;

    state.view = viewName;
    qsa("[data-view]").forEach((view) => view.classList.toggle("is-active", view === target));
    qsa("[data-view-link]").forEach((control) => {
      const active = control.dataset.viewLink === viewName;
      control.classList.toggle("is-active", active);
      if (control.matches("button")) control.setAttribute("aria-current", active ? "page" : "false");
    });

    if (!options.preserveScroll) window.scrollTo({ top: 0, behavior: "smooth" });
    const heading = qs("h1", target);
    if (heading && options.focusHeading) {
      heading.setAttribute("tabindex", "-1");
      heading.focus({ preventScroll: true });
    }
  }

  function setPreset(preset) {
    if (!taskPresets[preset]) return;
    state.preset = preset;
    const input = qs("#task-input");
    if (input) input.value = taskPresets[preset];
    qsa("[data-preset]").forEach((button) => button.classList.toggle("is-selected", button.dataset.preset === preset));
    previewRoute();
  }

  function setMode(mode) {
    if (!['auto', 'manual'].includes(mode)) return;
    state.mode = mode;
    qsa("[data-mode]").forEach((button) => button.classList.toggle("is-active", button.dataset.mode === mode));
    const preferenceBar = qs("#preference-bar");
    if (preferenceBar) {
      preferenceBar.style.opacity = mode === "auto" ? "1" : ".48";
      preferenceBar.setAttribute("aria-disabled", mode === "auto" ? "false" : "true");
    }
    previewRoute();
  }

  function chooseRoute() {
    if (state.mode === "manual") {
      const matching = Object.values(routeCatalog).find((item) => item.model === state.selectedManualModel);
      return { route: matching || routeCatalog.kanana, key: "manual", noSafeRoute: false };
    }

    if (state.scope === "local" && state.preset === "korean") {
      return {
        route: {
          model: "NO SAFE ROUTE",
          provider: "호출하지 않음",
          reason: "연결된 로컬 경로에 한국어 문서 기능 근거가 없습니다.",
          basis: "로컬 전용 · 기능 불충족",
          cost: "호출 없음 · ₩0",
          initial: "!",
          tone: "tone-ink",
        },
        key: "none",
        noSafeRoute: true,
      };
    }

    if (state.scope === "local") return { route: routeCatalog.qwen, key: "qwen", noSafeRoute: false };
    if (state.scope === "domestic") {
      return state.preset === "korean"
        ? { route: routeCatalog.hcx, key: "hcx", noSafeRoute: false }
        : { route: routeCatalog.kanana, key: "kanana", noSafeRoute: false };
    }

    if (state.optimize === "korean") {
      return state.preset === "code"
        ? { route: routeCatalog.kanana, key: "kanana", noSafeRoute: false }
        : { route: routeCatalog.hcx, key: "hcx", noSafeRoute: false };
    }
    if (state.optimize === "cost" || state.optimize === "latency") {
      if (state.scope === "preferred" && state.preset === "code") {
        return { route: routeCatalog.qwen, key: "qwen", noSafeRoute: false };
      }
      return { route: routeCatalog.gemini, key: "gemini", noSafeRoute: false };
    }

    if (state.preset === "korean") return { route: routeCatalog.hcx, key: "hcx", noSafeRoute: false };
    if (state.preset === "batch") return { route: routeCatalog.gemini, key: "gemini", noSafeRoute: false };
    return { route: routeCatalog.kanana, key: "kanana", noSafeRoute: false };
  }

  function fillCandidate(node, routeKey, selectedKey, index) {
    const route = routeCatalog[routeKey];
    if (!node || !route) return;
    const initial = qs(".provider-initial", node);
    const title = qs("strong", node);
    const meta = qs("small", node);
    const candidateState = qs(".candidate-state", node);

    if (initial) {
      initial.textContent = route.initial;
      initial.className = `provider-initial ${route.tone}`;
    }
    if (title) title.textContent = route.model;
    if (meta) meta.textContent = route.provider;

    const selected = routeKey === selectedKey;
    node.classList.toggle("is-selected", selected);
    node.classList.toggle("is-excluded", !selected && index === 2 && !state.allowFallback);
    if (candidateState) {
      candidateState.textContent = selected ? "선택" : (index === 2 ? (state.allowFallback ? "fallback" : "제외") : "후보");
    }
  }

  function previewRoute({ animate = false, revealResponse = false } = {}) {
    const canvas = qs("#route-canvas");
    const response = qs("#route-response");
    const routeResult = chooseRoute();
    const route = routeResult.route;
    const candidates = routeCandidateLayouts[state.preset] || routeCandidateLayouts.code;

    qsa(".candidate", canvas).forEach((node, index) => fillCandidate(node, candidates[index], routeResult.key, index));

    const resultModel = qs("#route-result-model");
    const resultReason = qs("#route-result-reason");
    if (resultModel) resultModel.textContent = route.model;
    if (resultReason) resultReason.textContent = route.reason;

    const summaryItems = qsa("#route-summary > div");
    if (summaryItems[0]) qs("strong", summaryItems[0]).textContent = route.basis;
    if (summaryItems[1]) qs("strong", summaryItems[1]).textContent = route.cost;
    if (summaryItems[2]) {
      const keyValue = qs("strong", summaryItems[2]);
      keyValue.textContent = routeResult.noSafeRoute ? "조건 불충족" : (routeResult.key === "qwen" ? "로컬 연결됨" : "연결됨");
      keyValue.classList.toggle("status-good", !routeResult.noSafeRoute);
    }

    const resultNode = qs(".route-result", canvas);
    if (resultNode) {
      resultNode.classList.toggle("is-no-route", routeResult.noSafeRoute);
      resultNode.style.borderColor = routeResult.noSafeRoute ? "var(--red)" : "var(--accent)";
      resultNode.style.background = routeResult.noSafeRoute ? "var(--red-soft)" : "#fff8f4";
    }

    if (response) {
      response.hidden = !revealResponse;
      response.classList.toggle("is-blocked", routeResult.noSafeRoute);
      const status = qs(".response-status", response);
      const meta = qs(".response-head > span:last-child", response);
      const paragraph = qs("p", response);
      const detailButton = qs("button", response);
      if (routeResult.noSafeRoute) {
        if (status) status.textContent = "요청을 보내지 않았습니다";
        if (meta) meta.textContent = "0 tokens · ₩0";
        if (paragraph) paragraph.textContent = "로컬 전용 조건을 유지하면서 한국어 문서 기능 근거가 있는 연결 경로가 없습니다. 처리 범위를 ‘국내·로컬 우선’으로 바꾸거나 로컬 모델을 추가하세요.";
        if (detailButton) {
          detailButton.textContent = "처리 범위 바꾸기";
          detailButton.dataset.viewLink = "start";
        }
      } else {
        if (status) status.innerHTML = "<span></span> 응답 완료";
        if (meta) meta.textContent = route.key === "qwen" ? "8.9초 · 624 tokens" : "1.8초 · 624 tokens";
        if (paragraph) paragraph.textContent = state.preset === "korean"
          ? "회의에서는 공급 일정 지연과 검수 기준 변경이 핵심 쟁점이었습니다. 결정사항은 8월 7일까지 수정 일정표를 제출하는 것이며, 담당자는 운영팀 김하늘입니다."
          : state.preset === "batch"
            ? "문의는 배송 지연, 결제 오류, 기능 사용법 순으로 많았습니다. 배송 지연 문의가 전체의 42%이며, 동일 문구가 반복된 18건은 하나의 장애 공지로 대응할 수 있습니다."
            : "로그인 콜백에서 세션 복원보다 사용자 프로필 조회가 먼저 실행되는 순서 문제가 의심됩니다. 우선 인증 초기화 순서를 분리하고 실패 재현 테스트를 추가하겠습니다.";
        if (detailButton) {
          detailButton.textContent = "선택 모델과 코드 보기";
          detailButton.dataset.viewLink = "detail";
        }
      }
    }

    if (canvas && animate) {
      canvas.classList.remove("is-routing");
      void canvas.offsetWidth;
      canvas.classList.add("is-routing");
      window.setTimeout(() => canvas.classList.remove("is-routing"), 1000);
    }
    return routeResult;
  }

  function resolveRoute() {
    const routeResult = previewRoute({ animate: true, revealResponse: false });
    const response = qs("#route-response");
    window.setTimeout(() => {
      previewRoute({ revealResponse: true });
      if (response) response.scrollIntoView({ block: "nearest", behavior: "smooth" });
      showToast(routeResult.noSafeRoute ? "안전한 경로가 없어 호출하지 않았습니다." : `${routeResult.route.model} 경로를 선택했습니다.`);
    }, window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 620);
  }

  function showPopover(popover, anchor) {
    qsa(".popover").forEach((item) => { if (item !== popover) item.hidden = true; });
    if (!popover || !anchor) return;
    const rect = anchor.getBoundingClientRect();
    popover.hidden = false;
    popover.style.left = `${Math.min(rect.left, window.innerWidth - 316)}px`;
    popover.style.top = `${Math.min(rect.bottom + 6, window.innerHeight - popover.offsetHeight - 12)}px`;
    const first = qs("button", popover);
    if (first) first.focus();
  }

  function updateScope(scope, label) {
    state.scope = scope;
    const target = qs("#scope-label");
    if (target) target.textContent = label;
    qsa("[data-scope]").forEach((button) => button.classList.toggle("is-active", button.dataset.scope === scope));
    const popover = qs("#scope-popover");
    if (popover) popover.hidden = true;
    previewRoute();
  }

  function updateOptimize(optimize, label) {
    state.optimize = optimize;
    const target = qs("#optimize-label");
    if (target) target.textContent = label;
    qsa("[data-optimize]").forEach((button) => button.classList.toggle("is-active", button.dataset.optimize === optimize));
    const popover = qs("#optimize-popover");
    if (popover) popover.hidden = true;
    previewRoute();
  }

  function filterModels() {
    const query = (qs("#model-search")?.value || "").trim().toLowerCase();
    const activeFilter = qs("#model-filters .is-active")?.dataset.filter || "all";
    let visibleCount = 0;
    qsa("#model-list .model-row").forEach((row) => {
      const text = row.textContent.toLowerCase();
      const tags = (row.dataset.tags || "").split(/\s+/);
      const visible = (!query || text.includes(query)) && (activeFilter === "all" || tags.includes(activeFilter));
      row.hidden = !visible;
      if (visible) visibleCount += 1;
    });
    const empty = qs("#empty-filter");
    if (empty) empty.hidden = visibleCount !== 0;
  }

  function setCode(tabGroup, key, targetId) {
    const sample = codeSamples[tabGroup]?.[key];
    const code = qs(`#${targetId} code`);
    if (sample && code) code.textContent = sample;
  }

  async function copyText(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const area = document.createElement("textarea");
        area.value = text;
        area.setAttribute("readonly", "");
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
      }
      showToast("복사했습니다.");
    } catch (_error) {
      showToast("복사하지 못했습니다. 직접 선택해 주세요.");
    }
  }

  let toastTimer = null;
  function showToast(message) {
    const toast = qs("#toast");
    if (!toast) return;
    toast.textContent = message;
    toast.hidden = false;
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => { toast.hidden = true; }, 2300);
  }

  function openKeyDrawer() {
    const drawer = qs("#key-drawer");
    const backdrop = qs("#drawer-backdrop");
    if (!drawer || !backdrop) return;
    drawer.hidden = false;
    backdrop.hidden = false;
    document.body.style.overflow = "hidden";
    qs("#close-key-drawer")?.focus();
  }

  function closeKeyDrawer() {
    const drawer = qs("#key-drawer");
    const backdrop = qs("#drawer-backdrop");
    if (!drawer || !backdrop) return;
    drawer.hidden = true;
    backdrop.hidden = true;
    document.body.style.overflow = "";
    qs("#key-form").hidden = true;
    qs(".provider-key-list").hidden = false;
    qs("#open-key-drawer")?.focus();
  }

  function showKeyForm(provider) {
    const list = qs(".provider-key-list");
    const form = qs("#key-form");
    if (!list || !form) return;
    list.hidden = true;
    form.hidden = false;
    qs("#key-provider-title").textContent = `${provider} 키`;
    const input = qs("#provider-key-input");
    input.value = "";
    input.focus();
  }

  function hideKeyForm() {
    qs("#key-form").hidden = true;
    qs(".provider-key-list").hidden = false;
    qs("[data-connect-provider]")?.focus();
  }

  function useModel(modelName) {
    state.selectedManualModel = modelName;
    setMode("manual");
    setView("start");
    const direct = qsa("[data-mode]").find((button) => button.dataset.mode === "manual");
    if (direct) {
      const title = qs("strong", direct);
      const description = qs("small", direct);
      if (title) title.textContent = modelName;
      if (description) description.textContent = "직접 선택한 모델로 고정합니다.";
    }
    previewRoute({ animate: true });
    showToast(`${modelName}을 직접 선택했습니다.`);
  }

  function wireEvents() {
    qsa("[data-view-link]").forEach((control) => {
      control.addEventListener("click", (event) => {
        event.preventDefault();
        setView(control.dataset.viewLink, { focusHeading: false });
      });
    });

    qsa("[data-preset]").forEach((button) => button.addEventListener("click", () => setPreset(button.dataset.preset)));
    qsa("[data-mode]").forEach((button) => button.addEventListener("click", () => setMode(button.dataset.mode)));

    qs("#scope-control")?.addEventListener("click", (event) => showPopover(qs("#scope-popover"), event.currentTarget));
    qs("#optimize-control")?.addEventListener("click", (event) => showPopover(qs("#optimize-popover"), event.currentTarget));
    qsa("[data-scope]").forEach((button) => button.addEventListener("click", () => updateScope(button.dataset.scope, qs("strong", button).textContent)));
    qsa("[data-optimize]").forEach((button) => button.addEventListener("click", () => updateOptimize(button.dataset.optimize, qs("strong", button).textContent)));

    qs("#fallback-toggle")?.addEventListener("change", (event) => {
      state.allowFallback = event.currentTarget.checked;
      previewRoute();
    });
    qs("#resolve-route")?.addEventListener("click", resolveRoute);
    qs("#replay-route")?.addEventListener("click", () => previewRoute({ animate: true, revealResponse: !qs("#route-response")?.hidden }));

    qs("#task-input")?.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        resolveRoute();
      }
    });

    qs("#model-search")?.addEventListener("input", filterModels);
    qsa("[data-filter]").forEach((button) => button.addEventListener("click", () => {
      qsa("[data-filter]").forEach((item) => item.classList.toggle("is-active", item === button));
      filterModels();
    }));
    qsa("[data-model-detail]").forEach((button) => button.addEventListener("click", () => setView("detail")));
    qsa("[data-use-model]").forEach((button) => button.addEventListener("click", () => useModel(button.dataset.useModel)));

    qs("#detail-run")?.addEventListener("click", () => {
      const result = qs("#detail-result");
      if (result) result.hidden = false;
      showToast("합성 응답을 표시했습니다.");
    });

    qsa("[data-code-tab]").forEach((button) => button.addEventListener("click", () => {
      qsa("[data-code-tab]").forEach((item) => item.classList.toggle("is-active", item === button));
      setCode("quick", button.dataset.codeTab, "quick-code");
    }));
    qsa("[data-dev-code]").forEach((button) => button.addEventListener("click", () => {
      qsa("[data-dev-code]").forEach((item) => item.classList.toggle("is-active", item === button));
      setCode("developer", button.dataset.devCode, "developer-code");
    }));

    qsa("[data-copy-target]").forEach((button) => button.addEventListener("click", () => {
      const target = qs(`#${button.dataset.copyTarget}`);
      if (target) copyText(target.textContent.trim());
    }));
    qsa("[data-copy-text]").forEach((button) => button.addEventListener("click", () => copyText(button.dataset.copyText)));

    qs("#open-key-drawer")?.addEventListener("click", openKeyDrawer);
    qs("#close-key-drawer")?.addEventListener("click", closeKeyDrawer);
    qs("#drawer-backdrop")?.addEventListener("click", closeKeyDrawer);
    qsa("[data-connect-provider]").forEach((button) => button.addEventListener("click", () => showKeyForm(button.dataset.connectProvider)));
    qs("#key-form-back")?.addEventListener("click", hideKeyForm);
    qs("#key-form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const input = qs("#provider-key-input");
      const provider = qs("#key-provider-title").textContent.replace(/ 키$/, "");
      if (!input.value.trim()) {
        input.focus();
        showToast("키를 입력해 주세요.");
        return;
      }
      input.value = "";
      hideKeyForm();
      showToast(`${provider} 연결 상태를 합성으로 표시했습니다.`);
    });

    qsa(".period-selector button").forEach((button) => button.addEventListener("click", () => {
      qsa(".period-selector button").forEach((item) => item.classList.toggle("is-active", item === button));
    }));

    document.addEventListener("click", (event) => {
      qsa(".popover").forEach((popover) => {
        const anchorId = popover.id === "scope-popover" ? "scope-control" : "optimize-control";
        if (!popover.hidden && !popover.contains(event.target) && event.target !== qs(`#${anchorId}`)) popover.hidden = true;
      });
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        qsa(".popover").forEach((popover) => { popover.hidden = true; });
        if (!qs("#key-drawer")?.hidden) closeKeyDrawer();
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setView("models");
        window.setTimeout(() => qs("#model-search")?.focus(), 20);
      }
    });

    window.addEventListener("resize", () => qsa(".popover").forEach((popover) => { popover.hidden = true; }));
  }

  wireEvents();
  setMode("auto");
  setPreset("code");
  previewRoute();
})();
