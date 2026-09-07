(() => {
  "use strict";

  function installConfirmDialog() {
    if (window.PadiemConfirmDialog) return;

    const dialog = document.createElement("dialog");
    dialog.id = "confirmDialog";
    dialog.className = "confirm-dialog";
    dialog.setAttribute("aria-labelledby", "confirmDialogTitle");
    dialog.setAttribute("aria-describedby", "confirmDialogMessage");

    const panel = document.createElement("section");
    panel.className = "confirm-dialog-panel";

    const kicker = document.createElement("p");
    kicker.className = "confirm-dialog-kicker";
    kicker.textContent = "확인";

    const title = document.createElement("h2");
    title.id = "confirmDialogTitle";

    const message = document.createElement("p");
    message.id = "confirmDialogMessage";
    message.className = "confirm-dialog-copy";

    const actions = document.createElement("div");
    actions.className = "confirm-dialog-actions";

    const cancelButton = document.createElement("button");
    cancelButton.id = "confirmDialogCancel";
    cancelButton.type = "button";
    cancelButton.className = "confirm-dialog-cancel";
    cancelButton.textContent = "취소";

    const confirmButton = document.createElement("button");
    confirmButton.id = "confirmDialogConfirm";
    confirmButton.type = "button";
    confirmButton.className = "confirm-dialog-confirm";
    confirmButton.textContent = "삭제";

    actions.append(cancelButton, confirmButton);
    panel.append(kicker, title, message, actions);
    dialog.appendChild(panel);
    document.body.appendChild(dialog);

    let active = null;

    function watchRecoverableTrigger(returnFocus) {
      if (!(returnFocus instanceof HTMLButtonElement)) return;
      let sawDisabled = returnFocus.disabled;
      const observer = new MutationObserver(() => {
        if (!returnFocus.isConnected) {
          observer.disconnect();
          return;
        }
        if (returnFocus.disabled) {
          sawDisabled = true;
          return;
        }
        if (!sawDisabled) return;
        const ownerDialog = returnFocus.closest("dialog");
        if (!ownerDialog || ownerDialog.open) returnFocus.focus();
        observer.disconnect();
      });
      observer.observe(returnFocus, { attributes: true, attributeFilter: ["disabled"] });
      window.setTimeout(() => observer.disconnect(), 5000);
    }

    function settle(value) {
      if (!active) return;
      const current = active;
      active = null;
      if (dialog.open) dialog.close();
      if (value === true) watchRecoverableTrigger(current.returnFocus);
      queueMicrotask(() => {
        if (current.returnFocus && current.returnFocus.isConnected && typeof current.returnFocus.focus === "function") {
          current.returnFocus.focus();
        }
        current.resolve(value === true);
      });
    }

    cancelButton.addEventListener("click", () => settle(false));
    confirmButton.addEventListener("click", () => settle(true));
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      settle(false);
    });
    dialog.addEventListener("keydown", (event) => {
      if (!active) return;
      if (event.key === "Escape") {
        // The modal owns Escape. Do not let the mobile drawer's Escape handler
        // close the underlying sidebar while confirmation is settling.
        event.stopPropagation();
        return;
      }
      if (event.key !== "Tab") return;
      const focusables = [cancelButton, confirmButton].filter((button) => !button.disabled && !button.hidden);
      if (focusables.length < 2) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

    window.PadiemConfirmDialog = Object.freeze({
      confirm(options = {}) {
        if (active || dialog.open) return Promise.resolve(false);
        const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        title.textContent = typeof options.title === "string" && options.title.trim() ? options.title.trim() : "삭제할까요?";
        message.textContent = typeof options.message === "string" ? options.message.trim() : "이 작업은 되돌릴 수 없습니다.";
        cancelButton.textContent = typeof options.cancelLabel === "string" && options.cancelLabel.trim() ? options.cancelLabel.trim() : "취소";
        confirmButton.textContent = typeof options.confirmLabel === "string" && options.confirmLabel.trim() ? options.confirmLabel.trim() : "삭제";
        return new Promise((resolve) => {
          active = { resolve, returnFocus };
          dialog.showModal();
          cancelButton.focus();
        });
      },
    });
  }

  function installClawManualIntakeShell() {
    const navButton = document.getElementById("clawNavButton");
    const dialog = document.getElementById("clawDialog");
    const closeButton = document.getElementById("clawDialogClose");
    if (!navButton || !dialog || dialog.dataset.manualIntakeShell === "true") return;

    const copy = document.documentElement.lang === "en" ? {
      status: "Manual intake preview shell — no backend route, storage, connector, or send action is connected.",
      channel: "Source channel",
      sender: "Sender/customer hint",
      senderPlaceholder: "Optional customer, vendor, or sender name",
      action: "Draft action",
      request: "Paste request text",
      requestPlaceholder: "Paste a KakaoTalk, SMS, email, Telegram, Discord, or other business request here.",
      generate: "Create preview draft",
      empty: "Paste request text before creating a preview.",
      result: "Preview result",
      resultReady: "Client-side preview only. This draft is not stored and is lost on refresh.",
      channelLabel: "Channel",
      actionLabel: "Action",
      senderLabel: "Sender hint",
      sourceLabel: "Source text",
      controls: [
        ["Markdown download", "Disabled until backend wiring"],
        ["DOCX download", "Disabled until backend wiring"],
        ["Memory save proposal", "Approval-gated / coming soon"],
        ["Email send", "User approval required / coming soon"],
        ["Share link", "Available only after storage connection"],
      ],
      channels: [["kakao", "KakaoTalk"], ["sms", "SMS"], ["email", "Email"], ["telegram", "Telegram"], ["discord", "Discord"], ["other", "Other"]],
      actions: [["quote", "Quote draft"], ["order", "Purchase order draft"], ["reply", "Reply draft"], ["summary", "Request summary"]],
    } : {
      status: "수동 인입 미리보기 셸 — 백엔드 경로, 저장소, 커넥터, 발송 기능은 아직 연결되지 않았습니다.",
      channel: "원문 채널",
      sender: "보낸 사람/거래처 힌트",
      senderPlaceholder: "선택 입력: 고객사, 공급사, 발신자명",
      action: "초안 작업",
      request: "요청 원문 붙여넣기",
      requestPlaceholder: "카카오톡, 문자, 이메일, Telegram, Discord 등으로 받은 업무 요청을 붙여넣으세요.",
      generate: "초안 만들기",
      empty: "요청 원문을 붙여넣은 뒤 초안을 만들 수 있습니다.",
      result: "미리보기 결과",
      resultReady: "클라이언트 미리보기 전용입니다. 저장되지 않으며 새로고침하면 사라집니다.",
      channelLabel: "채널",
      actionLabel: "작업",
      senderLabel: "발신자 힌트",
      sourceLabel: "요청 원문",
      controls: [
        ["Markdown 다운로드", "백엔드 연결 전까지 비활성화"],
        ["DOCX 다운로드", "백엔드 연결 전까지 비활성화"],
        ["메모리 저장 후보", "사용자 승인 필요 / 준비 중"],
        ["이메일 발송", "사용자 승인 필요 / 준비 중"],
        ["공유 링크", "저장소 연결 후 가능"],
      ],
      channels: [["kakao", "KakaoTalk"], ["sms", "SMS"], ["email", "Email"], ["telegram", "Telegram"], ["discord", "Discord"], ["other", "Other"]],
      actions: [["quote", "견적서 초안"], ["order", "발주서 초안"], ["reply", "답장 초안"], ["summary", "요청사항 정리"]],
    };

    function optionList(items) {
      return items.map(([value, label]) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        return option;
      });
    }

    function field(labelText, inputElement) {
      const label = document.createElement("label");
      label.className = "claw-field";
      const span = document.createElement("span");
      span.textContent = labelText;
      label.append(span, inputElement);
      return label;
    }

    function disabledControl(title, note) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "claw-disabled-control";
      button.disabled = true;
      button.setAttribute("aria-disabled", "true");
      const strong = document.createElement("strong");
      strong.textContent = title;
      const small = document.createElement("small");
      small.textContent = note;
      button.append(strong, small);
      return button;
    }

    const status = dialog.querySelector(".capability-status");
    if (status) status.textContent = copy.status;

    const oldGrid = dialog.querySelector(".capability-grid");
    if (oldGrid) oldGrid.remove();

    const form = document.createElement("form");
    form.className = "claw-manual-form";
    form.setAttribute("aria-label", copy.status);

    const row = document.createElement("div");
    row.className = "claw-field-row";

    const channel = document.createElement("select");
    channel.id = "clawChannel";
    optionList(copy.channels).forEach((option) => channel.appendChild(option));

    const action = document.createElement("select");
    action.id = "clawAction";
    optionList(copy.actions).forEach((option) => action.appendChild(option));

    row.append(field(copy.channel, channel), field(copy.action, action));

    const sender = document.createElement("input");
    sender.id = "clawSender";
    sender.type = "text";
    sender.maxLength = 120;
    sender.autocomplete = "off";
    sender.placeholder = copy.senderPlaceholder;

    const request = document.createElement("textarea");
    request.id = "clawRequestText";
    request.rows = 7;
    request.maxLength = 4000;
    request.autocomplete = "off";
    request.placeholder = copy.requestPlaceholder;

    const generate = document.createElement("button");
    generate.id = "clawGenerateBtn";
    generate.type = "submit";
    generate.className = "claw-generate-button";
    generate.textContent = copy.generate;

    const resultArea = document.createElement("section");
    resultArea.id = "clawResultArea";
    resultArea.className = "claw-result-area";
    resultArea.setAttribute("aria-live", "polite");
    const resultTitle = document.createElement("strong");
    resultTitle.textContent = copy.result;
    const resultPreview = document.createElement("pre");
    resultPreview.id = "clawResultPreview";
    resultPreview.textContent = copy.empty;
    resultArea.append(resultTitle, resultPreview);

    const controls = document.createElement("div");
    controls.className = "claw-disabled-controls";
    copy.controls.forEach(([title, note]) => controls.appendChild(disabledControl(title, note)));

    form.append(row, field(copy.sender, sender), field(copy.request, request), generate, resultArea, controls);
    dialog.appendChild(form);

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const body = request.value.trim();
      if (!body) {
        resultPreview.textContent = copy.empty;
        request.focus();
        return;
      }
      const channelText = channel.options[channel.selectedIndex].textContent || channel.value;
      const actionText = action.options[action.selectedIndex].textContent || action.value;
      const senderText = sender.value.trim() || "-";
      const clipped = body.length > 900 ? `${body.slice(0, 900)}…` : body;
      resultPreview.textContent = [
        copy.resultReady,
        "",
        `${copy.channelLabel}: ${channelText}`,
        `${copy.actionLabel}: ${actionText}`,
        `${copy.senderLabel}: ${senderText}`,
        "",
        `${copy.sourceLabel}:`,
        clipped,
      ].join("\n");
    });

    navButton.disabled = false;
    navButton.removeAttribute("disabled");
    navButton.setAttribute("aria-disabled", "false");
    navButton.addEventListener("click", () => {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
      navButton.setAttribute("aria-expanded", "true");
      request.focus();
    });

    function closeDialog() {
      if (dialog.open && typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      navButton.setAttribute("aria-expanded", "false");
      navButton.focus();
    }

    if (closeButton) closeButton.addEventListener("click", closeDialog);
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      closeDialog();
    });
    dialog.addEventListener("close", () => navButton.setAttribute("aria-expanded", "false"));
    dialog.dataset.manualIntakeShell = "true";
  }

  function installClawManualStyles() {
    if (document.querySelector("style[data-claw-manual-intake]")) return;
    const style = document.createElement("style");
    style.dataset.clawManualIntake = "true";
    style.textContent = `
      .claw-manual-form { display: grid; gap: 16px; margin-top: 18px; }
      .claw-field-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
      .claw-field { display: grid; gap: 8px; color: var(--text-muted, #9aa4b2); font-size: 0.84rem; }
      .claw-field input, .claw-field select, .claw-field textarea { width: 100%; border: 1px solid rgba(148, 163, 184, 0.28); border-radius: 14px; background: rgba(15, 23, 42, 0.72); color: inherit; padding: 11px 12px; font: inherit; }
      .claw-field textarea { min-height: 138px; resize: vertical; }
      .claw-generate-button { border: 0; border-radius: 999px; padding: 12px 16px; font-weight: 800; cursor: pointer; color: #07111f; background: linear-gradient(135deg, #f8fafc, #c7d2fe); }
      .claw-result-area { display: grid; gap: 8px; border: 1px solid rgba(148, 163, 184, 0.2); border-radius: 18px; padding: 14px; background: rgba(15, 23, 42, 0.46); }
      .claw-result-area pre { margin: 0; white-space: pre-wrap; word-break: break-word; color: var(--text, #e5e7eb); font-family: inherit; }
      .claw-disabled-controls { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
      .claw-disabled-control { text-align: left; border: 1px solid rgba(148, 163, 184, 0.16); border-radius: 14px; padding: 12px; background: rgba(148, 163, 184, 0.08); color: var(--text-muted, #94a3b8); }
      .claw-disabled-control strong, .claw-disabled-control small { display: block; }
      .claw-disabled-control small { margin-top: 4px; opacity: 0.8; }
      @media (max-width: 720px) { .claw-field-row, .claw-disabled-controls { grid-template-columns: 1fr; } }
    `;
    document.head.appendChild(style);
  }

  installConfirmDialog();
  installClawManualStyles();
  installClawManualIntakeShell();

  const shell = document.querySelector(".app-shell");
  const sidebar = document.getElementById("sidebar");
  const mainPanel = document.querySelector(".main-panel");
  const mobileMenu = document.getElementById("mobileMenu");
  const mobileClose = document.getElementById("mobileClose");
  const sidebarScrim = document.getElementById("sidebarScrim");
  if (!shell || !sidebar || !mainPanel || !mobileMenu || !mobileClose || !sidebarScrim) return;

  const mobileViewport = window.matchMedia("(max-width: 920px)");
  let escapeStartedOpen = false;

  function syncDrawerAccessibility() {
    const mobile = mobileViewport.matches;
    const open = mobile && shell.classList.contains("sidebar-open");

    if (!mobile) {
      sidebar.inert = false;
      mainPanel.inert = false;
      if (shell.classList.contains("sidebar-open")) shell.classList.remove("sidebar-open");
      mobileMenu.setAttribute("aria-expanded", "false");
      sidebarScrim.hidden = true;
      return;
    }

    sidebar.inert = !open;
    mainPanel.inert = open;
    mobileMenu.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function restoreMenuFocus() {
    if (!mobileViewport.matches) return;
    syncDrawerAccessibility();
    mobileMenu.focus();
  }

  mobileMenu.addEventListener("click", () => {
    syncDrawerAccessibility();
    if (shell.classList.contains("sidebar-open")) mobileClose.focus();
  });

  mobileClose.addEventListener("click", restoreMenuFocus);
  sidebarScrim.addEventListener("click", restoreMenuFocus);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") escapeStartedOpen = mobileViewport.matches && shell.classList.contains("sidebar-open");
  }, true);

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !escapeStartedOpen) return;
    escapeStartedOpen = false;
    queueMicrotask(restoreMenuFocus);
  });

  const drawerObserver = new MutationObserver(syncDrawerAccessibility);
  drawerObserver.observe(shell, { attributes: true, attributeFilter: ["class"] });
  mobileViewport.addEventListener("change", syncDrawerAccessibility);
  syncDrawerAccessibility();

  if (!document.querySelector("script[data-interaction-polish-loader]")) {
    const interactionPolish = document.createElement("script");
    interactionPolish.src = "./interaction-polish.js";
    interactionPolish.dataset.interactionPolishLoader = "true";
    document.head.appendChild(interactionPolish);
  }
})();