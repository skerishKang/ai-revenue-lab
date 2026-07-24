/* Business 14 Workspace (Phase 3)
 * Client-side conversation manager.
 * - Keys captured via "Apply" button, not per-keystroke
 * - Provider change clears key + messages (isolation)
 * - Reuses Phase 2 /api/pilot/v1/chat/completions directly
 * - XSS-safe: textContent only, no innerHTML for user/assistant content
 */
(function (global) {
  "use strict";

  var state = {
    messages: [],       // [{role, content}]
    apiKey: null,       // in-memory only
    activeModel: null,
    activeProvider: "",
    models: [],
    lang: "ko-KR",
    isSending: false,
    maxTokens: 512,
    errorCode: null,
    config: null,       // loaded from #workspace-config JSON
  };

  var DOM = {};

  var localeMap = {
    "key_status_set": "현재 페이지에서만 사용 중",
    "key_status_empty": "API key 없음",
    "send": "보내기",
    "sending": "전송 중...",
    "retry": "재시도",
    "key_apply": "API key 적용",
    "key_clear": "API key 지우기",
    "message_limit": "메시지가 너무 많습니다. 새 대화를 시작하거나 메시지를 줄이십시오.",
    "cost_unknown": "확인 불가",
    "model_provider": "Provider",
    "request_id": "Request ID",
    "latency": "지연 시간",
    "tokens": "토큰",
    "error": "오류",
    "provider_changed": "Provider가 변경되어 key와 대화가 초기화되었습니다. 새 API key를 입력하십시오.",
    "model_changed": "모델이 변경되어 대화가 초기화되었습니다.",
    "empty_key": "API key가 설정되지 않았습니다. key를 입력하고 적용 버튼을 누르십시오.",
  };

  var localeEn = {
    "key_status_set": "Active for this page only",
    "key_status_empty": "No API key",
    "send": "Send",
    "sending": "Sending...",
    "retry": "Retry",
    "key_apply": "Apply API Key",
    "key_clear": "Clear API Key",
    "message_limit": "Too many messages. Start a new chat or reduce messages.",
    "cost_unknown": "Unknown",
    "model_provider": "Provider",
    "request_id": "Request ID",
    "latency": "Latency",
    "tokens": "Tokens",
    "error": "Error",
    "provider_changed": "Provider changed. Key and conversation cleared. Please enter a new API key.",
    "model_changed": "Model changed. Conversation cleared.",
    "empty_key": "No API key set. Enter a key and click Apply.",
  };

  function t(key) {
    if (state.lang === "en" && localeEn[key]) return localeEn[key];
    return localeMap[key] || key;
  }

  // ── Model change ──────────────────────────────────────────────────────
  function onModelChange() {
    var opt = DOM.model.options[DOM.model.selectedIndex];
    if (!opt) return;
    var newProvider = opt.getAttribute("data-provider") || "";
    var newModel = opt.value;

    // Skip reset on initial page load (first call from init)
    if (DOM._initializing) {
      state.activeModel = newModel;
      state.activeProvider = newProvider;
      updateProviderDisplay();
      return;
    }

    // Model changed — clear key and messages for isolation
    var providerChanged = newProvider !== state.activeProvider;
    state.activeModel = newModel;
    state.activeProvider = newProvider;
    updateProviderDisplay();

    // Clear state
    state.apiKey = null;
    state.messages = [];
    DOM.chatArea.replaceChildren();
    showEmpty(true);
    DOM.keyStatus.textContent = t("key_status_empty");
    DOM.keyInput.value = "";
    DOM.keyClear.style.display = "none";
    DOM.msgLimit.style.display = "none";

    if (providerChanged) {
      addSystemMsg("🔄 " + t("provider_changed"));
    } else {
      addSystemMsg("🔄 " + t("model_changed"));
    }
    scrollToBottom();
    DOM.keyInput.focus();
  }

  function updateProviderDisplay() {
    var note = document.getElementById("ws_provider_name");
    if (note) {
      note.innerHTML = "";
      note.appendChild(document.createTextNode(
        t("model_provider") + ": " + state.activeProvider
      ));
    }
  }

  // ── Key management (button-based capture) ───────────────────────────
  function applyKey() {
    var value = DOM.keyInput.value.trim();
    if (value.length === 0) {
      addSystemMsg("❌ " + t("empty_key"), true);
      scrollToBottom();
      return;
    }
    state.apiKey = value;
    DOM.keyInput.value = "";  // Clear input immediately
    DOM.keyStatus.textContent = t("key_status_set");
    DOM.keyClear.style.display = "";
    addSystemMsg("🔑 " + t("key_status_set"));
    scrollToBottom();
    DOM.input.focus();
  }

  function onKeyEnter(e) {
    if (e.key === "Enter") {
      e.preventDefault();
      applyKey();
    }
  }

  function clearKey() {
    state.apiKey = null;
    DOM.keyStatus.textContent = t("key_status_empty");
    DOM.keyClear.style.display = "none";
    DOM.keyInput.value = "";
    DOM.keyInput.focus();
    addSystemMsg("🔑 " + t("key_status_empty"));
    scrollToBottom();
  }

  // ── Chat rendering (XSS-safe) ────────────────────────────────────────
  function addMessage(role, content) {
    var div = document.createElement("div");
    div.className = "ws-msg ws-msg-" + role;

    var meta = document.createElement("div");
    meta.className = "ws-msg-meta";
    var label = role === "user" ? "You" : "Assistant";
    if (role === "assistant") {
      label = state.activeProvider || label;
    }
    meta.appendChild(document.createTextNode(label));
    div.appendChild(meta);

    var body = document.createElement("div");
    body.className = "ws-msg-body";
    body.appendChild(document.createTextNode(content));  // Safe: textContent
    div.appendChild(body);

    DOM.chatArea.appendChild(div);
  }

  function addSystemMsg(text, isError) {
    var div = document.createElement("div");
    div.className = "ws-msg ws-msg-system" + (isError ? " ws-msg-error" : "");
    div.appendChild(document.createTextNode(text));
    DOM.chatArea.appendChild(div);
  }

  function addMetadata(biz14) {
    if (!biz14) return;
    var div = document.createElement("div");
    div.className = "ws-msg ws-msg-meta";

    var parts = [];
    if (biz14.request_id) parts.push(t("request_id") + ": " + biz14.request_id);
    if (biz14.latency_ms) parts.push(t("latency") + ": " + biz14.latency_ms + "ms");
    if (biz14.provider) parts.push(t("model_provider") + ": " + biz14.provider);
    if (biz14.model_route) parts.push("Model: " + biz14.model_route);
    if (biz14.usage) {
      var u = biz14.usage;
      parts.push(t("tokens") + ": " + (u.prompt_tokens || "?") + " \u2192 " + (u.completion_tokens || "?"));
    }
    if (biz14.estimated_krw === null || biz14.estimated_krw === undefined) {
      parts.push(t("cost_unknown"));
    }

    div.appendChild(document.createTextNode(parts.join(" \u00b7 ")));
    DOM.chatArea.appendChild(div);
  }

  function scrollToBottom() {
    DOM.chatArea.scrollTop = DOM.chatArea.scrollHeight;
  }

  function showEmpty(show) {
    DOM.empty.style.display = show ? "" : "none";
  }

  // Rollback user message on failure: removes from state and DOM
  function rollbackUserMessage() {
    state.messages.pop();
    var last = DOM.chatArea.lastChild;
    if (last && last.classList && last.classList.contains("ws-msg-user")) {
      DOM.chatArea.removeChild(last);
    }
    showEmpty(state.messages.length === 0);
  }

  // ── Send message (direct Phase 2 API call) ──────────────────────────
  function checkMessageLimit() {
    if (state.messages.length > 80) {
      DOM.msgLimit.style.display = "";
      return true;
    }
    DOM.msgLimit.style.display = "none";
    return false;
  }

  async function sendMessage() {
    if (state.isSending) return;

    var text = DOM.input.value.trim();
    if (!text) return;

    if (checkMessageLimit()) return;

    // Validate key
    if (!state.apiKey) {
      addSystemMsg("\u274c " + t("empty_key"), true);
      scrollToBottom();
      return;
    }

    if (!state.activeModel) {
      addSystemMsg("\u274c " + t("error"), true);
      scrollToBottom();
      return;
    }

    state.isSending = true;
    DOM.sendBtn.disabled = true;
    DOM.sendBtn.textContent = t("sending");
    DOM.input.value = "";

    // Push to state BEFORE fetch so state is consistent
    // Build msgs from state AFTER push (single source of truth)
    state.messages.push({ role: "user", content: text });
    var msgs = state.messages.slice();  // copy for API body

    // Render user message immediately
    addMessage("user", text);
    showEmpty(false);
    scrollToBottom();

    try {
      // Call Phase 2 API directly — no server-side proxy
      var resp = await fetch("/api/pilot/v1/chat/completions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Business14-Provider-Key": state.apiKey,
        },
        body: JSON.stringify({
          model: state.activeModel,
          messages: msgs,
          temperature: 0.2,
          max_tokens: state.maxTokens,
        }),
      });

      var data = await resp.json();

      if (!resp.ok || data.error) {
        rollbackUserMessage();
        var errMsg = data.error && data.error.message
          ? data.error.message
          : t("error") + " (code: " + (data.error && data.error.code || resp.status) + ")";
        addSystemMsg("\u274c " + errMsg, true);
        if (data.error && data.error.request_id) {
          addSystemMsg("Request ID: " + data.error.request_id);
        }
        DOM.sendBtn.textContent = t("retry");
        scrollToBottom();
        return;
      }

      var choice = data.choices && data.choices[0];
      var content = (choice && choice.message && choice.message.content) || "";
      state.messages.push({ role: "assistant", content: content });

      addMessage("assistant", content);
      addMetadata(data.business14);

    } catch (err) {
      rollbackUserMessage();
      addSystemMsg("\u274c " + t("error"), true);
    }

    state.isSending = false;
    DOM.sendBtn.disabled = false;
    DOM.sendBtn.textContent = t("send");
    scrollToBottom();
    DOM.input.focus();
  }

  // ── New chat / Clear ─────────────────────────────────────────────────
  function newChat() {
    state.messages = [];
    DOM.chatArea.replaceChildren();
    showEmpty(true);
    DOM.msgLimit.style.display = "none";
    DOM.input.focus();
  }

  function clearChat() {
    state.messages = [];
    DOM.chatArea.replaceChildren();
    showEmpty(true);
    DOM.msgLimit.style.display = "none";
    DOM.input.focus();
  }

  // ── Keyboard ─────────────────────────────────────────────────────────
  function onInputKeydown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  // ── Init ─────────────────────────────────────────────────────────────
  function init(config) {
    config = config || {};
    state.config = config;
    state.models = config.models || [];
    state.lang = config.lang || "ko-KR";
    state.maxTokens = config.maxTokens || 512;
    state.errorCode = config.errorCode || null;

    if (config.models && config.models.length > 0) {
      state.activeModel = config.models[0].id;
      state.activeProvider = config.models[0].provider_name || "";
    }

    // Cache DOM
    DOM.model = document.getElementById("ws_model");
    DOM.keyInput = document.getElementById("ws_key");
    DOM.keyStatus = document.getElementById("ws_key_status");
    DOM.keyClear = document.getElementById("ws_key_clear");
    DOM.keyApply = document.getElementById("ws_key_apply");
    DOM.chatArea = document.getElementById("ws_chat");
    DOM.empty = document.getElementById("ws_empty");
    DOM.input = document.getElementById("ws_input");
    DOM.sendBtn = document.getElementById("ws_send");
    DOM.newChatBtn = document.getElementById("ws_new_chat");
    DOM.clearChatBtn = document.getElementById("ws_clear_chat");
    DOM.msgLimit = document.getElementById("ws_msg_limit");

    // Disable send if not configured or invalid registry
    if (config.errorCode === "registry_invalid" || !config.pilotConfigured) {
      if (DOM.sendBtn) DOM.sendBtn.disabled = true;
      if (DOM.input) DOM.input.disabled = true;
    }

    // Bind events
    DOM._initializing = true;
    if (DOM.model) DOM.model.addEventListener("change", onModelChange);
    if (DOM.keyApply) DOM.keyApply.addEventListener("click", applyKey);
    if (DOM.keyInput) DOM.keyInput.addEventListener("keydown", onKeyEnter);
    if (DOM.keyClear) DOM.keyClear.addEventListener("click", clearKey);
    if (DOM.sendBtn) DOM.sendBtn.addEventListener("click", sendMessage);
    if (DOM.input) DOM.input.addEventListener("keydown", onInputKeydown);
    if (DOM.newChatBtn) DOM.newChatBtn.addEventListener("click", newChat);
    if (DOM.clearChatBtn) DOM.clearChatBtn.addEventListener("click", clearChat);

    // Initialize provider display
    if (DOM.model && DOM.model.options.length > 0) {
      onModelChange();
    }
    DOM._initializing = false;
  }

  // ── Expose ──────────────────────────────────────────────────────────
  global.Business14Workspace = {
    init: init,
    sendMessage: sendMessage,
    newChat: newChat,
    clearChat: clearChat,
    clearKey: clearKey,
    applyKey: applyKey,
    state: state,
  };

})(window);
