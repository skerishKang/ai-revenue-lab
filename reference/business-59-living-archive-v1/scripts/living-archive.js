(() => {
  "use strict";

  const volumes = window.LIVING_ARCHIVE_VOLUMES;
  const state = {
    volumeId: volumes[0].id,
    sourceId: `${volumes[0].id}-source-01`,
    pageIndex: volumes[0].pageIndex,
    readingMode: "shelf",
    zoom: 100,
    searchQuery: "",
    searchMatches: [],
    searchCursor: 0,
    bookmarks: new Set(),
    notes: new Map(),
    reducedMotion: false
  };

  const $ = (selector) => document.querySelector(selector);
  const app = $("#app");
  const views = {
    shelf: $("#shelf-view"),
    book: $("#book-view"),
    reader: $("#reader-view")
  };

  const currentVolume = () => volumes.find((volume) => volume.id === state.volumeId);
  const clampPage = (index) => Math.max(0, Math.min(index, currentVolume().sections.length - 1));

  function announce(message) {
    $("#live-region").textContent = message;
  }

  function setMode(mode) {
    state.readingMode = mode;
    app.dataset.mode = mode;
    Object.entries(views).forEach(([name, element]) => {
      element.hidden = name !== mode;
    });
    if (mode === "shelf") renderShelfSummary();
    if (mode === "book") renderBook();
    if (mode === "reader") renderReader();
    window.history.replaceState({
      volumeId: state.volumeId,
      sourceId: state.sourceId,
      pageIndex: state.pageIndex,
      readingMode: state.readingMode,
      zoom: state.zoom,
      searchQuery: state.searchQuery,
      bookmarks: [...state.bookmarks]
    }, "", `#${mode}/${state.volumeId}/${state.pageIndex + 1}`);
  }

  function renderShelf() {
    const shelf = $("#shelf");
    shelf.innerHTML = "";
    volumes.forEach((volume, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "volume";
      button.dataset.volumeId = volume.id;
      button.style.setProperty("--cover", volume.color);
      button.style.setProperty("--foil", volume.accent);
      button.style.setProperty("--height", `${340 + index * 22}px`);
      button.setAttribute("aria-pressed", String(volume.id === state.volumeId));
      button.innerHTML = `<span class="volume__number">${String(index + 1).padStart(2, "0")}</span><strong>${volume.title}</strong><span>${volume.collection}</span>`;
      button.addEventListener("click", () => selectVolume(volume.id));
      button.addEventListener("dblclick", () => setMode("book"));
      shelf.appendChild(button);
    });
  }

  function selectVolume(volumeId) {
    state.volumeId = volumeId;
    state.sourceId = `${volumeId}-source-01`;
    state.pageIndex = currentVolume().pageIndex;
    renderShelf();
    renderShelfSummary();
    announce(`${currentVolume().title} 선택됨`);
  }

  function renderShelfSummary() {
    const volume = currentVolume();
    $("#summary-collection").textContent = volume.collection;
    $("#summary-title").textContent = volume.title;
    $("#summary-description").textContent = volume.description;
    $("#summary-sources").textContent = volume.sources;
    $("#summary-progress").textContent = `${state.pageIndex + 1} / ${volume.sections.length}장`;
    $("#summary-updated").textContent = volume.updated;
    document.querySelectorAll(".volume").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.volumeId === state.volumeId));
    });
  }

  function pageMarkup(section, label) {
    return `<p class="page-folio">${label}</p><h3>${section.title}</h3>${section.body.map((paragraph) => `<p>${paragraph}</p>`).join("")}`;
  }

  function renderBook() {
    const volume = currentVolume();
    state.pageIndex = clampPage(state.pageIndex);
    const leftIndex = state.pageIndex;
    const rightIndex = Math.min(leftIndex + 1, volume.sections.length - 1);
    $("#book-title").textContent = volume.title;
    $("#preview-left").innerHTML = pageMarkup(volume.sections[leftIndex], `${leftIndex + 1}`);
    $("#preview-right").innerHTML = pageMarkup(volume.sections[rightIndex], `${rightIndex + 1}`);
    $("#preview-label").textContent = volume.sections[leftIndex].title;
    $("#preview-counter").textContent = `${leftIndex + 1}–${rightIndex + 1} / ${volume.sections.length}`;
    $("#preview-previous").disabled = leftIndex === 0;
    $("#preview-next").disabled = rightIndex >= volume.sections.length - 1;
    $("#open-book").style.setProperty("--book-cover", volume.color);
  }

  function renderOutline() {
    const list = $("#outline-list");
    list.innerHTML = "";
    currentVolume().sections.forEach((section, index) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = section.title;
      button.setAttribute("aria-current", index === state.pageIndex ? "page" : "false");
      button.addEventListener("click", () => {
        state.pageIndex = index;
        renderReader();
      });
      item.appendChild(button);
      list.appendChild(item);
    });
  }

  function renderReader() {
    const volume = currentVolume();
    state.pageIndex = clampPage(state.pageIndex);
    const section = volume.sections[state.pageIndex];
    $("#reader-kind").textContent = volume.kind;
    $("#reader-title").textContent = volume.title;
    $("#document-page").innerHTML = `<p class="document-source">원본 위치 · ${state.sourceId} · 장 ${state.pageIndex + 1}</p><h1>${section.title}</h1>${section.body.map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("")}`;
    $("#reader-page-label").textContent = section.title;
    $("#reader-page-counter").textContent = `${state.pageIndex + 1} / ${volume.sections.length}`;
    $("#reader-previous").disabled = state.pageIndex === 0;
    $("#reader-next").disabled = state.pageIndex === volume.sections.length - 1;
    $("#reader-document").style.setProperty("--reader-scale", state.zoom / 100);
    $("#note-anchor").textContent = `연결 위치: ${state.sourceId} · ${state.pageIndex + 1}장`;
    $("#note-input").value = state.notes.get(noteKey()) || "";
    $("#toggle-bookmark").setAttribute("aria-pressed", String(state.bookmarks.has(noteKey())));
    $("#toggle-bookmark").textContent = state.bookmarks.has(noteKey()) ? "책갈피 해제" : "책갈피";
    renderOutline();
    applySearch();
  }

  function noteKey() {
    return `${state.volumeId}:${state.pageIndex}`;
  }

  function escapeHtml(value) {
    return value.replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
  }

  function applySearch() {
    const query = state.searchQuery.trim().toLocaleLowerCase("ko-KR");
    const page = $("#document-page");
    page.querySelectorAll("mark").forEach((mark) => mark.replaceWith(mark.textContent));
    state.searchMatches = [];
    state.searchCursor = 0;
    if (!query) {
      $("#search-count").textContent = "0";
      return;
    }
    const walker = document.createTreeWalker(page, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((node) => {
      const text = node.nodeValue;
      const lower = text.toLocaleLowerCase("ko-KR");
      let cursor = 0;
      const fragment = document.createDocumentFragment();
      let matched = false;
      while (true) {
        const index = lower.indexOf(query, cursor);
        if (index === -1) break;
        fragment.append(text.slice(cursor, index));
        const mark = document.createElement("mark");
        mark.textContent = text.slice(index, index + query.length);
        fragment.append(mark);
        state.searchMatches.push(mark);
        cursor = index + query.length;
        matched = true;
      }
      if (matched) {
        fragment.append(text.slice(cursor));
        node.replaceWith(fragment);
      }
    });
    $("#search-count").textContent = String(state.searchMatches.length);
    focusSearchResult();
  }

  function focusSearchResult() {
    state.searchMatches.forEach((match) => match.removeAttribute("data-active"));
    if (!state.searchMatches.length) return;
    const active = state.searchMatches[state.searchCursor % state.searchMatches.length];
    active.dataset.active = "true";
    active.scrollIntoView({ block: "center", behavior: state.reducedMotion ? "auto" : "smooth" });
  }

  function shiftPage(delta, mode) {
    state.pageIndex = clampPage(state.pageIndex + delta);
    if (mode === "book") renderBook();
    if (mode === "reader") renderReader();
  }

  $("#open-3d").addEventListener("click", () => setMode("book"));
  $("#open-2d-direct").addEventListener("click", () => setMode("reader"));
  $("#back-to-shelf").addEventListener("click", () => setMode("shelf"));
  $("#continue-2d").addEventListener("click", () => setMode("reader"));
  $("#reader-back-3d").addEventListener("click", () => setMode("book"));
  $("#preview-previous").addEventListener("click", () => shiftPage(-2, "book"));
  $("#preview-next").addEventListener("click", () => shiftPage(2, "book"));
  $("#reader-previous").addEventListener("click", () => shiftPage(-1, "reader"));
  $("#reader-next").addEventListener("click", () => shiftPage(1, "reader"));

  $("#search-input").addEventListener("input", (event) => {
    state.searchQuery = event.target.value;
    renderReader();
  });
  $("#search-next").addEventListener("click", () => {
    if (!state.searchMatches.length) return;
    state.searchCursor = (state.searchCursor + 1) % state.searchMatches.length;
    focusSearchResult();
  });
  $("#zoom-range").addEventListener("input", (event) => {
    state.zoom = Number(event.target.value);
    $("#reader-document").style.setProperty("--reader-scale", state.zoom / 100);
  });
  $("#toggle-bookmark").addEventListener("click", () => {
    const key = noteKey();
    state.bookmarks.has(key) ? state.bookmarks.delete(key) : state.bookmarks.add(key);
    renderReader();
  });
  $("#save-note").addEventListener("click", () => {
    state.notes.set(noteKey(), $("#note-input").value.trim());
    $("#save-status").textContent = "이 세션의 현재 위치에 기록했습니다.";
  });

  const dialog = $("#import-dialog");
  $("#open-import").addEventListener("click", () => dialog.showModal());
  $("#file-concept").addEventListener("change", (event) => {
    const file = event.target.files[0];
    $("#file-concept-status").textContent = file ? `${file.name}을 선택했습니다. 이 MVP에서는 전송·저장하지 않습니다.` : "";
    event.target.value = "";
  });

  $("#toggle-motion").addEventListener("click", (event) => {
    state.reducedMotion = !state.reducedMotion;
    app.classList.toggle("reduced-motion", state.reducedMotion);
    event.currentTarget.setAttribute("aria-pressed", String(state.reducedMotion));
    event.currentTarget.textContent = state.reducedMotion ? "기본 움직임" : "움직임 줄이기";
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.readingMode !== "shelf" && !dialog.open) setMode("shelf");
    if (event.key === "ArrowLeft" && state.readingMode === "book") shiftPage(-2, "book");
    if (event.key === "ArrowRight" && state.readingMode === "book") shiftPage(2, "book");
  });

  renderShelf();
  renderShelfSummary();
})();
