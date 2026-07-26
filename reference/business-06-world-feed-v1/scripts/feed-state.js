(() => {
  const app = window.WorldFeed = window.WorldFeed || {};
  const listeners = new Set();
  const validStoryIds = new Set(["maker", "market-studio", "harbor", "cinema"]);
  const state = {
    route: "feed",
    filter: "feed",
    preference: "default",
    previousPreference: "default",
    selectedStoryId: "maker",
    returnContext: null,
    reducedMotion: false
  };

  function snapshot() {
    return {
      route: state.route,
      filter: state.filter,
      preference: state.preference,
      previousPreference: state.previousPreference,
      selectedStoryId: state.selectedStoryId,
      returnContext: state.returnContext ? { ...state.returnContext } : null,
      reducedMotion: state.reducedMotion
    };
  }

  function emit(reason) {
    const detail = snapshot();
    listeners.forEach((listener) => listener(detail, reason));
    dispatchEvent(new CustomEvent("world-feed-state", { detail: { state: detail, reason } }));
  }

  function setRoute(route) {
    state.route = route;
    if (["feed", "nearby", "culture"].includes(route)) state.filter = route;
    emit("route");
  }

  function setStoryId(storyId) {
    const next = validStoryIds.has(storyId) ? storyId : "maker";
    if (next === state.selectedStoryId) return;
    state.selectedStoryId = next;
    emit("story");
  }

  function setPreference(value) {
    if (!["default", "nearby"].includes(value) || value === state.preference) return;
    state.previousPreference = state.preference;
    state.preference = value;
    emit("preference");
  }

  function undoPreference() {
    const next = state.previousPreference;
    state.previousPreference = state.preference;
    state.preference = next;
    emit("undo");
  }

  function resetAll() {
    state.filter = "feed";
    state.previousPreference = state.preference;
    state.preference = "default";
    state.selectedStoryId = "maker";
    emit("reset");
  }

  function captureReturnContext({ route, scrollY, focusId }) {
    state.returnContext = { route, scrollY, focusId };
    emit("context-captured");
  }

  function clearReturnContext() {
    state.returnContext = null;
    emit("context-cleared");
  }

  function setReducedMotion(matches) {
    state.reducedMotion = Boolean(matches);
    document.documentElement.dataset.reducedMotion = String(state.reducedMotion);
    emit("reduced-motion");
  }

  function subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  app.store = {
    getState: snapshot,
    setRoute,
    setStoryId,
    setPreference,
    undoPreference,
    resetAll,
    captureReturnContext,
    clearReturnContext,
    setReducedMotion,
    subscribe
  };
})();
