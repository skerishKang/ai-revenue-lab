// #7216 R5 1단계 — 설정 구역 (app.js 클로저에서 이동).
// 동작·문구·DOM id·이벤트 이름 변경 없음. 공유 상태와 DOM 참조는 deps getter/
// setter로만 읽고 쓴다. app.js는 같은 이름의 한 줄 전달 함수를 유지한다.
(() => {
  "use strict";
  window.PadiemChatSettingsModule = {
    create(deps) {
      // #7812 R5 B5: settings-only DOM/state lives here (create() reads no deps).
      // The full page opens on top of the screen the user came from (home, chat
      // or claw); its back entry returns there instead of assuming home.
      let advancedSettingsReturnState = null;
      const settingsCloseButton = document.getElementById("settingsCloseButton");
      const settingsAdvancedOpen = document.getElementById("settingsAdvancedOpen");
      const advancedSettingsBack = document.getElementById("advancedSettingsBack");
      const advancedMenuButtons = [...document.querySelectorAll(".advanced-menu-link")];
      const advancedPageBlocks = [...document.querySelectorAll(".advanced-page-block")];

      // #4317/#5222: product-capabilities.js owns the tier state; an account
      // that chose a tier keeps it across reloads and the server re-validates.
      function selectedProductTier() {
        const tier = window.PadiemTierSelection?.get?.();
        return ["free", "plus", "pro", "max", "admin"].includes(tier) ? tier : "free";
      }
      function openSettings() {
        if (typeof deps.settingsDialog.showModal === "function") deps.settingsDialog.showModal();
        else deps.settingsDialog.setAttribute("open", "");
        deps.settingsButton.setAttribute("aria-expanded", "true");
        deps.profileToggle.setAttribute("aria-expanded", "true");
      }
      function closeSettings() {
        if (deps.settingsDialog.open && typeof deps.settingsDialog.close === "function") deps.settingsDialog.close();
        else deps.settingsDialog.removeAttribute("open");
        deps.settingsButton.setAttribute("aria-expanded", "false");
        deps.profileToggle.setAttribute("aria-expanded", "false");
      }
      function openAdvancedSettingsView() {
        if (!deps.advancedSettingsView) { openSettings(); return; }
        closeSettings();
        if (deps.shell.dataset.state && deps.shell.dataset.state !== "settings") {
          advancedSettingsReturnState = deps.shell.dataset.state;
        }
        deps.advancedSettingsView.hidden = false;
        deps.shell.dataset.state = "settings";
        deps.setNavActive();
        selectAdvancedMenu("pc");
        window.dispatchEvent(new CustomEvent("padiem:advanced-settings-open"));
      }
      function closeAdvancedSettingsView() {
        if (!deps.advancedSettingsView) return;
        deps.advancedSettingsView.hidden = true;
        deps.shell.dataset.state = advancedSettingsReturnState || "home";
        advancedSettingsReturnState = null;
        deps.setNavActive();
        window.dispatchEvent(new CustomEvent("padiem:advanced-settings-close"));
      }

      // R5 A7 후속: app.js에 남았던 고급 설정 메뉴 전환을 settings 모듈로 합쳤다.
      function selectAdvancedMenu(key) {
        for (const button of advancedMenuButtons) {
          button.classList.toggle("selected", button.dataset.advancedMenu === key);
        }
        for (const block of advancedPageBlocks) {
          block.hidden = block.dataset.advancedBlock !== key;
        }
      }

      // #7812 R5 B5 (rule (b)): registered from app.js at the original blocks so
      // the document-level order is unchanged.
      function wireTierChange() {
        window.addEventListener("padiem:tierchange", () => {
          if (deps.shell.dataset.state === "claw") deps.shell.dataset.clawTier = selectedProductTier();
        });
      }

      function wireAdvancedSettings() {
        if (settingsAdvancedOpen) settingsAdvancedOpen.addEventListener("click", () => {
          closeSettings();
          openAdvancedSettingsView();
        });
        if (advancedSettingsBack) advancedSettingsBack.addEventListener("click", () => { closeAdvancedSettingsView(); });
        // Escape takes the same close path as the back entry. An open dialog
        // inside the page (password change, deletes) keeps Escape for itself.
        document.addEventListener("keydown", (event) => {
          if (event.key !== "Escape" || event.isComposing) return;
          if (!deps.advancedSettingsView || deps.advancedSettingsView.hidden) return;
          if (document.querySelector("dialog[open]")) return;
          closeAdvancedSettingsView();
        });
      }

      function wireSettingsDialog() {
        deps.settingsDialog.addEventListener("cancel", (event) => {
          event.preventDefault();
          closeSettings();
        });
        // The dialog element is the panel itself, so a backdrop click reports the
        // dialog as the target. Any click inside the panel hits a descendant first.
        deps.settingsDialog.addEventListener("click", (event) => {
          if (event.target === deps.settingsDialog) closeSettings();
        });
        settingsCloseButton.addEventListener("click", closeSettings);
      }

      // R5 A7 후속 (rule (b)): app.js의 원래 블록 자리에서 호출된다.
      function wireAdvancedMenuListeners() {
        for (const button of advancedMenuButtons) {
          button.addEventListener("click", () => selectAdvancedMenu(button.dataset.advancedMenu));
        }
      }

      return { selectedProductTier, openSettings, closeSettings, openAdvancedSettingsView, closeAdvancedSettingsView, selectAdvancedMenu, wireTierChange, wireAdvancedSettings, wireSettingsDialog, wireAdvancedMenuListeners };
    },
  };
})();
