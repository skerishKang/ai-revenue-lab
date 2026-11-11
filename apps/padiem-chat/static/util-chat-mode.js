/*
 * #7461 · Shared Util conversational intake & Form ↔ Conversation bridge.
 *
 * File boundary: lives in static/util-chat-mode.js (+ util-chat-mode.css);
 * app.js is untouched (R5 #7216). Runs strictly inside the Util tool screen —
 * never navigates to the Chat or Claw conversation surfaces.
 *
 * Contract:
 * - Reads fields, missingFields(id, values) and nextQuestion(id, values, lang)
 *   directly from window.PadiemUtilManifest (or an injected manifest for tests).
 * - Asks missing required fields one at a time in manifest order (including
 *   type="file" attachment fields, with zero tool-specific hardcoding).
 * - Triggers server generation ONLY when all required fields are present.
 * - Preserves values both ways: Form -> Conversation keeps typed/selected inputs,
 *   and Conversation -> Form populates the Form controls with collected answers.
 */
(() => {
  "use strict";

  const COPY = Object.freeze({
    ko: Object.freeze({
      modeGroup: "입력 방식",
      formTab: "폼 방식",
      chatTab: "대화 방식",
      openForm: "폼으로 열기",
      refineInChat: "대화로 다듬기",
      generateNow: "지금 생성",
      attachFile: "파일 첨부",
      send: "보내기",
      inputLabel: "답변 입력",
      refinePlaceholder: "다듬을 내용을 적어 주세요 (예: 더 짧게, 따뜻한 말투로)",
      answerRequired: "답변을 입력해 주세요.",
      fileRequired: "파일을 첨부해 주세요.",
      collectedLabel: "모은 항목",
      allReadyIdle: "필수 항목이 모두 채워져 있습니다. 바로 생성하거나 덧붙일 요청을 입력해 주세요.",
      allReadyWithDraft: "현재 초안과 입력값을 유지하고 있습니다. 다듬을 점(예: 더 짧게, 말투 부드럽게)을 적어 주세요.",
      generatingTurn: "필수 항목이 모두 모였습니다. 초안을 생성합니다…",
      generatedTurn: "오른쪽 결과 칸에 초안을 준비했습니다. 다듬을 내용을 이어서 적거나 '폼으로 열기'로 세부 항목을 바꿀 수 있습니다.",
      generationFailedTurn: "초안을 생성하지 못했습니다. 아래 안내를 확인한 뒤 다시 시도해 주세요.",
      logLabel: "대화형 입력 내역",
    }),
    en: Object.freeze({
      modeGroup: "Input mode",
      formTab: "Form mode",
      chatTab: "Chat mode",
      openForm: "Open in form",
      refineInChat: "Refine in chat",
      generateNow: "Generate now",
      attachFile: "Attach file",
      send: "Send",
      inputLabel: "Your answer",
      refinePlaceholder: "Tell me how to refine the draft (e.g. shorter, warmer tone)",
      answerRequired: "Please enter an answer.",
      fileRequired: "Please attach a file.",
      collectedLabel: "Collected fields",
      allReadyIdle: "All required fields are filled. Generate right away or add a note below.",
      allReadyWithDraft: "Keeping your current draft and inputs. Tell me what to refine (e.g. shorter, gentler tone).",
      generatingTurn: "All required fields are ready. Generating the draft…",
      generatedTurn: "Your draft is ready in the result pane. Reply here to refine it, or choose 'Open in form' to edit fields.",
      generationFailedTurn: "Couldn’t generate the draft. Check the status below and try again.",
      logLabel: "Conversational intake log",
    }),
  });

  function lang() {
    return document.documentElement && document.documentElement.lang === "en" ? "en" : "ko";
  }

  function t(key, overrideCopy) {
    const code = lang();
    const custom = overrideCopy && overrideCopy[code] ? overrideCopy[code][key] : undefined;
    if (custom !== undefined) return custom;
    const table = COPY[code] || COPY.ko;
    return table[key] !== undefined ? table[key] : COPY.ko[key];
  }

  function localized(entry) {
    if (!entry) return "";
    if (typeof entry === "string") return entry;
    return entry[lang()] || entry.ko || "";
  }

  function el(tagName, className, text) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function buildModeSwitch(initialMode, onSelect) {
    const bar = el("div", "util-mode-switch");
    bar.setAttribute("role", "group");
    bar.setAttribute("aria-label", t("modeGroup"));

    const formBtn = el("button", "util-mode-tab", t("formTab"));
    formBtn.type = "button";
    formBtn.setAttribute("data-util-mode", "form");
    formBtn.setAttribute("aria-pressed", initialMode === "chat" ? "false" : "true");

    const chatBtn = el("button", "util-mode-tab", t("chatTab"));
    chatBtn.type = "button";
    chatBtn.setAttribute("data-util-mode", "chat");
    chatBtn.setAttribute("aria-pressed", initialMode === "chat" ? "true" : "false");

    function setActive(mode) {
      const isChat = mode === "chat";
      formBtn.setAttribute("aria-pressed", isChat ? "false" : "true");
      chatBtn.setAttribute("aria-pressed", isChat ? "true" : "false");
    }

    formBtn.addEventListener("click", () => {
      setActive("form");
      if (onSelect) onSelect("form");
    });
    chatBtn.addEventListener("click", () => {
      setActive("chat");
      if (onSelect) onSelect("chat");
    });

    bar.appendChild(formBtn);
    bar.appendChild(chatBtn);
    return { root: bar, setActive: setActive, formBtn: formBtn, chatBtn: chatBtn };
  }

  function normalizeOptionAnswer(field, rawText) {
    const trimmed = String(rawText || "").trim();
    if (!field || !Array.isArray(field.options) || !field.options.length) return trimmed;
    const lowered = trimmed.toLowerCase();
    for (let i = 0; i < field.options.length; i += 1) {
      const opt = field.options[i];
      const koLabel = opt.label && opt.label.ko ? String(opt.label.ko).trim() : "";
      const enLabel = opt.label && opt.label.en ? String(opt.label.en).trim() : "";
      if (
        String(opt.value).toLowerCase() === lowered
        || koLabel.toLowerCase() === lowered
        || enLabel.toLowerCase() === lowered
      ) {
        return String(opt.value);
      }
    }
    return trimmed;
  }

  function matchOptionalChoice(fields, rawText) {
    const lowered = String(rawText || "").trim().toLowerCase();
    if (!lowered || !Array.isArray(fields)) return null;
    for (let i = 0; i < fields.length; i += 1) {
      const fld = fields[i];
      if (!fld || !Array.isArray(fld.options) || !fld.options.length) continue;
      for (let j = 0; j < fld.options.length; j += 1) {
        const opt = fld.options[j];
        const ko = opt.label && opt.label.ko ? String(opt.label.ko).trim().toLowerCase() : "";
        const en = opt.label && opt.label.en ? String(opt.label.en).trim().toLowerCase() : "";
        if (String(opt.value).toLowerCase() === lowered || ko === lowered || en === lowered) {
          return { key: fld.key, value: String(opt.value) };
        }
      }
    }
    return null;
  }

  function fileNamesOf(rawValue) {
    if (!rawValue) return [];
    if (typeof rawValue === "string") return rawValue.trim() ? [rawValue.trim()] : [];
    if (typeof rawValue.length === "number") {
      const out = [];
      for (let i = 0; i < rawValue.length; i += 1) {
        const item = rawValue[i];
        const name = item && typeof item === "object" && item.name ? String(item.name).trim() : String(item || "").trim();
        if (name) out.push(name);
      }
      return out;
    }
    return [];
  }

  function displayFieldValue(field, rawValue) {
    if (field && field.type === "file") {
      return fileNamesOf(rawValue).join(", ");
    }
    const val = String(rawValue == null ? "" : rawValue).trim();
    if (!val) return "";
    if (field && Array.isArray(field.options) && field.options.length) {
      const hit = field.options.find((o) => String(o.value) === val);
      if (hit) return localized(hit.label) || val;
    }
    return val;
  }

  function create(options) {
    const opts = options || {};
    const toolId = String(opts.toolId || "");
    const reg = opts.manifest || window.PadiemUtilManifest;
    const tool = reg && typeof reg.getTool === "function" ? reg.getTool(toolId) : null;
    if (!reg || !tool) return null;
    const customCopy = opts.copy || null;
    const tx = (key) => t(key, customCopy);
    const pcImport = opts.pcImport && typeof opts.pcImport.run === "function" ? opts.pcImport : null;

    const root = el("div", "util-chat-intake");
    root.setAttribute("data-util-chat-intake", toolId);

    const summaryBar = el("div", "util-chat-summary");
    summaryBar.setAttribute("aria-label", tx("collectedLabel"));
    const summaryChips = el("div", "util-chat-summary-chips");
    const openFormBtn = el("button", "util-chat-open-form", tx("openForm"));
    openFormBtn.type = "button";
    openFormBtn.setAttribute("data-util-open-form", "");
    summaryBar.appendChild(summaryChips);
    summaryBar.appendChild(openFormBtn);

    const log = el("div", "util-chat-log");
    log.setAttribute("role", "log");
    log.setAttribute("aria-live", "polite");
    log.setAttribute("aria-label", tx("logLabel"));

    const quickChoices = el("div", "util-chat-choices");
    quickChoices.hidden = true;

    const fileBar = el("div", "util-chat-file-bar");
    fileBar.hidden = true;
    const fileInput = el("input", "util-chat-file-input");
    fileInput.type = "file";
    fileInput.hidden = true;
    fileInput.setAttribute("data-util-chat-file", "");
    const filePickBtn = el("button", "util-chat-choice util-chat-file-pick", tx("attachFile"));
    filePickBtn.type = "button";
    filePickBtn.setAttribute("data-util-chat-file-trigger", "");
    fileBar.appendChild(fileInput);
    fileBar.appendChild(filePickBtn);

    const readyActions = el("div", "util-chat-ready-actions");
    readyActions.hidden = true;
    const generateNowBtn = el("button", "util-generate util-chat-generate-now", tx("generateNow"));
    generateNowBtn.type = "button";
    generateNowBtn.setAttribute("data-util-chat-generate", "");
    readyActions.appendChild(generateNowBtn);

    const composer = el("form", "util-chat-composer");
    composer.noValidate = true;
    const inputLabel = el("label", "util-chat-composer-label");
    const inputId = "utilChatInput-" + toolId;
    inputLabel.setAttribute("for", inputId);
    inputLabel.appendChild(el("span", "util-chat-sr-only", tx("inputLabel")));
    const textarea = el("textarea", "util-input util-chat-input");
    textarea.id = inputId;
    textarea.name = "chat_answer";
    textarea.rows = 2;
    textarea.setAttribute("aria-invalid", "false");
    inputLabel.appendChild(textarea);

    const composerRow = el("div", "util-chat-composer-actions");
    let pcButton = null;
    let pcNote = null;
    if (pcImport) {
      pcButton = el("button", "util-chat-choice util-chat-pc-import", pcImport.label || "");
      pcButton.type = "button";
      pcButton.setAttribute("data-util-chat-pc-import", "");
      composerRow.appendChild(pcButton);
      pcNote = el("p", "util-chat-pc-note");
      pcNote.hidden = true;
      pcNote.appendChild(el("span", null, pcImport.note || ""));
      const pcConnect = el("button", "util-chat-choice util-chat-pc-connect", pcImport.connect || "");
      pcConnect.type = "button";
      pcConnect.setAttribute("data-util-chat-pc-connect", "");
      pcConnect.addEventListener("click", () => {
        if (typeof pcImport.onConnect === "function") pcImport.onConnect();
      });
      pcNote.appendChild(pcConnect);
    }
    const statusText = el("span", "util-chat-hint");
    statusText.hidden = true;
    const sendBtn = el("button", "util-generate util-chat-send", tx("send"));
    sendBtn.type = "submit";
    sendBtn.setAttribute("data-util-chat-send", "");
    composerRow.appendChild(statusText);
    composerRow.appendChild(sendBtn);

    composer.appendChild(inputLabel);
    composer.appendChild(composerRow);

    root.appendChild(summaryBar);
    root.appendChild(log);
    root.appendChild(quickChoices);
    root.appendChild(fileBar);
    root.appendChild(readyActions);
    root.appendChild(composer);
    if (pcNote) root.appendChild(pcNote);

    let values = {};
    let askedFieldKey = null;
    let readyPromptShown = false;
    let busy = false;

    function readExternalValues() {
      const fromForm = typeof opts.getValues === "function" ? opts.getValues() : {};
      const merged = Object.assign({}, values);
      if (fromForm && typeof fromForm === "object") {
        Object.keys(fromForm).forEach((key) => { merged[key] = fromForm[key]; });
      }
      values = merged;
      return values;
    }

    function pushValuesToForm() {
      if (typeof opts.setValues === "function") {
        opts.setValues(Object.assign({}, values));
      }
    }

    function setHint(message) {
      statusText.textContent = message || "";
      statusText.hidden = !message;
    }

    function appendBubble(role, text, extraAttr) {
      const item = el("div", "util-chat-turn util-chat-turn-" + role);
      item.setAttribute("data-chat-role", role);
      if (extraAttr && extraAttr.fieldKey) {
        item.setAttribute("data-question-field", extraAttr.fieldKey);
      }
      item.textContent = text;
      log.appendChild(item);
      if (typeof log.scrollTop === "number" && typeof log.scrollHeight === "number") {
        log.scrollTop = log.scrollHeight;
      }
      return item;
    }

    function renderSummary() {
      summaryChips.replaceChildren();
      (tool.fields || []).forEach((field) => {
        const shown = displayFieldValue(field, values[field.key]);
        if (!shown) return;
        if (!field.required && (field.type === "select" || field.type === "choice") && values[field.key] === field.defaultValue) {
          return;
        }
        const chip = el("span", "util-chat-summary-chip", localized(field.label) + ": " + shown);
        chip.setAttribute("data-summary-field", field.key);
        summaryChips.appendChild(chip);
      });
    }

    function renderQuickChoices(field) {
      quickChoices.replaceChildren();
      if (!field || !Array.isArray(field.options) || !field.options.length) {
        quickChoices.hidden = true;
        return;
      }
      field.options.forEach((opt) => {
        const label = localized(opt.label) || String(opt.value);
        const btn = el("button", "util-chat-choice", label);
        btn.type = "button";
        btn.setAttribute("data-choice-value", String(opt.value));
        btn.addEventListener("click", () => { void submitTurn(label, String(opt.value)); });
        quickChoices.appendChild(btn);
      });
      quickChoices.hidden = false;
    }

    function renderFileControl(field) {
      if (!field || field.type !== "file") {
        fileBar.hidden = true;
        return;
      }
      fileInput.accept = field.accept || "";
      fileInput.multiple = field.key === "files";
      const label = localized(field.label);
      filePickBtn.textContent = label ? tx("attachFile") + " · " + label : tx("attachFile");
      fileBar.hidden = false;
    }

    function currentNext() {
      return reg.nextQuestion(toolId, values, lang());
    }

    function syncPromptState() {
      renderSummary();
      const next = currentNext();
      if (next) {
        readyPromptShown = false;
        readyActions.hidden = true;
        renderQuickChoices(next.field);
        renderFileControl(next.field);
        const ph = localized(next.field && next.field.placeholder);
        textarea.placeholder = ph || next.question;
        if (askedFieldKey !== next.fieldKey) {
          askedFieldKey = next.fieldKey;
          appendBubble("assistant", next.question, { fieldKey: next.fieldKey });
        }
        return;
      }
      askedFieldKey = null;
      renderQuickChoices(null);
      renderFileControl(null);
      textarea.placeholder = tx("refinePlaceholder");
      const hasDraft = typeof opts.hasDraft === "function" ? Boolean(opts.hasDraft()) : false;
      readyActions.hidden = hasDraft;
      if (!readyPromptShown) {
        readyPromptShown = true;
        appendBubble("assistant", hasDraft ? tx("allReadyWithDraft") : tx("allReadyIdle"));
      }
    }

    async function runGenerateFromChat(refinementNote) {
      const missing = reg.missingFields(toolId, values);
      if (missing.length > 0 || busy) return false;
      busy = true;
      sendBtn.disabled = true;
      generateNowBtn.disabled = true;
      filePickBtn.disabled = true;
      readyActions.hidden = true;
      const statusBubble = appendBubble("assistant", tx("generatingTurn"));
      try {
        const ok = typeof opts.onGenerate === "function"
          ? await opts.onGenerate(Object.assign({}, values), String(refinementNote || "").trim())
          : true;
        if (ok === false) {
          statusBubble.textContent = tx("generationFailedTurn");
          return false;
        }
        statusBubble.textContent = tx("generatedTurn");
        readyPromptShown = true;
        return true;
      } catch (_) {
        statusBubble.textContent = tx("generationFailedTurn");
        return false;
      } finally {
        busy = false;
        sendBtn.disabled = false;
        generateNowBtn.disabled = false;
        filePickBtn.disabled = false;
        const hasDraft = typeof opts.hasDraft === "function" ? Boolean(opts.hasDraft()) : false;
        readyActions.hidden = hasDraft || reg.missingFields(toolId, values).length > 0;
      }
    }

    async function attachFiles(rawFiles) {
      if (busy) return false;
      const list = rawFiles ? Array.from(rawFiles).filter(Boolean) : [];
      const pending = currentNext();
      const fileField = (pending && pending.field && pending.field.type === "file")
        ? pending.field
        : (tool.fields || []).find((f) => f.type === "file");
      if (!fileField || !list.length) {
        setHint(tx("fileRequired"));
        return false;
      }
      textarea.setAttribute("aria-invalid", "false");
      setHint("");
      values[fileField.key] = list;
      appendBubble("user", fileNamesOf(list).join(", "));
      pushValuesToForm();
      const stillMissing = currentNext();
      if (stillMissing) {
        syncPromptState();
        return false;
      }
      renderSummary();
      askedFieldKey = null;
      renderQuickChoices(null);
      renderFileControl(null);
      textarea.placeholder = tx("refinePlaceholder");
      return await runGenerateFromChat("");
    }

    async function submitTurn(displayText, explicitValue) {
      if (busy) return false;
      const pending = currentNext();
      const raw = displayText !== undefined ? String(displayText) : String(textarea.value || "");
      const trimmed = raw.trim();
      if (!trimmed) {
        textarea.setAttribute("aria-invalid", "true");
        setHint(pending && pending.field && pending.field.type === "file" ? tx("fileRequired") : tx("answerRequired"));
        if (typeof textarea.focus === "function") textarea.focus();
        return false;
      }
      textarea.setAttribute("aria-invalid", "false");
      setHint("");
      textarea.value = "";
      appendBubble("user", trimmed);

      if (pending) {
        if (pending.field && pending.field.type === "file") {
          const pickedOption = matchOptionalChoice(tool.fields, trimmed);
          if (pickedOption) {
            values[pickedOption.key] = pickedOption.value;
            pushValuesToForm();
            renderSummary();
          }
          setHint(tx("fileRequired"));
          appendBubble("assistant", pending.question, { fieldKey: pending.fieldKey });
          return false;
        }
        const resolved = explicitValue !== undefined
          ? explicitValue
          : normalizeOptionAnswer(pending.field, trimmed);
        values[pending.fieldKey] = resolved;
        pushValuesToForm();
        const stillMissing = currentNext();
        if (stillMissing) {
          syncPromptState();
          return false;
        }
        renderSummary();
        askedFieldKey = null;
        renderQuickChoices(null);
        renderFileControl(null);
        textarea.placeholder = tx("refinePlaceholder");
        return await runGenerateFromChat("");
      }

      const pickedOption = matchOptionalChoice(tool.fields, trimmed);
      if (pickedOption) {
        values[pickedOption.key] = pickedOption.value;
      }
      pushValuesToForm();
      renderSummary();
      return await runGenerateFromChat(trimmed);
    }

    filePickBtn.addEventListener("click", () => {
      if (!busy && !fileInput.disabled) fileInput.click();
    });
    fileInput.addEventListener("change", () => {
      if (fileInput.files && fileInput.files.length) {
        void attachFiles(fileInput.files);
      }
      fileInput.value = "";
    });

    // Modern Web Guidance (ime-safe-enter-submit): Enter submits without Shift,
    // while guarding Korean/CJK IME composition (isComposing or keyCode 229).
    textarea.addEventListener("keydown", (event) => {
      if (event && event.key === "Enter" && !event.shiftKey) {
        if (typeof event.preventDefault === "function") event.preventDefault();
        if (event.isComposing || event.keyCode === 229) return;
        void submitTurn();
      }
    });
    textarea.addEventListener("input", () => {
      if (String(textarea.value || "").trim()) {
        textarea.setAttribute("aria-invalid", "false");
        setHint("");
      }
    });

    composer.addEventListener("submit", (event) => {
      if (event && typeof event.preventDefault === "function") event.preventDefault();
      void submitTurn();
    });

    generateNowBtn.addEventListener("click", () => { void runGenerateFromChat(""); });
    openFormBtn.addEventListener("click", () => {
      pushValuesToForm();
      if (typeof opts.onSwitchToForm === "function") opts.onSwitchToForm();
    });

    if (pcButton) {
      pcButton.addEventListener("click", async () => {
        if (busy || pcButton.disabled) return;
        pcButton.disabled = true;
        pcNote.hidden = true;
        setHint("");
        try {
          const outcome = await pcImport.run();
          if (!outcome) return;
          if (outcome.needPc) {
            pcNote.hidden = false;
            return;
          }
          if (!outcome.ok) {
            setHint(outcome.message || pcImport.failed || "");
            return;
          }
          const fieldKey = String(pcImport.fieldKey || "");
          if (!fieldKey) return;
          const current = String(values[fieldKey] || "");
          if (current.trim()) {
            const proceed = typeof window.confirm === "function"
              ? window.confirm(pcImport.confirmReplace || "") : false;
            if (!proceed) return;
          }
          values[fieldKey] = outcome.text;
          pushValuesToForm();
          appendBubble("user", String(outcome.name || pcImport.label || ""));
          syncPromptState();
        } finally {
          pcButton.disabled = false;
        }
      });
    }

    function enter(optionsOnEnter) {
      readExternalValues();
      syncPromptState();
      if (optionsOnEnter && optionsOnEnter.focusInput && typeof textarea.focus === "function") {
        textarea.focus({ preventScroll: true });
      }
    }

    return Object.freeze({
      root: root,
      enter: enter,
      submitAnswer: (text) => submitTurn(text),
      attachFiles: (files) => attachFiles(files),
      getValues: () => Object.assign({}, values),
      syncFromForm: () => { readExternalValues(); syncPromptState(); },
    });
  }

  function bindPdfmd(cfg) {
    if (!cfg || !cfg.panel || !cfg.inputCol || !cfg.formWrap || cfg.loginRequired) {
      if (cfg && cfg.inputCol && cfg.formWrap) cfg.inputCol.insertBefore(cfg.formWrap, cfg.uploadStatus || null);
      return { sync() {} };
    }
    const panel = cfg.panel;
    const hostBody = typeof panel.closest === "function" ? panel.closest(".util-tool-body") : panel.parentElement;
    const initAttr = hostBody && typeof hostBody.getAttribute === "function" ? hostBody.getAttribute("data-util-initial-mode") : null;
    const state = panel._pdfmdChatState || (panel._pdfmdChatState = {
      activeMode: initAttr === "chat" ? "chat" : "form",
      files: [],
      modeValue: cfg.modeSel ? cfg.modeSel.value : "fast",
    });
    if (cfg.modeSel && state.modeValue) {
      cfg.modeSel.value = state.modeValue;
      Array.prototype.forEach.call(cfg.modeSel.children || [], (o) => { o.selected = o.value === state.modeValue; });
      if (cfg.updateModeHelp) cfg.updateModeHelp();
    }
    if (!cfg.workBlocked && state.files.length && cfg.dropTitle) {
      cfg.dropTitle.textContent = state.files.map((f) => f.name).join(", ");
    }

    const syncValues = (vals) => {
      if (!vals || typeof vals !== "object") return;
      if (Array.isArray(vals.files)) {
        state.files = vals.files.slice();
        if (!cfg.workBlocked && state.files.length && cfg.dropTitle) {
          cfg.dropTitle.textContent = state.files.map((f) => f.name).join(", ");
        }
      }
      if (cfg.modeSel && (vals.mode === "fast" || vals.mode === "verify")) {
        cfg.modeSel.value = vals.mode;
        state.modeValue = vals.mode;
        Array.prototype.forEach.call(cfg.modeSel.children || [], (o) => { o.selected = o.value === vals.mode; });
        if (cfg.updateModeHelp) cfg.updateModeHelp();
      }
    };

    const hasResult = () => {
      const s = cfg.getState ? cfg.getState() : {};
      return Boolean(s.currentJobId || (Array.isArray(s.currentItems) && s.currentItems.length > 0));
    };

    let modeSwitch = null;
    let intake = null;
    function setMode(nextMode, focusChat) {
      if (!intake || !modeSwitch) return;
      const toChat = nextMode === "chat";
      state.activeMode = toChat ? "chat" : "form";
      panel.setAttribute("data-active-mode", state.activeMode);
      modeSwitch.setActive(state.activeMode);
      cfg.formWrap.hidden = toChat;
      intake.root.hidden = !toChat;
      if (toChat) intake.enter({ focusInput: Boolean(focusChat) });
      else syncValues(intake.getValues());
    }

    intake = create({
      toolId: "pdfmd",
      copy: {
        ko: {
          refinePlaceholder: "변환 방식을 바꾸려면 입력해 주세요 (예: 검증 변환, 빠른 변환)",
          allReadyIdle: "첨부 파일이 준비되었습니다. 바로 업로드하거나 변환 방식을 입력해 주세요.",
          allReadyWithDraft: "첨부 파일과 변환 설정을 유지하고 있습니다. 변환 방식을 바꾸려면 입력해 주세요.",
          generatingTurn: "첨부한 파일을 기존 변환 경로로 올리고 있습니다…",
          generatedTurn: "오른쪽 목록에 파일을 준비했습니다. '변환 실행'을 누르거나 '폼으로 열기'로 확인할 수 있습니다.",
        },
        en: {
          refinePlaceholder: "Enter a conversion mode to switch (e.g. Verified conversion, Fast conversion)",
          allReadyIdle: "Attached file is ready. Upload now or specify a conversion mode.",
          allReadyWithDraft: "Keeping your file and conversion mode. Reply to switch mode.",
          generatingTurn: "Uploading your attached file via the conversion pipeline…",
          generatedTurn: "Your file is in the list on the right. Run conversion there or choose 'Open in form'.",
        },
      },
      getValues: () => ({ files: state.files, mode: cfg.modeSel ? cfg.modeSel.value : "fast" }),
      setValues: syncValues,
      hasDraft: hasResult,
      onGenerate: async (vals, note) => {
        const prevMode = cfg.modeSel ? cfg.modeSel.value : "fast";
        syncValues(vals);
        if (cfg.workBlocked || !state.files.length) return false;
        const cur = cfg.getState ? cfg.getState() : {};
        if (note && cfg.modeSel && cfg.modeSel.value !== prevMode && cur.currentJobId && cfg.startNewJob) {
          cfg.startNewJob();
        }
        await cfg.uploadFiles(state.files);
        const after = cfg.getState ? cfg.getState() : {};
        return Boolean(after.currentJobId && !after.lastUploadError);
      },
      onSwitchToForm: () => setMode("form", false),
    });

    if (!intake) {
      cfg.inputCol.insertBefore(cfg.formWrap, cfg.uploadStatus || null);
      return { sync() {} };
    }

    modeSwitch = buildModeSwitch(state.activeMode, (picked) => setMode(picked, picked === "chat"));
    cfg.inputCol.insertBefore(modeSwitch.root, cfg.uploadStatus || null);
    cfg.inputCol.insertBefore(cfg.formWrap, cfg.uploadStatus || null);
    cfg.inputCol.insertBefore(intake.root, cfg.uploadStatus || null);

    let refineBtn = null;
    if (cfg.archiveControls) {
      const label = cfg.copy ? cfg.copy("util-refine-chat", t("refineInChat")) : t("refineInChat");
      refineBtn = el("button", "pdfmd-btn util-result-button", label);
      refineBtn.type = "button";
      refineBtn.disabled = !hasResult();
      refineBtn.setAttribute("data-util-refine-chat", "");
      refineBtn.addEventListener("click", () => setMode("chat", true));
      cfg.archiveControls.appendChild(refineBtn);
    }

    if (cfg.modeSel) {
      cfg.modeSel.addEventListener("change", () => { state.modeValue = cfg.modeSel.value; });
    }
    setMode(state.activeMode, false);

    return {
      recordFiles(files) { state.files = Array.isArray(files) ? files.slice() : []; },
      sync() { if (refineBtn) refineBtn.disabled = !hasResult(); },
    };
  }

  window.PadiemUtilChatMode = Object.freeze({
    buildModeSwitch: buildModeSwitch,
    create: create,
    bindPdfmd: bindPdfmd,
  });
})();
