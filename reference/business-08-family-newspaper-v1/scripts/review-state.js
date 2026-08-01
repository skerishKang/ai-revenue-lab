(() => {
  "use strict";

  const stateOrder = ["front", "news", "photos", "calendar", "sources", "mobile", "fold"];
  const stateLabels = {
    front: "이번 주 1면",
    news: "가족 소식면",
    photos: "사진 특집",
    calendar: "이번 달 일정과 기념일",
    sources: "누가 어떻게 만들었나요",
    mobile: "모바일 390px",
    fold: "Page Fold / 지면 넘김",
  };

  const panels = new Map(
    [...document.querySelectorAll("[data-state-panel]")].map((panel) => [panel.dataset.statePanel, panel]),
  );
  const stateButtons = [...document.querySelectorAll("[data-state-target]")];
  const stepButtons = [...document.querySelectorAll("[data-state-step]")];
  const jumpButtons = [...document.querySelectorAll("[data-jump-state]")];
  const currentStateLabel = document.querySelector("#current-state-label");
  const statePosition = document.querySelector("#state-position");
  const sourceToggle = document.querySelector(".source-toggle");
  const sourceDetails = document.querySelector("#source-details");
  const foldStage = document.querySelector(".fold-stage");
  const foldReplay = document.querySelector(".fold-replay");
  const foldLocation = document.querySelector("#fold-location");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  let activeState = "front";
  let foldTimer = null;

  function validState(candidate) {
    return stateOrder.includes(candidate) ? candidate : "front";
  }

  function updateUrlState(state) {
    const nextUrl = new URL(window.location.href);
    nextUrl.searchParams.set("state", state);
    window.history.replaceState({}, "", nextUrl);
  }

  function setActiveState(nextState, options = {}) {
    const state = validState(nextState);
    const index = stateOrder.indexOf(state);

    panels.forEach((panel, panelState) => {
      const isActive = panelState === state;
      panel.hidden = !isActive;
      panel.classList.toggle("is-active", isActive);
      panel.setAttribute("aria-hidden", String(!isActive));
    });

    stateButtons.forEach((button) => {
      const isActive = button.dataset.stateTarget === state;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", String(isActive));
    });

    activeState = state;
    currentStateLabel.textContent = stateLabels[state];
    statePosition.textContent = `${index + 1} / ${stateOrder.length}`;
    document.title = `${stateLabels[state]} — 우리 가족 신문`;

    if (options.updateUrl !== false) {
      updateUrlState(state);
    }

    if (options.focusPanel) {
      const heading = panels.get(state)?.querySelector("h1, h2");
      if (heading) {
        heading.tabIndex = -1;
        heading.focus({ preventScroll: true });
      }
    }

    window.scrollTo({ top: 0, behavior: reduceMotion.matches ? "auto" : "smooth" });
  }

  function stepState(step) {
    const currentIndex = stateOrder.indexOf(activeState);
    const nextIndex = (currentIndex + step + stateOrder.length) % stateOrder.length;
    setActiveState(stateOrder[nextIndex]);
  }

  function replayFold() {
    if (!foldStage || !foldLocation) {
      return;
    }

    window.clearTimeout(foldTimer);
    foldStage.classList.remove("is-folding", "is-complete");
    foldLocation.textContent = "1면 → 가족 소식면";
    void foldStage.offsetWidth;

    if (reduceMotion.matches) {
      foldStage.classList.add("is-complete");
      foldLocation.textContent = "가족 소식면 · 이동 없이 전환";
      return;
    }

    foldStage.classList.add("is-folding");
    foldLocation.textContent = "지면을 넘기는 중…";
    foldTimer = window.setTimeout(() => {
      foldStage.classList.remove("is-folding");
      foldStage.classList.add("is-complete");
      foldLocation.textContent = "가족 소식면 · 2면";
    }, 680);
  }

  stateButtons.forEach((button) => {
    button.addEventListener("click", () => setActiveState(button.dataset.stateTarget));
    button.addEventListener("keydown", (event) => {
      const currentIndex = stateButtons.indexOf(button);
      let nextIndex = null;

      if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % stateButtons.length;
      if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + stateButtons.length) % stateButtons.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = stateButtons.length - 1;

      if (nextIndex !== null) {
        event.preventDefault();
        stateButtons[nextIndex].focus();
        setActiveState(stateButtons[nextIndex].dataset.stateTarget);
      }
    });
  });

  stepButtons.forEach((button) => {
    button.addEventListener("click", () => stepState(Number(button.dataset.stateStep)));
  });

  jumpButtons.forEach((button) => {
    button.addEventListener("click", () => setActiveState(button.dataset.jumpState, { focusPanel: true }));
  });

  sourceToggle?.addEventListener("click", () => {
    const willOpen = sourceToggle.getAttribute("aria-expanded") !== "true";
    sourceToggle.setAttribute("aria-expanded", String(willOpen));
    sourceToggle.textContent = willOpen ? "편집 자료 접기" : "편집 자료 자세히 보기";
    sourceDetails.hidden = !willOpen;
  });

  foldReplay?.addEventListener("click", replayFold);

  document.addEventListener("keydown", (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.target.matches("button, a, input, textarea, select")) {
      return;
    }
    if (event.key === "]") stepState(1);
    if (event.key === "[") stepState(-1);
    if (event.key.toLowerCase() === "r" && activeState === "fold") replayFold();
  });

  reduceMotion.addEventListener("change", () => {
    if (activeState === "fold") replayFold();
  });

  const requestedState = validState(new URL(window.location.href).searchParams.get("state"));
  setActiveState(requestedState, { updateUrl: false });
})();
