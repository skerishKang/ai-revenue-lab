(() => {
  const app = window.WorldFeed = window.WorldFeed || {};
  const matrixRoutes = new Set(["loading", "empty", "error", "story-unavailable", "source-unavailable"]);
  const routeAnnouncements = {
    loading: "나의 피드를 정리하는 상태를 표시합니다.",
    empty: "적용한 조건에 맞는 이야기가 없습니다.",
    error: "합성 오류 상태입니다. 다시 시도할 수 있습니다.",
    "story-unavailable": "선택한 이야기를 표시할 수 없습니다. 이전 탐색으로 돌아갈 수 있습니다.",
    "source-unavailable": "연결된 실제 원문이 없습니다. 이야기 또는 이전 탐색으로 돌아갈 수 있습니다."
  };
  const timers = new Set();
  let lastRoute = null;

  function clearTimers() {
    timers.forEach((timer) => clearTimeout(timer));
    timers.clear();
  }

  function selectedStory(state) {
    return app.story.stories[state.selectedStoryId] || app.story.stories.maker;
  }

  function setText(selector, value) {
    document.querySelectorAll(selector).forEach((node) => { node.textContent = value; });
  }

  function resetAsyncControl(selector, stateName) {
    const button = document.querySelector(selector);
    if (!button) return;
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.removeAttribute("aria-disabled");
    const surface = button.closest("[data-async-state]");
    if (surface) {
      surface.dataset.asyncState = stateName;
      if (button.matches("[data-complete-loading]")) surface.dataset.loadingState = stateName;
    }
  }

  function render(state) {
    const routeChanged = state.route !== lastRoute;
    lastRoute = state.route;
    if (!["loading", "error"].includes(state.route)) clearTimers();
    const shell = document.querySelector(".review-shell");
    shell.dataset.uxState = matrixRoutes.has(state.route) ? state.route : "populated";
    document.querySelectorAll("[data-state-route]").forEach((control) => {
      const active = control.dataset.stateRoute === state.route;
      if (active) control.setAttribute("aria-current", "page");
      else control.removeAttribute("aria-current");
    });
    if (state.route === "loading") resetAsyncControl("[data-complete-loading]", "waiting");
    if (state.route === "error") resetAsyncControl("[data-retry-feed]", "ready");
    if (routeChanged && routeAnnouncements[state.route]) app.preferences?.announce(routeAnnouncements[state.route]);
    if (["story-unavailable", "source-unavailable"].includes(state.route)) {
      const story = selectedStory(state);
      setText("[data-unavailable-story-title]", story.title.join(" "));
      setText("[data-unavailable-source]", story.source);
      setText("[data-unavailable-time]", story.time);
    }
  }

  function completeAfter(button, waitingMessage, successMessage) {
    if (button.getAttribute("aria-busy") === "true") return;
    clearTimers();
    const surface = button.closest("[data-async-state]");
    button.setAttribute("aria-busy", "true");
    button.setAttribute("aria-disabled", "true");
    if (surface) {
      surface.dataset.asyncState = "working";
      if (button.matches("[data-complete-loading]")) surface.dataset.loadingState = "completing";
    }
    app.preferences.announce(waitingMessage);
    const timer = setTimeout(() => {
      timers.delete(timer);
      app.navigation.navigate("feed");
      app.preferences.announce(successMessage);
    }, 180);
    timers.add(timer);
  }

  function bindControls() {
    document.querySelectorAll("[data-state-route]").forEach((control) => {
      control.addEventListener("click", (event) => {
        event.preventDefault();
        const target = control.dataset.stateRoute;
        app.navigation.navigate(target);
      });
    });
    document.querySelector("[data-complete-loading]")?.addEventListener("click", (event) => {
      completeAfter(event.currentTarget, "나의 피드를 정리하고 있습니다.", "나의 피드를 불러왔습니다.");
    });
    document.querySelector("[data-clear-empty]")?.addEventListener("click", () => {
      app.preferences.announce("‘심야 산책 · 광주’ 조건을 해제했습니다. 전체 피드를 표시합니다.");
      app.navigation.navigate("feed");
    });
    document.querySelector("[data-retry-feed]")?.addEventListener("click", (event) => {
      completeAfter(event.currentTarget, "피드를 다시 정리하고 있습니다.", "다시 시도해 피드를 정상적으로 표시했습니다.");
    });
    document.querySelector("[data-return-story]")?.addEventListener("click", () => {
      app.navigation.navigate("story", { storyId: app.store.getState().selectedStoryId });
    });
  }

  function initialize() {
    app.store.subscribe(render);
    bindControls();
    render(app.store.getState());
  }

  app.stateMatrix = { initialize, render };
})();
