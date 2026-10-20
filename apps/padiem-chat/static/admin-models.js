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
    authorized: false, writeEnabled: false, pendingReceipt: null, pendingRequest: 0,
    routeWriteEnabled: false, routeRows: [], routeStatic: null, routeRevision: 0,
    routeReceipt: null, routeRequest: 0, routeConnected: false,
  };
  const ROUTE_PRODUCTS = Object.freeze(["chat", "claw", "b66"]);
  const ROUTE_TIERS = Object.freeze(["FREE", "PLUS", "PRO", "MAX"]);

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
    state.pendingReceipt = null;
    $("applyBtn").hidden = true;
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

  // #2505: Chat and Claw are two screens of one AI product, so the central
  // grade setting they share is stored and read once.
  const SHARED_ROUTE_PRODUCT = "chat";
  const SHARED_ROUTE_LABEL = "Chat·Claw 공통";

  function sharedRouteRows() {
    // One row per grade: the shared row wins, and a legacy alias row still
    // governs its own grade until a shared row is written for that grade.
    const shared = new Map();
    const alias = new Map();
    for (const row of state.routeRows) {
      if (row.product === SHARED_ROUTE_PRODUCT) shared.set(row.tier, row);
      else if (row.product === "claw" && !alias.has(row.tier)) alias.set(row.tier, row);
    }
    const rows = new Map(shared);
    for (const [tier, row] of alias) {
      if (!rows.has(tier)) rows.set(tier, row);
    }
    return [...rows.values()];
  }

  function routeRowsFor(productId) {
    if (productId === "chat" || productId === "claw") return sharedRouteRows();
    return state.routeRows.filter((row) => row.product === productId);
  }

  function routeTile(productId, modelId, fallback, label) {
    // The central per-product/per-grade route ledger is the runtime-enforced
    // placement of a model. Show the administrator where this exact model is
    // actually assigned instead of a fixed "not wired" label.
    const name = label || PRODUCTS[productId].name;
    const rows = routeRowsFor(productId);
    const placed = rows.filter((row) =>
      row.primary_model_id === modelId || row.fallback_model_id === modelId);
    const note = fallback && fallback.detail ? " · " + fallback.detail : "";
    if (!placed.length) {
      if (!rows.length) return fallback;
      return {
        name: name,
        status: "미배정",
        detail: "중앙 등급별 실행 경로에 이 모델 배정 없음" + note,
        kind: "unknown",
      };
    }
    if (fallback && fallback.policy_blocked) {
      // An explicit product-policy OFF stays visible: a central route
      // assignment never hides a blocked model.
      return {
        name: name,
        status: fallback.status,
        detail: "중앙 등급별 실행 경로 배정 있음 · " + fallback.detail,
        kind: "blocked",
      };
    }
    return {
      name: name,
      status: placed.map((row) => row.tier + (
        row.primary_model_id === modelId ? " 기본" : " 폴백")).join(" · "),
      detail: "중앙 등급별 실행 경로 배정" + note,
      kind: fallback && fallback.kind === "blocked" ? "blocked" : "ready",
    };
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
    const central = state.routeConnected ?
      {name: "중앙 정책", status: "실행 경로 " + state.routeRevision,
        detail: "등급별 실행 경로 원장 연결", kind: "ready"} :
      {name: "중앙 정책", status: "미연결", detail: "등급별 정책 조회 전", kind: "unknown"};
    const result = [
      b14,
      central,
      routeTile("chat", modelId, {
        name: "Padiem Chat", status: "미연결",
        detail: "실제 배정 여부 미확인", kind: "unknown"}),
      routeTile("claw", modelId, {
        name: SHARED_ROUTE_LABEL, status: "미연결",
        detail: "Chat·Claw 등급 배정 공유", kind: "unknown"}, SHARED_ROUTE_LABEL),
    ];
    const b66 = state.products?.b66;
    let b66Tile;
    if (b66?.status !== "connected") {
      b66Tile = {name: "B66 견적", status: "조회 불가", detail: "D1 정책 조회 불가", kind: "unknown"};
    } else if (b66.disabled_models?.includes(modelId)) {
      b66Tile = {name: "B66 견적", status: "차단됨", detail: "B66 정책의 모델 OFF",
        kind: "blocked", policy_blocked: true};
    } else if (b66.active === false) {
      b66Tile = {name: "B66 견적", status: "정책 비활성", detail: "정책 active=false", kind: "unknown"};
    } else {
      const tiers = Object.entries(b66.tiers || {})
        .filter(([, ids]) => Array.isArray(ids) && ids.includes(modelId))
        .map(([tier]) => tier);
      b66Tile = {
        name: "B66 견적", status: tiers.length ? tiers.join(" · ") : "미배정",
        detail: tiers.length ? "B66 정책의 등급 배정; 최종 실행은 별도 검증" : "해당 모델의 등급 배정 없음",
        kind: tiers.length ? "ready" : "blocked",
      };
    }
    result.push(routeTile("b66", modelId, b66Tile));
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
      const isConnected = data.status === "connected" || data.status === "stored_only";
      if (isConnected) connected++;
      const card = node("div", null, "source-card");
      card.append(node("strong", product.name));
      card.append(node("span", data.status === "stored_only" ? "◌ 저장 원장만 연결" :
        isConnected ? "● 정책 조회됨" :
        data.status === "not_wired" ? "◌ 아직 미연결" : "◌ 조회 불가",
        isConnected ? "connected" : "unknown"));
      card.append(node("small", SOURCES[id]));
      if (id === "central" && data.status === "stored_only") card.append(
        node("small", "Revision " + data.revision + " · 실제 실행 미적용"));
      if (id === "b66" && isConnected) card.append(
        node("small", "Revision " + data.revision + (data.active ? " · 활성" : " · 비활성")));
      root.append(card);
    }
    $("sourceCount").textContent = connected + " / 5 연결";
    $("flowCentral").textContent = state.products?.central?.status === "stored_only" ?
      "원장 연결 · 미적용" : "미연결";
    $("flowProducts").textContent = connected + "/5 정책 조회";
  }

  function updateModeBadge() {
    $("modeBadge").textContent = state.routeWriteEnabled ? "실행 경로 저장 가능" :
      state.writeEnabled ? "정책 원장 저장 가능" : "미리보기 전용";
  }

  function routeConfigured(product, tier) {
    // One shared grade setting: the Claw column reads the same central row
    // the Chat column reads.
    if (product === "chat" || product === "claw") {
      return sharedRouteRows().find((row) => row.tier === tier) || null;
    }
    return state.routeRows.find((row) => row.product === product && row.tier === tier) || null;
  }

  function routeStatic(product, tier) {
    const value = state.routeStatic?.[product]?.[tier];
    return value && typeof value.primary_model_id === "string" ? value : null;
  }

  function modelName(modelId) {
    if (!modelId) return "없음";
    return state.catalog.find((row) => row.model_id === modelId)?.name || modelId;
  }

  function fillModelSelect(select, selected, allowNone) {
    select.replaceChildren();
    if (allowNone) {
      const empty = node("option", "없음");
      empty.value = "";
      select.append(empty);
    }
    if (selected && !state.selectableIds.has(selected)) {
      const missing = node("option", (modelName(selected)) + " (선택 불가)");
      missing.value = selected;
      select.append(missing);
    }
    for (const model of state.catalog.filter((row) => state.selectableIds.has(row.model_id))) {
      const option = node("option", model.name + " · " + model.model_id);
      option.value = model.model_id;
      select.append(option);
    }
    select.value = selected || (allowNone ? "" : (select.options[0]?.value || ""));
  }

  function clearRoutePreview() {
    state.routeReceipt = null;
    $("routeApplyBtn").hidden = true;
    $("routePreviewResult").hidden = true;
    $("routePreviewResult").replaceChildren();
    $("routePreviewResult").className = "preview";
  }

  function renderRouteForm() {
    const productSelect = $("routeProduct");
    if (!productSelect.options.length) {
      for (const key of ROUTE_PRODUCTS) {
        const option = node("option", key === "claw" ? SHARED_ROUTE_LABEL : PRODUCTS[key].name);
        option.value = key;
        productSelect.append(option);
      }
    }
    const product = productSelect.value || ROUTE_PRODUCTS[0];
    const tier = $("routeTier").value || ROUTE_TIERS[0];
    const configured = routeConfigured(product, tier);
    const effective = configured || routeStatic(product, tier);
    $("routeEnabled").checked = configured ? configured.enabled : true;
    fillModelSelect($("routePrimary"), effective?.primary_model_id || null, false);
    fillModelSelect($("routeFallback"), effective?.fallback_model_id || null, true);
    $("routeResetBtn").disabled = !state.routeWriteEnabled || !configured;
    $("routePreviewBtn").disabled = !state.routeWriteEnabled;
  }

  function renderRouteTable() {
    const root = $("routeTable");
    root.replaceChildren();
    const head = node("div", null, "route-row route-row-head");
    for (const label of ["제품", "등급", "기본 모델", "자동 폴백", "상태"]) head.append(node("span", label));
    root.append(head);
    for (const product of ROUTE_PRODUCTS) {
      for (const tier of ROUTE_TIERS) {
        const configured = routeConfigured(product, tier);
        const effective = configured || routeStatic(product, tier);
        const row = node("button", null, "route-row");
        row.type = "button";
        row.append(node("span", product === "claw" ? SHARED_ROUTE_LABEL : PRODUCTS[product].name), node("span", tier));
        row.append(node("span", modelName(effective?.primary_model_id)));
        row.append(node("span", modelName(effective?.fallback_model_id)));
        const status = !configured ? "정적 기본값" : configured.enabled ? "중앙 설정" : "사용 안 함";
        row.append(node("span", status, !configured ? "static" : configured.enabled ? "central" : "off"));
        row.addEventListener("click", () => {
          $("routeProduct").value = product;
          $("routeTier").value = tier;
          clearRoutePreview();
          renderRouteForm();
        });
        root.append(row);
      }
    }
  }

  function renderRouteEvents(events) {
    const root = $("routeEvents");
    root.replaceChildren();
    if (!Array.isArray(events) || !events.length) {
      root.append(node("p", "저장된 경로 변경 이력이 없습니다.", "placeholder"));
      return;
    }
    for (const entry of events.slice(0, 12)) {
      const row = node("div", null, "source-card");
      row.append(node("strong", "리비전 " + entry.revision + " · " +
        (entry.operation === "rollback" ? "롤백" : "저장")));
      row.append(node("small", String(entry.at || "")));
      root.append(row);
    }
  }

  function renderRoutePreview(result) {
    const root = $("routePreviewResult");
    root.replaceChildren();
    root.className = "preview";
    root.hidden = false;
    root.append(node("strong", "✓ 실행 경로 변경안 검증 완료"),
      node("small", "아직 저장되지 않았습니다 · 저장하면 다음 요청부터 적용됩니다"));
    const list = node("ul");
    for (const item of (result.diff || [])) {
      const before = item.previous ?
        (item.previous.enabled ? item.previous.primary_model_id +
          (item.previous.fallback_model_id ? " / " + item.previous.fallback_model_id : "") : "사용 안 함") :
        "정적 기본값";
      const after = item.next ?
        (item.next.enabled ? item.next.primary_model_id +
          (item.next.fallback_model_id ? " / " + item.next.fallback_model_id : "") : "사용 안 함") :
        "정적 기본값";
      list.append(node("li", (PRODUCTS[item.product]?.name || item.product) + " · " +
        item.tier + " · " + before + " → " + after));
    }
    root.append(list);
  }

  async function loadRoutes() {
    const seq = ++state.routeRequest;
    state.routeWriteEnabled = false;
    state.routeRows = [];
    state.routeStatic = null;
    state.routeRevision = 0;
    state.routeConnected = false;
    clearRoutePreview();
    $("routeStatus").textContent = "확인 중";
    $("routeTable").replaceChildren(node("p", "실행 경로를 확인하고 있습니다.", "placeholder"));
    $("routeEvents").replaceChildren(node("small", "이력 확인 중"));
    $("routePreviewBtn").disabled = true;
    $("routeResetBtn").disabled = true;
    try {
      const result = await getJSON("/api/admin/models/routes");
      if (seq !== state.routeRequest) return;
      if (!Array.isArray(result.routes) || !Number.isSafeInteger(result.revision) ||
          !result.static || result.runtime_enforced !== true) throw new Error("invalid_routes");
      state.routeRows = result.routes;
      state.routeStatic = result.static;
      state.routeRevision = result.revision;
      state.routeConnected = true;
      state.routeWriteEnabled = result.write_enabled === true;
      $("routeStatus").textContent = "실행 적용 · 리비전 " + result.revision;
      renderRouteForm();
      renderRouteTable();
      renderRouteEvents(result.events);
      updateModeBadge();
    } catch (err) {
      if (seq !== state.routeRequest) return;
      $("routeStatus").textContent = "사용 불가";
      $("routeTable").replaceChildren(node("p",
        "실행 경로 원장을 사용할 수 없습니다. (" + String(err.message) + ")", "placeholder"));
      $("routeEvents").replaceChildren(node("small", "이력 조회 불가"));
      updateModeBadge();
    }
  }

  async function previewRoute(action) {
    if (!state.routeWriteEnabled) return;
    const product = $("routeProduct").value;
    const tier = $("routeTier").value;
    const body = action === "reset" ? {product, tier, action: "reset"} : {
      product, tier, action: "set",
      primary_model_id: $("routePrimary").value || null,
      fallback_model_id: $("routeFallback").value || null,
      enabled: $("routeEnabled").checked,
    };
    if (action === "set" && !body.primary_model_id) {
      alertMessage("기본 모델을 선택해 주세요."); return;
    }
    if (action === "set" && body.primary_model_id === body.fallback_model_id) {
      alertMessage("자동 폴백은 기본 모델과 다른 모델이어야 합니다."); return;
    }
    const seq = ++state.routeRequest;
    $("routePreviewBtn").disabled = true;
    $("routeResetBtn").disabled = true;
    clearRoutePreview();
    try {
      const result = await getJSON("/api/admin/models/route-preview", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body),
      });
      if (seq !== state.routeRequest) return;
      if (result.applied !== false || result.persisted !== false ||
          result.runtime_enforced !== true || typeof result.confirmation_receipt !== "string") {
        throw new Error("invalid_route_preview");
      }
      renderRoutePreview(result);
      state.routeReceipt = result.confirmation_receipt;
      $("routeApplyBtn").hidden = false;
      alertMessage("");
    } catch (err) {
      if (seq !== state.routeRequest) return;
      $("routePreviewResult").hidden = false;
      $("routePreviewResult").className = "preview error";
      $("routePreviewResult").replaceChildren(node("strong", "경로 미리보기 실패"),
        node("small", String(err.message)));
    } finally {
      if (seq === state.routeRequest) {
        $("routePreviewBtn").disabled = !state.routeWriteEnabled;
        $("routeResetBtn").disabled = !state.routeWriteEnabled ||
          !routeConfigured($("routeProduct").value, $("routeTier").value);
      }
    }
  }

  async function applyRoute() {
    if (!state.routeWriteEnabled || !state.routeReceipt) return;
    if (!window.confirm("등급별 실행 경로를 저장하시겠습니까? 다음 Chat · Claw · B66 요청부터 실제 모델 선택이 변경됩니다.")) return;
    const receipt = state.routeReceipt;
    $("routeApplyBtn").disabled = true;
    try {
      const data = await getJSON("/api/admin/models/route-apply", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({confirmation_receipt: receipt}),
      });
      if (data.persisted !== true || data.runtime_enforced !== true) {
        throw new Error("invalid_route_commit");
      }
      await load();
      alertMessage("실행 경로 리비전 " + data.revision + " 저장 완료 · 다음 요청부터 적용됩니다", "success");
    } catch (err) {
      clearRoutePreview();
      alertMessage("실행 경로 저장 실패: " + String(err.message));
    } finally {
      $("routeApplyBtn").disabled = false;
    }
  }

  function renderPreview(result) {
    const root = $("previewResult");
    root.replaceChildren();
    root.className = "preview";
    root.hidden = false;
    root.append(node("strong", "✓ 변경안 검증 완료"),
      node("small", state.writeEnabled ? "아직 저장되지 않았습니다 · 허용·차단 원장 전용, 실행 경로 미적용" : "저장 및 운영 반영 없음"));
    const list = node("ul");
    for (const item of (result.diff || result.targets || [])) {
      const product = item.product || item.product_id;
      const before = item.previous ? " (" + ACTIONS[item.previous] + " →)" : "";
      list.append(node("li", (PRODUCTS[product]?.name || product) + " · " +
        item.tier + " · " + before + " " + ACTIONS[item.action]));
    }
    root.append(list);
    if (state.writeEnabled && typeof result.confirmation_receipt === "string" &&
        result.confirmation_receipt.length > 40) {
      state.pendingReceipt = result.confirmation_receipt;
      $("applyBtn").hidden = false;
    }
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
      const result = await getJSON(state.writeEnabled ?
        "/api/admin/models/change-preview" : "/api/admin/models/preview", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({model_id: state.selected.model_id, targets}),
      });
      if (seq !== state.pendingRequest) return;
      if (result.applied !== false || result.persisted !== false ||
          result.runtime_enforced === true ||
          !(Array.isArray(result.targets) || Array.isArray(result.diff))) {
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
    state.writeEnabled = false;
    $("policyHistory").hidden = true;
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
      const me = await getJSON("/api/admin/models/me");
      if (seq !== state.pendingRequest) return;
      const result = await getJSON("/api/admin/models/snapshot");
      if (seq !== state.pendingRequest) return;
      if (!["read_only", "stored_only"].includes(result.mode) ||
          !Array.isArray(result.b14?.models)) throw new Error("invalid_snapshot");
      state.writeEnabled = me.write_enabled === true && result.write_enabled === true &&
        result.products?.central?.status === "stored_only";
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
      updateModeBadge();
      $("policyHistory").hidden = !state.writeEnabled;
      $("writeNote").firstChild.textContent = state.writeEnabled ?
        "허용·차단 규칙은 저장 원장에만 기록되며 실행 경로에는 아직 적용되지 않습니다. " :
        "미리보기 단계에서는 설정이 바뀌지 않습니다. ";
      renderCatalog();
      renderSources();
      renderPlacement();
      await loadRoutes();
      // The central route ledger is the runtime-enforced per-product placement,
      // so the placement panel is projected again once it is known.
      renderPlacement();
      if (state.writeEnabled) await loadAudit();
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
      $("routeStatus").textContent = "확인 불가";
      $("routeTable").replaceChildren(node("p", "상태를 확인할 수 없습니다.", "placeholder"));
      $("routeEvents").replaceChildren(node("small", "이력 조회 불가"));
      alertMessage(code === "authentication_required" ? "로그인 후 이용할 수 있습니다." :
        code === "global_model_admin_forbidden" ? "중앙 관리자 권한이 없습니다." :
        code === "central_admin_not_configured" ? "중앙 관리자 권한이 아직 설정되지 않았습니다." :
        "관리 데이터를 불러오지 못했습니다. (" + code + ")");
    }
  }

  async function loadAudit() {
    const root = $("policyAudit");
    root.replaceChildren(node("small", "이력 확인 중"));
    try {
      const data = await getJSON("/api/admin/models/audit");
      if (!Array.isArray(data.events)) throw new Error("invalid_audit");
      root.replaceChildren();
      if (!data.events.length) root.append(node("p", "저장된 변경 이력이 없습니다.", "placeholder"));
      for (const entry of data.events.slice(0, 12)) {
        const row = node("div", null, "source-card");
        row.append(node("strong", "리비전 " + entry.revision + " · " +
          (entry.operation === "rollback" ? "롤백" : "저장")));
        row.append(node("small", String(entry.at || "")));
        root.append(row);
      }
    } catch (err) {
      root.replaceChildren(node("small", "이력 조회 불가: " + String(err.message)));
    }
  }

  async function applyChange() {
    if (!state.writeEnabled || !state.pendingReceipt) return;
    if (!window.confirm("선택한 허용·차단 규칙을 D1 원장에 저장하시겠습니까? 이 원장은 아직 제품 실행에 적용되지 않습니다.")) return;
    const receipt = state.pendingReceipt;
    $("applyBtn").disabled = true;
    try {
      const data = await getJSON("/api/admin/models/change-apply", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({confirmation_receipt: receipt}),
      });
      if (data.persisted !== true || data.runtime_enforced !== false) {
        throw new Error("invalid_commit");
      }
      await load();
      alertMessage("정책 리비전 " + data.revision + " 저장 완료 · 실제 제품 실행은 미적용", "success");
    } catch (err) {
      clearPreview();
      alertMessage("정책 저장 실패: " + String(err.message));
    } finally {
      $("applyBtn").disabled = false;
    }
  }

  async function rollbackPreview() {
    if (!state.writeEnabled) return;
    const revision = Number($("rollbackRevision").value);
    if (!Number.isSafeInteger(revision) || revision < 0) {
      alertMessage("유효한 롤백 리비전을 입력해 주세요."); return;
    }
    clearPreview();
    try {
      const result = await getJSON("/api/admin/models/rollback-preview", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({target_revision: revision}),
      });
      renderPreview(result);
      alertMessage("");
    } catch (err) {
      alertMessage("롤백 미리보기 실패: " + String(err.message));
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
  $("applyBtn").addEventListener("click", applyChange);
  $("rollbackPreviewBtn").addEventListener("click", rollbackPreview);
  $("routeProduct").addEventListener("change", () => { clearRoutePreview(); renderRouteForm(); });
  $("routeTier").addEventListener("change", () => { clearRoutePreview(); renderRouteForm(); });
  $("routePreviewBtn").addEventListener("click", () => previewRoute("set"));
  $("routeResetBtn").addEventListener("click", () => previewRoute("reset"));
  $("routeApplyBtn").addEventListener("click", applyRoute);
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
  renderRouteForm();
  load();
})();