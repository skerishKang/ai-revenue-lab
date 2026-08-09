(() => {
  const app = window.WorldFeed = window.WorldFeed || {};
  const liveRegion = () => document.querySelector("[data-live-region]");
  let liveTimer = 0;

  function announce(message) {
    const region = liveRegion();
    if (!region) return;
    clearTimeout(liveTimer);
    region.textContent = message;
    liveTimer = setTimeout(() => { region.textContent = ""; }, 4200);
  }

  function renderPreference(state) {
    const applied = state.preference === "nearby";
    document.querySelector(".review-shell").dataset.preference = state.preference;
    document.querySelectorAll("[data-feed-variant]").forEach((variant) => {
      variant.hidden = variant.dataset.feedVariant !== (applied ? "nearby" : "default");
    });
    document.querySelector("[data-preference-banner]").hidden = !applied;
    document.querySelectorAll("[data-undo-preference]").forEach((button) => { button.disabled = !applied; });
    const label = document.querySelector("[data-preference-state-label]");
    if (label) label.textContent = applied ? "적용됨 · 가까운 이야기가 피드 앞쪽으로 이동합니다." : "아직 변경하지 않았습니다.";
    const preview = document.querySelector("[data-after-preview]");
    if (preview) preview.dataset.active = String(applied);
  }

  function bindPreferenceControls() {
    document.querySelectorAll("[data-apply-preference]").forEach((button) => {
      button.addEventListener("click", () => {
        app.store.setPreference("nearby");
        announce("동네 소식 더 보기가 적용되었습니다. 변경된 나의 피드로 이동합니다.");
        app.navigation.navigate("feed");
      });
    });
    document.querySelectorAll("[data-undo-preference]").forEach((button) => {
      button.addEventListener("click", () => {
        if (app.store.getState().preference === "default") return;
        app.store.undoPreference();
        announce("선호 변경을 실행 취소했습니다. 기존 피드 순서로 돌아갑니다.");
      });
    });
    document.querySelectorAll("[data-reset-all]").forEach((button) => {
      button.addEventListener("click", () => {
        app.store.resetAll();
        announce("필터와 선호를 모두 초기화했습니다.");
        app.navigation.navigate("feed");
      });
    });
    document.querySelectorAll("[data-reset-filter]").forEach((button) => {
      button.addEventListener("click", () => app.navigation.navigate("feed"));
    });
  }

  function initialize() {
    app.store.subscribe(renderPreference);
    bindPreferenceControls();
    renderPreference(app.store.getState());
  }

  app.preferences = { initialize, announce, renderPreference };
})();
