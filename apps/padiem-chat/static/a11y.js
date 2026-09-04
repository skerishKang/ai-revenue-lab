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

  installConfirmDialog();

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
})();