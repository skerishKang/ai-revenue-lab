(() => {
  "use strict";

  const shell = document.querySelector(".review-shell");
  const tabs = Array.from(document.querySelectorAll(".review-tab"));
  const panels = Array.from(document.querySelectorAll("[data-state-panel]"));
  const stateJumps = Array.from(document.querySelectorAll("[data-state-jump], [data-state-link]"));
  const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const validStates = new Set(panels.map((panel) => panel.dataset.statePanel));

  function setState(nextState, options = {}) {
    const { focusPanel = false, updateHash = true } = options;
    const state = validStates.has(nextState) ? nextState : "home";

    shell.dataset.currentState = state;
    tabs.forEach((tab) => {
      const active = tab.dataset.state === state;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-pressed", String(active));
    });

    panels.forEach((panel) => {
      const active = panel.dataset.statePanel === state;
      panel.hidden = !active;
      panel.classList.toggle("is-active", active);
    });

    if (updateHash) {
      history.replaceState(null, "", `#${state}`);
    }

    if (focusPanel) {
      const panel = document.querySelector(`[data-state-panel="${state}"]`);
      const heading = panel?.querySelector("h1");
      if (heading) {
        heading.setAttribute("tabindex", "-1");
        heading.focus({ preventScroll: false });
      }
    }

    window.scrollTo({ top: 0, behavior: motionQuery.matches ? "auto" : "smooth" });
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => setState(tab.dataset.state));
    tab.addEventListener("keydown", (event) => {
      if (!(["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key))) return;
      event.preventDefault();
      let nextIndex = index;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = tabs.length - 1;
      tabs[nextIndex].focus();
      setState(tabs[nextIndex].dataset.state);
    });
  });

  stateJumps.forEach((control) => {
    control.addEventListener("click", (event) => {
      event.preventDefault();
      const state = control.dataset.stateJump || control.dataset.stateLink;
      setState(state, { focusPanel: true });
    });
  });

  const topicData = {
    neighborhood: {
      image: "./assets/images/small-cinema.svg",
      alt: "동네 소극장을 표현한 합성 편집 일러스트",
      signalClass: "signal-nearby",
      signal: "가까운 곳 · 작은 극장",
      title: "상영 시간표보다\n동네의 밤을 바꾸는 극장",
      description: "한 편의 영화가 끝난 뒤에도 사람들이 흩어지지 않는 이유. 작은 극장 주변의 서점, 식당, 버스 정류장을 함께 보는 짧은 장소 기록입니다.",
      source: "Neighborhood Screen"
    },
    craft: {
      image: "./assets/images/ceramic-hands.svg",
      alt: "도자기를 빚는 손을 표현한 합성 편집 일러스트",
      signalClass: "signal-personal",
      signal: "나의 관심 · 공예와 손",
      title: "완성보다 과정이\n더 오래 남는 작업실",
      description: "도자기와 수선, 작은 인쇄 작업처럼 손의 속도가 그대로 보이는 장소를 묶은 합성 편집면입니다. 결과물보다 만드는 장면을 중심에 둡니다.",
      source: "Form & Hand"
    }
  };

  const topicLayout = document.querySelector(".topic-layout");
  const topicImage = topicLayout?.querySelector(".topic-hero img");
  const topicSignal = topicLayout?.querySelector(".topic-main-copy .signal");
  const topicTitle = topicLayout?.querySelector(".topic-main-copy h2");
  const topicDescription = topicLayout?.querySelector(".topic-main-copy > p");
  const topicSource = topicLayout?.querySelector(".stable-source span");
  const topicButtons = Array.from(document.querySelectorAll("[data-topic]"));

  function changeTopic(topic) {
    const data = topicData[topic];
    if (!data || !topicLayout) return;

    topicButtons.forEach((button) => {
      const selected = button.dataset.topic === topic;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });

    topicLayout.classList.remove("is-topic-shifting");
    void topicLayout.offsetWidth;
    topicLayout.classList.add("is-topic-shifting");

    const update = () => {
      topicImage.src = data.image;
      topicImage.alt = data.alt;
      topicSignal.className = `signal ${data.signalClass}`;
      topicSignal.textContent = data.signal;
      topicTitle.innerHTML = data.title.replace("\n", "<br>");
      topicDescription.textContent = data.description;
      topicSource.textContent = data.source;
    };

    if (motionQuery.matches) {
      update();
      topicLayout.classList.remove("is-topic-shifting");
    } else {
      window.setTimeout(update, 220);
      window.setTimeout(() => topicLayout.classList.remove("is-topic-shifting"), 720);
    }
  }

  topicButtons.forEach((button) => {
    button.addEventListener("click", () => changeTopic(button.dataset.topic));
  });

  const compareCanvas = document.querySelector(".comparison-canvas");
  const compareButtons = Array.from(document.querySelectorAll("[data-compare]"));
  compareButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const compare = button.dataset.compare;
      compareCanvas.dataset.compareView = compare;
      compareButtons.forEach((item) => {
        const active = item === button;
        item.classList.toggle("is-selected", active);
        item.setAttribute("aria-pressed", String(active));
      });
    });
  });

  const motionDemo = document.querySelector(".motion-demo");
  const playMotion = document.querySelector("#play-motion");
  let motionTimer = 0;

  function resetMotionDemo() {
    if (!motionDemo) return;
    window.clearTimeout(motionTimer);
    motionDemo.classList.remove("is-shifting");
    void motionDemo.offsetWidth;
  }

  function playHorizonShift() {
    if (!motionDemo || !playMotion) return;
    resetMotionDemo();
    motionDemo.classList.add("is-shifting");
    playMotion.textContent = motionQuery.matches ? "즉시 전환됨" : "모션 재생 중";
    playMotion.setAttribute("aria-busy", "true");

    const duration = motionQuery.matches ? 80 : 760;
    motionTimer = window.setTimeout(() => {
      playMotion.textContent = "다시 재생";
      playMotion.removeAttribute("aria-busy");
    }, duration);
  }

  playMotion?.addEventListener("click", playHorizonShift);

  function updateMotionPreference() {
    document.documentElement.dataset.reducedMotion = String(motionQuery.matches);
  }
  updateMotionPreference();
  motionQuery.addEventListener?.("change", updateMotionPreference);

  window.addEventListener("hashchange", () => {
    const requested = location.hash.slice(1);
    if (validStates.has(requested)) setState(requested, { updateHash: false });
  });

  const initialState = validStates.has(location.hash.slice(1)) ? location.hash.slice(1) : "home";
  setState(initialState, { updateHash: false });

  window.WorldFeedReview = Object.freeze({ setState, playHorizonShift, changeTopic });
})();
