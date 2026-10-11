"use strict";
/* Deterministic DOM + fetch shim for the Project Drive case-folder browser QA.
 * Usage: node -e <this file> <module source> <scenario>
 */
const fs = require("fs");
const moduleSource = process.argv[1];
const scenario = process.argv[2];

let focused = null;
const registry = {};
const allElements = [];

class El {
  constructor(tag) {
    this.tagName = String(tag || "div").toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attrs = {};
    this.listeners = {};
    this._text = "";
    this.hidden = false;
    this.disabled = false;
    this.className = "";
    this.type = "";
    this.open = false;
    allElements.push(this);
  }
  get textContent() {
    if (this.children.length) return this.children.map((c) => c.textContent).join("");
    return this._text;
  }
  set textContent(value) {
    this._text = String(value === undefined || value === null ? "" : value);
    this.children = [];
  }
  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  setAttribute(key, value) {
    this.attrs[key] = String(value);
  }
  getAttribute(key) {
    return this.attrs[key];
  }
  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }
  dispatch(type, extra) {
    (this.listeners[type] || []).forEach((fn) => fn(Object.assign({ type: type, preventDefault() {} }, extra || {})));
  }
  focus() {
    focused = this;
  }
  showModal() {
    this.open = true;
  }
  close() {
    this.open = false;
  }
  querySelectorAll(selector) {
    const attrMatch = selector.match(/\[([^\]=\s]+)(?:="([^"]*)")?\]/);
    const tag = selector.replace(/\[.*$/, "").toUpperCase();
    const out = [];
    const walk = (node) => {
      node.children.forEach((child) => {
        let match = true;
        if (tag && child.tagName !== tag) match = false;
        if (match && attrMatch) {
          const actual = child.attrs[attrMatch[1]];
          if (actual === undefined) match = false;
          else if (attrMatch[2] !== undefined && actual !== attrMatch[2]) match = false;
        }
        if (match) out.push(child);
        walk(child);
      });
    };
    walk(this);
    return out;
  }
}

[
  "projectDrivePanel",
  "projectDriveStatus",
  "projectDriveStatusLive",
  "projectDrivePickButton",
  "projectDriveClearButton",
  "projectDrivePicker",
  "projectDrivePickerClose",
  "projectDriveSearchInput",
  "projectDriveFolderList",
  "projectDrivePickerState",
].forEach((id) => {
  registry[id] = new El(id === "projectDriveFolderList" ? "div" : "button");
});

const documentShim = {
  readyState: "complete",
  activeElement: registry.projectDrivePickButton,
  getElementById: (id) => registry[id] || null,
  createElement: (tag) => new El(tag),
  addEventListener: () => {},
};

const windowShim = {};

let route = null; // (url, init) => response
let calls = [];

function makeResponse(status, body, options) {
  const opts = options || {};
  return {
    status: status,
    ok: status >= 200 && status < 300,
    json: async () => {
      if (opts.delayJson) await opts.delayJson;
      return body;
    },
  };
}

function install() {
  global.document = documentShim;
  global.window = windowShim;
  global.fetch = async (url, init) => {
    calls.push({ url: String(url), init: init || {} });
    return route(String(url), init || {});
  };
  windowShim.padiemProjectDriveFolder = undefined;
}

function boot() {
  // eslint-disable-next-line no-eval
  eval(moduleSource);
  return windowShim.padiemProjectDriveFolder;
}

