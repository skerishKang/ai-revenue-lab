(() => {
  const app = window.WorldFeed;
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");

  function syncFilterLabel(state) {
    const labels = { feed: "나의 피드", nearby: "가까운 동네", culture: "장소와 문화" };
    document.querySelectorAll("[data-current-filter-label]").forEach((node) => {
      node.textContent = labels[state.filter] || labels.feed;
    });
  }

  function initialize() {
    app.store.subscribe(syncFilterLabel);
    app.store.setReducedMotion(reducedMotion.matches);
    reducedMotion.addEventListener?.("change", (event) => app.store.setReducedMotion(event.matches));
    app.navigation.initialize();
    app.story.initialize();
    app.preferences.initialize();
    app.stateMatrix.initialize();
    syncFilterLabel(app.store.getState());
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, { once: true });
  else initialize();
})();
