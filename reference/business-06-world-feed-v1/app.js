(() => {
  const stateNames = ["home", "topic", "story", "why", "adjusted", "mobile", "motion"];
  const shell = document.querySelector(".review-shell");
  const tabs = [...document.querySelectorAll("[data-state]")];
  const panels = [...document.querySelectorAll("[data-state-panel]")];
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");

  function normalizedState(value) {
    return stateNames.includes(value) ? value : "home";
  }

  function showState(nextState, { updateHash = true, focusMain = false } = {}) {
    const state = normalizedState(nextState);
    shell.dataset.currentState = state;
    panels.forEach((panel) => {
      const active = panel.dataset.statePanel === state;
      panel.hidden = !active;
      panel.classList.toggle("is-active", active);
    });
    tabs.forEach((tab) => {
      const active = tab.dataset.state === state;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-pressed", String(active));
    });
    if (updateHash && location.hash !== `#${state}`) history.replaceState(null, "", `#${state}`);
    if (focusMain) document.querySelector("#main")?.focus({ preventScroll: true });
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => showState(tab.dataset.state));
    tab.addEventListener("keydown", (event) => {
      let target = index;
      if (event.key === "ArrowRight") target = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft") target = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === "Home") target = 0;
      else if (event.key === "End") target = tabs.length - 1;
      else return;
      event.preventDefault();
      tabs[target].focus();
      showState(tabs[target].dataset.state);
    });
  });

  document.querySelectorAll("[data-state-jump], [data-state-link]").forEach((control) => {
    control.addEventListener("click", (event) => {
      event.preventDefault();
      showState(control.dataset.stateJump || control.dataset.stateLink, { focusMain: true });
    });
  });

  const topicData = {
    neighborhood: {
      image: "./assets/images/small-cinema.svg",
      alt: "동네 소극장을 표현한 합성 편집 일러스트",
      signal: "가까운 곳 · 작은 극장",
      title: ["상영 시간표보다", "동네의 밤을 바꾸는 극장"],
      copy: "한 편의 영화가 끝난 뒤에도 사람들이 흩어지지 않는 이유. 작은 극장 주변의 서점, 식당, 버스 정류장을 함께 보는 짧은 장소 기록입니다."
    },
    craft: {
      image: "./assets/images/maker-studio.svg",
      alt: "저녁 공방을 표현한 합성 편집 일러스트",
      signal: "나의 관심 · 공예와 손",
      title: ["완성품보다", "만드는 시간을 보는 작업실"],
      copy: "시장 안쪽의 작은 작업실에서 재료와 사람의 시간이 어떻게 겹치는지 보는 짧은 공예 기록입니다."
    }
  };

  document.querySelectorAll("[data-topic]").forEach((button) => {
    button.addEventListener("click", () => {
      const data = topicData[button.dataset.topic];
      const layout = document.querySelector(".topic-layout");
      if (!data || !layout) return;
      document.querySelectorAll("[data-topic]").forEach((item) => {
        const active = item === button;
        item.classList.toggle("is-selected", active);
        item.setAttribute("aria-pressed", String(active));
      });
      layout.classList.add("is-shifting");
      setTimeout(() => {
        const image = document.querySelector("[data-topic-image]");
        image.src = data.image;
        image.alt = data.alt;
        document.querySelector("[data-topic-signal]").textContent = data.signal;
        document.querySelector("[data-topic-title]").innerHTML = data.title.map((line) => `<span>${line}</span>`).join("");
        document.querySelector("[data-topic-copy]").textContent = data.copy;
      }, reducedMotion.matches ? 0 : 180);
      setTimeout(() => layout.classList.remove("is-shifting"), reducedMotion.matches ? 20 : 680);
    });
  });

  document.querySelectorAll("[data-compare]").forEach((button) => {
    button.addEventListener("click", () => {
      const value = button.dataset.compare;
      document.querySelector("[data-compare-view]").dataset.compareView = value;
      document.querySelectorAll("[data-compare]").forEach((item) => {
        const active = item === button;
        item.classList.toggle("is-selected", active);
        item.setAttribute("aria-pressed", String(active));
      });
    });
  });

  const motionButton = document.querySelector("#play-motion");
  const motionDemo = document.querySelector(".motion-demo");
  motionButton?.addEventListener("click", () => {
    if (!motionDemo || motionDemo.classList.contains("is-shifting")) return;
    motionButton.setAttribute("aria-busy", "true");
    motionDemo.classList.add("is-shifting");
    motionButton.textContent = reducedMotion.matches ? "즉시 전환됨" : "전환 중";
    setTimeout(() => {
      motionDemo.classList.remove("is-shifting");
      motionDemo.dataset.motionMode = motionDemo.dataset.motionMode === "harbor" ? "studio" : "harbor";
      motionButton.removeAttribute("aria-busy");
      motionButton.textContent = "모션 재생";
    }, reducedMotion.matches ? 80 : 760);
  });

  function syncReducedMotion() {
    document.documentElement.dataset.reducedMotion = String(reducedMotion.matches);
  }
  reducedMotion.addEventListener?.("change", syncReducedMotion);
  syncReducedMotion();
  addEventListener("hashchange", () => showState(location.hash.slice(1), { updateHash: false }));
  showState(location.hash.slice(1), { updateHash: false });
})();
