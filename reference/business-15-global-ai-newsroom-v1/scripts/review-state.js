(() => {
  "use strict";

  const version = "global-ai-newsroom-20260728-1";
  const tabs = Array.from(document.querySelectorAll("[data-state-target]"));
  const panels = Array.from(document.querySelectorAll("[data-review-state]"));
  const motionButton = document.querySelector("[data-convergence-play]");
  const validStates = new Set(panels.map((panel) => panel.dataset.reviewState));

  function requestedState() {
    const params = new URLSearchParams(window.location.search);
    const state = params.get("state");
    return validStates.has(state) ? state : "global";
  }

  function setState(state, { focusPanel = false, updateUrl = true } = {}) {
    if (!validStates.has(state)) return;
    document.body.dataset.activeState = state;

    for (const panel of panels) {
      const active = panel.dataset.reviewState === state;
      panel.hidden = !active;
      if (active && focusPanel) panel.focus({ preventScroll: true });
    }

    for (const tab of tabs) {
      const active = tab.dataset.stateTarget === state;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    }

    if (updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set("state", state);
      try {
        history.replaceState({ state, version }, "", url);
      } catch {
        // In-memory visual validation may not expose a mutable document URL.
      }
    }
  }

  function moveTab(currentIndex, direction) {
    const nextIndex = (currentIndex + direction + tabs.length) % tabs.length;
    tabs[nextIndex].focus();
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => setState(tab.dataset.stateTarget));
    tab.addEventListener("keydown", (event) => {
      if (event.key === "ArrowRight" || event.key === "ArrowDown") {
        event.preventDefault();
        moveTab(index, 1);
      } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
        event.preventDefault();
        moveTab(index, -1);
      } else if (event.key === "Home") {
        event.preventDefault();
        tabs[0].focus();
      } else if (event.key === "End") {
        event.preventDefault();
        tabs[tabs.length - 1].focus();
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        setState(tab.dataset.stateTarget);
      }
    });
  });

  motionButton?.addEventListener("click", () => {
    const scene = document.querySelector(".convergence-scene");
    if (!scene) return;
    const seal = scene.querySelector(".human-seal");
    if (!seal) return;
    if (scene.classList.contains("motion-complete") || scene.classList.contains("is-converging")) return;
    setState("global");
    scene.classList.remove("motion-complete", "is-converging");
    void scene.offsetWidth;
    scene.classList.add("is-converging");
    motionButton.setAttribute("aria-pressed", "true");
    function onComplete() {
      scene.classList.remove("is-converging");
      scene.classList.add("motion-complete");
      motionButton.setAttribute("aria-pressed", "false");
    }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      seal.getAnimations().forEach(a => a.finish());
      onComplete();
    } else {
      seal.addEventListener("animationend", onComplete, { once: true });
    }
  });

  window.addEventListener("popstate", () => setState(requestedState(), { updateUrl: false }));
  setState(requestedState(), { updateUrl: false });
  document.documentElement.dataset.assetVersion = version;
})();
