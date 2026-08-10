(() => {
  const app = window.WorldFeed = window.WorldFeed || {};
  const validRoutes = new Set([
    "loading", "feed", "nearby", "culture", "story", "why", "preferences",
    "empty", "error", "story-unavailable", "source-unavailable"
  ]);
  const routeViews = () => [...document.querySelectorAll("[data-route-view]")];
  let restoreTimer = 0;

  function routeFromHash() {
    const value = location.hash.slice(1).split("?")[0];
    // V4 is the product entry. The legacy loading route remains available to
    // the in-app state matrix via navigate("loading"), but external entry and
    // stale #loading deep-links normalize to the cinematic feed.
    if (!value || value === "loading") return "feed";
    return validRoutes.has(value) ? value : "feed";
  }

  function updateNavigation(route) {
    document.querySelectorAll("[data-route-link]").forEach((control) => {
      const active = control.dataset.routeLink === route;
      if (control.matches("a")) {
        if (active) control.setAttribute("aria-current", "page");
        else control.removeAttribute("aria-current");
      }
      control.classList.toggle("is-selected", active);
    });
  }

  function animateTopicRoute(route) {
    if (!["nearby", "culture"].includes(route)) return;
    const layout = document.querySelector(`[data-route-view="${route}"] .topic-layout`);
    if (!layout) return;
    layout.classList.add("is-shifting");
    const duration = app.store.getState().reducedMotion ? 20 : 680;
    setTimeout(() => layout.classList.remove("is-shifting"), duration);
  }

  function setScrollInstant(top) {
    const root = document.documentElement;
    const previous = root.style.scrollBehavior;
    root.style.scrollBehavior = "auto";
    window.scrollTo(0, top);
    requestAnimationFrame(() => window.scrollTo(0, top));
    setTimeout(() => { root.style.scrollBehavior = previous; }, 80);
  }

  function restoreContextIfNeeded(route) {
    const context = app.store.getState().returnContext;
    if (!context || context.route !== route) return false;
    clearTimeout(restoreTimer);
    const root = document.documentElement;
    const previousScrollBehavior = root.style.scrollBehavior;
    const restore = () => {
      root.style.scrollBehavior = "auto";
      window.scrollTo(0, context.scrollY);
      const control = context.focusId ? document.getElementById(context.focusId) : null;
      control?.focus({ preventScroll: true });
    };
    restoreTimer = setTimeout(() => {
      restore();
      requestAnimationFrame(restore);
      setTimeout(restore, 80);
      setTimeout(() => { root.style.scrollBehavior = previousScrollBehavior; }, 140);
      const view = document.querySelector(`[data-route-view="${route}"]`);
      view?.setAttribute("data-restoring", "true");
      setTimeout(() => view?.removeAttribute("data-restoring"), 180);
    }, 20);
    return true;
  }

  function currentHistoryState(route) {
    return { route, storyId: app.store.getState().selectedStoryId };
  }

  function renderRoute(route, { focusMain = false, fromHistory = false, storyId = null } = {}) {
    const next = validRoutes.has(route) ? route : "feed";
    if (storyId) app.store.setStoryId(storyId);
    const shell = document.querySelector(".review-shell");
    shell.dataset.route = next;
    shell.dataset.storyId = app.store.getState().selectedStoryId;
    routeViews().forEach((view) => {
      const active = view.dataset.routeView === next;
      view.hidden = !active;
      view.classList.toggle("is-active", active);
    });
    updateNavigation(next);
    app.store.setRoute(next);
    animateTopicRoute(next);
    const restoring = restoreContextIfNeeded(next);
    if (!restoring) setScrollInstant(0);
    if (focusMain && !fromHistory) document.getElementById("main")?.focus({ preventScroll: true });
  }

  function navigate(route, { captureOrigin = false, originControl = null, replace = false, storyId = null } = {}) {
    const current = app.store.getState().route;
    if (captureOrigin && ["feed", "nearby", "culture"].includes(current)) {
      app.store.captureReturnContext({
        route: current,
        scrollY: window.scrollY,
        focusId: originControl?.id || document.activeElement?.id || null
      });
    }
    if (storyId) app.store.setStoryId(storyId);
    const method = replace ? "replaceState" : "pushState";
    history[method](currentHistoryState(route), "", `#${route}`);
    renderRoute(route, { focusMain: true });
  }

  function returnToContext() {
    const context = app.store.getState().returnContext;
    const route = context?.route || "feed";
    history.pushState(currentHistoryState(route), "", `#${route}`);
    renderRoute(route);
  }

  function bindNavigation() {
    document.querySelectorAll("[data-route-link]").forEach((control) => {
      control.addEventListener("click", (event) => {
        event.preventDefault();
        const target = control.dataset.routeLink;
        navigate(target, { captureOrigin: target === "story", originControl: control });
      });
    });
    document.querySelectorAll("[data-return-context]").forEach((control) => {
      control.addEventListener("click", returnToContext);
    });
    addEventListener("popstate", (event) => {
      const route = event.state?.route || routeFromHash();
      renderRoute(route, { fromHistory: true, storyId: event.state?.storyId || null });
    });
  }

  function initialize() {
    if ("scrollRestoration" in history) history.scrollRestoration = "manual";
    const route = routeFromHash();
    const storyId = history.state?.storyId || app.store.getState().selectedStoryId;
    app.store.setStoryId(storyId);
    history.replaceState(currentHistoryState(route), "", `#${route}`);
    bindNavigation();
    renderRoute(route, { storyId });
  }

  app.navigation = { initialize, navigate, renderRoute, returnToContext, routeFromHash };
})();
