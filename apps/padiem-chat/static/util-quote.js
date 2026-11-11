/*
 * #7460 / #7173 PR4 · 견적서 초안 inside the Util app (#util/quote).
 *
 * File boundary: this screen and its sheet (util-quote.css) live in the Util
 * app; field definitions come from window.PadiemUtilManifest (util-manifest.js);
 * app.js gains nothing (R5 #7216).
 *
 * Layout (#7460): PC (>= 921px) places Left Input (.util-pane-input) and Right
 * Result (.util-pane-result) side by side; Phone (<= 920px) stacks them.
 */
(() => {
  "use strict";

  const T = Object.freeze({
    ko: Object.freeze({
      loginRequired: "로그인 후 이용할 수 있습니다.",
      loginUnknown: "로그인 상태를 확인하는 중입니다.",
      login: "로그인",
      required: "요청 원문을 입력해 주세요.",
      previewing: "초안을 만드는 중…",
      result: "초안 미리보기",
      emptyResult: "왼쪽에 받은 요청 원문을 넣고 초안 만들기를 누르면 견적서·발주서·답장 초안이 표시됩니다.",
      copy: "복사",
      copied: "복사됨",
      copyFailed: "복사하지 못했습니다.",
      regenerate: "다시 만들기",
      refineChat: "대화로 다듬기",
      clawExecute: "Claw에서 실행",
      clawNote: "결과 화면의 보조 동작입니다. 실행은 기존 Claw 흐름에서 이어집니다.",
      requestLabel: "요청 원문",
      requestPlaceholder: "받은 요청이나 메시지를 그대로 붙여넣어 주세요. 견적서·발주서·답장 초안을 만듭니다.",
      channelLabel: "채널",
      actionLabel: "작업",
      senderLabel: "발신자 힌트 (선택)",
      senderPlaceholder: "예: A상사 담당자",
      generate: "초안 만들기",
      authNeeded: "로그인이 필요합니다. 다시 로그인한 뒤 시도해 주세요.",
      rateLimited: "요청이 잠시 많습니다. 잠시 후 다시 시도해 주세요.",
      tooLong: "요청이 너무 깁니다. 12,000자 이내로 줄여 주세요.",
      generic: "초안을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.",
      invalid: "미리보기 응답을 확인하지 못했습니다. 다시 시도해 주세요.",
    }),
    en: Object.freeze({
      loginRequired: "Sign in to use this tool.",
      loginUnknown: "Checking your sign-in state.",
      login: "Sign in",
      required: "Enter the request text.",
      previewing: "Drafting…",
      result: "Draft preview",
      emptyResult: "Paste the received request on the left and build the draft to preview it here.",
      copy: "Copy",
      copied: "Copied",
      copyFailed: "Couldn’t copy.",
      regenerate: "Draft again",
      refineChat: "Refine in chat",
      clawExecute: "Run in Claw",
      clawNote: "A secondary action on the result. Execution continues in the existing Claw flow.",
      requestLabel: "Request",
      requestPlaceholder: "Paste the request or message as received. This drafts a quotation, purchase order or reply.",
      channelLabel: "Channel",
      actionLabel: "Action",
      senderLabel: "Sender hint (optional)",
      senderPlaceholder: "e.g. the contact at Company A",
      generate: "Draft it",
      authNeeded: "Sign in first, then try again.",
      rateLimited: "Too many requests for a moment. Try again shortly.",
      tooLong: "The request is too long. Keep it within 12,000 characters.",
      generic: "Couldn’t build the draft. Try again shortly.",
      invalid: "The preview response could not be verified. Try again.",
    }),
  });

  const CHANNELS = Object.freeze([
    ["other", "기타", "Other"],
    ["kakao", "카카오톡", "KakaoTalk"],
    ["sms", "문자", "SMS"],
    ["email", "이메일", "Email"],
    ["telegram", "텔레그램", "Telegram"],
    ["discord", "디스코드", "Discord"],
  ]);

  const ACTIONS = Object.freeze([
    ["quote", "견적서 초안", "Quote draft"],
    ["order", "발주서 초안", "Purchase order draft"],
    ["reply", "답장 초안", "Reply draft"],
    ["summary", "요청 항목 정리", "Summarize the request"],
    ["extract_candidates", "후보 추출", "Extract candidates"],
  ]);

  const MAX_REQUEST_CHARS = 12000;
  const MAX_SENDER_CHARS = 120;

  const QUOTE_CHAT_COPY = Object.freeze({
    ko: Object.freeze({
      refinePlaceholder: "추가할 품목·수량이나 조건을 적어 주세요 (예: A4 용지 5박스 추가)",
      allReadyIdle: "요청 원문이 준비되었습니다. 바로 초안을 만들거나 품목·조건을 덧붙여 주세요.",
      allReadyWithDraft: "현재 견적 초안과 입력값을 유지하고 있습니다. 품목·수량·조건을 덧붙이면 같은 계산 경로로 다시 만듭니다.",
      generatingTurn: "모은 항목으로 견적 초안을 계산하고 있습니다…",
      generatedTurn: "오른쪽에 계산된 초안을 표시했습니다. 항목을 덧붙이거나 '폼으로 열기'로 칸을 수정할 수 있습니다.",
    }),
    en: Object.freeze({
      refinePlaceholder: "Add items, quantities or terms (e.g. add 5 boxes of A4 paper)",
      allReadyIdle: "Request text is ready. Generate now or add items and terms below.",
      allReadyWithDraft: "Keeping your draft and inputs. Add items or terms to rebuild via the same calculation path.",
      generatingTurn: "Building the quote draft from the collected items…",
      generatedTurn: "Your calculated draft is in the result pane. Reply to add items, or choose 'Open in form'.",
    }),
  });

  function lang() {
    return document.documentElement && document.documentElement.lang === "en" ? "en" : "ko";
  }

  function t(key) {
    const table = T[lang()] || T.ko;
    return table[key] !== undefined ? table[key] : T.ko[key];
  }

  function manifestField(key) {
    const reg = window.PadiemUtilManifest;
    const tool = reg && typeof reg.getTool === "function" ? reg.getTool("quote") : null;
    if (!tool || !Array.isArray(tool.fields)) return null;
    return tool.fields.find((f) => f.key === key) || null;
  }

  function optionEntries(fieldKey, fallbackEntries) {
    const spec = manifestField(fieldKey);
    if (spec && Array.isArray(spec.options) && spec.options.length) {
      return spec.options.map((opt) => [opt.value, opt.label.ko, opt.label.en]);
    }
    return fallbackEntries;
  }

  function optionLabel(entry) {
    return entry[lang() === "en" ? 2 : 1];
  }

  function element(tagName, className, text) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function markdownModule() {
    const markdown = window.PadiemUtilMarkdown;
    return markdown && typeof markdown.render === "function" ? markdown : null;
  }

  function renderAnswer(host, value) {
    host.setAttribute("data-empty", "false");
    const markdown = markdownModule();
    if (markdown) {
      markdown.render(host, value);
      return;
    }
    host.textContent = value;
  }

  function paintEmptyResult(host) {
    host.setAttribute("data-empty", "true");
    host.replaceChildren(element("p", "util-result-empty", t("emptyResult")));
  }

  function plainAnswer(value) {
    const markdown = window.PadiemUtilMarkdown;
    return markdown && typeof markdown.plain === "function"
      ? markdown.plain(value)
      : String(value == null ? "" : value);
  }

  function authSession() {
    try {
      if (window.PadiemAuthSession && typeof window.PadiemAuthSession.get === "function") {
        const session = window.PadiemAuthSession.get();
        return session && typeof session === "object" ? session : null;
      }
    } catch (_) { /* an unreadable session is treated as unknown */ }
    return null;
  }

  function loginGate(known) {
    const gate = element("div", "util-gate");
    gate.appendChild(element("p", "util-gate-text", known ? t("loginRequired") : t("loginUnknown")));
    const login = element("button", "util-gate-login", t("login"));
    login.type = "button";
    login.addEventListener("click", () => {
      const button = document.getElementById("loginButton");
      if (button && typeof button.click === "function") button.click();
    });
    gate.appendChild(login);
    return gate;
  }

  function labelledField(labelText, control) {
    const label = element("label", "util-field");
    label.appendChild(element("span", "util-field-label", labelText));
    label.setAttribute("for", control.id);
    label.appendChild(control);
    return label;
  }

  function buildSelect(name, labelText, entries, selected) {
    const select = element("select", "util-input");
    select.name = name;
    select.id = "utilQuoteField-" + name;
    entries.forEach((entry) => {
      const option = element("option", null, optionLabel(entry));
      option.value = entry[0];
      option.selected = entry[0] === selected;
      select.appendChild(option);
    });
    return labelledField(labelText, select);
  }

  function errorMessage(err) {
    const status = err && err.status;
    if (status === 401 || status === 403) return t("authNeeded");
    if (status === 429) return t("rateLimited");
    const code = err && err.code;
    if (code === "content_too_long" || code === "request_too_large" || code === "sender_hint_too_long") {
      return t("tooLong");
    }
    if (code === "invalid_content") return t("required");
    if (code === "invalid_preview") return t("invalid");
    return t("generic");
  }

  async function requestPreview(values) {
    const response = await window.fetch("/api/util/quote/preview", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({
        content: values.content,
        channel: values.channel,
        action: values.action,
        sender_hint: values.sender_hint || null,
      }),
    });
    if (!response.ok) {
      const error = new Error("preview failed");
      error.status = response.status;
      try {
        const body = await response.json();
        error.code = body && body.error && typeof body.error.code === "string" ? body.error.code : "";
      } catch (_) { /* a non-JSON refusal keeps the status sentence */ }
      throw error;
    }
    const data = await response.json().catch(() => null);
    if (!data || data.ok !== true || !data.preview || typeof data.preview.result_text !== "string") {
      const error = new Error("invalid preview");
      error.code = "invalid_preview";
      throw error;
    }
    return data.preview;
  }

  function openClawQuote() {
    const nav = document.getElementById("clawNavButton");
    if (nav && typeof nav.click === "function") nav.click();
    const card = document.getElementById("clawQuoteCard");
    if (card && typeof card.click === "function") card.click();
  }

  function buildScreen(initialMode) {
    const chatApi = window.PadiemUtilChatMode;
    const hasChatMode = Boolean(
      chatApi
      && typeof chatApi.create === "function"
      && typeof chatApi.buildModeSwitch === "function"
    );
    const wrap = element("div", "util-tool-form util-tool-workbench util-quote-form");
    wrap.setAttribute("data-util-form", "quote");

    const inputPane = element("div", "util-pane-input");
    inputPane.setAttribute("data-util-pane", "input");

    const form = element("form", "util-form");
    form.id = "utilToolForm-quote";
    form.noValidate = true;

    const content = element("textarea", "util-input util-quote-request");
    content.name = "content";
    content.id = "utilQuoteField-content";
    content.rows = 6;
    content.required = true;
    content.setAttribute("aria-invalid", "false");
    content.addEventListener("input", () => {
      if (String(content.value || "").trim()) content.setAttribute("aria-invalid", "false");
    });
    content.maxLength = MAX_REQUEST_CHARS;
    content.placeholder = t("requestPlaceholder");
    form.appendChild(labelledField(t("requestLabel"), content));

    const row = element("div", "util-field-row");
    row.appendChild(buildSelect("channel", t("channelLabel"), optionEntries("channel", CHANNELS), "other"));
    row.appendChild(buildSelect("action", t("actionLabel"), optionEntries("action", ACTIONS), "quote"));
    form.appendChild(row);

    const sender = element("input", "util-input");
    sender.type = "text";
    sender.name = "sender_hint";
    sender.id = "utilQuoteField-sender_hint";
    sender.maxLength = MAX_SENDER_CHARS;
    sender.placeholder = t("senderPlaceholder");
    form.appendChild(labelledField(t("senderLabel"), sender));

    const actions = element("div", "util-form-actions");
    const primary = element("button", "util-generate", t("generate"));
    primary.type = "submit";
    primary.id = "utilQuoteGenerate";
    actions.appendChild(primary);
    form.appendChild(actions);

    const status = element("p", "util-status");
    status.id = "utilQuoteStatus";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.hidden = true;

    const resultPane = element("div", "util-pane-result");
    resultPane.setAttribute("data-util-pane", "result");

    const result = element("section", "util-result");
    result.id = "utilQuoteResult";
    result.hidden = false;
    const resultTitle = element("h4", "util-result-title", t("result"));
    const output = element("div", "util-result-output");
    output.id = "utilQuoteOutput";
    output.setAttribute("role", "region");
    output.setAttribute("aria-label", t("result"));
    output.setAttribute("tabindex", "0");
    paintEmptyResult(output);

    const resultActions = element("div", "util-result-actions");
    const copyBtn = element("button", "util-result-button", t("copy"));
    copyBtn.type = "button";
    copyBtn.disabled = true;
    copyBtn.setAttribute("data-util-copy", "");
    const againBtn = element("button", "util-result-button util-result-generate", t("regenerate"));
    againBtn.type = "button";
    againBtn.disabled = true;
    againBtn.setAttribute("data-util-regenerate", "");
    const clawBtn = element("button", "util-result-button util-quote-claw", t("clawExecute"));
    clawBtn.type = "button";
    clawBtn.setAttribute("data-util-claw", "");
    resultActions.appendChild(copyBtn);
    resultActions.appendChild(againBtn);
    let refineBtn = null;
    if (hasChatMode) {
      refineBtn = element("button", "util-result-button", t("refineChat"));
      refineBtn.type = "button";
      refineBtn.disabled = true;
      refineBtn.setAttribute("data-util-refine-chat", "");
      resultActions.appendChild(refineBtn);
    }
    resultActions.appendChild(clawBtn);
    const clawNote = element("p", "util-quote-note", t("clawNote"));
    result.appendChild(resultTitle);
    result.appendChild(output);
    result.appendChild(resultActions);
    result.appendChild(clawNote);
    resultPane.appendChild(result);

    function setStatus(text, tone) {
      status.textContent = text || "";
      status.hidden = !text;
      status.setAttribute("data-tone", tone || "info");
    }

    let busy = false;
    let lastPreview = null;

    function readValues() {
      return {
        content: String(content.value || "").trim(),
        channel: String((form.querySelector("#utilQuoteField-channel") || {}).value || "other"),
        action: String((form.querySelector("#utilQuoteField-action") || {}).value || "quote"),
        sender_hint: String(sender.value || "").trim(),
      };
    }

    function writeValues(incoming) {
      if (!incoming || typeof incoming !== "object") return;
      if (Object.prototype.hasOwnProperty.call(incoming, "content")) {
        content.value = String(incoming.content == null ? "" : incoming.content).slice(0, MAX_REQUEST_CHARS);
        if (String(content.value || "").trim()) content.setAttribute("aria-invalid", "false");
      }
      if (Object.prototype.hasOwnProperty.call(incoming, "sender_hint")) {
        sender.value = String(incoming.sender_hint == null ? "" : incoming.sender_hint).slice(0, MAX_SENDER_CHARS);
      }
      ["channel", "action"].forEach((fieldKey) => {
        if (!Object.prototype.hasOwnProperty.call(incoming, fieldKey)) return;
        const sel = form.querySelector("#utilQuoteField-" + fieldKey);
        if (!sel) return;
        const nextVal = String(incoming[fieldKey] == null ? "" : incoming[fieldKey]);
        sel.value = nextVal;
        if (Array.isArray(sel.children)) {
          sel.children.forEach((opt) => { opt.selected = opt.value === nextVal; });
        }
      });
    }

    async function runPreview(overrideValues, refinementNote) {
      if (busy) return false;
      if (overrideValues) writeValues(overrideValues);
      if (refinementNote) {
        const currentText = String(content.value || "").trim();
        const combined = currentText ? currentText + "\n" + String(refinementNote).trim() : String(refinementNote).trim();
        content.value = combined.slice(0, MAX_REQUEST_CHARS);
      }
      const values = readValues();
      if (!values.content) {
        content.setAttribute("aria-invalid", "true");
        setStatus(t("required"), "error");
        if (typeof content.focus === "function") content.focus();
        return false;
      }
      busy = true;
      primary.disabled = true;
      copyBtn.disabled = true;
      againBtn.disabled = true;
      if (refineBtn) refineBtn.disabled = true;
      clawBtn.disabled = true;
      setStatus(t("previewing"), "busy");
      result.hidden = false;
      const previousPreview = lastPreview;
      lastPreview = null;
      output.setAttribute("data-empty", "false");
      output.replaceChildren();
      try {
        const preview = await requestPreview(values);
        lastPreview = preview;
        resultTitle.textContent = preview.title ? String(preview.title) : t("result");
        renderAnswer(output, preview.result_text);
        result.hidden = false;
        setStatus("", null);
        return true;
      } catch (err) {
        setStatus(errorMessage(err), "error");
        if (previousPreview && previousPreview.result_text) {
          lastPreview = previousPreview;
          renderAnswer(output, previousPreview.result_text);
        } else {
          paintEmptyResult(output);
        }
        return false;
      } finally {
        busy = false;
        primary.disabled = false;
        const hasPreview = Boolean(lastPreview && lastPreview.result_text);
        copyBtn.disabled = !hasPreview;
        againBtn.disabled = !hasPreview;
        if (refineBtn) refineBtn.disabled = !hasPreview;
        clawBtn.disabled = false;
      }
    }

    let modeSwitch = null;
    let chatIntake = null;
    function setMode(nextMode, focusChat) {
      if (!chatIntake || !modeSwitch) return;
      const toChat = nextMode === "chat";
      wrap.setAttribute("data-active-mode", toChat ? "chat" : "form");
      modeSwitch.setActive(toChat ? "chat" : "form");
      if (toChat) {
        setStatus("", null);
        form.hidden = true;
        chatIntake.root.hidden = false;
        chatIntake.enter({ focusInput: Boolean(focusChat) });
      } else {
        writeValues(chatIntake.getValues());
        chatIntake.root.hidden = true;
        form.hidden = false;
      }
    }

    if (hasChatMode) {
      chatIntake = chatApi.create({
        toolId: "quote",
        copy: QUOTE_CHAT_COPY,
        getValues: () => readValues(),
        setValues: (vals) => writeValues(vals),
        hasDraft: () => Boolean(lastPreview && lastPreview.result_text),
        onGenerate: (vals, note) => runPreview(vals, note),
        onSwitchToForm: () => setMode("form", false),
      });
      if (chatIntake) {
        const startMode = initialMode === "chat" ? "chat" : "form";
        modeSwitch = chatApi.buildModeSwitch(startMode, (picked) => setMode(picked, picked === "chat"));
        inputPane.appendChild(modeSwitch.root);
        inputPane.appendChild(form);
        inputPane.appendChild(chatIntake.root);
        inputPane.appendChild(status);
        setMode(startMode, false);
      }
    }
    if (!chatIntake) {
      inputPane.appendChild(form);
      inputPane.appendChild(status);
    }

    wrap.appendChild(inputPane);
    wrap.appendChild(resultPane);

    form.addEventListener("submit", (event) => {
      if (event && typeof event.preventDefault === "function") event.preventDefault();
      void runPreview(null, "");
    });
    againBtn.addEventListener("click", () => { void runPreview(null, ""); });
    if (refineBtn) {
      refineBtn.addEventListener("click", () => { setMode("chat", true); });
    }
    clawBtn.addEventListener("click", () => { openClawQuote(); });
    copyBtn.addEventListener("click", () => {
      const text = plainAnswer(lastPreview && lastPreview.result_text).trim();
      if (!text) return;
      const copier = window.PadiemAnswerCopy && typeof window.PadiemAnswerCopy.copyText === "function"
        ? window.PadiemAnswerCopy.copyText
        : null;
      const done = (ok) => setStatus(ok ? t("copied") : t("copyFailed"), ok ? "info" : "error");
      if (copier) {
        Promise.resolve(copier(text)).then(done, () => done(false));
        return;
      }
      const nav = typeof navigator !== "undefined" ? navigator : null;
      if (nav && nav.clipboard && typeof nav.clipboard.writeText === "function") {
        Promise.resolve(nav.clipboard.writeText(text)).then(() => done(true), () => done(false));
        return;
      }
      done(false);
    });
    return wrap;
  }

  let current = null;

  function mount(host) {
    if (!host || typeof host.appendChild !== "function") return false;
    host.setAttribute("data-util-mounted", "form");
    const session = authSession();
    if (session && session.authenticated !== true) {
      host.appendChild(loginGate(true));
      current = { host: host };
      return true;
    }
    if (session === null) {
      host.appendChild(loginGate(false));
      current = { host: host };
      return true;
    }
    const initMode = host.getAttribute && host.getAttribute("data-util-initial-mode") === "chat" ? "chat" : "form";
    host.appendChild(buildScreen(initMode));
    current = { host: host };
    return true;
  }

  function remount() {
    if (!current || !current.host) return;
    const host = current.host;
    if (host.isConnected === false) return;
    if (typeof host.replaceChildren !== "function") return;
    host.replaceChildren();
    mount(host);
  }

  window.addEventListener("padiem:auth-state", remount);

  window.PadiemUtilQuote = Object.freeze({ mount: mount });
})();
