/* #4428 S0 compact operator UI; strictly READ-ONLY + server-validated preview. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const PRODUCTS = Object.freeze({
    central: {name: "중앙 정책", icon: "target"},
    chat: {name: "Padiem Chat", icon: "message"},
    claw: {name: "Claw", icon: "terminal"},
    b66: {name: "B66 견적", icon: "file"},
    "b14-router": {name: "B14 Router", icon: "route"},
  });
  const SOURCES = Object.freeze({
    central: "Control Plane", chat: "Chat 등급 라우팅", claw: "B14 선택 목록",
    b66: "B66 회원 D1", "b14-router": "B14 외부 API",
  });
  const ACTIONS = Object.freeze({allow: "허용", block: "차단", inherit: "상속"});
  const state = {
    catalog: [], products: null, selected: null,
    selectableIds: new Set(), fullInventory: false,
    authorized: false, pendingRequest: 0,
  };

  function node(tag, value, className) {
    const el = document.createElement(tag);
    if (value !== undefined && value !== null) el.textContent = String(value);
    if (className) el.className = className;
    return el;
  }

  const ICON_STROKES = Object.freeze({
    target: ["circle|12,12,9", "circle|12,12,4"],
    message: ["path|M21 11.5a8.5 8.5 0 0 1-8.5 8.5 9.3 9.3 0 0 1-4-.9L3 21l1.9-5.5a9.3 9.3 0 0 1-.9-4A8.5 8.5 0 0 1 12.5 3a8.5 8.5 0 0 1 8.5 8.5Z"],
    terminal: ["rect|3,4,18,16,2", "path|m7 9 3 3-3 3", "path|M12 15h5"],
    file: ["path|M8 3h8l4 4v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h3", "path|M15 3v5h5M8 12h8M8 16h8"],
    route: ["circle|6,17,2", "circle|18,6,2", "path|M8 17h6a4 4 0 0 0 4-4V8"],
  });

  function productIcon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("class", "product-icon");
    svg.setAttribute("aria-hidden", "true");
    for (const spec of ICON_STROKES[name] || []) {
      const [kind, coords] = spec.split("|");
      const child = document.createElementNS("http://www.w3.org/2000/svg", kind);
      if (kind === "path") {
        child.setAttribute("d", coords);
      } else if (kind === "circle") {
        const [cx, cy, r] = coords.split(",");
        child.setAttribute("cx", cx);
        child.setAttribute("cy", cy);
        child.setAttribute("r", r);
      } else if (kind === "rect") {
        const [x, y, width, height, rx] = coords.split(",");
        for (const [key, value] of Object.entries({x, y, width, height, rx})) {
          child.setAttribute(key, value);
        }
      }
      svg.append(child);
    }
    return svg;
  }

  function alertMessage(value, variant = "error") {
    const notice = $("accessNotice");
    notice.hidden = !value;
    notice.className = "notice " + variant;
    notice.textContent = value || "";
  }

  function chosenAction() {
    return document.querySelector('input[name="action"]:checked')?.value || "allow";
  }

  function chosenTargets() {
    return Array.from($("targetGrid").querySelectorAll('input[type="checkbox"]:checked'))
      .map((input) => ({
        product_id: input.value, tier: $("tierSelect").value, action: chosenAction(),
      }));
  }

  function clearPreview() {
    $("previewResult").hidden = true;
    $("previewResult").replaceChildren();
    $("previewResult").className = "preview";
  }

  function canPreview() {
    return state.authorized && state.selected &&
      state.selectableIds.has(state.selected.model_id) &&
      state.selected.owner_excluded !== true && state.selected.b14_enabled !== false;
  }

  function updateSelection() {
    state.pendingRequest += 1;
    const selected = chosenTargets().length;
    $("targetCount").textContent = String(selected);
    $("previewBtn").disabled = !(canPreview() && selected);
    clearPreview();
  }

  function renderTargets() {
    const root = $("targetGrid");
    root.replaceChildren();
    for (const [key, product] of Object.entries(PRODUCTS)) {
      const label = node("label", null, "target");
      const name = node("span", null, "target-title");
      name.append(productIcon(product.icon), node("span", product.name));
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = key;
      checkbox.setAttribute("aria-label", product.name + " 변경 대상");
      const slider = node("span", null, "switch-track");
      slider.setAttribute("aria-hidden", "true");
      checkbox.addEventListener("change", updateSelection);
      label.append(name, checkbox, slider);
      root.append(label);
    }
  }

  function chooseModel(modelId) {
    state.selected = state.catalog.find((m) => m.model_id === modelId) || null;
    $("selectedModel").textContent = state.selected?.name || "왼쪽에서 모델을 선택하세요";
    $("selectedId").textContent = state.selected?.model_id || "미선택";
    $("editorForm").disabled = !canPreview();
    renderCatalog();
    renderPlacement();
    updateSelection();
  }

  function renderCatalog() {
    const root = $("modelList");
    root.replaceChildren();
    const query = $("modelSearch").value.trim().toLowerCase();
    const models = state.catalog.filter((m) =>
      m.model_id.toLowerCase().includes(query) || m.name.toLowerCase().includes(query));
    if (!models.length) {
      root.append(node("p", state.catalog.length ? "검색 결과가 없습니다." :
        "선택 가능한 모델이 없습니다.", "placeholder"));
      return;
    }
    for (const model of models) {
      const row = node("button", null, "model-item");
      row.type = "button";
      const selected = state.selected?.model_id === model.model_id;
      row.setAttribute("aria-pressed", String(selected));
      row.classList.toggle("model-inactive", model.b14_enabled === false || model.owner_excluded === true);
      const words = node("span", null, "model-words");
      words.append(node("strong", model.name), node("small", model.model_id));
      const status = model.owner_excluded === true ? "제외" :
        model.b14_enabled === false ? "OFF" : state.fullInventory ? "ON" : "";
      row.append(node("span", "●", "model-dot"), words);
      if (status) row.append(node("span", status, "model-state"));
      row.append(node("span", selected ? "✓" : "›", "model-chevron"));
      row.addEventListener("click", () => chooseModel(model.model_id));
      root.append(row);
    }
  }

  function positions() {
    const modelId = state.selected?.model_id;
    if (!modelId) return [];
    const b14 = state.selected?.owner_excluded === true ?
      {name: "B14 공통", status: "선택 제외", detail: "B14 소유자 정책상 제외된 모델", kind: "blocked"} :
      state.selected?.b14_enabled === false ?
      {name: "B14 공통", status: "OFF", detail: "B14 등록은 됐지만 활성 목록에서 제외됨", kind: "blocked"} :
      state.selectableIds.has(modelId) ?
      {name: "B14 공통", status: "조회됨", detail: "B14 선택 가능 목록에 있음; 실제 실행 성공과 별개", kind: "ready"} :
      {name: "B14 공통", status: "미확인", detail: "제품 선택 가능 여부 확인 필요", kind: "unknown"};
    const result = [
      b14,
      {name: "중앙 정책", status: "미연결", detail: "등급별 정책 조회 전", kind: "unknown"},
      {name: "Padiem Chat", status: "미연결", detail: "실제 배정 여부 미확인", kind: "unknown"},
      {name: "Claw", status: "미연결", detail: "제품별 최종 실행 허용 미확인", kind: "unknown"},
    ];
    const b66 = state.products?.b66;
    if (b66?.status !== "connected") {
      result.push({name: "B66 견적", status: "조회 불가", detail: "D1 정책 조회 불가", kind: "unknown"});
    } else if (b66.disabled_models?.includes(modelId)) {
      result.push({name: "B66 견적", status: "차단됨", detail: "B66 정책의 모델 OFF", kind: "blocked"});
    } else if (b66.active === false) {
      result.push({name: "B66 견적", status: "정책 비활성", detail: "정책 active=false", kind: "unknown"});
    } else {
      const tiers = Object.entries(b66.tiers || {})
        .filter(([, ids]) => Array.isArray(ids) && ids.includes(modelId))
        .map(([tier]) => tier);
      result.push({
        name: "B66 견적", status: tiers.length ? tiers.join(" · ") : "미배정",
        detail: tiers.length ? "B66 정책의 등급 배정; 최종 실행은 별도 검증" : "해당 모델의 등급 배정 없음",
        kind: tiers.length ? "ready" : "blocked",
      });
    }
    result.push({name: "B14 Router", status: "미연결", detail: "외부 API 상품 정책 조회 전", kind: "unknown"});
    return result;
  }

  function renderPlacement() {
    const root = $("modelPlacement");
    root.replaceChildren();
    if (!state.authorized || !state.selected) {
      root.append(node("p", "모델을 선택해 주세요.", "placeholder"));
      return;
    }
    for (const p of positions()) {
      const tile = node("div", null, "placement-item " + p.kind);
      const title = node("strong", p.name);
      const status = node("span", p.status, "position-status");
      status.title = p.detail;
      tile.append(title, status);
      root.append(tile);
    }
  }

  function renderSources() {
    const root = $("sourceList");
    root.replaceChildren();
    let connected = 0;
    for (const [id, product] of Object.entries(PRODUCTS)) {
      const data = state.products?.[id] || {status: "unavailable"};
      const isConnected = data.status === "connected";
      if (isConnected) connected++;
      const card = node("div", null, "source-card");
      card.append(node("strong", product.name));
      card.append(node("span", isConnected ? "● 정책 조회됨" :
        data.status === "not_wired" ? "◌ 아직 미연결" : "◌ 조회 불가",
        isConnected ? "connected" : "unknown"));
      card.append(node("small", SOURCES[id]));
      if (id === "b66" && isConnected) card.append(
        node("small", "Revision " + data.revision + (data.active ? " · 활성" : " · 비활성")));
      root.append(card);
    }
    $("sourceCount").textContent = connected + " / 5 연결";
    $("flowCentral").textContent = "미연결";
    $("flowProducts").textContent = connected + "/5 정책 조회";
  }

  function renderPreview(result) {
    const root = $("previewResult");
    root.replaceChildren();
    root.className = "preview";
    root.hidden = false;
    root.append(node("strong", "✓ 변경안 검증 완료"), node("small", "저장 및 운영 반영 없음"));
    const list = node("ul");
    for (const item of result.targets) {
      list.append(node("li", PRODUCTS[item.product_id].name + " · " +
        item.tier + " · " + ACTIONS[item.action]));
    }
    root.append(list);
  }

  async function getJSON(path, options = {}) {
    const response = await fetch(path, {
      credentials: "same-origin", cache: "no-store",
      headers: {"Accept": "application/json", ...(options.headers || {})}, ...options,
    });
    let data;
    try { data = await response.json(); } catch { data = null; }
    if (!response.ok || data?.ok !== true) {
      throw new Error(typeof data?.error?.code === "string" ? data.error.code : "http_" + response.status);
    }
    return data;
  }

  async function preview() {
    const targets = chosenTargets();
    if (!canPreview() || !targets.length) return;
    const seq = ++state.pendingRequest;
    $("previewBtn").disabled = true;
    clearPreview();
    try {
      const result = await getJSON("/api/admin/models/preview", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({model_id: state.selected.model_id, targets}),
      });
      if (seq !== state.pendingRequest) return;
      if (result.applied !== false || result.persisted !== false ||
          result.dispatch_authorized === true || !Array.isArray(result.targets)) {
        throw new Error("invalid_preview_receipt");
      }
      renderPreview(result);
    } catch (err) {
      if (seq !== state.pendingRequest) return;
      $("previewResult").hidden = false;
      $("previewResult").className = "preview error";
      $("previewResult").replaceChildren(node("strong", "미리보기 실패"), node("small", String(err.message)));
    } finally {
      if (seq === state.pendingRequest) {
        $("previewBtn").disabled = !canPreview() || !chosenTargets().length;
      }
    }
  }

  async function load() {
    const seq = ++state.pendingRequest;
    state.authorized = false;
    state.catalog = [];
    state.selectableIds = new Set();
    state.fullInventory = false;
    state.products = null;
    state.selected = null;
    $("modelCount").textContent = "—";
    $("sourceCount").textContent = "—";
    $("targetCount").textContent = "0";
    $("selectedModel").textContent = "왼쪽에서 모델을 선택하세요";
    $("selectedId").textContent = "미선택";
    $("modelList").replaceChildren(node("p", "모델 목록을 확인하고 있습니다.", "placeholder"));
    $("sourceList").replaceChildren(node("p", "연결 상태 확인 중", "placeholder"));
    $("modelPlacement").replaceChildren(node("p", "모델을 선택해 주세요.", "placeholder"));
    $("editorForm").disabled = true;
    $("previewBtn").disabled = true;
    $("modeBadge").textContent = "접속 확인 중";
    $("catalogStatus").textContent = "확인 중";
    $("flowB14").textContent = "조회 대기";
    $("flowCentral").textContent = "확인 중";
    $("flowProducts").textContent = "확인 중";
    clearPreview();
    alertMessage("");
    try {
      await getJSON("/api/admin/models/me");
      if (seq !== state.pendingRequest) return;
      const result = await getJSON("/api/admin/models/snapshot");
      if (seq !== state.pendingRequest) return;
      if (result.mode !== "read_only" || result.write_enabled !== false ||
          !Array.isArray(result.b14?.models)) throw new Error("invalid_snapshot");
      const complete = result.b14.complete_registration_inventory === true &&
        Array.isArray(result.b14.registered_models);
      state.selectableIds = new Set(result.b14.models.map((m) => m.model_id));
      state.fullInventory = complete;
      state.catalog = complete ? result.b14.registered_models : result.b14.models;
      if (!state.catalog.every((m) => typeof m.model_id === "string" &&
            typeof m.name === "string" &&
            (!complete || (typeof m.b14_enabled === "boolean" &&
             typeof m.owner_excluded === "boolean")))) {
        throw new Error("invalid_snapshot");
      }
      state.products = result.products;
      state.authorized = true;
      $("modelCount").textContent = String(state.catalog.length);
      $("flowB14").textContent = state.catalog.length + (complete ? "개 등록" : "개 선택 가능");
      $("catalogStatus").textContent = complete ?
        "ON " + state.catalog.filter((m) => m.b14_enabled && !m.owner_excluded).length +
        " · OFF " + state.catalog.filter((m) => !m.b14_enabled).length : "일부 목록";
      $("modeBadge").textContent = "미리보기 전용";
      renderCatalog();
      renderSources();
      renderPlacement();
    } catch (err) {
      if (seq !== state.pendingRequest) return;
      const code = String(err.message);
      $("modeBadge").textContent = "접근 제한";
      $("catalogStatus").textContent = "조회 불가";
      $("flowB14").textContent = "조회 불가";
      $("flowCentral").textContent = "확인 불가";
      $("flowProducts").textContent = "확인 불가";
      $("modelList").replaceChildren(node("p", "조회 가능한 모델이 없습니다.", "placeholder"));
      $("modelPlacement").replaceChildren(node("p", "상태를 확인할 수 없습니다.", "placeholder"));
      $("sourceList").replaceChildren(node("p", "접근할 수 없습니다.", "placeholder"));
      alertMessage(code === "authentication_required" ? "로그인 후 이용할 수 있습니다." :
        code === "global_model_admin_forbidden" ? "중앙 관리자 권한이 없습니다." :
        code === "central_admin_not_configured" ? "중앙 관리자 권한이 아직 설정되지 않았습니다." :
        "관리 데이터를 불러오지 못했습니다. (" + code + ")");
    }
  }

  function help(section) {
    const dialog = $("helpDialog");
    const content = $("helpContent");
    for (const item of content.querySelectorAll("h3")) item.hidden = false;
    for (const item of content.querySelectorAll("p")) item.hidden = false;
    // The same accessible help can be opened from any contextual affordance.
    $("helpTitle").textContent = section || "모델 관리자 안내";
    if (!dialog.open) dialog.showModal();
  }

  $("modelSearch").addEventListener("input", renderCatalog);
  $("tierSelect").addEventListener("change", updateSelection);
  for (const input of document.querySelectorAll('input[name="action"]')) {
    input.addEventListener("change", updateSelection);
  }
  $("previewBtn").addEventListener("click", preview);
  $("refreshBtn").addEventListener("click", load);
  $("helpBtn").addEventListener("click", () => help("모델 관리자 안내"));
  $("flowInfoBtn").addEventListener("click", () => help("전체 흐름 안내"));
  $("catalogInfoBtn").addEventListener("click", () => help("모델 목록 안내"));
  $("previewInfoBtn").addEventListener("click", () => help("미리보기 안내"));
  $("closeHelpBtn").addEventListener("click", () => $("helpDialog").close());
  $("helpDialog").addEventListener("click", (event) => {
    if (event.target === $("helpDialog")) $("helpDialog").close();
  });
  renderTargets();
  load();
})();