function deferred() {
  let release;
  const promise = new Promise((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

function statusText() {
  return registry.projectDriveStatus.textContent;
}

function rowData() {
  return registry.projectDriveFolderList.children.map((row) => ({
    name: row.children[0] ? row.children[0].textContent : "",
    space: row.children[1] ? row.children[1].textContent : "",
    button: row.children[2] || null,
  }));
}

function sleep() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function okStatus(configured, spaceKind) {
  return makeResponse(200, {
    configured: configured,
    space_kind: spaceKind || null,
    updated_at: "2026-09-28T00:00:00+00:00",
  });
}

function foldersBody(names) {
  return {
    folders: names.map((entry, index) => ({
      folder_id: "folder_" + (index + 1),
      name: entry[0],
      space_kind: entry[1],
      modified_time: null,
    })),
    more: false,
    exhaustive: false,
  };
}

const scenarioRuns = {
  async status() {
    const api = boot();
    const out = {};
    route = () => okStatus(false);
    await api.loadStatus("proj_a");
    out.unconfigured = statusText();
    route = () => okStatus(true, "my_drive");
    await api.loadStatus("proj_a");
    out.my_drive = statusText();
    route = () => okStatus(true, "shared_drive");
    await api.loadStatus("proj_a");
    out.shared_drive = statusText();
    route = () => makeResponse(409, { error: { code: "drive_not_connected", message: "x" } });
    await api.loadStatus("proj_a");
    out.not_connected = statusText();
    route = () => makeResponse(409, { error: { code: "drive_binding_drift", message: "x" } });
    await api.loadStatus("proj_a");
    out.other_409 = statusText();
    route = () => makeResponse(502, { error: { code: "drive_case_folder_failed", message: "x" } });
    await api.loadStatus("proj_a");
    out.http_502 = statusText();
    return out;
  },

  async loading() {
    const api = boot();
    route = () => new Promise(() => {});
    api.loadStatus("proj_a");
    await sleep();
    return {
      busy: registry.projectDriveStatusLive.getAttribute("aria-busy"),
      text: registry.projectDriveStatusLive.textContent,
    };
  },

  async configured_buttons() {
    const api = boot();
    const out = {};
    route = () => okStatus(false);
    await api.loadStatus("proj_a");
    out.unconfigured_clear_hidden = registry.projectDriveClearButton.hidden;
    out.unconfigured_pick_label = registry.projectDrivePickButton.textContent;
    route = () => okStatus(true, "my_drive");
    await api.loadStatus("proj_a");
    out.configured_clear_hidden = registry.projectDriveClearButton.hidden;
    out.configured_pick_label = registry.projectDrivePickButton.textContent;
    return out;
  },

  async picker() {
    const api = boot();
    const out = {};
    api.state().projectId = "proj_a";
    route = () => makeResponse(200, foldersBody([["사건자료", "my_drive"], ["공유사건", "shared_drive"]]));
    api.openPicker();
    await api.loadFolders("");
    await sleep();
    const rows = rowData();
    out.recent_rows = rows.length;
    out.recent_first_name = rows[0] ? rows[0].name : null;
    out.recent_first_space = rows[0] ? rows[0].space : null;
    out.recent_second_space = rows[1] ? rows[1].space : null;

    route = () => makeResponse(200, foldersBody([]));
    await api.loadFolders("");
    out.recent_empty = registry.projectDrivePickerState.textContent;

    route = () => makeResponse(200, foldersBody([]));
    await api.loadFolders("없는폴더");
    out.search_empty = registry.projectDrivePickerState.textContent;
    out.search_query_in_url = calls.some((call) => call.url.indexOf("query=") !== -1);
    return out;
  },

  async picker_errors() {
    const api = boot();
    const out = {};
    api.state().projectId = "proj_a";
    route = () => makeResponse(409, { error: { code: "drive_not_connected", message: "x" } });
    await api.loadFolders("");
    out.not_connected = registry.projectDrivePickerState.textContent;
    route = () => makeResponse(409, { error: { code: "drive_binding_drift", message: "x" } });
    await api.loadFolders("");
    out.other_409 = registry.projectDrivePickerState.textContent;
    route = () => makeResponse(502, { error: { code: "x", message: "x" } });
    await api.loadFolders("");
    out.http_502 = registry.projectDrivePickerState.textContent;
    return out;
  },

  async mutations() {
    const api = boot();
    const out = {};
    route = (url, init) => {
      if (init.method === "PUT") return makeResponse(200, { configured: true, space_kind: "my_drive", updated_at: "t" });
      if (init.method === "DELETE") return makeResponse(200, { configured: false, cleared: true });
      return okStatus(true, "my_drive");
    };
    api.state().projectId = "proj_a";
    await api.selectFolder("folder_a");
    const put = calls.filter((call) => call.init.method === "PUT").pop();
    out.select_method = put.init.method;
    out.select_body = JSON.parse(put.init.body);
    out.select_status_refreshed = statusText() === "연결됨 · 내 드라이브";

    await api.selectFolder("folder_b");
    out.replace_body = JSON.parse(calls.filter((call) => call.init.method === "PUT").pop().init.body);

    route = (url, init) => (init.method === "DELETE" ? makeResponse(200, { configured: false, cleared: true }) : okStatus(false));
    await api.clearFolder();
    out.clear_method = "DELETE";
    out.after_clear = statusText();
    return out;
  },

  async double_submit() {
    const api = boot();
    let release;
    const gate = new Promise((resolve) => {
      release = resolve;
    });
    route = (url, init) => {
      if (init.method === "PUT") {
        return {
          status: 200,
          ok: true,
          json: async () => {
            await gate;
            return { configured: true, space_kind: "my_drive", updated_at: "t" };
          },
        };
      }
      return okStatus(true, "my_drive");
    };
    api.state().projectId = "proj_a";
    const list = registry.projectDriveFolderList;
    const row = new El("div");
    const name = new El("span");
    name.textContent = "사건자료";
    const space = new El("span");
    space.textContent = "내 드라이브";
    const button = new El("button");
    button.setAttribute("data-folder-select", "folder_1");
    row.appendChild(name);
    row.appendChild(space);
    row.appendChild(button);
    list.appendChild(row);
    api.selectFolder("folder_1");
    await sleep();
    const disabled = button.disabled;
    release();
    await sleep();
    return { disabled_during_put: disabled };
  },

  async stale_project_switch() {
    const api = boot();
    const gate = deferred();
    let first = true;
    route = () => {
      if (first) {
        first = false;
        return makeResponse(200, { configured: true, space_kind: "shared_drive", updated_at: "t" }, { delayJson: gate.promise });
      }
      return okStatus(true, "my_drive");
    };
    const pending = api.loadStatus("proj_a");
    await sleep();
    api.reset();
    route = () => okStatus(true, "my_drive");
    await api.loadStatus("proj_b");
    gate.release();
    await pending;
    await sleep();
    return {
      status_after_switch: statusText(),
      stale_status_applied: statusText() === "연결됨 · 공유 드라이브",
    };
  },

  async stale_dialog_close() {
    const api = boot();
    const gate = deferred();
    route = () => makeResponse(200, { configured: true, space_kind: "shared_drive", updated_at: "t" }, { delayJson: gate.promise });
    const pending = api.loadStatus("proj_a");
    await sleep();
    api.reset();
    gate.release();
    await pending;
    await sleep();
    return {
      status_after_reset: statusText(),
      stale_status_applied: statusText() === "연결됨 · 공유 드라이브",
    };
  },

  async stale_search() {
    const api = boot();
    const gate = deferred();
    let first = true;
    route = () => {
      if (first) {
        first = false;
        return makeResponse(200, foldersBody([["첫번째", "my_drive"]]), { delayJson: gate.promise });
      }
      return makeResponse(200, foldersBody([["두번째", "my_drive"]]));
    };
    api.state().projectId = "proj_a";
    const pending = api.loadFolders("");
    await sleep();
    await api.loadFolders("query-b");
    gate.release();
    await pending;
    await sleep();
    const rows = rowData();
    return {
      final_first_name: rows[0] ? rows[0].name : null,
      stale_search_applied: (rows[0] ? rows[0].name : null) === "첫번째",
    };
  },

  async xss() {
    const api = boot();
    route = () =>
      makeResponse(
        200,
        foldersBody([
          ["<img src=x onerror=alert(1)>", "my_drive"],
          ["<script>alert(1)</script>", "shared_drive"],
        ])
      );
    api.state().projectId = "proj_a";
    await api.loadFolders("");
    const rows = rowData();
    const tags = allElements.map((element) => element.tagName);
    return {
      visible_names: rows.map((row) => row.name),
      img_nodes: tags.filter((tag) => tag === "IMG").length,
      script_nodes: tags.filter((tag) => tag === "SCRIPT").length,
      raw_folder_id_visible: registry.projectDriveFolderList.textContent.indexOf("folder_1") !== -1,
    };
  },

  async keyboard() {
    const api = boot();
    route = () => makeResponse(200, foldersBody([["사건자료", "my_drive"]]));
    documentShim.activeElement = registry.projectDrivePickButton;
    api.openPicker();
    await sleep();
    const opened = focused === registry.projectDriveSearchInput;
    registry.projectDrivePicker.dispatch("keydown", { key: "Escape" });
    return {
      focused_on_open: opened ? "projectDriveSearchInput" : focused ? focused.tagName : null,
      closed_on_escape: registry.projectDrivePicker.hidden === true,
      focus_returned_to_opener: focused === registry.projectDrivePickButton,
    };
  },
};

(async () => {
  install();
  const runner = scenarioRuns[scenario];
  if (!runner) {
    process.stdout.write(JSON.stringify({ error: "unknown scenario" }));
    return;
  }
  const result = await runner();
  process.stdout.write(JSON.stringify(result));
})().catch((error) => {
  process.stderr.write(String((error && error.stack) || error));
  process.exit(1);
});
