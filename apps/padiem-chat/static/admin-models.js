/* #4428 PADIEM Model Control Center: live read-only data + scoped preview.
 * No storage writes, local credential access, auto fallback or model dispatch.
 */
(() => {
  "use strict";

  const PRODUCT_NAMES = Object.freeze({
    "central": "중앙 등급 정책",
    "chat": "Padiem Chat",
    "claw": "Claw",
    "b66": "B66 견적서",
    "b14-router": "B14 API Router",
  });
  const SOURCE_NAMES = Object.freeze({
    "central": "Control Plane",
    "chat": "Chat 등급 라우팅",
    "claw": "B14 선택 목록",
    "b66": "B66 회원 D1",
    "b14-router": "B14 외부 API",
  });
  const ACTION_NAMES = Object.freeze({
    allow: "허용 제안", block: "차단 제안", inherit: "상위 정책 따르기",
  });
  const $ = (id) => document.getElementById(id);
  const state = {
    catalog: [], products: null, selected: null, authorized: false,
    pendingRequest: 0, loaded: false,
  };

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = String(text);
    if (className) element.className = className;
    return element;
  }

  function message(text, variant = "") {
    const item = $("accessNotice");
    item.textContent = text;
    item.className = "notice" + (variant ? " " + variant : "");
  }

  function setMode(text) {
    $("modeBadge").textContent = text;
  }

  async function getJSON(path, options = {}) {
    const response = await fetch(path, {
      credentials: "same-origin", cache: "no-store",
      headers: {"Accept": "application/json", ...(options.headers || {})},
      ...options,
    });
    let body;
    try { body = await response.json(); } catch { body = null; }
    if (!response.ok || !body || body.ok !== true) {
      const code = body && body.error && typeof body.error.code === "string"
        ? body.error.code : "http_" + response.status;
      throw new Error(code);
    }
    return body;
  }

  function refreshPreviewText() {
    $("previewResult").replaceChildren(node("span",
      "선택한 대상은 아직 적용되지 않았습니다. '정책 검증 · 미리보기'에서 검토할 수 있습니다.",
      "muted"));
    $("previewResult").className = "preview";
  }

  function chosenTargets() {
    return Array.from($("targetGrid").querySelectorAll('input[type="checkbox"]:checked'))
      .map((input) => ({
        product_id: input.value,
        tier: $("tierSelect").value,
        action: $("actionSelect").value,
      }));
  }

  function updateSelection() {
    // Invalidate a preview HTTP response if the model/targets/tier changed.
    state.pendingRequest += 1;
    $("targetCount").textContent = String(chosenTargets().length);
    $("previewBtn").disabled = !(state.authorized && state.selected && chosenTargets().length > 0);
    refreshPreviewText();
  }

  function renderTargets() {
    const root = $("targetGrid");
    root.replaceChildren();
    Object.entries(PRODUCT_NAMES).forEach(([key, label]) => {
      const item = node("label", null, "target");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = key;
      input.setAttribute("aria-label", label + " 변경 대상");
      input.addEventListener("change", updateSelection);
      const words = node("span");
      words.append(node("span", label));
      words.append(node("small", SOURCE_NAMES[key]));
      item.append(input, words);
      root.append(item);
    });
  }

  function chooseModel(modelId) {
    state.selected = state.catalog.find((row) => row.model_id === modelId) || null;
    $("selectedModel").textContent = state.selected ? state.selected.name : "모델 미선택";
    $("selectedId").textContent = state.selected ? state.selected.model_id : "미선택";
    $("editorForm").disabled = !state.authorized || !state.selected;
    renderCatalog();
    renderPlacement();
    updateSelection();
  }

  function renderCatalog() {
    const root = $("modelList");
    root.replaceChildren();
    const search = $("modelSearch").value.trim().toLowerCase();
    const models = state.catalog.filter((item) =>
      item.model_id.toLowerCase().includes(search) || item.name.toLowerCase().includes(search));
    if (!models.length) {
      root.append(node("p", state.catalog.length ? "일치하는 모델이 없습니다." :
        "B14에서 확인된 선택 가능 모델이 없습니다.", "placeholder"));
      return;
    }
    models.forEach((model) => {
      const row = node("button", null, "model-item");
      row.type = "button";
      row.setAttribute("aria-pressed", String(state.selected?.model_id === model.model_id));
      const title = node("span");
      title.append(node("strong", model.name), node("small", model.model_id));
      row.append(title, node("span", "B14 허용·준비", "ready-tag"));
      row.addEventListener("click", () => chooseModel(model.model_id));
      root.append(row);
    });
  }

  function renderPlacement() {
    const root = $("modelPlacement");
    root.replaceChildren();
    if (!state.authorized || !state.selected) {
      root.append(node("p", "모델을 선택하면 B14·중앙·제품별 실제 배정 위치가 표시됩니다.", "placeholder"));
      return;
    }
    const id = state.selected.model_id;
    const b66 = state.products?.b66;
    const positions = [
      {
        name: "B14 공통 실행",
        status: "B14 허용·준비",
        detail: "owner-allowed/live-ready 선택 목록에 포함 · 전체 등록 카탈로그 아님",
        kind: "ready",
      },
      {
        name: "중앙 등급 정책",
        status: "정책 미연결",
        detail: "Free/Plus/Pro/Max 공통 권한 소스 연동 전",
        kind: "unknown",
      },
      {
        name: "Padiem Chat",
        status: "모델별 배정 미확인",
        detail: "Chat 제품 등급 라우트와 이 모델의 정확한 연결 미검증",
        kind: "unknown",
      },
      {
        name: "Claw",
        status: "모델별 정책 미확인",
        detail: "B14 선택 목록은 공유하지만 최종 Claw 권한 상태는 별도",
        kind: "unknown",
      },
    ];
    if (b66?.status !== "connected") {
      positions.push({
        name: "B66 견적서",
        status: "정책 조회 불가", detail: "B66 D1 모델 정책을 확인하지 못했습니다",
        kind: "unknown",
      });
    } else if (Array.isArray(b66.disabled_models) && b66.disabled_models.includes(id)) {
      positions.push({
        name: "B66 견적서",
        status: "B66 전역 OFF", detail: "B66 관리자 제품 정책에서 해당 모델 차단",
        kind: "blocked",
      });
    } else if (b66.active === true) {
      const assigned = Object.entries(b66.tiers || {})
        .filter(([, models]) => Array.isArray(models) && models.includes(id))
        .map(([tier]) => tier);
      positions.push({
        name: "B66 견적서",
        status: assigned.length ? "배정: " + assigned.join(" · ") : "등급 배정 없음",
        detail: "B66의 저장된 D1 제품 정책 · 실제 사용에는 별도 사용자/실행 검증 필요",
        kind: assigned.length ? "ready" : "blocked",
      });
    } else {
      positions.push({
        name: "B66 견적서",
        status: "등급 정책 비활성",
        detail: "정규 B66 D1 정책이 active=false · 전역 모델 OFF와는 별개",
        kind: "unknown",
      });
    }
    positions.push({
      name: "B14 Router 상품",
      status: "외부 API 상품 정책 미연결",
      detail: "B14 공통 실행 가용성과 Router 상품 구독 권한은 서로 다릅니다",
      kind: "unknown",
    });
    positions.forEach((position) => {
      const row = node("div", null, "placement-item");
      row.append(node("strong", position.name));
      const status = node("span", position.status, "position-status " + position.kind);
      row.append(status);
      row.append(node("small", position.detail));
      root.append(row);
    });
  }

  function renderSources(products) {
    const root = $("sourceList");
    root.replaceChildren();
    let connected = 0;
    Object.entries(PRODUCT_NAMES).forEach(([id, name]) => {
      const data = products?.[id] || {status: "unavailable"};
      const isConnected = data.status === "connected";
      if (isConnected) connected += 1;
      const card = node("div", null, "source-card");
      card.append(node("strong", name));
      card.append(node("span", isConnected ? "연결된 정책 조회" :
        data.status === "not_wired" ? "중앙 정책 연결 예정" : "정책 데이터 확인 불가",
        isConnected ? "connected" : "disabled"));
      card.append(node("small", SOURCE_NAMES[id]));
      if (id === "b66" && isConnected) {
        card.append(node("small", "정책 revision " + data.revision + (data.active ? " · 활성" : " · 비활성")));
      }
      root.append(card);
    });
    $("sourceCount").textContent = String(connected) + " / 5";
    $("flowCentral").textContent = "실제 중앙 설정은 아직 미연결";
    $("flowProducts").textContent = connected + "개 제품 정책 소스 확인";
  }

  function renderPreview(result) {
    const root = $("previewResult");
    root.replaceChildren();
    root.className = "preview";
    root.append(node("strong", "검증 통과 · 운영 반영 없음"));
    root.append(node("span", result.model_id + " · " + result.targets.length + "개 변경 영역"));
    const lines = node("ol");
    result.targets.forEach(({product_id, tier, action}) => {
      lines.append(node("li", PRODUCT_NAMES[product_id] + " / " + tier + " → " + ACTION_NAMES[action]));
    });
    root.append(lines, node("span",
      "변경안은 서버에서 실제 B14 모델 ID와 대상 형식만 검증했습니다. 저장·배포·실행 권한은 변경되지 않았습니다.",
      "muted"));
  }

  async function preview() {
    const targets = chosenTargets();
    if (!state.authorized || !state.selected || !targets.length) return;
    $("previewBtn").disabled = true;
    const seq = ++state.pendingRequest;
    try {
      const result = await getJSON("/api/admin/models/preview", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({model_id: state.selected.model_id, targets}),
      });
      if (seq === state.pendingRequest) {
        if (result.applied !== false || result.persisted !== false) throw new Error("invalid_preview_receipt");
        renderPreview(result);
      }
    } catch (err) {
      if (seq === state.pendingRequest) {
        $("previewResult").replaceChildren(node("strong", "검증 불가 · " + String(err.message), ""));
        $("previewResult").className = "preview error";
      }
    } finally {
      if (seq === state.pendingRequest) {
        $("previewBtn").disabled = !state.authorized || !state.selected || !chosenTargets().length;
      }
    }
  }

  async function load() {
    const seq = ++state.pendingRequest;
    state.authorized = false;
    state.loaded = false;
    state.catalog = [];
    state.products = null;
    state.selected = null;
    $("modelCount").textContent = "—";
    $("sourceCount").textContent = "—";
    $("targetCount").textContent = "0";
    $("selectedModel").textContent = "왼쪽에서 모델을 선택하세요";
    $("selectedId").textContent = "미선택";
    $("modelList").replaceChildren(node("p", "중앙 관리자 권한을 확인하고 있습니다.", "placeholder"));
    $("sourceList").replaceChildren(node("p", "권한 확인 중", "placeholder"));
    $("modelPlacement").replaceChildren(node("p", "중앙 관리자 권한 확인 중", "placeholder"));
    $("editorForm").disabled = true;
    $("previewBtn").disabled = true;
    setMode("권한 확인 중");
    message("중앙 관리자 인증과 실제 B14 모델 목록을 확인하고 있습니다.");
    try {
      await getJSON("/api/admin/models/me");
      if (seq !== state.pendingRequest) return;
      const result = await getJSON("/api/admin/models/snapshot");
      if (seq !== state.pendingRequest) return;
      if (result.write_enabled !== false || result.mode !== "read_only"
          || !Array.isArray(result.b14?.models)) throw new Error("invalid_snapshot");
      state.catalog = result.b14.models;
      state.products = result.products;
      state.authorized = true;
      state.loaded = true;
      $("modelCount").textContent = String(state.catalog.length);
      $("catalogStatus").textContent = "B14 확인된 모델";
      $("flowB14").textContent = state.catalog.length + "개 선택 가능 (전체 등록 수 아님)";
      setMode("관리자 조회 허용 · READ ONLY");
      message("실제 B14 모델과 기존 제품 정책의 연결 상태를 불러왔습니다. 체크한 변경안은 미리보기만 가능합니다.", "good");
      renderCatalog();
      renderSources(state.products);
      renderPlacement();
    } catch (err) {
      if (seq !== state.pendingRequest) return;
      const code = String(err.message);
      setMode("중앙 관리자 접근 제한");
      $("catalogStatus").textContent = "조회 차단";
      $("flowB14").textContent = "권한 있는 조회 대기";
      $("modelList").replaceChildren(node("p", "모델 목록을 표시하지 않습니다. 중앙 관리자 권한 확인이 필요합니다.", "placeholder"));
      $("sourceList").replaceChildren(node("p", "권한 확인 전 정책 정보 비공개", "placeholder"));
      $("modelPlacement").replaceChildren(node("p", "계층별 모델 배정 정보에 접근할 수 없습니다.", "placeholder"));
      message(code === "central_admin_not_configured"
        ? "중앙 관리자 권한기관이 아직 연결되지 않았습니다. B66 관리자 권한으로 자동 승격되지 않습니다."
        : code === "authentication_required"
          ? "로그인 후 중앙 관리자 자격을 확인할 수 있습니다. 먼저 PADIEM 계정으로 로그인하세요."
          : code === "global_model_admin_forbidden"
            ? "이 계정에는 중앙 모델 관리자 권한이 없습니다."
            : "모델 관리 데이터를 조회할 수 없습니다 (" + code + ").", "error");
    }
  }

  $("modelSearch").addEventListener("input", renderCatalog);
  $("tierSelect").addEventListener("change", updateSelection);
  $("actionSelect").addEventListener("change", updateSelection);
  $("previewBtn").addEventListener("click", preview);
  $("refreshBtn").addEventListener("click", load);
  renderTargets();
  load();
})();
