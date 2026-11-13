// #7216 R5 1단계 — 설정 구역 (app.js 클로저에서 이동).
// 동작·문구·DOM id·이벤트 이름 변경 없음. 공유 상태와 DOM 참조는 deps getter/
// setter로만 읽고 쓴다. app.js는 같은 이름의 한 줄 전달 함수를 유지한다.
(() => {
  "use strict";
  window.PadiemChatSettingsModule = {
    create(deps) {
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
          deps.advancedSettingsReturnState = deps.shell.dataset.state;
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
        deps.shell.dataset.state = deps.advancedSettingsReturnState || "home";
        deps.advancedSettingsReturnState = null;
        deps.setNavActive();
        window.dispatchEvent(new CustomEvent("padiem:advanced-settings-close"));
      }

      // R5 A7 후속: app.js에 남았던 고급 설정 메뉴 전환을 settings 모듈로 합쳤다.
      const advancedMenuButtons = deps.advancedMenuButtons;
      const advancedPageBlocks = deps.advancedPageBlocks;
      function selectAdvancedMenu(key) {
        for (const button of advancedMenuButtons) {
          button.classList.toggle("selected", button.dataset.advancedMenu === key);
        }
        for (const block of advancedPageBlocks) {
          block.hidden = block.dataset.advancedBlock !== key;
        }
      }

      // R5 A7 후속 (rule (b)): app.js의 원래 블록 자리에서 호출된다.
      function wireAdvancedMenuListeners() {
        for (const button of advancedMenuButtons) {
          button.addEventListener("click", () => selectAdvancedMenu(button.dataset.advancedMenu));
        }
      }

      return { selectedProductTier, openSettings, closeSettings, openAdvancedSettingsView, closeAdvancedSettingsView, selectAdvancedMenu, wireAdvancedMenuListeners };
    },
  };
})();
