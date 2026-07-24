/* Business 14 Workspace (Phase 3)
 * Client-side conversation manager.
 * Keys stored only in JS memory (never in DOM, storage, cookies).
 * XSS-safe text rendering (no innerHTML for user/assistant content).
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
  };

  var DOM = {};

  function qs(sel) { return document.querySelector(sel); }
  function qsa(sel) { return document.querySelectorAll(sel); }

  // ── Safe text ──────────────────────────────────────────────────────────
  function escHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  // ── Locale access via server-provided strings ──────────────────────────
  // Simple map for workspace UI strings (server renders the initial text)
  var localeMap = {
    "key_status_set": "현재 페이지에서만 사용 중",
    "key_status_empty": "API key 없음",
    "sending": "전송 중...",
    "message_limit": "메시지가 너무 많습니다. 새 대화를 시작하거나 메시지를 줄이십시오.",
    "cost_unknown": "확인 불가",
    "model_provider": "Provider",
    "request_id": "Request ID",
    "latency": "지연 시간",
    "tokens": "토큰",
    "error": "오류",
    "retry": "재시도",
  };

  var localeEn = {
    "key_status_set": "Active for this page only",
    "key_status_empty": "No API key",
    "sending": "Sending...",
    "message_limit": "Too many messages. Start a new chat or reduce messages.",
    "cost_unknown": "Unknown",
    "model_provider": "Provider",
    "request_id": "Request ID",
    "latency": "Latency",
    "tokens": "Tokens",
    "error": "Error",
    "retry": "Retry",
  };

  function t(key) {
    if (state.lang === "en" && localeEn[key]) return localeEn[key];
    return localeMap[key] || key;
  }

  // ── Model change ──────────────────────────────────────────────────────
  function onModelChange() {
    var opt = DOM.model.options[DOM.model.selectedIndex];
    if (!opt) return;
    state.activeModel = opt.value;
    state.activeProvider = opt.getAttribute("data-provider") || "";
    var note = document.getElementById("ws_provider_name");
    if (note) {
      note.textContent = t("model_provider") + ": " + state.activeProvider;
    }
  }

  // ── Key management ───────────────────────────────────────────────────
  function onKeyInput() {
    var value = DOM.keyInput.value.trim();
    if (value.length > 0) {
      state.apiKey = value;
      DOM.keyInput.value = "";  // Clear input immediately
      DOM.keyStatus.textContent = t("key_status_set");
      DOM.keyClear.style.display = "";
    }
  }

  function clearKey() {
    state.apiKey = null;
    DOM.keyStatus.textContent = t("key_status_empty");
    DOM.keyClear.style.display = "none";
    DOM.keyInput.value = "";
    DOM.keyInput.focus();
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
    meta.textContent = label;
    div.appendChild(meta);

    var body = document.createElement("div");
    body.className = "ws-msg-body";
    body.textContent = content;  // Safe: no innerHTML
    div.appendChild(body);

    DOM.chatArea.appendChild(div);
  }

  function addSystemMsg(text, isError) {
    var div = document.createElement("div");
    div.className = "ws-msg ws-msg-system" + (isError ? " ws-msg-error" : "");
    div.textContent = text;
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
      parts.push(t("tokens") + ": " + (u.prompt_tokens || "?") + "→" + (u.completion_tokens || "?"));
    }

    div.textContent = parts.join(" · ");
    DOM.chatArea.appendChild(div);
  }

  function scrollToBottom() {
    DOM.chatArea.scrollTop = DOM.chatArea.scrollHeight;
  }

  function showEmpty(show) {
    DOM.empty.style.display = show ? "" : "none";
  }

  // ── Send message ────────────────────────────────────────────────────
  function buildMessages() {
    return state.messages;
  }

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

    // Build conversation history
    var msgs = state.messages.concat([{ role: "user", content: text }]);

    // Validate
    if (!state.apiKey) {
      addSystemMsg("❌ " + t("key_status_empty"), true);
      scrollToBottom();
      return;
    }

    if (!state.activeModel) {
      addSystemMsg("❌ " + t("model_provider") + " " + t("error"), true);
      scrollToBottom();
      return;
    }

    state.isSending = true;
    DOM.sendBtn.disabled = true;
    DOM.sendBtn.textContent = t("sending");
    DOM.overlay.style.display = "";
    DOM.input.value = "";

    // Render user message immediately
    addMessage("user", text);
    showEmpty(false);
    scrollToBottom();

    try {
      var resp = await fetch("/workspace/api/chat", {
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
        var errMsg = data.error?.message || t("error") + " (code: " + (data.error?.code || resp.status) + ")";
        addSystemMsg("❌ " + errMsg, true);
        if (data.error?.request_id) {
          addSystemMsg("Request ID: " + data.error.request_id);
        }
        state.isSending = false;
        DOM.sendBtn.disabled = false;
        DOM.sendBtn.textContent = t("sending").replace(t("sending"), t("retry"));
        DOM.overlay.style.display = "none";
        scrollToBottom();
        return;
      }

      var choice = data.choices?.[0];
      var content = choice?.message?.content || "";
      state.messages.push({ role: "user", content: text });
      state.messages.push({ role: "assistant", content: content });

      addMessage("assistant", content);
      addMetadata(data.business14);

      var usage = data.usage;
      if (usage) {
        addSystemMsg("Tokens: " + (usage.prompt_tokens || "?") + " → " + (usage.completion_tokens || "?"));
      }

    } catch (err) {
      addSystemMsg("❌ " + t("error") + ": " + err.message, true);
    }

    state.isSending = false;
    DOM.sendBtn.disabled = false;
    DOM.sendBtn.textContent = t("sending").replace(t("sending"), t("retry"));
    DOM.overlay.style.display = "none";
    scrollToBottom();
    DOM.input.focus();
  }

  // ── New chat / Clear ─────────────────────────────────────────────────
  function newChat() {
    state.messages = [];
    DOM.chatArea.innerHTML = "";
    showEmpty(true);
    // Keep apiKey (only cleared by explicit clear or reload)
    checkMessageLimit();
    DOM.input.focus();
  }

  function clearChat() {
    state.messages = [];
    DOM.chatArea.innerHTML = "";
    showEmpty(true);
    checkMessageLimit();
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
  function init(opts) {
    opts = opts || {};
    state.models = opts.models || [];
    state.lang = opts.lang || "ko-KR";
    state.maxTokens = opts.maxTokens || 512;
    state.errorCode = opts.errorCode || null;

    if (opts.models && opts.models.length > 0) {
      var first = opts.models[0];
      state.activeModel = first.id;
      state.activeProvider = first.provider_name || "";
    }

    // Cache DOM
    DOM.model = document.getElementById("ws_model");
    DOM.keyInput = document.getElementById("ws_key");
    DOM.keyStatus = document.getElementById("ws_key_status");
    DOM.keyClear = document.getElementById("ws_key_clear");
    DOM.chatArea = document.getElementById("ws_chat");
    DOM.empty = document.getElementById("ws_empty");
    DOM.input = document.getElementById("ws_input");
    DOM.sendBtn = document.getElementById("ws_send");
    DOM.newChatBtn = document.getElementById("ws_new_chat");
    DOM.clearChatBtn = document.getElementById("ws_clear_chat");
    DOM.overlay = document.getElementById("ws_overlay");
    DOM.msgLimit = document.getElementById("ws_msg_limit");

    if (localeEn && state.lang === "en") {
      localeMap = localeEn;
    }

    // Bind events
    if (DOM.model) DOM.model.addEventListener("change", onModelChange);
    if (DOM.keyInput) DOM.keyInput.addEventListener("input", onKeyInput);
    if (DOM.keyClear) DOM.keyClear.addEventListener("click", clearKey);
    if (DOM.sendBtn) DOM.sendBtn.addEventListener("click", sendMessage);
    if (DOM.input) DOM.input.addEventListener("keydown", onInputKeydown);
    if (DOM.newChatBtn) DOM.newChatBtn.addEventListener("click", newChat);
    if (DOM.clearChatBtn) DOM.clearChatBtn.addEventListener("click", clearChat);

    // Call onModelChange for initial provider display
    if (DOM.model && DOM.model.options.length > 0) {
      onModelChange();
    }
  }

  // ── Expose ──────────────────────────────────────────────────────────
  global.Business14Workspace = {
    init: init,
    sendMessage: sendMessage,
    newChat: newChat,
    clearChat: clearChat,
    clearKey: clearKey,
    state: state,
  };

})(window);
