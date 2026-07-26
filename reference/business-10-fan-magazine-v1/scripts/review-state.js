(() => {
  const states = ["cover", "feature", "trajectory", "rediscovery", "fan-note", "mobile", "reveal"];
  const shell = document.querySelector(".review-shell");
  const stage = document.querySelector("#review-stage");
  const stateButtons = [...document.querySelectorAll("[data-state]")];
  const panels = [...document.querySelectorAll("[data-state-panel]")];
  const previousButton = document.querySelector('[data-step="previous"]');
  const nextButton = document.querySelector('[data-step="next"]');
  const revealStage = document.querySelector("[data-reveal-stage]");
  const revealToggle = document.querySelector("[data-reveal-toggle]");
  const revealStatus = document.querySelector("[data-reveal-status]");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  const normalizeState = (value) => states.includes(value) ? value : "cover";
  const currentState = () => normalizeState(shell.dataset.currentState);

  function resetReveal() {
    if (!revealStage) return;
    revealStage.classList.remove("is-revealed");
    revealToggle.setAttribute("aria-pressed", "false");
    revealToggle.textContent = "커버 리빌 재생";
    revealStatus.textContent = reducedMotion.matches ? "표지 상태 · reduced motion" : "표지 상태 · 680ms";
  }

  function showState(nextState, options = {}) {
    const { updateHash = true, focusStage = false } = options;
    const state = normalizeState(nextState);
    shell.dataset.currentState = state;

    panels.forEach((panel) => {
      const isActive = panel.dataset.statePanel === state;
      panel.hidden = !isActive;
      panel.classList.toggle("is-active", isActive);
    });

    stateButtons.forEach((button) => {
      const isActive = button.dataset.state === state;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", String(isActive));
    });

    if (state !== "reveal") resetReveal();
    if (updateHash && window.location.hash !== `#${state}`) history.replaceState(null, "", `#${state}`);
    if (focusStage) stage.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: reducedMotion.matches ? "auto" : "smooth" });
  }

  function stepState(direction) {
    const index = states.indexOf(currentState());
    const nextIndex = (index + direction + states.length) % states.length;
    showState(states[nextIndex], { focusStage: true });
  }

  function toggleReveal() {
    if (!revealStage) return;
    const revealed = !revealStage.classList.contains("is-revealed");
    revealStage.classList.toggle("is-revealed", revealed);
    revealToggle.setAttribute("aria-pressed", String(revealed));
    revealToggle.textContent = revealed ? "표지로 돌아가기" : "커버 리빌 재생";
    revealStatus.textContent = reducedMotion.matches
      ? (revealed ? "펼침면 즉시 전환됨" : "표지 즉시 전환됨")
      : (revealed ? "펼침면 상태 · 680ms 완료" : "표지 상태 · 재생 가능");
  }

  function updateMotionPreference() {
    document.documentElement.dataset.reducedMotion = String(reducedMotion.matches);
    if (currentState() === "reveal") {
      revealStatus.textContent = reducedMotion.matches ? "표지 상태 · reduced motion" : "표지 상태 · 680ms";
    }
  }

  stateButtons.forEach((button) => {
    button.addEventListener("click", () => showState(button.dataset.state, { focusStage: true }));
  });
  previousButton.addEventListener("click", () => stepState(-1));
  nextButton.addEventListener("click", () => stepState(1));
  revealToggle.addEventListener("click", toggleReveal);

  window.addEventListener("hashchange", () => showState(window.location.hash.slice(1), { updateHash: false }));
  window.addEventListener("keydown", (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      stepState(-1);
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      stepState(1);
    }
    if (event.key === "Escape" && currentState() === "reveal") resetReveal();
  });

  if (typeof reducedMotion.addEventListener === "function") {
    reducedMotion.addEventListener("change", updateMotionPreference);
  } else {
    reducedMotion.addListener(updateMotionPreference);
  }

  updateMotionPreference();
  showState(window.location.hash.slice(1), { updateHash: true });
})();
