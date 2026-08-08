(() => {
  const app = window.WorldFeed = window.WorldFeed || {};
  let dialogTrigger = null;

  const stories = {
    maker: {
      signal: "가까운 곳 · 시장 골목", signalClass: "signal-nearby",
      title: ["문 닫은 가게 안에서", "다시 켜진 작업등"], image: "./assets/images/maker-studio.svg", alt: "저녁 공방 합성 일러스트",
      intro: "이 화면은 원문을 대신하지 않습니다. World Feed가 이 작업등 장면을 발견한 맥락과 출처 상태만 짧게 보여줍니다.",
      body: ["시장 문이 닫힌 뒤에도 한 점포의 작업등은 늦게까지 켜져 있습니다. 낮에는 비어 보이던 공간이 저녁에는 책 수선과 도자기 작업을 나누는 작은 공방으로 바뀝니다.", "이 편집면이 주목한 것은 특정 상점의 실제 최신 소식이 아니라, 동네 공간이 시간에 따라 다르게 쓰이는 장면입니다."],
      source: "Local Field Notes", format: "합성 지역 관찰 메모", time: "과거 합성 기록 · 6일 전", scope: "장소 맥락 2문단",
      whyLead: "최근에 본 이야기 가운데 ‘가까운 공간의 변화’와 ‘만드는 과정’이 자주 겹쳤기 때문입니다.",
      reasons: [["저장해 둔 관심", "공예, 수선, 작은 작업실 이야기를 여러 번 선택했습니다."], ["가까운 장소 선호", "멀리 있는 명소보다 동네 공간의 변화에 오래 머물렀습니다."], ["최근 반응", "짧은 장소 기록을 연달아 열어본 현재 세션의 선택이 반영됐습니다."]]
    },
    "market-studio": {
      signal: "가까운 곳 · 광주", signalClass: "signal-nearby",
      title: ["시장 골목의 빈 점포가", "저녁 공방으로 바뀌는 중"], image: "./assets/images/maker-studio.svg", alt: "시장 골목 저녁 공방 합성 일러스트",
      intro: "빈 점포가 저녁 시간에 다른 쓰임을 얻는 과정을 짧은 동네 기록으로 보여줍니다.",
      body: ["낮 동안 셔터가 내려가 있던 점포 안에 저녁이 되면 작업대와 작은 의자가 놓입니다. 책 수선과 도자기, 짧은 공연이 번갈아 공간을 사용합니다.", "실제 상권 소식이 아니라, 비어 있던 장소가 시간대에 따라 공동 작업 공간으로 바뀌는 가능성을 보여주는 합성 기록입니다."],
      source: "Local Field Notes", format: "합성 골목 변화 메모", time: "합성 기록 · 6일 전", scope: "동네 변화 맥락 2문단",
      whyLead: "최근 가까운 골목의 변화와 작은 작업 공간 이야기를 연이어 살펴봤기 때문입니다.",
      reasons: [["가까운 동네", "광주와 주변 골목의 생활 변화를 자주 선택했습니다."], ["공간의 재사용", "비어 있던 가게가 다른 용도로 바뀌는 이야기에 머물렀습니다."], ["짧은 지역 기록", "긴 기사보다 이미지와 두세 문단의 동네 기록을 열어봤습니다."]]
    },
    harbor: {
      signal: "세계 · 해안 도시", signalClass: "signal-world",
      title: ["낯선 항구의 저녁이", "오늘의 첫 장면이 된 이유"], image: "./assets/images/hero-harbor.svg", alt: "해질녘 항구 도시 합성 일러스트",
      intro: "항구 도시의 산책로와 늦은 저녁 풍경이 첫 장면으로 선택된 맥락을 짧게 보여줍니다.",
      body: ["해가 늦게 지는 계절의 항구는 낮과 밤 사이의 시간을 길게 늘입니다. 사람들은 목적지를 향하기보다 물가를 따라 걷고, 작은 가게들은 문 앞의 의자를 먼저 내놓습니다.", "특정 도시의 최신 소식이 아니라 바다와 골목이 만나는 장소의 감각을 발견하도록 돕는 합성 세계 기록입니다."],
      source: "Atlas Letter", format: "합성 여행 에세이 메모", time: "과거 합성 기록 · 4분", scope: "장소 맥락 2문단",
      whyLead: "저장해 둔 장소 관심과 천천히 이동하는 여행 장면을 최근 자주 열어봤기 때문입니다.",
      reasons: [["해안 도시 관심", "바다와 도시가 맞닿는 장소 이야기를 저장해 두었습니다."], ["느린 이동 장면", "관광 정보보다 산책과 저녁 풍경에 오래 머물렀습니다."], ["짧은 세계 기록", "이미지와 짧은 장소 맥락이 있는 항목을 선택했습니다."]]
    },
    cinema: {
      signal: "나의 관심 · 영화와 장소", signalClass: "signal-personal",
      title: ["상영 시간표보다", "동네의 밤을 바꾸는 극장"], image: "./assets/images/small-cinema.svg", alt: "동네 소극장 합성 일러스트",
      intro: "한 편의 영화가 끝난 뒤에도 사람들이 주변에 머무는 장소의 맥락을 보여줍니다.",
      body: ["작은 극장의 마지막 상영이 끝난 뒤 관객들은 곧장 흩어지지 않습니다. 옆 서점과 식당, 버스 정류장이 한동안 같은 밤의 흐름을 이어갑니다.", "실제 상영 정보가 아니라 문화 공간 하나가 주변 골목의 사용법을 바꾸는 장면을 편집한 합성 기록입니다."],
      source: "Neighborhood Screen", format: "합성 문화 공간 메모", time: "합성 기록 · 7분", scope: "극장과 주변 장소 2문단",
      whyLead: "영화 자체뿐 아니라 극장 주변의 서점과 골목을 함께 보는 이야기를 자주 선택했기 때문입니다.",
      reasons: [["영화와 장소", "작품 정보보다 극장이 놓인 장소의 분위기에 관심을 보였습니다."], ["가까운 문화 공간", "동네 서점과 작은 공연장 이야기를 여러 번 열었습니다."], ["관련 장소 탐색", "하나의 문화 공간에서 주변 골목으로 이어지는 항목을 선택했습니다."]]
    }
  };

  function storyFor(id) { return stories[id] || stories.maker; }
  function setText(selector, value) { const node = document.querySelector(selector); if (node) node.textContent = value; }
  function setSignal(selector, story) {
    const node = document.querySelector(selector);
    if (!node) return;
    node.textContent = story.signal;
    node.classList.remove("signal-world", "signal-nearby", "signal-personal");
    node.classList.add(story.signalClass);
  }

  function renderStory(storyId) {
    const story = storyFor(storyId);
    const shell = document.querySelector(".review-shell");
    shell.dataset.storyId = storyId in stories ? storyId : "maker";
    const title = document.querySelector("[data-story-title]");
    title?.querySelectorAll("span").forEach((line, index) => { line.textContent = story.title[index] || ""; });
    setSignal("[data-story-signal]", story);
    setText("[data-story-intro]", story.intro);
    const image = document.querySelector("[data-story-image]");
    if (image) { image.src = story.image; image.alt = story.alt; }
    setText("[data-story-caption]", `${story.title.join(" ")} · 현재 사실을 나타내지 않는 UX 검토용 합성 장면.`);
    setText("[data-story-body-one]", story.body[0]);
    setText("[data-story-body-two]", story.body[1]);
    setText("[data-story-source]", story.source);
    setText("[data-story-format]", story.format);
    setText("[data-story-status]", "UX 검토용 가상 출처");
    setText("[data-story-time]", story.time);
    setText("[data-story-scope]", story.scope);
    const whyImage = document.querySelector("[data-why-image]");
    if (whyImage) { whyImage.src = story.image; whyImage.alt = story.alt; }
    setSignal("[data-why-signal]", story);
    setText("[data-why-story-title]", story.title.join(" "));
    setText("[data-why-source]", story.source);
    setText("[data-why-time]", story.time);
    setText("[data-why-lead]", story.whyLead);
    story.reasons.forEach(([titleText, bodyText], index) => {
      setText(`[data-reason-title="${index}"]`, titleText);
      setText(`[data-reason-text="${index}"]`, bodyText);
    });
  }

  function bindStoryControls() {
    document.querySelectorAll("[data-open-story]").forEach((control) => {
      control.addEventListener("click", () => {
        const storyId = control.dataset.storyId || "maker";
        app.store.setStoryId(storyId);
        renderStory(storyId);
        app.navigation.navigate("story", { captureOrigin: true, originControl: control, storyId });
      });
    });
  }

  function bindSourceDialog() {
    const dialog = document.getElementById("source-dialog");
    if (!dialog) return;
    document.querySelectorAll("[data-source-action]").forEach((control) => {
      control.addEventListener("click", () => { dialogTrigger = control; dialog.showModal(); });
    });
    dialog.addEventListener("close", () => dialogTrigger?.focus({ preventScroll: true }));
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  }

  function initialize() {
    app.store.subscribe((state, reason) => { if (["story", "reset"].includes(reason)) renderStory(state.selectedStoryId); });
    bindStoryControls();
    bindSourceDialog();
    renderStory(app.store.getState().selectedStoryId);
  }

  app.story = { initialize, renderStory, stories };
})();
