(() => {
  const app = window.WorldFeed = window.WorldFeed || {};
  const validRoutes = new Set(["feed", "nearby", "culture", "story", "why", "preferences"]);
  const routeViews = () => [...document.querySelectorAll("[data-route-view]")];
  let restoreTimer = 0;

  function routeFromHash() {
    const value = location.hash.slice(1).split("?")[0];
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
      document.querySelector(`[data-route-view="${route}"]`)?.setAttribute("data-restoring", "true");
      setTimeout(() => document.querySelector(`[data-route-view="${route}"]`)?.removeAttribute("data-restoring"), 180);
    }, 20);
    return true;
  }

  function renderRoute(route, { focusMain = false, fromHistory = false } = {}) {
    const next = validRoutes.has(route) ? route : "feed";
    document.querySelector(".review-shell").dataset.route = next;
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

  function navigate(route, { captureOrigin = false, originControl = null, replace = false } = {}) {
    const current = app.store.getState().route;
    if (captureOrigin && ["feed", "nearby", "culture"].includes(current)) {
      app.store.captureReturnContext({
        route: current,
        scrollY: window.scrollY,
        focusId: originControl?.id || document.activeElement?.id || null
      });
    }
    const method = replace ? "replaceState" : "pushState";
    history[method]({ route }, "", `#${route}`);
    renderRoute(route, { focusMain: true });
  }

  function returnToContext() {
    const context = app.store.getState().returnContext;
    const route = context?.route || "feed";
    history.pushState({ route, restored: true }, "", `#${route}`);
    renderRoute(route);
  }

  function bindNavigation() {
    document.querySelectorAll("[data-route-link]").forEach((control) => {
      control.addEventListener("click", (event) => {
        event.preventDefault();
        const target = control.dataset.routeLink;
        const preserve = ["story", "why", "preferences"].includes(target);
        navigate(target, { captureOrigin: preserve && target === "story", originControl: control });
      });
    });
    document.querySelectorAll("[data-return-context]").forEach((control) => {
      control.addEventListener("click", returnToContext);
    });
    addEventListener("popstate", () => renderRoute(routeFromHash(), { fromHistory: true }));
  }

  function initialize() {
    if ("scrollRestoration" in history) history.scrollRestoration = "manual";
    const route = routeFromHash();
    history.replaceState({ route }, "", `#${route}`);
    bindNavigation();
    renderRoute(route);
  }

  app.navigation = { initialize, navigate, renderRoute, returnToContext, routeFromHash };
})();
