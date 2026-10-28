// #5895: the shared "bring a file from my PC" and "save it back" part every menu can open.
//
// One call opens either half — `window.PadiemPcFileExchange.open({ onSelect })` to pick
// a file up, `.open({ mode: "save", content, onSave })` to put one down — so the stable
// writing screen, the B66 quote sheet and the PDF·Markdown menu never grow their own
// file browser.
//
// What the owner sees is only their own words: which PC, which folder, which file. No
// path box, no device identifier, no technical term. Nothing here decides how long a
// PC may take, how many entries a folder holds, or when to stop asking: the server's
// own record ends the wait, and while it runs the screen says what is true in the same
// words #5895 uses everywhere else — still working, with the time that has passed.
(function (root) {
  "use strict";

  const BROWSE = "/api/pc/browse";
  const FIND = "/api/pc/find";
  const FETCH = "/api/pc/fetch";
  const SAVE = "/api/pc/save";
  const RESULT = "/api/pc/result";
  // How many already-received entries are shown before "더 보기". It splits the
  // answer on the screen; it never discards part of it.
  const PAGE = 60;

  const state = {
    open: false, nodes: null, mode: "import", linkId: null, path: ".", folderName: "",
    items: [], shown: PAGE, selection: null, waiting: false, error: null,
    startedAt: 0, timer: null, focusBefore: null, dispatchId: null, onFileName: null,
  };

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
    nodes.status.hidden = true;
    nodes.status.textContent = "";
  }

  function busy() {
    state.waiting = true;
    state.error = null;
    state.startedAt = root.Date.now();
    paintStatus();
    if (state.timer === null) state.timer = root.setInterval(paintStatus, 1000);
  }

  function done() {
    state.waiting = false;
    stopClock();
    paintStatus();
  }

  function refused(code) {
    state.waiting = false;
    state.error = code || "pc-exchange-no-answer";
    stopClock();
    paintStatus();
  }

  // No attempt count and no give-up time: the operation is over when the server's
  // own record says it is, and the clock keeps counting until then.
  async function wait(id, onReady) {
    busy();
    for (;;) {
      let answer = null;
      try {
        answer = await read(id);
      } catch (_) {
        answer = null;
      }
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

  function listed(body) {
    state.items = body.items || [];
    state.shown = PAGE;
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

  function askForPc(links) {
    if (links.length === 0) {
      refused("pc-exchange-no-pc");
      return;
    }
    offerChoices(links.map((link) => ({
      label: link.label || copy("pc-exchange-my-pc"), value: link.link_id,
    })), (choice) => {
      state.linkId = choice.value;
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
        state.path = pathOf(item);
        state.folderName = item.name;
        state.selection = null;
        void start(BROWSE, { path: state.path }, listed);
        return;
      }
      state.selection = item;
      if (state.mode === "save" && typeof state.onFileName === "function") {
        // The owner is naming a file, not opening one: the list is only showing
        // what already lives in this folder.
        state.onFileName(item.name);
        state.selection = null;
        return;
      }
      paintList();
    });
    row.append(button);
    return row;
  }

  function paintList() {
    const nodes = state.nodes;
    if (!nodes) return;
    nodes.list.replaceChildren();
    const shown = state.items.slice(0, state.shown);
    shown.forEach((item) => nodes.list.append(rowFor(item)));
    nodes.more.hidden = state.items.length <= shown.length;
    nodes.folderLabel.textContent = state.folderName || copy("pc-exchange-contents");
    if (state.mode === "save") {
      nodes.pick.hidden = false;
      return;
    }
    nodes.pick.hidden = !(state.selection && state.selection.kind === "file");
    nodes.pick.textContent = state.selection
      ? copy("pc-exchange-open-file", { name: state.selection.name })
      : copy("pc-exchange-open-file", { name: "" });
  }

  // One request shape for all four verbs: ask, then watch the server's record.
  async function start(url, payload, onReady) {
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
      askForPc((answer.body.links || []).filter((link) => link && link.link_id));
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
    state.items = [];
    state.shown = PAGE;
    paintList();
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

    const list = element("ul", "pc-exchange-list");
    // The dialog keeps its own title and says which folder is open on its own line,
    // so browsing never replaces the words that named what the owner is doing.
    const folderLabel = element("p", "pc-exchange-folder-label", copy("pc-exchange-contents"));
    const more = element("button", "pc-exchange-more", copy("pc-exchange-more"));
    more.type = "button";
    more.hidden = true;
    const status = element("p", "pc-exchange-status");
    status.hidden = true;

    const footer = element("div", "pc-exchange-footer");
    const cancel = element("button", "pc-exchange-cancel", copy("pc-exchange-close"));
    cancel.type = "button";
    const pick = element("button", "pc-exchange-pick", copy("pc-exchange-open-file", { name: "" }));
    pick.type = "button";
    pick.hidden = true;
    footer.append(cancel, pick);

    dialog.append(heading, note, pcs, tools, folderLabel, list, more, status, footer);
    overlay.append(dialog);

    back.addEventListener("click", () => {
      const parent = parentOf(state.path);
      if (parent === state.path) return;
      state.path = parent;
      const text = parent.replace(/\/+$/, "");
      state.folderName = text ? text.slice(text.lastIndexOf("/") + 1) : "";
      state.selection = null;
      void start(BROWSE, { path: parent }, listed);
    });
    more.addEventListener("click", () => {
      state.shown += PAGE;
      paintList();
    });
    cancel.addEventListener("click", close);
    overlay.addEventListener("click", (event) => { if (event.target === overlay) close(); });
    searchButton.addEventListener("click", () => {
      const name = search.value.trim();
      if (!name) return;
      state.folderName = "";
      void start(FIND, { name }, (body) => {
        state.items = body.found || [];
        paintList();
      });
    });
    search.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        searchButton.click();
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
        };
        close();
        onSelect(picked);
      });
    });
    if (mode === "save") {
      // A file already on the PC is a name worth offering, not a thing to open:
      // choosing it only fills in the name box, and saving over it is what the
      // backup that #5573 takes first is for.
      tools.append(naming);
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
      fileName, folderLabel,
    };
  }

  function close() {
    if (!state.open) return;
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
    state.path = ".";
    state.folderName = "";
    state.items = [];
    state.shown = PAGE;
    state.selection = null;
    state.error = null;
    state.dispatchId = null;
    state.focusBefore = root.document.activeElement;
    state.nodes = build(settings);
    root.document.body.append(state.nodes.overlay);
    state.nodes.dialog.focus();
    void start(BROWSE, { path: "." }, listed);
    return { close: close };
  }

  root.PadiemPcFileExchange = Object.freeze({
    open: open,
    close: close,
    isOpen: function () { return state.open; },
    current: function () {
      return {
        path: state.path, linkId: state.linkId, waiting: state.waiting,
        items: state.items.length, dispatchId: state.dispatchId,
      };
    },
  });
})(typeof window !== "undefined" ? window : globalThis);
