(() => {
  "use strict";

  // #4489: the sidebar Library destination.
  //
  // Scope contract (do not widen):
  //   - Owns #filesNavButton behavior and the Library view only.
  //   - Navigable for any signed-in owner, whether or not project-file storage is
  //     provisioned. Protected actions stay unavailable with an accurate reason.
  //   - Reads only the canonical owner-scoped project-file pages this service
  //     publishes (`/api/project-files`), and opens a file only through the project
  //     seam app.js owns. It never fetches file bytes, builds a second reader, walks
  //     projects one by one, or indexes Drive, local PC, provider or Claw workspace
  //     data.
  //   - Pages are walked with the server's keyset cursor until the caller reaches the
  //     oldest stored file. Nothing here claims a complete listing unless the server
  //     reported no further page and every read succeeded.
  //   - This service does not persist chat images, so the image collection reports
  //     that truthfully instead of showing a fabricated list.
  //   - No browser storage primitive is read or written here.

  const OWNER_FILES_ENDPOINT = "/api/project-files";
  const OWNER_FILES_PAGE = 50;

  const shell = document.querySelector(".app-shell");
  const navButton = document.getElementById("filesNavButton");
  const view = document.getElementById("libraryView");
  const kicker = document.getElementById("libraryKicker");
  const heading = document.getElementById("libraryTitle");
  const subtitle = document.getElementById("librarySubtitle");
  const closeButton = document.getElementById("libraryCloseButton");
  const filesTab = document.getElementById("libraryFilesTab");
  const imagesTab = document.getElementById("libraryImagesTab");
  const note = document.getElementById("libraryNote");
  const filesPanel = document.getElementById("libraryFilesPanel");
  const imagesPanel = document.getElementById("libraryImagesPanel");
  const fileList = document.getElementById("libraryFileList");
  const imageList = document.getElementById("libraryImageList");
  const messageList = document.getElementById("messageList");

  if (!shell || !navButton || !view || !kicker || !heading || !subtitle || !closeButton) return;
  if (!filesTab || !imagesTab || !note || !filesPanel || !imagesPanel) return;
  if (!fileList || !imageList) return;

  let signedIn = false;
  let projectFilesReady = false;
  let authSignature = "";
  let lastAuthProjection = null;
  let activeTab = "files";
  let generation = 0;
  let loading = false;
  let loadingMore = false;
  let outcome = "idle";
  let rows = [];
  let cursor = null;
  let hasMore = false;
  let partialFailure = false;
  let complete = false;

  function copy(ko, en) {
    return document.documentElement.lang.toLowerCase().startsWith("en") ? en : ko;
  }

  const TEXT = {
    title: () => copy("라이브러리", "Library"),
    kicker: () => copy("PADIEM CHAT", "PADIEM CHAT"),
    subtitle: () => copy(
      "이 계정에 실제로 저장된 파일만 표시됩니다.",
      "Only files actually stored for this account are listed.",
    ),
    close: () => copy("채팅으로 돌아가기", "Back to chat"),
    files: () => copy("파일", "Files"),
    images: () => copy("이미지", "Images"),
    login: () => copy(
      "저장된 파일을 확인하려면 로그인하세요.",
      "Sign in to see your saved files.",
    ),
    loading: () => copy("불러오는 중…", "Loading…"),
    retry: () => copy("다시 시도", "Retry"),
    errorTitle: () => copy("파일 목록을 불러오지 못했습니다", "The file list could not be loaded"),
    errorBody: () => copy(
      "네트워크나 서버 상태를 확인한 뒤 다시 시도하세요.",
      "Check your connection or the server, then try again.",
    ),
    storageOff: () => copy(
      "이 계정에는 저장된 파일이 없습니다. 프로젝트 파일 저장이 아직 켜지지 않았습니다.",
      "No files are stored for this account. Project-file storage is not enabled yet.",
    ),
    empty: () => copy(
      "아직 저장된 파일이 없습니다. 프로젝트에 파일을 추가하면 여기에 표시됩니다.",
      "No saved files yet. Files added to a project will appear here.",
    ),
    incompleteEmpty: () => copy(
      "확인한 페이지에서 파일을 찾지 못했습니다. 전체 목록을 확인한 것은 아닙니다.",
      "No files found in the pages read so far. This is not a complete listing.",
    ),
    partial: () => copy(
      "일부 페이지를 불러오지 못했습니다. 아래 목록은 전체가 아닙니다.",
      "Some pages could not be read, so this list may be incomplete.",
    ),
    loadMore: () => copy("이전 파일 더 보기", "Load earlier files"),
    loadingMore: () => copy("이전 파일 불러오는 중…", "Loading earlier files…"),
    reachedEnd: () => copy(
      "가장 오래된 파일까지 확인했습니다.",
      "Reached the oldest stored file.",
    ),
    imagesTitle: () => copy("이미지는 저장되지 않습니다", "Images are not stored"),
    imagesBody: () => copy(
      "PADIEM Chat은 대화에 올린 이미지를 별도 라이브러리로 보관하지 않습니다. 이미지는 요청할 때만 사용되므로 지난 대화의 첨부 파일을 여기서 다시 열 수 없습니다. 저장된 문서 파일은 파일 탭에 표시됩니다.",
      "PADIEM Chat does not keep chat image uploads as a library. An image is used only for the request it was sent with, so earlier attachments cannot be reopened here. Stored document files appear in the Files tab.",
    ),
    project: (name) => copy(`프로젝트 ${name}`, `Project ${name}`),
    unnamedProject: () => copy("프로젝트 이름 확인 불가", "project name unavailable"),
    moreAvailable: () => copy(
      "이보다 오래된 저장 파일이 있습니다.",
      "Older stored files are available.",
    ),
    meta: (chars, mediaType) => copy(
      `${mediaType} · ${chars.toLocaleString()}자`,
      `${mediaType} · ${chars.toLocaleString()} characters`,
    ),
    open: () => copy("프로젝트에서 열기", "Open in project"),
    openBlocked: () => copy(
      "지금 열 수 없습니다. 진행 중인 요청을 마친 뒤 다시 시도하세요.",
      "Cannot open right now. Finish the request in progress, then try again.",
    ),
    count: (total) => copy(
      `저장된 파일 ${total}개`,
      `${total} stored file${total === 1 ? "" : "s"}`,
    ),
    // The plain total is only truthful once the server reported no further page and
    // every read succeeded; anything else says how much was actually confirmed.
    countSoFar: (total) => copy(
      `지금까지 확인한 파일 ${total}개`,
      `${total} file${total === 1 ? "" : "s"} read so far`,
    ),
  };

  function setNote(text) {
    note.textContent = text || "";
    note.hidden = !text;
  }

  // One monotonic generation per intent. A response carrying an older generation
  // is dropped before it can touch the DOM, so a superseded read or a session
  // flip can never paint over the current one.
  function invalidate() {
    generation += 1;
    loading = false;
    loadingMore = false;
    outcome = "idle";
    rows = [];
    cursor = null;
    hasMore = false;
    partialFailure = false;
    complete = false;
    fileList.replaceChildren();
    imageList.replaceChildren();
    setNote("");
  }

  function buildRow({ title, meta, detail, action }) {
    const item = document.createElement("div");
    item.className = "library-item";
    item.setAttribute("role", "listitem");

    const text = document.createElement("div");
    text.className = "library-item-text";
    const titleEl = document.createElement("p");
    titleEl.className = "library-item-title";
    titleEl.textContent = title;
    text.appendChild(titleEl);
    for (const value of [meta, detail]) {
      if (!value) continue;
      const line = document.createElement("p");
      line.className = value === meta ? "library-item-meta" : "library-item-detail";
      line.textContent = value;
      text.appendChild(line);
    }
    item.appendChild(text);

    if (action) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "library-item-action";
      button.textContent = action.label;
      button.addEventListener("click", action.run);
      item.appendChild(button);
    }
    return item;
  }

  function renderFiles() {
    fileList.replaceChildren();
    if (!signedIn) {
      setNote(TEXT.login());
      return;
    }
    if (loading) {
      setNote(TEXT.loading());
      return;
    }
    if (outcome === "error") {
      setNote(TEXT.errorBody());
      fileList.appendChild(buildRow({
        title: TEXT.errorTitle(),
        action: { label: TEXT.retry(), run: () => loadFiles() },
      }));
      return;
    }
    if (outcome === "storage-off") {
      setNote(TEXT.storageOff());
      return;
    }
    if (outcome !== "ready") {
      setNote("");
      return;
    }
    if (!rows.length) {
      // An unfinished walk or a failed page read is NOT a truthful empty account.
      setNote((!complete || partialFailure)
        ? [TEXT.incompleteEmpty(), partialFailure ? TEXT.partial() : ""].filter(Boolean).join(" · ")
        : TEXT.empty());
      if (hasMore) appendLoadMore();
      return;
    }
    setNote([
      complete ? TEXT.count(rows.length) : TEXT.countSoFar(rows.length),
      partialFailure ? TEXT.partial() : "",
      complete ? TEXT.reachedEnd() : "",
    ].filter(Boolean).join(" · "));
    for (const file of rows) {
      const label = typeof file.project_name === "string" && file.project_name
        ? file.project_name
        : TEXT.unnamedProject();
      fileList.appendChild(buildRow({
        title: file.name,
        meta: TEXT.project(label),
        detail: TEXT.meta(Number(file.content_chars) || 0, String(file.media_type || "")),
        action: { label: TEXT.open(), run: () => openProject(file.project_id) },
      }));
    }
    if (hasMore) appendLoadMore();
  }

  function appendLoadMore() {
    fileList.appendChild(buildRow({
      title: TEXT.moreAvailable(),
      action: {
        label: loadingMore ? TEXT.loadingMore() : TEXT.loadMore(),
        run: () => loadMore(),
      },
    }));
  }

  function renderImages() {
    imageList.replaceChildren();
    imageList.appendChild(buildRow({
      title: TEXT.imagesTitle(),
      detail: TEXT.imagesBody(),
    }));
    setNote("");
  }

  function render() {
    kicker.textContent = TEXT.kicker();
    heading.textContent = TEXT.title();
    subtitle.textContent = TEXT.subtitle();
    closeButton.textContent = "✕";
    closeButton.setAttribute("aria-label", TEXT.close());
    closeButton.title = TEXT.close();
    filesTab.textContent = TEXT.files();
    imagesTab.textContent = TEXT.images();
    filesTab.setAttribute("aria-selected", activeTab === "files" ? "true" : "false");
    imagesTab.setAttribute("aria-selected", activeTab === "images" ? "true" : "false");
    filesPanel.hidden = activeTab !== "files";
    imagesPanel.hidden = activeTab !== "images";
    if (activeTab === "files") {
      renderFiles();
    } else {
      renderImages();
    }
  }

  function isOpen() {
    return shell.dataset.state === "library";
  }

  function syncVisibility() {
    const active = isOpen();
    view.hidden = !active;
    navButton.setAttribute("aria-current", active ? "page" : "false");
    if (active) render();
  }

  function applyAvailability() {
    navButton.disabled = !signedIn;
    navButton.setAttribute("aria-disabled", signedIn ? "false" : "true");
  }

  function closeSidebar() {
    shell.classList.remove("sidebar-open");
    const menu = document.getElementById("mobileMenu");
    if (menu) menu.setAttribute("aria-expanded", "false");
    const scrim = document.getElementById("sidebarScrim");
    if (scrim) scrim.hidden = true;
  }

  function leaveLibrary() {
    // Only the surface state changes, so an in-flight request and the selected
    // model are untouched; the existing chat surface decides its own state.
    const hasMessages = Boolean(messageList && !messageList.hidden && messageList.childElementCount > 0);
    shell.dataset.state = hasMessages ? "chat" : "home";
    syncVisibility();
  }

  function openLibrary() {
    if (!signedIn) return;
    shell.dataset.state = "library";
    syncVisibility();
    closeSidebar();
    filesPanel.focus();
    if (activeTab === "files") loadFiles();
  }

  // The canonical dialog path owns project-file permission and every edit guard.
  // A project that is not in the loaded owner list resolves to nothing here.
  function openProject(projectId) {
    const opener = window.PadiemChatProjectOpener;
    if (!opener || typeof opener.open !== "function" || !opener.open(projectId)) {
      setNote(TEXT.openBlocked());
    }
  }

  // Exactly one fetch site for this whole surface: every read is a bounded, owner-scoped
  // page of the canonical project-file route.
  async function fetchPage(url, seq) {
    const response = await fetch(url, {
      headers: { "Accept": "application/json" },
      credentials: "same-origin",
      cache: "no-store",
    });
    if (seq !== generation) return null;
    const data = await response.json().catch(() => null);
    if (!response.ok || !data || !Array.isArray(data.files)) throw new Error("unavailable");
    return data;
  }

  // Appends one page in the server's keyset order. A row already shown is never shown
  // twice; a row the server did not send is never implied. Returning false means this
  // generation was superseded, so no state moves at all.
  async function readPage(after, seq) {
    const query = after === null
      ? `${OWNER_FILES_ENDPOINT}?limit=${OWNER_FILES_PAGE}`
      : `${OWNER_FILES_ENDPOINT}?limit=${OWNER_FILES_PAGE}&cursor=${encodeURIComponent(after)}`;
    const data = await fetchPage(query, seq);
    if (data === null) return false;
    const seen = new Set(rows.map((file) => file.id));
    for (const item of data.files) {
      if (!item || typeof item.id !== "string" || seen.has(item.id)) continue;
      if (typeof item.name !== "string" || typeof item.project_id !== "string") continue;
      seen.add(item.id);
      rows.push(item);
    }
    hasMore = data.has_more === true;
    cursor = typeof data.next_cursor === "string" ? data.next_cursor : null;
    return true;
  }

  async function loadFiles() {
    if (!signedIn || loading) return;
    const seq = ++generation;
    loading = true;
    outcome = "idle";
    rows = [];
    cursor = null;
    hasMore = false;
    partialFailure = false;
    complete = false;
    render();
    try {
      if (!projectFilesReady) {
        outcome = "storage-off";
        return;
      }
      if (!(await readPage(null, seq))) return;
      outcome = "ready";
      complete = !hasMore && !partialFailure;
    } catch (_) {
      if (seq !== generation) return;
      outcome = "error";
    } finally {
      if (seq === generation) {
        loading = false;
        if (isOpen() && activeTab === "files") render();
      }
    }
  }

  // Walking back through the same keyset is a continuation of one read, not a new
  // intent: it keeps the current generation, so a session flip mid-page still discards
  // the result instead of appending another account's rows. A failed page keeps what is
  // already shown and marks the listing not complete — never "all files loaded".
  async function loadMore() {
    if (!signedIn || loading || loadingMore || !hasMore || typeof cursor !== "string") return;
    const seq = generation;
    loadingMore = true;
    if (isOpen() && activeTab === "files") render();
    try {
      if (!(await readPage(cursor, seq)) || seq !== generation) return;
      complete = !hasMore && !partialFailure;
    } catch (_) {
      if (seq === generation) {
        partialFailure = true;
        complete = false;
      }
    } finally {
      loadingMore = false;
      if (seq === generation && isOpen() && activeTab === "files") render();
    }
  }

  // Entry availability follows the canonical capability projection, so it
  // re-checks when that projection changes — never on a timer.
  function applyAuthState(auth) {
    const nextSignedIn = Boolean(auth && auth.loaded === true && auth.authenticated === true);
    const nextProjectFilesReady = Boolean(auth && auth.projectFilesReady === true);
    // The public capability projection intentionally omits the user ID. A
    // refreshed auth snapshot is a NEW frozen object even when signed-in and
    // storage-ready booleans (and the visible account name) stay identical.
    // Treat every new auth projection as a session boundary to avoid showing
    // another owner's previously rendered filenames after a direct switch.
    const nextProjection = auth && typeof auth === "object" ? auth : null;
    const projectionChanged = nextProjection !== lastAuthProjection;
    lastAuthProjection = nextProjection;
    signedIn = nextSignedIn;
    projectFilesReady = nextProjectFilesReady;
    const signature = `${nextSignedIn}/${nextProjectFilesReady}`;
    const changed = signature !== authSignature;
    authSignature = signature;
    // Login as well as logout crosses here, so a new account can never inherit
    // the previous owner's rendered rows.
    if (changed || projectionChanged) invalidate();
    applyAvailability();
    if (!signedIn && isOpen()) leaveLibrary();
    if (isOpen()) {
      render();
      // If the same signed-in state was refreshed while Library is open,
      // show fresh owner-scoped data instead of retaining an older DOM.
      if (projectionChanged && signedIn && activeTab === "files") loadFiles();
    }
  }

  function readCapabilityAuth() {
    const api = window.PadiemProductCapabilities;
    if (!api || typeof api.get !== "function") return null;
    try {
      const state = api.get();
      return state && state.auth ? state.auth : null;
    } catch (_) {
      return null;
    }
  }

  function selectTab(next) {
    if (activeTab === next) return;
    invalidate();
    activeTab = next;
    render();
    if (next === "files") loadFiles();
  }

  filesTab.addEventListener("click", () => selectTab("files"));
  imagesTab.addEventListener("click", () => selectTab("images"));
  navButton.addEventListener("click", openLibrary);
  closeButton.addEventListener("click", leaveLibrary);

  window.addEventListener("padiem:capabilitychange", (event) => {
    const auth = event && event.detail ? event.detail.auth : null;
    applyAuthState(auth || readCapabilityAuth());
  });

  window.addEventListener("padiem:localechange", () => {
    if (isOpen()) render();
  });

  // Any other path that leaves the Library surface (new chat, Claw, Calendar,
  // opening a conversation) hides this view without importing this module.
  if (typeof MutationObserver === "function") {
    new MutationObserver(syncVisibility).observe(shell, {
      attributes: true,
      attributeFilter: ["data-state"],
    });
  }

  applyAuthState(readCapabilityAuth());
  syncVisibility();

  window.PadiemChatLibrary = Object.freeze({
    isOpen,
    getOutcome: () => outcome,
    getRowCount: () => rows.length,
    hasMore: () => hasMore,
    isComplete: () => complete,
    hasPartialFailure: () => partialFailure,
    isLoadingMore: () => loadingMore,
  });
})();
