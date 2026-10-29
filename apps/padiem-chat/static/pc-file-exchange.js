// #5895: the shared "bring a file from my PC" and "save it back" part every menu can open.
//
// One call opens either half — `window.PadiemPcFileExchange.open({ onSelect })` to pick
// a file up, `.open({ mode: "save", content, onSave })` to put one down — so the stable
// writing screen, the B66 quote sheet and the PDF·Markdown menu never grow their own
// file browser.
//
// What the owner sees is only their own words: which PC, which folder, which file. No
// path box, no device identifier, no technical term. Nothing here decides how long a
// PC may take or how many entries a folder holds; the server's own record ends the
// wait, and while it runs the screen says what is true in the same words #5895 uses
// everywhere else — still working, with the time that has passed. The owner can always
// press 그만, which stops asking and takes what has not reached the PC out of its queue.
//
// A search is spread over the folders instead of run as one long command, so the
// matches arrive as they are found and the PC is never held by one huge sweep.
(function (root) {
  "use strict";

  const BROWSE = "/api/pc/browse";
  const FIND = "/api/pc/find";
  const FETCH = "/api/pc/fetch";
  const SAVE = "/api/pc/save";
  const MOVE = "/api/pc/move";
  const DELETE = "/api/pc/delete";
  const CANCEL = "/api/pc/cancel";
  const RESULT = "/api/pc/result";
  // How many already-received entries are shown before "더 보기". It splits the
  // answer on the screen; it never discards part of it.
  const PAGE = 60;

  const state = {
    open: false, nodes: null, mode: "import", linkId: null, path: ".", folderName: "",
    items: [], shown: PAGE, selection: null, chosenPath: null, waiting: false, error: null, note: null,
    startedAt: 0, timer: null, focusBefore: null, dispatchId: null, onFileName: null,
    runId: null, sweep: null,
    // #5895 follow-up: a folder is paged by the server. These carry the PC's own total,
    // where the next page starts, and whether a page failed — so the screen can say
    // "남은 N개" and never present a part of a folder as the whole of it.
    total: null, hasMore: false, nextCursor: null, loadingMore: false, partial: false,
    filter: "", query: "", seen: null,
  };
  // Every stop raises this, so a wait that is still in flight notices it and returns
  // instead of polling on for an operation the owner has left behind.
  let waitToken = 0;

  function copy(key, variables) {
    const locale = root.__padiemLocale;
    return locale && typeof locale.text === "function" ? locale.text(key, variables) : key;
  }

  function element(tag, className, text) {
    const node = root.document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  async function post(url, payload) {
    const response = await root.fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      credentials: "same-origin",
      cache: "no-store",
      body: JSON.stringify(payload),
    });
    return { status: response.status, body: await response.json().catch(() => null) };
  }

  async function read(id) {
    const query = new root.URLSearchParams({ dispatch_id: id });
    const response = await root.fetch(RESULT + "?" + query.toString(), {
      headers: { Accept: "application/json" }, credentials: "same-origin", cache: "no-store",
    });
    return { status: response.status, body: await response.json().catch(() => null) };
  }

  function stopClock() {
    if (state.timer !== null) {
      root.clearInterval(state.timer);
      state.timer = null;
    }
  }

  function elapsedText() {
    const seconds = Math.max(0, Math.floor((root.Date.now() - state.startedAt) / 1000));
    const clock = root.PadiemChatLifecycle && root.PadiemChatLifecycle.elapsedClockText;
    return typeof clock === "function" ? clock(seconds) : seconds + "s";
  }

  function paintStatus() {
    const nodes = state.nodes;
    if (!nodes) return;
    const sweeping = state.sweep !== null;
    nodes.stop.hidden = !(sweeping || state.waiting);
    if (state.waiting && sweeping) {
      // What is true while the search walks the folders: how many it has been through
      // and how many matches it has so far. Not a failure, not a count of what is left.
      nodes.status.textContent = copy("pc-exchange-searching", {
        folders: state.sweep.asked + 1, files: state.items.length,
      });
      nodes.status.dataset.state = "status";
      nodes.status.hidden = false;
      return;
    }
    if (state.waiting) {
      nodes.status.textContent = copy("pc-exchange-working", { elapsed: elapsedText() });
      nodes.status.dataset.state = "status";
      nodes.status.hidden = false;
      return;
    }
    if (state.error) {
      nodes.status.textContent = copy(state.error);
      nodes.status.dataset.state = "error";
      nodes.status.hidden = false;
      return;
    }
    if (state.partial) {
      // Half a folder is stated as half a folder — never as an empty one and never
      // as a finished one.
      nodes.status.textContent = copy("pc-exchange-partial");
      nodes.status.dataset.state = "error";
      nodes.status.hidden = false;
      return;
    }
    if (state.note) {
      nodes.status.textContent = copy(state.note);
      nodes.status.dataset.state = "note";
      nodes.status.hidden = false;
      return;
    }
    nodes.status.hidden = true;
    nodes.status.textContent = "";
  }

  function busy() {
    state.waiting = true;
    state.error = null;
    state.note = null;
    state.startedAt = root.Date.now();
    paintStatus();
    if (state.timer === null) state.timer = root.setInterval(paintStatus, 1000);
  }

  function done() {
    state.waiting = false;
    if (state.sweep === null) state.runId = null;
    stopClock();
    paintStatus();
  }

  function refused(code) {
    if (state.loadingMore) {
      // A page that did not arrive is not an empty folder. Keep what was received,
      // stop asking, and say plainly that this is only some of it.
      state.loadingMore = false;
      state.partial = true;
      stopClock();
      paintStatus();
      paintList();
      return;
    }
    // An operation that came back refused leaves nothing else waiting behind it.
    stopSweep({ quiet: true });
    state.waiting = false;
    state.error = code || "pc-exchange-no-answer";
    stopClock();
    paintStatus();
  }

  // No attempt count and no give-up time: the operation is over when the server's
  // own record says it is, and the clock keeps counting until then. The one thing that
  // ends a wait early is the owner's own 그만, which raises the token below.
  async function wait(id, onReady) {
    const token = waitToken;
    busy();
    for (;;) {
      if (token !== waitToken) return;
      let answer = null;
      try {
        answer = await read(id);
      } catch (_) {
        answer = null;
      }
      if (token !== waitToken) return;
      if (answer === null) continue;
      const body = answer.body;
      if (answer.status === 200 && body && body.state === "working") {
        const seconds = Number(body.poll_seconds);
        await new Promise((resolve) => root.setTimeout(resolve, (seconds > 0 ? seconds : 2) * 1000));
        continue;
      }
      if (answer.status === 200 && body && body.state === "ready") {
        done();
        onReady(body);
        return;
      }
      if (answer.status === 200 && body && body.state === "cancelled") {
        // The server's record already says the owner stopped this. It is a state of
        // the operation, not a PC that failed, so nothing is shown as an error.
        done();
        return;
      }
      refused("pc-exchange-no-answer");
      return;
    }
  }

  function pathOf(item) {
    if (typeof item.path === "string" && item.path) return item.path;
    if (state.path === ".") return item.name;
    return state.path.endsWith("/") ? state.path + item.name : state.path + "/" + item.name;
  }

  // A folder the owner came in through is named by its label, so its parent is the
  // place that offers the labels again — never a half-typed drive letter.
  function parentOf(path) {
    const text = path.replace(/\/+$/, "");
    if (!text || text === ".") return ".";
    const index = text.lastIndexOf("/");
    if (index < 0) return ".";
    return text.slice(0, index + 1);
  }

  function pageInto(body, append) {
    const items = Array.isArray(body.items) ? body.items : [];
    if (!append) state.seen = new Set();
    // A folder can change between two pages: a row that has already been shown is not
    // shown again, so the list never carries the same name twice.
    const fresh = items.filter((item) => {
      const name = String((item && item.name) || "");
      if (!state.seen || state.seen.has(name)) return false;
      state.seen.add(name);
      return true;
    });
    state.items = append ? state.items.concat(fresh) : fresh;
    state.total = typeof body.total === "number" ? body.total : null;
    state.hasMore = body.has_more === true;
    state.nextCursor = typeof body.next_cursor === "string" ? body.next_cursor : null;
    state.loadingMore = false;
    state.partial = false;
    if (!append) state.shown = PAGE;
    if (state.query && state.items.length === 0 && !state.hasMore) {
      // The PC looked through the whole folder for the name and found nothing. That is
      // said as such, never as an empty folder.
      state.note = "pc-exchange-folder-search-empty";
    }
    paintList();
    paintStatus();
  }

  function listed(body) {
    pageInto(body, false);
  }

  function visibleItems() {
    const needle = state.filter.trim().toLowerCase();
    if (!needle) return state.items;
    return state.items.filter(
      (item) => String(item.name || "").toLowerCase().includes(needle));
  }

  // The next page is a real request to the PC: the server only ever handed back the
  // rows it had, and this asks for the ones after them at the same fixed order.
  function loadMore() {
    if (!state.hasMore || !state.nextCursor || state.loadingMore || state.waiting) return;
    state.loadingMore = true;
    state.partial = false;
    paintStatus();
    const payload = { path: state.path, cursor: state.nextCursor };
    if (state.query) payload.filter = state.query;
    void start(BROWSE, payload, (body) => pageInto(body, true), { keep: true });
  }

  // The whole folder, searched by the PC itself. The screen only ever holds the pages
  // it was given, so a name that lives on a page nobody fetched is found here — not by
  // pretending the received page is the folder.
  function searchWholeFolder() {
    const term = state.filter.trim();
    if (!term) return;
    stopSweep({ quiet: true });
    state.query = term;
    state.items = [];
    state.shown = PAGE;
    state.total = null;
    state.hasMore = false;
    state.nextCursor = null;
    state.loadingMore = false;
    state.partial = false;
    state.note = null;
    paintList();
    void start(BROWSE, { path: state.path, filter: term }, listed);
  }

  function backToWholeFolder() {
    state.query = "";
    state.items = [];
    state.shown = PAGE;
    state.total = null;
    state.hasMore = false;
    state.nextCursor = null;
    state.partial = false;
    state.note = null;
    paintList();
    void start(BROWSE, { path: state.path }, listed);
  }

  // A search is one operation spread over folders instead of one command over a whole
  // drive. The screen asks for one folder at a time, so every match shows up as soon as
  // its folder has been looked through, and a PC is never held by one huge sweep while
  // the owner waits for a folder listing. Stopping is the same thing as stopping asking.
  function startSearch(name) {
    stopSweep({ quiet: true });
    state.sweep = { name: name, folder: null, remaining: [], asked: 0, running: true,
                    stopped: false };
    state.folderName = "";
    state.selection = null;
    state.items = [];
    state.shown = PAGE;
    state.total = null;
    state.hasMore = false;
    state.nextCursor = null;
    state.loadingMore = false;
    state.partial = false;
    state.query = "";
    state.note = null;
    paintList();
    void sweepStep();
  }

  function sweepStep() {
    const sweep = state.sweep;
    if (!sweep || sweep.stopped) return;
    const payload = { name: sweep.name };
    if (sweep.folder) {
      payload.run_id = state.runId;
      payload.folder = sweep.folder;
      payload.remaining = sweep.remaining;
    }
    void start(FIND, payload, (body) => {
      if (sweep.stopped) return;
      appendFound(body.found || []);
      if (!sweep.folder) sweep.remaining = (body.folders || []).slice();
      if (sweep.remaining.length > 0) {
        sweep.folder = sweep.remaining.shift();
        sweep.asked += 1;
        void sweepStep();
        return;
      }
      // Nothing is left to look in, so there is nothing to stop either.
      state.sweep = null;
      state.note = state.items.length
        ? "pc-exchange-searched" : "pc-exchange-searched-empty";
      done();
    }, { keep: true, retry: sweepStep });
  }

  function appendFound(rows) {
    if (rows.length === 0) return;
    state.items = state.items.concat(rows);
    paintList();
  }

  // The owner pressed 그만: the screen stops waiting, and the server takes out of the
  // queue whatever has not reached a PC yet. A command the PC is already running is
  // left to finish — refusing it would only make the connector hold the queue longer.
  function stopAsking() {
    const runId = state.runId;
    waitToken += 1;
    if (state.sweep) {
      state.sweep.stopped = true;
      state.sweep.running = false;
    }
    state.sweep = null;
    state.runId = null;
    return runId;
  }

  function stopSweep(options) {
    const settings = options || {};
    const runId = stopAsking();
    // Whatever the owner is doing next — pressing 그만, stepping into a folder, or
    // searching again — the folder that has not reached a PC yet must not sit in the
    // queue behind it. Only the screen state differs between those cases.
    if (runId) void post(CANCEL, { run_id: runId }).catch(() => null);
    if (settings.quiet) return;
    state.waiting = false;
    state.error = null;
    state.note = "pc-exchange-stopped";
    stopClock();
    paintStatus();
    paintList();
  }

  function hideChoices() {
    if (state.nodes) state.nodes.pcs.hidden = true;
  }

  function offerChoices(items, onPick, groupLabelKey) {
    const nodes = state.nodes;
    if (!nodes) return;
    nodes.pcs.replaceChildren();
    nodes.pcs.setAttribute("aria-label", copy(groupLabelKey));
    items.forEach((item) => {
      const button = element("button", "pc-exchange-choice", item.label);
      button.type = "button";
      button.dataset.choice = item.value;
      button.addEventListener("click", () => {
        hideChoices();
        onPick(item);
      });
      nodes.pcs.append(button);
    });
    nodes.pcs.hidden = false;
  }

  function askForPc(links, retry) {
    if (links.length === 0) {
      refused("pc-exchange-no-pc");
      return;
    }
    offerChoices(links.map((link) => ({
      label: link.label || copy("pc-exchange-my-pc"), value: link.link_id,
    })), (choice) => {
      state.linkId = choice.value;
      if (retry) {
        retry();
        return;
      }
      state.path = ".";
      state.folderName = "";
      state.selection = null;
      void start(BROWSE, { path: "." }, listed);
    }, "pc-exchange-choose-pc");
  }

  function askForFolder(folders) {
    offerChoices(folders.map((folder) => ({
      label: folder.label, value: folder.path,
    })), (choice) => {
      state.path = choice.value;
      state.folderName = choice.label;
      state.selection = null;
      void start(BROWSE, { path: choice.value }, listed);
    }, "pc-exchange-choose-folder");
  }

  function rowFor(item) {
    const row = element("li", "pc-exchange-item");
    const button = element("button", "pc-exchange-entry");
    button.type = "button";
    button.dataset.name = item.name;
    button.dataset.kind = item.kind;
    button.append(element("span", "pc-exchange-mark", item.kind === "folder" ? "▸" : "•"));
    button.append(element("span", "pc-exchange-name", item.name));
    if (item.kind === "file" && Number.isFinite(item.size_bytes)) {
      button.append(element("span", "pc-exchange-size", Math.max(1, Math.round(item.size_bytes / 1024)) + " KB"));
    }
    if (typeof item.folder === "string" && item.folder) {
      button.append(element("span", "pc-exchange-folder", item.folder));
    }
    button.addEventListener("click", () => {
      if (item.kind === "folder") {
        // Stepping into a folder is the short request the sweep must not be holding:
        // the search stops asking, and the listing is asked for on its own.
        stopSweep({ quiet: true });
        clearFilter();
        state.query = "";
        state.path = pathOf(item);
        state.folderName = item.name;
        state.selection = null;
        void start(BROWSE, { path: state.path }, listed);
        return;
      }
      state.selection = item;
      if (state.mode === "save" && typeof state.onFileName === "function") {
        // The owner is naming a file, not opening one: the list is only showing
        // what already lives in this folder. The chosen file is remembered so
        // moving or deleting it acts on the file the owner actually clicked.
        state.onFileName(item.name);
        state.chosenPath = pathOf(item);
        state.selection = null;
        if (state.nodes && state.nodes.move) {
          state.nodes.move.hidden = false;
          state.nodes.erase.hidden = false;
        }
        return;
      }
      paintList();
    });
    row.append(button);
    return row;
  }

  function clearFilter() {
    state.filter = "";
    if (state.nodes && state.nodes.search) state.nodes.search.value = "";
  }

  function paintList() {
    const nodes = state.nodes;
    if (!nodes) return;
    nodes.list.replaceChildren();
    const visible = visibleItems();
    const shown = visible.slice(0, state.shown);
    shown.forEach((item) => nodes.list.append(rowFor(item)));
    const canReveal = visible.length > shown.length;
    nodes.more.hidden = !(canReveal || state.hasMore);
    // What the search box is actually looking at: only the rows received so far, which
    // is not the folder. Said plainly whenever a filter is typed.
    const term = state.filter.trim();
    if (nodes.scope) {
      nodes.scope.hidden = !term;
      if (term) {
        nodes.scope.textContent = copy("pc-exchange-filter-scope", {
          received: state.items.length,
          total: state.total === null ? "?" : state.total,
        });
      }
    }
    if (nodes.searchAll) {
      // Nothing matched among what arrived, and the PC still holds rows nobody asked
      // for: offer the whole-folder search instead of an "empty" the folder may not be.
      nodes.searchAll.hidden = !(term && visible.length === 0 && state.hasMore);
    }
    const remaining = state.total === null ? null : Math.max(0, state.total - state.items.length);
    nodes.more.textContent = remaining === null || remaining === 0
      ? copy("pc-exchange-more")
      : copy("pc-exchange-more-remaining", { count: remaining });
    nodes.folderLabel.textContent = state.folderName || copy("pc-exchange-contents");
    // Every path change lands here: the root disables 이전 폴더, any folder
    // inside re-arms it — in save mode too.
    nodes.back.disabled = state.path === ".";
    if (state.mode === "save") {
      nodes.pick.hidden = false;
      return;
    }
    nodes.pick.hidden = !(state.selection && state.selection.kind === "file");
    nodes.pick.textContent = state.selection
      ? copy("pc-exchange-open-file", { name: state.selection.name })
      : copy("pc-exchange-open-file", { name: "" });
  }

  // One request shape for every verb: ask, then watch the server's record. `keep`
  // leaves the entries already on the screen where they are, which is what a search
  // needs as it moves from folder to folder.
  async function start(url, payload, onReady, options) {
    const settings = options || {};
    if (state.linkId) payload.link_id = state.linkId;
    let answer;
    try {
      answer = await post(url, payload);
    } catch (_) {
      refused("pc-exchange-no-answer");
      return;
    }
    const code = answer.body && answer.body.error && answer.body.error.code;
    if (code === "pc_link_selection_required") {
      askForPc((answer.body.links || []).filter((link) => link && link.link_id), settings.retry);
      return;
    }
    if (code === "pc_folder_selection_required") {
      askForFolder((answer.body.folders || []).filter((folder) => folder && folder.label));
      return;
    }
    if (code === "pc_not_linked") {
      refused("pc-exchange-no-pc");
      return;
    }
    hideChoices();
    if (answer.status !== 200 || !answer.body || answer.body.ok !== true) {
      refused("pc-exchange-no-answer");
      return;
    }
    state.dispatchId = answer.body.dispatch_id;
    state.runId = answer.body.run_id || null;
    if (!settings.keep) {
      state.items = [];
      state.shown = PAGE;
      paintList();
    }
    await wait(answer.body.dispatch_id, onReady);
  }

  function build(settings) {
    const mode = settings.mode === "save" ? "save" : "import";
    const onSelect = settings.onSelect;
    const onSave = settings.onSave;
    const overlay = element("div", "pc-exchange-overlay");
    const dialog = element("section", "pc-exchange-dialog");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-label", copy(mode === "save"
      ? "pc-exchange-save-title" : "pc-exchange-import-title"));
    dialog.setAttribute("tabindex", "-1");

    const heading = element("h2", "pc-exchange-heading",
      copy(mode === "save" ? "pc-exchange-save-title" : "pc-exchange-import-title"));
    const note = element("p", "pc-exchange-note",
      copy(mode === "save" ? "pc-exchange-save-note" : "pc-exchange-import-note"));
    const pcs = element("div", "pc-exchange-pcs");
    pcs.hidden = true;
    pcs.setAttribute("role", "group");
    pcs.setAttribute("aria-label", copy("pc-exchange-choose-pc"));

    const tools = element("div", "pc-exchange-tools");
    const back = element("button", "pc-exchange-back", copy("pc-exchange-up"));
    back.type = "button";
    // The dialog opens at the root, where there is no parent folder: the button
    // is born disabled and paintList keeps the state glued to the path the
    // owner is actually in. The name stays on the button for assistive tech
    // even on the phone, where the row only has room for the arrow.
    back.setAttribute("aria-label", copy("pc-exchange-up"));
    back.disabled = state.path === ".";
    const search = element("input", "pc-exchange-search");
    search.type = "search";
    search.setAttribute("aria-label", copy("pc-exchange-search-placeholder"));
    search.placeholder = copy("pc-exchange-search-placeholder");
    const searchButton = element("button", "pc-exchange-search-button", copy("pc-exchange-search"));
    searchButton.type = "button";
    // Saving names the file it writes, so the folder it lands in can be chosen.
    const naming = element("label", "pc-exchange-naming");
    const fileName = element("input", "pc-exchange-filename");
    fileName.type = "text";
    fileName.value = settings.fileName || "";
    fileName.setAttribute("aria-label", copy("pc-exchange-save-name"));
    fileName.placeholder = copy("pc-exchange-save-name");
    naming.append(element("span", "pc-exchange-name-label", copy("pc-exchange-save-name")));
    naming.append(fileName);
    tools.append(back, search, searchButton);

    const scope = element("p", "pc-exchange-scope");
    scope.hidden = true;
    const list = element("ul", "pc-exchange-list");
    // The dialog keeps its own title and says which folder is open on its own line,
    // so browsing never replaces the words that named what the owner is doing.
    const folderLabel = element("p", "pc-exchange-folder-label", copy("pc-exchange-contents"));
    const more = element("button", "pc-exchange-more", copy("pc-exchange-more"));
    more.type = "button";
    more.hidden = true;
    const searchAll = element("button", "pc-exchange-search-all", copy("pc-exchange-search-all"));
    searchAll.type = "button";
    searchAll.hidden = true;
    const status = element("p", "pc-exchange-status");
    status.hidden = true;

    const footer = element("div", "pc-exchange-footer");
    const cancel = element("button", "pc-exchange-cancel", copy("pc-exchange-close"));
    cancel.type = "button";
    // The one control that ends a wait early: it stops this account's own operation,
    // and what the PC has already answered stays on the screen. No question is asked
    // first, because the owner already said so by pressing it.
    const stop = element("button", "pc-exchange-stop", copy("pc-exchange-stop"));
    stop.type = "button";
    stop.hidden = true;
    const pick = element("button", "pc-exchange-pick", copy("pc-exchange-open-file", { name: "" }));
    pick.type = "button";
    pick.hidden = true;
    footer.append(cancel, stop, pick);

    dialog.append(heading, note, pcs, tools, scope, folderLabel, list, more, searchAll,
      status, footer);
    overlay.append(dialog);

    back.addEventListener("click", () => {
      const parent = parentOf(state.path);
      if (parent === state.path) return;
      // One short request at a time: stepping out stops the search that was walking the
      // folders, so the listing the owner asked for is not queued behind it.
      stopSweep({ quiet: true });
      clearFilter();
      state.query = "";
      state.path = parent;
      const text = parent.replace(/\/+$/, "");
      state.folderName = text ? text.slice(text.lastIndexOf("/") + 1) : "";
      state.selection = null;
      void start(BROWSE, { path: parent }, listed);
    });
    searchAll.addEventListener("click", () => searchWholeFolder());
    more.addEventListener("click", () => {
      // Already-received rows first (it splits the answer on the screen), then the
      // next page from the PC — a folder is never cut off at one page.
      if (visibleItems().length > state.shown) {
        state.shown += PAGE;
        paintList();
        return;
      }
      loadMore();
    });
    // Reaching the bottom of the list asks for the next page by itself; the button
    // stays for keyboards and for anyone who would rather ask.
    list.addEventListener("scroll", () => {
      if (state.loadingMore || !state.hasMore) return;
      if (list.scrollTop + list.clientHeight < list.scrollHeight - 48) return;
      if (visibleItems().length > state.shown) {
        state.shown += PAGE;
        paintList();
        return;
      }
      loadMore();
    });
    cancel.addEventListener("click", close);
    stop.addEventListener("click", () => stopSweep({}));
    overlay.addEventListener("click", (event) => { if (event.target === overlay) close(); });
    searchButton.addEventListener("click", () => {
      const name = search.value.trim();
      if (!name) return;
      state.folderName = "";
      startSearch(name);
    });
    search.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        searchButton.click();
      }
    });
    // Typing filters what has already arrived, immediately. Asking the PC for a
    // full name search is still the button/Enter path, so a large folder is never
    // walked just because someone typed a letter.
    search.addEventListener("input", () => {
      state.filter = search.value;
      state.shown = PAGE;
      paintList();
      if (state.query && !state.filter.trim()) {
        // Clearing the box means the owner is done with the search: go back to the
        // folder itself rather than leave a filtered listing behind an empty box.
        backToWholeFolder();
      }
    });
    pick.addEventListener("click", () => {
      if (mode === "save") {
        const wanted = fileName.value.trim();
        if (!wanted) return;
        const path = state.path === "." ? wanted : state.path.replace(/\/+$/, "") + "/" + wanted;
        const payload = settings.fileId ? { path, file_id: settings.fileId }
          : { path, content: typeof settings.content === "string" ? settings.content : "" };
        void start(SAVE, payload, (body) => {
          const saved = body.saved || {};
          if (body.ok !== true) {
            refused("pc-exchange-save-failed");
            return;
          }
          close();
          onSave(saved);
        });
        return;
      }
      const item = state.selection;
      if (!item) return;
      void start(FETCH, { path: pathOf(item) }, (body) => {
        const picked = {
          name: item.name,
          kind: body.content_kind === "text" ? "text" : "file",
          content: typeof body.content === "string" ? body.content : null,
          fileId: body.file_id || null,
          sizeBytes: Number.isFinite(body.size_bytes) ? body.size_bytes : null,
          // The folder it was found in, so a result can be offered back beside it.
          folder: state.path,
        };
        close();
        onSelect(picked);
      });
    });
    let moveButton = null;
    let eraseButton = null;
    if (mode === "save") {
      // A file already on the PC is a name worth offering, not a thing to open:
      // choosing it only fills in the name box, and saving over it is what the
      // backup that #5573 takes first is for.
      tools.append(naming);
      // The same file the name box is describing can also be moved under the new
      // name, or taken off the PC. Both go through #5573's write, so the copy that
      // is replaced is backed up first, exactly as saving over it would be.
      const manage = element("div", "pc-exchange-manage");
      const move = element("button", "pc-exchange-move", copy("pc-exchange-move-button"));
      move.type = "button";
      move.hidden = true;
      const erase = element("button", "pc-exchange-delete", copy("pc-exchange-delete-button"));
      erase.type = "button";
      erase.hidden = true;
      moveButton = move;
      eraseButton = erase;
      manage.append(move, erase);
      tools.append(manage);      move.addEventListener("click", () => {
        const wanted = fileName.value.trim();
        if (!state.chosenPath || !wanted) return;
        const folder = state.path === "." ? "" : state.path.replace(/\/+$/, "") + "/";
        void start(MOVE, { path: state.chosenPath, destination: folder + wanted }, (body) => {
          if (body.ok !== true) {
            refused("pc-exchange-move-failed");
            return;
          }
          close();
          onSave(body.moved || {});
        });
      });
      erase.addEventListener("click", () => {
        if (!state.chosenPath) return;
        void start(DELETE, { path: state.chosenPath }, (body) => {
          if (body.ok !== true) {
            refused("pc-exchange-delete-failed");
            return;
          }
          close();
          onSave(body.deleted || {});
        });
      });
      search.hidden = true;
      searchButton.hidden = true;
      pick.hidden = false;
      pick.className = "pc-exchange-save";
      pick.textContent = copy("pc-exchange-save-button");
      pick.disabled = !fileName.value.trim();
      state.onFileName = (name) => {
        fileName.value = name;
        pick.disabled = false;
      };
    }

    return {
      overlay, dialog, heading, list, more, status, search, searchButton, back, pcs, pick,
      fileName, folderLabel, stop, move: moveButton, erase: eraseButton, scope, searchAll,
    };
  }

  function close() {
    if (!state.open) return;
    // Leaving the dialog is also a stop: a folder the PC has not started looking in
    // must not sit in the queue for whoever uses this PC next.
    stopSweep({ quiet: true });
    state.open = false;
    state.waiting = false;
    state.onFileName = null;
    stopClock();
    if (state.nodes && state.nodes.overlay.parentNode) {
      state.nodes.overlay.parentNode.removeChild(state.nodes.overlay);
    }
    state.nodes = null;
    const restore = state.focusBefore;
    state.focusBefore = null;
    if (restore && typeof restore.focus === "function") restore.focus();
  }

  function open(options) {
    const settings = options || {};
    const saving = settings.mode === "save";
    if (typeof (saving ? settings.onSave : settings.onSelect) !== "function") {
      return { close: close };
    }
    if (state.open) close();
    state.open = true;
    state.mode = saving ? "save" : "import";
    state.linkId = null;
    // A save can name the folder it starts in, so a converted result lands
    // beside the document it came from instead of at the top of the drive.
    state.path = (typeof settings.startFolder === "string" && settings.startFolder)
      ? settings.startFolder : ".";
    state.folderName = state.path === "."
      ? "" : state.path.replace(/\/+$/, "").split("/").pop();
    state.items = [];
    state.shown = PAGE;
    state.total = null;
    state.hasMore = false;
    state.nextCursor = null;
    state.loadingMore = false;
    state.partial = false;
    state.filter = "";
    state.query = "";
    state.seen = null;
    state.selection = null;
    state.chosenPath = null;
    state.error = null;
    state.note = null;
    state.dispatchId = null;
    state.runId = null;
    state.sweep = null;
    state.focusBefore = root.document.activeElement;
    state.nodes = build(settings);
    root.document.body.append(state.nodes.overlay);
    state.nodes.dialog.focus();
    void start(BROWSE, { path: state.path }, listed);
    return { close: close };
  }

  root.PadiemPcFileExchange = Object.freeze({
    open: open,
    close: close,
    stop: function () { stopSweep({}); },
    isOpen: function () { return state.open; },
    current: function () {
      return {
        path: state.path, linkId: state.linkId, waiting: state.waiting,
        items: state.items.length, dispatchId: state.dispatchId,
        runId: state.runId, sweeping: state.sweep !== null,
        foldersLookedIn: state.sweep ? state.sweep.asked : 0,
      };
    },
  });
})(typeof window !== "undefined" ? window : globalThis);
