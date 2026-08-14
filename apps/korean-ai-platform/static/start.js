/* Business 14 Start Screen (Alpha 1)
 * Client-side controller for the v3.2 Start screen.
 * - Reads config from workspace-config script element
 * - Handles prompt input, preset selection, model selection (auto/manual)
 * - Calls POST /api/pilot/v1/chat/completions (Alpha mode: no X-Business14-Provider-Key header)
 * - Displays mock/live mode labeling
 * - XSS-safe: textContent only, no innerHTML for user/assistant content
 * - try/finally ensures send button always recovers after errors
 */
(function (global) {
  "use strict";

  var state = {
    messages: [],
    activeModel: null,
    activeRouteMode: "auto",
    preset: "general",
    optimizeFor: "balanced",
    externalFallback: true,
    isSending: false,
    lang: "ko-KR",
    config: null,
    catalogModels: [],
    b14ProviderMode: "mock",
    b14HasKey: false,
  };

  var DOM = {};
  var _sentinels = {
    no_key_live: "Live 모드에서는 OPENROUTER_API_KEY가 필요합니다. .env 파일에 키를 설정하십시오.",
    no_safe_route: "안전한 라우팅 경로를 찾을 수 없습니다.",
    mock_label: "모의 응답 · 실제 Provider 호출 없음",
    live_label: "실제 Provider 응답",
  };

  var localeMap = {
    send: "보내기",
    sending: "전송 중...",
    mock_label: "모의 응답 · 실제 Provider 호출 없음",
    live_label: "실제 Provider 응답",
    provider: "Provider",
    request_id: "Request ID",
    latency: "지연 시간",
    tokens: "토큰",
    cost: "예상 비용",
    cost_unknown: "확인 불가",
    error: "오류",
    select_model: "모델 선택",
    model_provider: "Provider",
    route_mode: "라우팅 모드",
    auto: "자동",
    manual: "수동",
    optimize_for: "최적화 기준",
    external_fallback: "외부 fallback 허용",
    cost_notice: "실제 비용은 Provider 계정과 계약에 따라 별도로 청구됩니다. Business 14는 이 파일럿에서 사용료를 청구하지 않습니다.",
  };

  var localeEn = {
    send: "Send",
    sending: "Sending...",
    mock_label: "Mock response - no real Provider call",
    live_label: "Live Provider response",
    provider: "Provider",
    request_id: "Request ID",
    latency: "Latency",
    tokens: "Tokens",
    cost: "Estimated Cost",
    cost_unknown: "Unknown",
    error: "Error",
    select_model: "Select Model",
    model_provider: "Provider",
    route_mode: "Routing mode",
    auto: "Auto",
    manual: "Manual",
    optimize_for: "Optimize for",
    external_fallback: "Allow external fallback",
    cost_notice: "Actual costs are billed separately by your Provider contract. Business 14 does not charge for this pilot.",
  };

  function t(key) {
    if (state.lang === "en" && localeEn[key]) return localeEn[key];
    return localeMap[key] || key;
  }

  function $(id) {
    return document.getElementById(id);
  }

  // ── DOM initialization ──────────────────────────────────────────────
  function init() {
    var configEl = document.getElementById("workspace-config");
    if (!configEl) {
      console.error("Start Screen: workspace-config not found");
      return;
    }

    try {
      var config = JSON.parse(configEl.textContent);
      state.config = config;
    } catch (e) {
      console.error("Start Screen: config parse error", e);
      return;
    }

    state.lang = config.lang || "ko-KR";
    state.b14ProviderMode = config.b14ProviderMode || "mock";
    state.b14HasKey = config.b14HasKey || false;
    state.catalogModels = config.b14CatalogModels || [];

    DOM.prompt = $("start_prompt");
    DOM.modelSelect = $("start_model");
    DOM.routeModeRadios = document.getElementsByName("start_route_mode");
    DOM.presetChips = document.querySelectorAll(".preset-chip");
    DOM.optimizeSelect = $("start_optimize_for");
    DOM.externalFallback = $("start_external_fallback");
    DOM.sendBtn = $("start_send");
    DOM.sendLoading = $("start_send_loading");
    DOM.routePreview = $("start_route_preview");
    DOM.routeMeta = $("start_route_meta");
    DOM.selectedProvider = $("start_selected_provider");
    DOM.selectedModel = $("start_selected_model");
    DOM.selectedReason = $("start_selected_reason");
    DOM.requestStatus = $("start_request_status");
    DOM.costEstimate = $("start_cost_estimate");
    DOM.costValue = $("start_cost_value");
    DOM.responseBody = $("start_response_body");
    DOM.responseMeta = $("start_response_meta");
    DOM.responseMode = $("start_response_mode");
    DOM.requestIdEl = $("start_request_id");
    DOM.tokensEl = $("start_tokens");
    DOM.costEl = $("start_estimated_cost");
    DOM.latencyEl = $("start_latency");

    // Set initial values
    state.activeModel = DOM.modelSelect ? DOM.modelSelect.value : "b14/auto";
    state.activeRouteMode = "auto";
    state.optimizeFor = DOM.optimizeSelect ? DOM.optimizeSelect.value : "balanced";
    state.externalFallback = DOM.externalFallback ? DOM.externalFallback.checked : true;

    // Attach event listeners
    if (DOM.sendBtn) DOM.sendBtn.addEventListener("click", sendMessage);
    if (DOM.modelSelect) DOM.modelSelect.addEventListener("change", onModelChange);
    if (DOM.prompt) DOM.prompt.addEventListener("keydown", onPromptKeydown);
    if (DOM.routeModeRadios && DOM.routeModeRadios.length) {
      for (var i = 0; i < DOM.routeModeRadios.length; i++) {
        DOM.routeModeRadios[i].addEventListener("change", onRouteModeChange);
      }
    }
    if (DOM.presetChips && DOM.presetChips.length) {
      for (var j = 0; j < DOM.presetChips.length; j++) {
        DOM.presetChips[j].addEventListener("click", onPresetClick);
      }
    }

    updateRoutePreview();
  }

  // ── Keyboard: Enter to send, Shift+Enter for newline ─────────────────
  function onPromptKeydown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  // ── Route mode: auto vs manual ──────────────────────────────────────
  function onRouteModeChange() {
    for (var i = 0; i < DOM.routeModeRadios.length; i++) {
      if (DOM.routeModeRadios[i].checked) {
        state.activeRouteMode = DOM.routeModeRadios[i].value;
        break;
      }
    }
    updateRoutePreview();
  }

  // ── Preset selection ────────────────────────────────────────────────
  function onPresetClick(e) {
    var chip = e.currentTarget;
    var preset = chip.getAttribute("data-preset") || "general";
    state.preset = preset;

    if (DOM.presetChips) {
      for (var i = 0; i < DOM.presetChips.length; i++) {
        DOM.presetChips[i].classList.remove("is-active");
      }
    }
    chip.classList.add("is-active");

    _applyPreset(preset);
  }

  function _applyPreset(preset) {
    if (preset === "korean") {
      state.optimizeFor = "korean";
      if (DOM.optimizeSelect) DOM.optimizeSelect.value = "korean";
    } else if (preset === "code") {
      state.optimizeFor = "cost";
      if (DOM.optimizeSelect) DOM.optimizeSelect.value = "cost";
    } else if (preset === "document") {
      state.optimizeFor = "balanced";
      if (DOM.optimizeSelect) DOM.optimizeSelect.value = "balanced";
    } else {
      state.optimizeFor = "balanced";
      if (DOM.optimizeSelect) DOM.optimizeSelect.value = "balanced";
    }
    updateRoutePreview();
  }

  // ── Model selection ─────────────────────────────────────────────────
  function onModelChange() {
    if (!DOM.modelSelect) return;
    state.activeModel = DOM.modelSelect.value;
    updateRoutePreview();
  }

  // ── Route preview (deterministic, no upstream call) ─────────────────
  function updateRoutePreview() {
    var model = state.activeModel;
    var cm = null;
    for (var i = 0; i < state.catalogModels.length; i++) {
      if (state.catalogModels[i].id === model) {
        cm = state.catalogModels[i];
        break;
      }
    }

    if (DOM.routePreview) {
      var txt = document.createTextNode(
        state.activeRouteMode === "auto"
          ? "자동으로 최적 모델을 선택합니다. (" + t("optimize_for") + ": " + state.optimizeFor + ")"
          : "선택한 모델로 요청을 전송합니다: " + model
      );
      DOM.routePreview.replaceChildren(txt);
    }

    if (DOM.selectedModel) {
      DOM.selectedModel.textContent = cm ? cm.name : model;
    }
    if (DOM.selectedProvider) {
      DOM.selectedProvider.textContent = cm ? cm.provider : "OpenRouter";
    }
    if (DOM.selectedReason) {
      DOM.selectedReason.textContent = state.activeRouteMode === "auto"
        ? "b14/auto가 " + (state.optimizeFor === "korean" ? "한국어 적합도" : state.optimizeFor === "cost" ? "비용" : state.optimizeFor === "latency" ? "속도" : "균형") + " 기준으로 선택"
        : "수동 선택";
    }

    _updateModeBadges();
  }

  function _updateModeBadges() {
    var modeLabel = DOM.responseMode;
    if (!modeLabel) return;
    if (state.b14ProviderMode === "live") {
      modeLabel.textContent = t("live_label");
      modeLabel.className = "response-mode-badge mode-live";
    } else {
      modeLabel.textContent = t("mock_label");
      modeLabel.className = "response-mode-badge mode-mock";
    }
  }

  // ── Send message ────────────────────────────────────────────────────
  async function sendMessage() {
    if (state.isSending) return;

    var text = DOM.prompt ? DOM.prompt.value.trim() : "";
    if (!text) {
      addSystemMsg("❌ " + "메시지를 입력하십시오.", true);
      scrollToBottom();
      return;
    }

    if (!state.b14HasKey && state.b14ProviderMode === "live") {
      addSystemMsg("❌ " + _sentinels.no_key_live, true);
      scrollToBottom();
      return;
    }

    state.isSending = true;
    if (DOM.sendBtn) DOM.sendBtn.style.display = "none";
    if (DOM.sendLoading) DOM.sendLoading.style.display = "inline-flex";
    if (DOM.sendLoading) DOM.sendLoading.disabled = true;
    if (DOM.requestStatus) {
      DOM.requestStatus.textContent = t("sending");
    }

    var model = state.activeRouteMode === "auto" ? "b14/auto" : state.activeModel;
    var b14_opts = {
      task_type: _getTaskType(),
      required_capabilities: ["chat"],
      optimize_for: state.optimizeFor,
      allow_external_fallback: state.externalFallback,
    };

    try {
      var resp = await fetch("/api/pilot/v1/chat/completions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: model,
          messages: [{ role: "user", content: text }],
          temperature: 0.2,
          max_tokens: 512,
          business14: b14_opts,
        }),
      });

      var data = await resp.json();

      if (!resp.ok || data.error) {
        var errCode = data.error ? data.error.code : "http_error";
        var errMsg = data.error && data.error.message ? data.error.message : t("error");
        displayError(errCode, errMsg, data.error ? data.error.request_id : "");
        return;
      }

      displayResponse(data);
    } catch (err) {
      displayError("network_error", t("error"), "");
    } finally {
      state.isSending = false;
      if (DOM.sendBtn) DOM.sendBtn.style.display = "inline-flex";
      if (DOM.sendLoading) DOM.sendLoading.style.display = "none";
      if (DOM.requestStatus) {
        DOM.requestStatus.textContent = "완료";
      }
      scrollToBottom();
    }
  }

  function _getTaskType() {
    var mapping = {
      general: "general",
      korean: "korean",
      code: "coding",
      document: "document",
      batch: "batch",
    };
    return mapping[state.preset] || "general";
  }

  // ── Display helpers ─────────────────────────────────────────────────
  function displayResponse(data) {
    if (DOM.responseMeta) DOM.responseMeta.style.display = "";
    if (DOM.routeMeta) DOM.routeMeta.style.display = "";

    var biz14 = data.business14 || {};
    _updateModeBadges();

    var choice = data.choices && data.choices[0];
    var content = choice && choice.message ? choice.message.content : "";

    if (DOM.responseBody) {
      DOM.responseBody.replaceChildren(document.createTextNode(content));
    }

    if (DOM.requestIdEl) {
      DOM.requestIdEl.textContent = biz14.request_id || "-";
    }

    var usage = data.usage || {};
    if (DOM.tokensEl) {
      DOM.tokensEl.textContent =
        (usage.prompt_tokens || 0) + " → " + (usage.completion_tokens || 0) +
        " (총 " + (usage.total_tokens || 0) + ")";
    }

    if (DOM.costEl) {
      if (biz14.estimated_krw !== null && biz14.estimated_krw !== undefined) {
        DOM.costEl.textContent = biz14.estimated_krw + "원 (약 $" + (biz14.estimated_usd || 0) + ")";
      } else {
        DOM.costEl.textContent = biz14.estimated_usd !== null && biz14.estimated_usd !== undefined
          ? "약 $" + biz14.estimated_usd
          : "계산 불가 (price 미공개)";
      }
    }

    if (DOM.latencyEl) {
      DOM.latencyEl.textContent = biz14.latency_ms ? biz14.latency_ms + "ms" : "-";
    }

    if (DOM.selectedModel) {
      DOM.selectedModel.textContent = biz14.selected_model || biz14.model_route || "-";
    }
    if (DOM.selectedProvider) {
      DOM.selectedProvider.textContent = biz14.selected_provider || "-";
    }
    if (DOM.selectedReason) {
      DOM.selectedReason.textContent = biz14.reason_codes ? biz14.reason_codes.join(", ") : "-";
    }

    // Cost estimate row
    if (DOM.costValue && biz14.estimated_krw !== null && biz14.estimated_krw !== undefined) {
      DOM.costValue.textContent = biz14.estimated_krw + "원";
    }

    addSystemMsg("📊 " + (biz14.route_evidence_status || ""), false);
    scrollToBottom();
  }

  function displayError(code, message, requestId) {
    if (DOM.responseBody) {
      DOM.responseBody.replaceChildren();
    }
    if (DOM.responseMeta) DOM.responseMeta.style.display = "none";
    if (DOM.routeMeta) DOM.routeMeta.style.display = "none";

    var label = DOM.responseMode;
    if (label) {
      if (state.b14ProviderMode === "live") {
        label.textContent = t("live_label");
        label.className = "response-mode-badge mode-live";
      } else {
        label.textContent = t("mock_label");
        label.className = "response-mode-badge mode-mock";
      }
    }

    addSystemMsg("❌ " + message, true);
    if (requestId) {
      addSystemMsg("Request ID: " + requestId);
    }
    scrollToBottom();
  }

  function addSystemMsg(text, isError) {
    if (!DOM.responseBody) return;
    var div = document.createElement("div");
    div.className = "ws-msg ws-msg-system" + (isError ? " ws-msg-error" : "");
    div.appendChild(document.createTextNode(text));
    DOM.responseBody.appendChild(div);
  }

  function scrollToBottom() {
    if (DOM.responseBody && typeof DOM.responseBody.scrollIntoView === "function") {
      DOM.responseBody.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }

  // ── Self-initialization ─────────────────────────────────────────────
  function initializeFromDocument() {
    var configEl = document.getElementById("workspace-config");
    if (!configEl) return;
    try {
      var config = JSON.parse(configEl.textContent);
      init();
    } catch (e) {
      console.error("Start Screen: config parse error", e);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeFromDocument, { once: true });
  } else {
    initializeFromDocument();
  }

  global.Business14Start = { init: init, state: state };
})(window);
