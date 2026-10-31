// #5785 — one fake-DOM host for the REAL util-menu.js so the three 의원3종
// tools (speech / SNS / meeting) can be exercised one at a time.
//
// The DOM shim and the recording fetch follow the same contract the #5608 and
// #5728 harnesses already established for this file: the browser module under
// test is the shipped `static/util-menu.js`, the backend is a recording fake of
// the EXISTING endpoints (/api/chat, /api/projects, /api/projects/{id}/files),
// and nothing here invents a product behaviour or a second API.
//
// Usage: node _5785_util_harness.js <util-menu.js path> <scenario>
//   scenario = speech | sns | meeting | shared | tier
// Prints one JSON object of observations; the Python test modules own the
// assertions so a changed contract fails in the readable place.
const fs = require("node:fs");
const vm = require("node:vm");

const utilMenuPath = process.argv[2];
const scenario = String(process.argv[3] || "").toLowerCase();

class N {
  constructor(tag) {
    this.tagName = String(tag || "div").toUpperCase();
    this.children = [];
    this.attrs = {};
    this.dataset = {};
    this.style = {};
    this.value = "";
    this.textContent = "";
    this.hidden = false;
    this.type = "";
    this.name = "";
    this.placeholder = "";
    this.checked = false;
    this.rows = 0;
    this.required = false;
    this.multiple = false;
    this.id = "";
    this.files = [];
    this._listeners = {};
    this._cls = "";
  }
  set className(v) { this._cls = String(v || ""); }
  get className() { return this._cls || ""; }
  get classList() {
    const self = this;
    const has = (c) => (self._cls || "").split(/\s+/).filter(Boolean).includes(c);
    return {
      add: (...c) => { self._cls = [...new Set([...(self._cls || "").split(/\s+/).filter(Boolean), ...c])].join(" "); },
      remove: (...c) => { const drop = new Set(c); self._cls = (self._cls || "").split(/\s+/).filter((x) => x && !drop.has(x)).join(" "); },
      contains: (c) => has(c),
      toggle: (c, forced) => { const want = forced === undefined ? !has(c) : forced; if (want) self.classList.add(c); else self.classList.remove(c); },
    };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "class") this._cls = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
  append(...children) { children.forEach((child) => this.appendChild(child)); }
  removeChild(child) { const i = this.children.indexOf(child); if (i >= 0) this.children.splice(i, 1); }
  insertBefore(child, ref) {
    // A real document raises NotFoundError when the reference node is not a
    // child. Tolerating that here is what let util-menu.js:1507/#1787 pass this
    // harness while the SNS and meeting panels failed in production.
    if (ref != null && this.children.indexOf(ref) < 0) {
      throw new Error("NotFoundError: The node before which the new node is to be inserted is not a child of this node.");
    }
    if (ref == null) return this.appendChild(child);
    const i = this.children.indexOf(ref);
    this.children.splice(i, 0, child);
    child.parentNode = this;
    return child;
  }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  removeEventListener() {}
  async dispatch(type, event) {
    const evt = Object.assign({ preventDefault() {}, target: this }, event || {});
    let node = this;
    while (node) {
      for (const fn of (node._listeners[type] || []).slice()) await fn.call(node, evt);
      node = node.parentNode;
    }
  }
  focus() {}
  scrollIntoView() {}
  click() { return this.dispatch("click"); }
  querySelector(sel) { return this.findAll(sel)[0] || null; }
  querySelectorAll(sel) { return this.findAll(sel); }
  _descendants() {
    const out = [];
    for (const child of this.children) { out.push(child); out.push(...child._descendants()); }
    return out;
  }
  findAll(sel) {
    const parts = String(sel).trim().split(/\s+/);
    let scope = [this, ...this.children];
    parts.forEach((part, index) => {
      const next = [];
      for (const node of scope) {
        if (index === 0 && simpleMatch(node, part)) next.push(node);
        for (const descendant of node._descendants()) {
          if (simpleMatch(descendant, part)) next.push(descendant);
        }
      }
      scope = Array.from(new Set(next));
    });
    return scope;
  }
}

function simpleMatch(node, part) {
  if (!node || !node.tagName) return false;
  let token = String(part);
  // `:checked` is the only pseudo-class the module queries.
  let wantsChecked = false;
  if (token.endsWith(":checked")) {
    wantsChecked = true;
    token = token.slice(0, -":checked".length);
  }
  if (wantsChecked && !node.checked) return false;
  if (token.startsWith("#")) return node.id === token.slice(1);
  if (token.startsWith(".")) return node.classList.contains(token.slice(1));
  const attr = /^\[([\w-]+)(?:="?([^"\]]*)"?)?\]$/.exec(token);
  if (attr) {
    const key = attr[1];
    const want = attr[2];
    const have = key === "name" ? node.name : node.getAttribute(key);
    if (want === undefined) return have !== null && have !== undefined && have !== "";
    return have === want;
  }
  return node.tagName === token.toUpperCase();
}

class FakeFormData {
  constructor(form) {
    this._entries = [];
    const seen = new Set();
    const all = [form, ...form._descendants()];
    for (const node of all) {
      if (!node.name || seen.has(node.name)) continue;
      seen.add(node.name);
      this._entries.push([node.name, node.value]);
    }
  }
  get(name) {
    const found = this._entries.find(([key]) => key === name);
    return found ? found[1] : null;
  }
  entries() { return this._entries[Symbol.iterator](); }
}

// ── recording backend: only the endpoints the util tools already use ────────
const requests = [];
const chatPayloads = [];
let chatResponseOverride = null;
const storedFiles = [];
// #5783 G5: what a download action hands the browser. `downloadText` builds one
// Blob, one object URL and one <a download>, so recording those three pieces
// pins the exported file name, MIME type and exact bytes.
const exportedBlobs = [];
const downloads = [];
// #5895: what the PC carries, as this account last saw it. The authoring screens read
// these two shapes exactly as production does.
let pcLinks = [{ link_id: "pclink_" + "1".repeat(32), label: "사무실 PC", state: "active" }];
const pcReferenceTexts = {};
// #5895: the refusals the Worker answers by code, so the menu can say them out loud.
const pcReferenceErrors = {};
const pcReferenceRequests = [];
const alerts = [];
// A browser logs an unhandled rejection and keeps the page alive; model that so
// one recorded defect does not hide the rest of the feature's contract.
const pageErrors = [];
process.on("unhandledRejection", (reason) => {
  pageErrors.push(String((reason && reason.message) || reason));
});
const PROJECT_ID = "p1";
const ANSWER = "생성된 초안 본문입니다.\n\n두 번째 문단입니다.";

function json(payload, status) {
  return { ok: (status || 200) < 400, status: status || 200, json: async () => payload };
}

// #5783 G5 failure half: a scenario answers the next requests itself. The
// override runs BEFORE the recording fake and returns a response (or throws,
// which is how a request that never reached a server is modelled); returning
// a falsy value hands the request back to the fake.
let fetchOverride = null;

async function fetch(url, opts) {
  const options = opts || {};
  const method = String(options.method || "GET").toUpperCase();
  const rawUrl = String(url);
  const path = rawUrl.split("?")[0];
  let body = null;
  if (typeof options.body === "string") {
    try { body = JSON.parse(options.body); } catch (_) { body = null; }
  }
  requests.push({ method, url: path, credentials: options.credentials || null });

  if (fetchOverride) {
    const answered = fetchOverride(method, path, body);
    if (answered) return answered;
  }

  if (method === "GET" && path === "/api/pc/pairings") {
    return json({ ok: true, links: pcLinks.map((link) => ({ ...link })) });
  }
  if (method === "POST" && path === "/api/pc/reference" && body) {
    pcReferenceRequests.push(body);
    const refusal = pcReferenceErrors[body.file_id];
    if (refusal) {
      const status = refusal === "file_lane_unavailable" ? 503 : 422;
      return json({ ok: false, error: { code: refusal } }, status);
    }
    const entry = pcReferenceTexts[body.file_id];
    if (!entry) return json({ ok: false, error: { code: "pc_reference_unreadable" } }, 422);
    return json({ ok: true, name: entry.name, text: entry.text, chars: entry.text.length });
  }
  if (method === "POST" && path === "/api/chat") {
    chatPayloads.push(body);
    return chatResponseOverride || json({ answer: ANSWER });
  }
  if (method === "GET" && path === "/api/projects") {
    return json({ projects: [{ id: PROJECT_ID, name: "유틸 작업" }] });
  }
  if (method === "GET" && path === `/api/projects/${PROJECT_ID}/files`) {
    // Same projection the real collection route returns for a util row: the
    // list carries the kind and the version link, never the body.
    return json({
      files: storedFiles.map((f) => ({
        id: f.id, name: f.name, media_type: f.media_type, content_chars: f.content_chars,
        doc_kind: f.doc_kind || "", doc_version_of: f.doc_version_of || null, created_at: f.created_at || "",
      })),
    });
  }
  if (method === "POST" && path === `/api/projects/${PROJECT_ID}/files` && body) {
    const kind = String(body.doc_kind || "");
    // #5731 contract the screen must obey: the same name in the same kind is a
    // 409 with the existing row, never a second row.
    if (kind) {
      const same = storedFiles.find((f) => !f.doc_version_of && f.name === body.name && (f.doc_kind || "") === kind);
      if (same) {
        return json({ error: { code: "name_conflict", message: "같은 이름의 글이 이미 있습니다.", existing: { id: same.id, name: same.name } } }, 409);
      }
    }
    const file = {
      id: "f" + (storedFiles.length + 1),
      name: body.name,
      media_type: body.media_type,
      content: String(body.text || ""),
      content_chars: String(body.text || "").length,
      doc_kind: kind,
    };
    storedFiles.push(file);
    return json({ file });
  }
  const detail = new RegExp(`^/api/projects/${PROJECT_ID}/files/([\\w-]+)$`).exec(path);
  if (method === "GET" && detail) {
    const rec = storedFiles.find((f) => f.id === detail[1]);
    if (!rec) return json({}, 404);
    return json({ file: { id: rec.id, name: rec.name, media_type: rec.media_type, content_chars: rec.content_chars, doc_kind: rec.doc_kind || "", content: rec.content } });
  }
  if (method === "PUT" && detail && body) {
    // #5731 overwrite: the row keeps its id and kind, the displaced body stays
    // in the same project as `<name> (이전 N)` linked through doc_version_of.
    const rec = storedFiles.find((f) => f.id === detail[1]);
    if (!rec) return json({}, 404);
    const kind = String(body.doc_kind || rec.doc_kind || "");
    const stem = rec.name.replace(/\.[^.]+$/, "");
    const ext = (rec.name.match(/\.[^.]+$/) || [""])[0];
    let n = 1;
    while (storedFiles.some((f) => f.name === `${stem} (이전 ${n})${ext}`)) n += 1;
    const version = {
      id: "f" + (storedFiles.length + 1),
      name: `${stem} (이전 ${n})${ext}`,
      media_type: rec.media_type,
      content: rec.content,
      content_chars: rec.content.length,
      doc_kind: rec.doc_kind || kind,
      doc_version_of: rec.id,
    };
    storedFiles.push(version);
    rec.content = String(body.text || "");
    rec.content_chars = rec.content.length;
    rec.doc_kind = kind;
    return json({ file: rec, previous: version });
  }
  return json({}, 404);
}

// ── one util-menu.js execution against a fresh fake DOM ─────────────────────
function spawnSession(windowState = {}) {
  const root = new N("html");
  const byId = {};
  const mk = (tag, id, cls) => {
    const node = new N(tag);
    if (id) { node.id = id; byId[id] = node; }
    if (cls) node.className = cls;
    return node;
  };

  const shell = mk("div", null, "app-shell");
  shell.dataset.state = "chat";
  root.appendChild(shell);
  const main = mk("main", "mainPanel", "main-panel");
  shell.appendChild(main);
  const utilView = mk("section", "utilView", "util-view");
  utilView.hidden = true;
  main.appendChild(utilView);
  const navBtn = mk("button", "utilNavButton", "side-item");
  navBtn.setAttribute("aria-current", "false");
  shell.appendChild(navBtn);

  [["speech", "축사·인사말"], ["sns", "SNS 홍보"], ["meeting", "회의정리·책 제작"], ["pdfmd", "PDF → Markdown"]].forEach(([key, label]) => {
    const tab = mk("button", null, "util-tab" + (key === "speech" ? " active" : ""));
    tab.dataset.util = key;
    tab.textContent = label;
    utilView.appendChild(tab);
  });

  // #5908: the quick-run toolbox grid and the sidebar submenu the shipped
  // markup carries around the panels, plus the Claw entries two cards route
  // to. Clicks on the fake Claw controls are recorded so the tools scenario
  // can observe the real module's routing.
  const toolGrid = mk("section", "utilToolGrid", "util-tool-grid");
  toolGrid.setAttribute("aria-label", "빠른 실행 도구함");
  [["speech", "열기"], ["sns", "열기"], ["meeting", "열기"], ["pdfmd", "이력 열기"], ["claw-quote", "Claw에서 작성"], ["claw-excel", "Claw에서 진행"]].forEach(([key, label]) => {
    const card = mk("div", null, "util-tool-card");
    const open = mk("button", null, "util-tool-open");
    open.setAttribute("data-util-tool", key);
    open.textContent = label;
    card.appendChild(open);
    toolGrid.appendChild(card);
  });
  utilView.appendChild(toolGrid);

  const utilSubmenu = mk("div", "utilSubmenu", "util-submenu");
  ["speech", "sns", "meeting", "pdfmd"].forEach((key) => {
    const item = mk("button", null, "util-submenu-item");
    // dataset, not setAttribute: the shim does not sync data-* attributes
    // into dataset, and the shipped module reads item.dataset.util here.
    item.dataset.util = key;
    utilSubmenu.appendChild(item);
  });
  shell.appendChild(utilSubmenu);

  const clawNavClicks = [];
  const clawChipClicks = [];
  const clawNav = mk("button", "clawNavButton", "side-item");
  clawNav.addEventListener("click", () => clawNavClicks.push("claw"));
  shell.appendChild(clawNav);
  const clawChip = mk("button", "clawQuoteCard", "claw-chip");
  clawChip.setAttribute("aria-pressed", "false");
  clawChip.addEventListener("click", () => clawChipClicks.push("quote"));
  shell.appendChild(clawChip);

  // The speech form is shipped markup in index.html, so the harness builds the
  // same field set the browser would hand to `new FormData(form)`.
  const speechPanel = mk("div", "utilSpeechPanel", "util-panel");
  const speechForm = mk("form", "utilSpeechForm", "util-form");
  const speechFields = [
    ["event", "input"], ["date", "input"], ["place", "input"], ["nature", "input"],
    ["audience", "input"], ["author", "input"], ["message", "textarea"],
    ["emphasis", "textarea"], ["length", "input"], ["tone", "input"], ["style", "textarea"],
  ];
  speechFields.forEach(([name, tag]) => {
    const field = mk(tag, null, null);
    field.name = name;
    if (name === "length") field.value = "medium";
    if (name === "tone") field.value = "formal";
    speechForm.appendChild(field);
  });
  const speechActions = mk("div", null, "util-form-actions");
  const speechSubmit = mk("button", null, "util-generate");
  speechSubmit.type = "submit";
  speechSubmit.textContent = "초안 생성";
  const speechSave = mk("button", "utilSpeechSave", "util-save");
  speechSave.type = "button";
  speechSave.textContent = "저장";
  speechActions.append(speechSubmit, speechSave);
  speechForm.appendChild(speechActions);
  // #5895: the shared "from my PC" mount the shipped markup carries in the
  // reference fieldset.
  const speechPcMount = mk("div", "utilSpeechPcRef", "util-pc-ref-mount");
  speechForm.appendChild(speechPcMount);
  speechPanel.appendChild(speechForm);

  const speechResult = mk("div", "utilSpeechResult");
  speechResult.hidden = true;
  const speechOutput = mk("textarea", "utilSpeechOutput");
  speechResult.appendChild(speechOutput);
  const speechCopy = mk("button", "utilSpeechCopy");
  speechCopy.type = "button";
  const speechDownload = mk("button", "utilSpeechDownload");
  speechDownload.type = "button";
  const speechResultActions = mk("div", null, "util-actions");
  const speechPcSave = mk("button", "utilSpeechPcSave", "util-save");
  speechPcSave.type = "button";
  speechResultActions.append(speechCopy, speechDownload, speechPcSave);
  speechResult.appendChild(speechResultActions);
  speechPanel.appendChild(speechResult);
  utilView.appendChild(speechPanel);

  const snsPanel = mk("div", "utilSnsPanel", "util-panel");
  snsPanel.hidden = true;
  utilView.appendChild(snsPanel);
  const meetingPanel = mk("div", "utilMeetingPanel", "util-panel");
  meetingPanel.hidden = true;
  utilView.appendChild(meetingPanel);
  const pdfmdPanel = mk("div", "utilPdfmdPanel", "util-panel");
  pdfmdPanel.hidden = true;
  utilView.appendChild(pdfmdPanel);

  const ctx = {
    document: {
      readyState: "complete",
      body: mk("body", null),
      documentElement: root,
      getElementById: (id) => byId[id] || root._descendants().find((n) => n.id === id) || null,
      querySelector: (sel) => root.querySelector(sel),
      querySelectorAll: (sel) => root.querySelectorAll(sel),
      createElement: (tag) => {
        const node = new N(tag);
        // #5783 G5: the only <a> the util module builds is the download link
        // inside downloadText. Record its filename and the Blob it carries at
        // the moment the link is clicked, then run the normal click.
        if (String(tag).toLowerCase() === "a") {
          const originalClick = node.click.bind(node);
          node.click = async () => {
            downloads.push({
              filename: String(node.download || ""),
              href: String(node.href || ""),
              blob: exportedBlobs[exportedBlobs.length - 1] || null,
            });
            return originalClick();
          };
        }
        return node;
      },
      addEventListener() {},
    },
    window: windowState,
    navigator: { clipboard: { writeText: async () => {} } },
    fetch,
    alert: (message) => alerts.push(String(message)),
    console,
    setTimeout: () => 0,
    Blob: function Blob(parts, options) {
      this.parts = Array.isArray(parts) ? parts.map((part) => String(part)) : [];
      this.type = options && options.type ? String(options.type) : "";
      exportedBlobs.push({ parts: this.parts, type: this.type });
    },
    URL: { createObjectURL: () => "blob:fixture", revokeObjectURL() {} },
    FormData: FakeFormData,
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(utilMenuPath, "utf8"), ctx, { filename: "util-menu.js" });
  return { root, utilView, navBtn, byId, clawNavClicks, clawChipClicks };
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const text = (value) => String((value && value.textContent) || "");

// Panels the module builds itself are created through document.createElement,
// so the id map only knows the shipped skeleton; resolve against the live tree.
function find(session, id) {
  const known = session.byId[id];
  if (known) return known;
  const found = session.root._descendants().find((n) => n.id === id) || null;
  if (!found) throw new Error("element missing: #" + id);
  return found;
}

// The lazy builders mount the save-status line above the action row. That order
// is exactly what broke in production, so the built shape is read back here
// instead of being inferred from a submit that never gets that far.
function formShape(session, panelId, formId, stateId) {
  const panel = session.byId[panelId];
  const form = panel._descendants().find((n) => n.id === formId) || null;
  if (!form) {
    return { built: false, placeholderLeft: panel.children.length, loaded: panel.dataset.loaded || null };
  }
  const stateAt = form.children.findIndex((n) => n.id === stateId);
  const actionsAt = form.children.findIndex((n) => n.classList.contains("util-form-actions"));
  return {
    built: true,
    loaded: panel.dataset.loaded || null,
    statusLineIndex: stateAt,
    actionsIndex: actionsAt,
    statusAboveActions: stateAt >= 0 && actionsAt >= 0 && stateAt < actionsAt,
  };
}
const labels = (nodes) => nodes.map((n) => text(n).trim());

async function openTool(session, key) {
  await session.navBtn.dispatch("click");
  const tab = session.utilView.querySelectorAll(".util-tab").find((t) => t.dataset.util === key);
  if (!tab) throw new Error("util tab missing: " + key);
  await tab.dispatch("click");
  await sleep(20);
}

function storedByName(name) {
  return storedFiles.filter((f) => f.name === name);
}

function endpointSet() {
  return Array.from(new Set(requests.map((r) => r.method + " " + r.url))).sort();
}

// ── scenarios ──────────────────────────────────────────────────────────────
const REFERENCE_TEXT = "작년 신년사: 새해에도 여러분의 가정에 평안이 가득하기를 바랍니다.";
const REFERENCE_NAME = "작년 신년사.txt";
const PICKED_FILE_ID = "dsp_" + "a".repeat(32);

// The shared part is loaded on first use, so the harness provides what the browser
// would have after that load: the real module's public surface, recording every call.
function pcExchangeStub(pickedFileId = PICKED_FILE_ID, pickedContent = REFERENCE_TEXT) {
  const opened = [];
  return {
    opened,
    api: {
      open(options) {
        opened.push(options || {});
        if (options && typeof options.onSelect === "function") {
          options.onSelect({
            name: REFERENCE_NAME, kind: "text",
            content: pickedContent, fileId: pickedFileId, sizeBytes: REFERENCE_TEXT.length,
          });
        }
        if (options && typeof options.onSave === "function") options.onSave({ ok: true });
        return { close() {} };
      },
      close() {},
      isOpen() { return false; },
      stop() {},
    },
  };
}

const SCENARIOS = {
  async pcref() {
    const exchange = pcExchangeStub();
    const session = spawnSession({ PadiemPcFileExchange: exchange.api });
    await openTool(session, "speech");
    const mount = find(session, "utilSpeechPcRef");
    const pick = mount.querySelectorAll(".util-pc-ref-pick")[0];
    if (!pick) throw new Error("pick button missing");
    if (pick.hidden) throw new Error("pick button hidden while a PC is linked");
    await pick.dispatch("click");
    await sleep(20);
    const preview = text(mount.querySelectorAll(".util-pc-ref-preview")[0]);
    const form = find(session, "utilSpeechForm");
    const eventField = form.querySelectorAll("input").find((n) => n.name === "event");
    if (eventField) eventField.value = "창립기념식";
    form.dispatch("submit");
    await sleep(30);
    const prompt = chatPayloads.length ? String(chatPayloads[chatPayloads.length - 1].messages[0].content) : "";
    find(session, "utilSpeechOutput").value = ANSWER;
    await find(session, "utilSpeechPcSave").dispatch("click");
    await sleep(20);
    const saved = exchange.opened.filter((o) => o.mode === "save");
    return {
      pickCalls: exchange.opened.filter((o) => !o.mode).length,
      preview,
      promptHasReference: prompt.includes(REFERENCE_TEXT),
      promptNamesFile: prompt.includes(REFERENCE_NAME),
      saveCalled: saved.length === 1,
      saveContent: saved[0] ? String(saved[0].content || "") : "",
      saveFileName: saved[0] ? String(saved[0].fileName || "") : "",
      alerts: alerts.slice(),
    };
  },

  async pcref_nopc() {
    pcLinks = [];
    const exchange = pcExchangeStub();
    const session = spawnSession({ PadiemPcFileExchange: exchange.api });
    await openTool(session, "speech");
    const mount = find(session, "utilSpeechPcRef");
    const pick = mount.querySelectorAll(".util-pc-ref-pick")[0];
    const note = mount.querySelectorAll(".util-pc-ref-note")[0];
    const connect = mount.querySelectorAll(".util-pc-ref-connect")[0];
    return {
      pickHidden: Boolean(pick && pick.hidden),
      noteText: text(note).trim(),
      noteHidden: note ? Boolean(note.hidden) : true,
      connectLabel: connect ? text(connect).trim() : "",
      pickerOpened: exchange.opened.length,
    };
  },

  // #5895: the Worker's refusal codes are said out loud in Korean — a sealed or
  // distributed 한글 file, or a lane that is not running, is not a broken picker.
  async pcref_refusals() {
    const cases = [
      ["hwpEncrypted", "hwp_encrypted", "b"],
      ["hwpDistributable", "hwp_distributable", "c"],
      ["laneDown", "file_lane_unavailable", "d"],
    ];
    const refusals = {};
    for (const [key, code, tag] of cases) {
      const fileId = "dsp_" + tag.repeat(32);
      pcReferenceErrors[fileId] = code;
      // No inline content and a file id: exactly what a picked 한글 document is,
      // so the preview has to come from the reference route.
      const exchange = pcExchangeStub(fileId, "");
      const session = spawnSession({ PadiemPcFileExchange: exchange.api });
      await openTool(session, "speech");
      const mount = find(session, "utilSpeechPcRef");
      const pick = mount.querySelectorAll(".util-pc-ref-pick")[0];
      if (!pick) throw new Error("pick button missing");
      if (pick.hidden) throw new Error("pick button hidden while a PC is linked");
      await pick.dispatch("click");
      await sleep(20);
      refusals[key] = text(mount.querySelectorAll(".util-pc-ref-status")[0]).trim();
    }
    return { refusals, pageErrors };
  },

  async tier() {
    const windowState = {};
    const session = spawnSession(windowState);
    await openTool(session, "speech");
    const form = find(session, "utilSpeechForm");
    form.querySelector("[name=event]").value = "등급 전달 검증";
    const tiers = [];
    const cases = [
      ...["free", "plus", "pro", "max", "admin"].map((value) => [value, value]),
      ["absent", undefined], ["missing_getter", undefined],
      ["unknown", "other"], ["uppercase", "MAX"], ["null", null],
      ["number", 3], ["undefined", undefined],
    ];
    for (const [name, value] of cases) {
      if (name === "absent") delete windowState.PadiemTierSelection;
      else if (name === "missing_getter") windowState.PadiemTierSelection = {};
      else windowState.PadiemTierSelection = { get: () => value };
      const before = chatPayloads.length;
      await form.dispatch("submit");
      await sleep(20);
      tiers.push({ name, payload: chatPayloads[before], calls: chatPayloads.length - before,
        output: find(session, "utilSpeechOutput").value });
    }
    const errors = [];
    windowState.PadiemTierSelection = { get: () => "admin" };
    for (const [name, response] of [
      ["server_message", json({ error: { message: "관리자 인증을 확인해 주세요." } }, 403)],
      ["no_message", json({ error: { code: "unavailable" } }, 502)],
      ["non_string", json({ error: { message: { unsafe: true } } }, 403)],
      ["not_json", { ok: false, status: 503, json: async () => { throw new Error("not JSON"); } }],
    ]) {
      chatResponseOverride = response;
      const before = chatPayloads.length;
      await form.dispatch("submit");
      await sleep(20);
      errors.push({ name, output: find(session, "utilSpeechOutput").value,
        calls: chatPayloads.length - before });
    }
    chatResponseOverride = null;
    return { tiers, errors, pageErrors };
  },
  async speech() {
    const session = spawnSession();
    await openTool(session, "speech");
    const form = find(session, "utilSpeechForm");
    const field = (name) => form.querySelector(`[name=${name}]`);
    field("event").value = "제78주년 광복절 기념식";
    field("date").value = "2026-08-15";
    field("place").value = "시청 대강당";
    field("nature").value = "기념식";
    field("audience").value = "지역 주민과 보훈 가족";
    field("author").value = "국회의원 임미란";
    field("message").value = "감사의 마음과 다음 세대의 책임";
    field("emphasis").value = "독립운동가 후손";
    field("length").value = "long";
    field("tone").value = "warm";
    field("style").value = "존경하는 지역민 여러분, 오늘 이 자리는…";

    await form.dispatch("submit");
    await sleep(20);
    const prompt = chatPayloads.length ? chatPayloads[chatPayloads.length - 1].messages[0].content : "";
    const generated = find(session, "utilSpeechOutput").value;

    // The user edits the generated draft, then saves it.
    const edited = generated + "\n\n[편집: 마무리 인사 추가]";
    find(session, "utilSpeechOutput").value = edited;
    await find(session, "utilSpeechSave").dispatch("click");
    await sleep(30);

    const speechFiles = storedFiles.filter((f) => (f.name || "").endsWith(".txt"));
    const savedFile = speechFiles[speechFiles.length - 1] || null;
    const savedListButtons = session.root.querySelectorAll("#utilSpeechSaved button");
    let reopened = null;
    if (savedListButtons.length) {
      await savedListButtons[0].dispatch("click");
      await sleep(20);
      reopened = find(session, "utilSpeechOutput").value;
    }

    // #5731: a stored speech can be picked as the style reference. The saved
    // list exposes one 참고로 선택 action per row; picking one fills the style
    // sample textarea with the stored body, and the next generation's prompt
    // carries it inside the sample fence.
    const refButton = session.root.querySelectorAll("#utilSpeechSaved .util-speech-use-ref")[0] || null;
    let refSelected = null;
    let refPrompt = null;
    if (refButton) {
      const styleField = form.querySelector("[name=style]");
      styleField.value = "";
      await refButton.dispatch("click");
      await sleep(20);
      refSelected = styleField.value;
      await form.dispatch("submit");
      await sleep(20);
      refPrompt = chatPayloads.length ? chatPayloads[chatPayloads.length - 1].messages[0].content : "";
    }

    // #5731: re-entering the tool later must still list the stored speeches —
    // a fresh session opening speech sees the same saved list without saving
    // anything first.
    const reentry = spawnSession();
    await openTool(reentry, "speech");
    await sleep(30);
    const reentryListButtons = reentry.root.querySelectorAll("#utilSpeechSaved button");

    return {
      prompt,
      generated,
      edited,
      savedName: savedFile ? savedFile.name : null,
      savedBody: savedFile ? savedFile.content : null,
      savedListLabels: labels(savedListButtons),
      reopened,
      refSelected,
      refSelectedMatchesSaved: refSelected === (savedFile ? savedFile.content : null),
      refPromptCarriesSample: refPrompt ? refPrompt.indexOf("아래는 사용자의 기존 축사/인사말 샘플입니다") >= 0 && refPrompt.indexOf(refSelected || "") >= 0 : null,
      reentryListCount: reentryListButtons.length,
      reentryListLabels: labels(reentryListButtons),
      chatPayload: chatPayloads[0] || null,
      endpoints: endpointSet(),
      alerts,
      pageErrors,
    };
  },

  async sns() {
    const session = spawnSession();
    await openTool(session, "sns");
    const form = find(session, "utilSnsForm");
    const field = (name) => form.querySelector(`[name=${name}]`);
    field("event").value = "마을 한마음 축제";
    field("whenwhere").value = "10월 3일 · 항구 광장";
    field("content").value = "주민 노래자랑과 먹거리 장터가 열렸습니다.";
    field("memo").value = "사진은 마을 신문에도 씁니다.";
    field("audience").value = "지역 주민";
    field("tone").value = "casual";

    await form.dispatch("submit");
    await sleep(20);
    const blogPrompt = chatPayloads[chatPayloads.length - 1].messages[0].content;
    const blogOutput = find(session, "utilSnsOutput").value;
    const blogTitle = text(session.root.querySelector("#utilSnsResult h3"));

    // Edit, save the blog draft, then switch platform: the draft must survive.
    const edited = blogOutput + "\n\n#마을축제 #임미란";
    find(session, "utilSnsOutput").value = edited;
    await find(session, "utilSnsSave").dispatch("click");
    await sleep(30);
    const savedFile = storedFiles.filter((f) => (f.name || "").endsWith(".txt")).pop() || null;

    const fbTab = form.querySelectorAll(".util-sns-tab").find((t) => t.dataset.platform === "facebook");
    await fbTab.dispatch("click");
    const afterSwitch = {
      event: field("event").value,
      output: find(session, "utilSnsOutput").value,
      title: text(session.root.querySelector("#utilSnsResult h3")),
    };
    await form.dispatch("submit");
    await sleep(20);
    const fbPrompt = chatPayloads[chatPayloads.length - 1].messages[0].content;

    const igTab = form.querySelectorAll(".util-sns-tab").find((t) => t.dataset.platform === "instagram");
    await igTab.dispatch("click");
    await form.dispatch("submit");
    await sleep(20);
    const igPrompt = chatPayloads[chatPayloads.length - 1].messages[0].content;

    return {
      formBuild: formShape(session, "utilSnsPanel", "utilSnsForm", "utilSnsSaveState"),
      blogPrompt,
      fbPrompt,
      igPrompt,
      blogTitle,
      blogOutput,
      edited,
      afterSwitch,
      savedName: savedFile ? savedFile.name : null,
      savedBody: savedFile ? savedFile.content : null,
      platformTitles: [blogTitle, afterSwitch.title],
      endpoints: endpointSet(),
      alerts,
      pageErrors,
    };
  },

  // #6199: a stored speech/SNS piece reopens in the SAME editor, is edited, and
  // saves through the existing 409 (새 이름 / 덮어쓰기) path with its kind kept.
  // Opening a piece that is gone says so instead of a generic failure.
  async edit() {
    storedFiles.push(
      { id: "f71", name: "작년 신년사.txt", media_type: "text/plain", doc_kind: "speech",
        content: "작년 신년사 본문입니다.", content_chars: "작년 신년사 본문입니다.".length },
      { id: "f72", name: "봄 행사 기록.txt", media_type: "text/plain", doc_kind: "meeting",
        content: "봄 행사 기록 본문입니다.", content_chars: "봄 행사 기록 본문입니다.".length },
      { id: "f73", name: "개교 소식.txt", media_type: "text/plain", doc_kind: "sns",
        content: "개교 소식 본문입니다.", content_chars: "개교 소식 본문입니다.".length },
      { id: "f80", name: "사라진 글.txt", media_type: "text/plain", doc_kind: "speech",
        content: "곧 사라질 본문입니다.", content_chars: "곧 사라질 본문입니다.".length },
    );
    const session = spawnSession();
    await openTool(session, "speech");
    await sleep(30);

    const speechRows = () => find(session, "utilSpeechSaved").querySelectorAll(".util-edit-stored");
    const rowFor = (nodes, name) => nodes.find((b) => text(b).includes(name)) || null;
    const speechRowNames = (nodes) => labels(nodes);

    const initialRows = speechRowNames(speechRows());

    // 1) 고쳐 쓰기 loads the stored body into the editable draft, no new editor.
    find(session, "utilSpeechOutput").value = "";
    await rowFor(speechRows(), "작년 신년사.txt").dispatch("click");
    await sleep(30);
    const loadedBody = find(session, "utilSpeechOutput").value;
    const editStateNode = find(session, "utilSpeechEditState");
    const editStateVisible = !editStateNode.hidden;
    const editStateText = text(editStateNode);
    const editorCount = session.root._descendants().filter((n) => n.id === "utilSpeechOutput").length;

    // 2) Edit + save under the same name: the screen asks, 새 이름 keeps the kind.
    find(session, "utilSpeechOutput").value = "작년 신년사 본문입니다. 고친 문장입니다.";
    // The save click stays pending on the same-name question, so it is fired
    // and then the question is answered — awaiting it here would deadlock.
    void find(session, "utilSpeechSave").dispatch("click");
    await sleep(40);
    const ask = session.root.querySelector(".util-save-choice");
    const askText = ask ? text(ask.querySelector(".util-save-choice-text")) : "";
    const askLabels = ask ? labels(ask.querySelectorAll("button")) : [];
    const rowsBeforeChoice = storedFiles.filter((f) => f.doc_kind === "speech" && !f.doc_version_of).length;
    if (ask) {
      await ask.querySelector(".util-save-as-new").dispatch("click");
      await sleep(40);
    }
    const speechRowsAfterNewName = storedFiles
      .filter((f) => f.doc_kind === "speech" && !f.doc_version_of)
      .map((f) => ({ name: f.name, id: f.id }));
    const listAfterNewName = speechRowNames(speechRows());

    // 3) Reopen the original and overwrite: same row, previous body kept.
    await rowFor(speechRows(), "작년 신년사.txt").dispatch("click");
    await sleep(30);
    find(session, "utilSpeechOutput").value = "작년 신년사 본문입니다. 덮어쓴 문장입니다.";
    void find(session, "utilSpeechSave").dispatch("click");
    await sleep(40);
    const overwriteAsk = session.root.querySelector(".util-save-overwrite");
    if (!overwriteAsk) throw new Error("overwrite choice missing on the second same-name save");
    await overwriteAsk.dispatch("click");
    await sleep(40);
    const original = storedFiles.find((f) => f.id === "f71") || null;
    const versions = storedFiles.filter((f) => f.doc_version_of === "f71");
    const listAfterOverwrite = speechRowNames(speechRows());

    // 4) A piece that is gone answers its real status, out loud.
    const goneIndex = storedFiles.findIndex((f) => f.id === "f80");
    if (goneIndex >= 0) storedFiles.splice(goneIndex, 1);
    const alertsBeforeGone = alerts.length;
    await rowFor(speechRows(), "사라진 글.txt").dispatch("click");
    await sleep(30);
    const goneAlert = alerts.length > alertsBeforeGone ? String(alerts[alerts.length - 1]) : "";

    // 5) The same flow for SNS, and the kinds stay apart.
    await openTool(session, "sns");
    await sleep(40);
    const snsRows = () => find(session, "utilSnsSaved").querySelectorAll(".util-edit-stored");
    const snsLabels = labels(snsRows());
    await rowFor(snsRows(), "개교 소식.txt").dispatch("click");
    await sleep(30);
    const snsLoadedBody = find(session, "utilSnsOutput").value;
    const snsStateNode = find(session, "utilSnsEditState");
    const snsStateText = text(snsStateNode);
    find(session, "utilSnsOutput").value = "개교 소식 본문입니다. 고친 SNS 문장입니다.";
    void find(session, "utilSnsSave").dispatch("click");
    await sleep(40);
    const snsAsk = session.root.querySelector(".util-save-choice");
    if (snsAsk) {
      await snsAsk.querySelector(".util-save-as-new").dispatch("click");
      await sleep(40);
    }
    const snsStored = storedFiles.filter((f) => f.doc_kind === "sns" && !f.doc_version_of).map((f) => f.name);
    const speechStored = storedFiles.filter((f) => f.doc_kind === "speech" && !f.doc_version_of).map((f) => f.name);

    return {
      initialRows,
      loadedBody,
      editStateVisible,
      editStateText,
      editorCount,
      askText,
      askLabels,
      rowsBeforeChoice,
      speechRowsAfterNewName,
      listAfterNewName,
      overwrittenBody: original ? original.content : null,
      overwrittenKind: original ? original.doc_kind : null,
      versionRows: versions.map((v) => ({ name: v.name, doc_version_of: v.doc_version_of, doc_kind: v.doc_kind, content: v.content })),
      listAfterOverwrite,
      goneAlert,
      snsLabels,
      snsLoadedBody,
      snsStateText,
      snsStored,
      speechStored,
      endpoints: endpointSet(),
      alerts: alerts.slice(),
      pageErrors,
    };
  },

  // #5783 G5: the SAME chain in all three tools (write → save → reopen →
  // rewrite → export), against the one shipped module and the existing
  // endpoints. Each tool keeps its own kind, its own stored name, its own
  // 409 answer, and the export hands the browser a real file name/type/body.
  async g5() {
    const session = spawnSession();
    const observation = {};

    // ── 축사 ────────────────────────────────────────────────────────────
    await openTool(session, "speech");
    const speechForm = find(session, "utilSpeechForm");
    speechForm.querySelector("[name=event]").value = "가을 문화제 축사";
    speechForm.querySelector("[name=message]").value = "주민 화합과 감사";
    await speechForm.dispatch("submit");
    await sleep(20);
    const speechGenerated = find(session, "utilSpeechOutput").value;

    const speechFirstEdit = speechGenerated + "\n[편집: 저장 전]";
    find(session, "utilSpeechOutput").value = speechFirstEdit;
    await find(session, "utilSpeechSave").dispatch("click");
    await sleep(40);
    const speechStored = storedFiles.filter((f) => f.doc_kind === "speech" && !f.doc_version_of).pop();

    find(session, "utilSpeechOutput").value = "";
    const speechRow = find(session, "utilSpeechSaved")
      .querySelectorAll(".util-edit-stored")
      .find((button) => text(button).includes(speechStored.name));
    if (!speechRow) throw new Error("speech reopen row missing");
    await speechRow.dispatch("click");
    await sleep(30);
    const speechReopened = find(session, "utilSpeechOutput").value;
    const speechEditState = text(find(session, "utilSpeechEditState"));

    const speechSecondEdit = speechReopened + "\n[편집: 고쳐 쓰기]";
    find(session, "utilSpeechOutput").value = speechSecondEdit;
    void find(session, "utilSpeechSave").dispatch("click");
    await sleep(40);
    const speechAsk = session.root.querySelector(".util-save-choice");
    const speechAskText = speechAsk ? text(speechAsk.querySelector(".util-save-choice-text")) : "";
    const speechAskLabels = speechAsk ? labels(speechAsk.querySelectorAll("button")) : [];
    if (speechAsk) {
      await speechAsk.querySelector(".util-save-overwrite").dispatch("click");
      await sleep(40);
    }
    const speechAfterOverwrite = storedFiles.find((f) => f.id === speechStored.id) || null;
    const speechVersions = storedFiles.filter((f) => f.doc_version_of === speechStored.id);

    const speechBeforeDownload = downloads.length;
    await find(session, "utilSpeechDownload").dispatch("click");
    await sleep(10);
    const speechDownload = downloads[speechBeforeDownload] || null;

    observation.speech = {
      generated: speechGenerated,
      firstSavedName: speechStored.name,
      firstSavedKind: speechStored.doc_kind,
      reopened: speechReopened,
      editState: speechEditState,
      askText: speechAskText,
      askLabels: speechAskLabels,
      overwrittenBody: speechAfterOverwrite ? speechAfterOverwrite.content : null,
      overwrittenKind: speechAfterOverwrite ? speechAfterOverwrite.doc_kind : null,
      versions: speechVersions.map((v) => ({
        name: v.name, doc_kind: v.doc_kind, doc_version_of: v.doc_version_of, content: v.content,
      })),
      export: speechDownload ? {
        filename: speechDownload.filename,
        type: speechDownload.blob ? speechDownload.blob.type : null,
        content: speechDownload.blob ? speechDownload.blob.parts.join("") : null,
      } : null,
    };

    // ── SNS ─────────────────────────────────────────────────────────────
    await openTool(session, "sns");
    const snsForm = find(session, "utilSnsForm");
    const snsField = (name) => snsForm.querySelector(`[name=${name}]`);
    snsField("event").value = "가을 마을 축제";
    snsField("whenwhere").value = "10월 18일 · 시민공원";
    snsField("content").value = "가족 놀이마당과 먹거리 장터가 열립니다.";
    await snsForm.dispatch("submit");
    await sleep(20);
    const snsGenerated = find(session, "utilSnsOutput").value;
    const snsTitle = text(session.root.querySelector("#utilSnsResult h3"));

    const snsFirstEdit = snsGenerated + "\n#가을축제";
    find(session, "utilSnsOutput").value = snsFirstEdit;
    await find(session, "utilSnsSave").dispatch("click");
    await sleep(40);
    const snsStored = storedFiles.filter((f) => f.doc_kind === "sns" && !f.doc_version_of).pop();

    find(session, "utilSnsOutput").value = "";
    const snsRow = find(session, "utilSnsSaved")
      .querySelectorAll(".util-edit-stored")
      .find((button) => text(button).includes(snsStored.name));
    if (!snsRow) throw new Error("sns reopen row missing");
    await snsRow.dispatch("click");
    await sleep(30);
    const snsReopened = find(session, "utilSnsOutput").value;
    const snsEditState = text(find(session, "utilSnsEditState"));

    const snsSecondEdit = snsReopened + "\n#고쳐쓰기";
    find(session, "utilSnsOutput").value = snsSecondEdit;
    void find(session, "utilSnsSave").dispatch("click");
    await sleep(40);
    const snsAsk = session.root.querySelector(".util-save-choice");
    const snsAskText = snsAsk ? text(snsAsk.querySelector(".util-save-choice-text")) : "";
    const snsAskLabels = snsAsk ? labels(snsAsk.querySelectorAll("button")) : [];
    if (snsAsk) {
      // The safe default: save as a NEW name, original untouched.
      await snsAsk.querySelector(".util-save-as-new").dispatch("click");
      await sleep(40);
    }

    const snsBeforeDownload = downloads.length;
    await find(session, "utilSnsDownload").dispatch("click");
    await sleep(10);
    const snsDownload = downloads[snsBeforeDownload] || null;

    observation.sns = {
      generated: snsGenerated,
      title: snsTitle,
      firstSavedName: snsStored.name,
      firstSavedKind: snsStored.doc_kind,
      reopened: snsReopened,
      editState: snsEditState,
      askText: snsAskText,
      askLabels: snsAskLabels,
      storedNames: storedFiles.filter((f) => f.doc_kind === "sns" && !f.doc_version_of).map((f) => f.name),
      originalBody: (storedFiles.find((f) => f.id === snsStored.id) || {}).content || null,
      export: snsDownload ? {
        filename: snsDownload.filename,
        type: snsDownload.blob ? snsDownload.blob.type : null,
        content: snsDownload.blob ? snsDownload.blob.parts.join("") : null,
      } : null,
    };

    // ── 회의정리 ────────────────────────────────────────────────────────
    await openTool(session, "meeting");
    const meetingForm = find(session, "utilMeetingForm");
    const meetingField = (name) => meetingForm.querySelector(`[name=${name}]`);
    meetingField("title").value = "가을 주민 간담회";
    meetingField("when").value = "2026-10-20T14:00";
    meetingField("attendees").value = "비서실장, 주민 대표";
    meetingField("content").value = "공원 조명 보수와 버스 증회를 논의했습니다.";
    await meetingForm.dispatch("submit");
    await sleep(20);
    const meetingGenerated = find(session, "utilMeetingOutput").value;

    const meetingFirstEdit = meetingGenerated + "\n[편집: 저장 전]";
    find(session, "utilMeetingOutput").value = meetingFirstEdit;
    await find(session, "utilMeetingSave").dispatch("click");
    await sleep(40);
    const meetingStored = storedFiles.filter((f) => f.doc_kind === "meeting" && !f.doc_version_of).pop();

    find(session, "utilMeetingOutput").value = "";
    const meetingReopenRow = find(session, "utilMeetingArchive")
      .querySelectorAll("button")
      .find((button) => text(button).includes(meetingStored.name));
    if (!meetingReopenRow) throw new Error("meeting reopen row missing");
    const meetingRowLabel = text(meetingReopenRow).trim();
    await meetingReopenRow.dispatch("click");
    await sleep(30);
    const meetingReopened = find(session, "utilMeetingOutput").value;
    const meetingEditState = text(find(session, "utilMeetingEditState"));

    const meetingSecondEdit = meetingReopened + "\n[편집: 고쳐 쓰기]";
    find(session, "utilMeetingOutput").value = meetingSecondEdit;
    void find(session, "utilMeetingSave").dispatch("click");
    await sleep(40);
    const meetingAsk = session.root.querySelector(".util-save-choice");
    const meetingAskText = meetingAsk ? text(meetingAsk.querySelector(".util-save-choice-text")) : "";
    const meetingAskLabels = meetingAsk ? labels(meetingAsk.querySelectorAll("button")) : [];
    if (meetingAsk) {
      await meetingAsk.querySelector(".util-save-overwrite").dispatch("click");
      await sleep(40);
    }
    const meetingAfterOverwrite = storedFiles.find((f) => f.id === meetingStored.id) || null;
    const meetingVersions = storedFiles.filter((f) => f.doc_version_of === meetingStored.id);

    const meetingBeforeDownload = downloads.length;
    await find(session, "utilMeetingDownload").dispatch("click");
    await sleep(10);
    const meetingDownload = downloads[meetingBeforeDownload] || null;

    observation.meeting = {
      generated: meetingGenerated,
      firstSavedName: meetingStored.name,
      firstSavedKind: meetingStored.doc_kind,
      reopened: meetingReopened,
      rowLabel: meetingRowLabel,
      editState: meetingEditState,
      askText: meetingAskText,
      askLabels: meetingAskLabels,
      overwrittenBody: meetingAfterOverwrite ? meetingAfterOverwrite.content : null,
      overwrittenKind: meetingAfterOverwrite ? meetingAfterOverwrite.doc_kind : null,
      versions: meetingVersions.map((v) => ({
        name: v.name, doc_kind: v.doc_kind, doc_version_of: v.doc_version_of, content: v.content,
      })),
      export: meetingDownload ? {
        filename: meetingDownload.filename,
        type: meetingDownload.blob ? meetingDownload.blob.type : null,
        content: meetingDownload.blob ? meetingDownload.blob.parts.join("") : null,
      } : null,
    };

    observation.endpoints = endpointSet();
    // #6234: the chat request key is {messages, tier, util} — the three tabs
    // are told apart by util, and the mode request key no longer exists.
    observation.chatUtils = chatPayloads.map((payload) => payload.util);
    observation.storedKinds = storedFiles.filter((f) => !f.doc_version_of).map((f) => ({ name: f.name, doc_kind: f.doc_kind }));
    observation.versionCount = storedFiles.filter((f) => f.doc_version_of).length;
    observation.alerts = alerts.slice();
    observation.pageErrors = pageErrors;
    return observation;
  },

  // #5783 failure half: a save that stored nothing says so inside the tab.
  // Each case injects one status on the project-file write and reads the tab's
  // own status line; the retry case then presses 다시 시도 with the failure
  // gone and expects the very same save to complete. No case may alert.
  async g5fail() {
    const session = spawnSession();
    const observation = { cases: {}, alertsAfterCases: null };

    async function speechSaveFailureCase(override) {
      fetchOverride = override;
      find(session, "utilSpeechOutput").value = "저장 실패 본문";
      await find(session, "utilSpeechSave").dispatch("click");
      await sleep(30);
      const line = find(session, "utilSpeechSaveState");
      const result = {
        text: text(line),
        hidden: Boolean(line.hidden),
        hasRetry: Boolean(line.querySelector(".util-retry")),
        ariaLive: line.getAttribute("aria-live"),
        storedCount: storedFiles.length,
      };
      fetchOverride = null;
      return result;
    }

    // ── 축사: every status the save path can answer, on the tab's own line ──
    // Each failing case keeps the form's event name, so every POST collides
    // with nothing — nothing is stored while the override answers.
    await openTool(session, "speech");
    const speechForm = find(session, "utilSpeechForm");
    speechForm.querySelector("[name=event]").value = "상태별 안내 확인";
    speechForm.querySelector("[name=message]").value = "본문";
    await speechForm.dispatch("submit");
    await sleep(20);

    observation.cases.speech403 = await speechSaveFailureCase(
      (method, path) => (
        method === "POST" && path === "/api/projects/p1/files" ? json({ error: { code: "forbidden" } }, 403) : null
      ),
    );
    observation.cases.speech404 = await speechSaveFailureCase(
      (method, path) => (
        method === "POST" && path === "/api/projects/p1/files" ? json({ error: { code: "not_found" } }, 404) : null
      ),
    );
    observation.cases.speech413 = await speechSaveFailureCase(
      (method, path) => (
        method === "POST" && path === "/api/projects/p1/files" ? json({ error: { code: "invalid_document" } }, 413) : null
      ),
    );
    observation.cases.speech422limit = await speechSaveFailureCase(
      (method, path) => (
        method === "POST" && path === "/api/projects/p1/files" ? json({ error: { code: "project_file_limit", message: "본문이 너무 길어요" } }, 422) : null
      ),
    );
    // 연결 실패: the request never reaches an answer — the override throws.
    observation.cases.speechOffline = await speechSaveFailureCase(
      (method, path) => {
        if (method === "POST" && path === "/api/projects/p1/files") throw new Error("network down");
        return null;
      },
    );

    // 5xx: the line rides the 다시 시도 button, and pressing it re-runs the
    // SAME save — the stored row proves the retry really saved.
    // The retry re-runs the SAME save — a fresh event name, so the row it
    // stores is this save's own and no earlier failure's.
    speechForm.querySelector("[name=event]").value = "재시도 축사";
    const retryName = "재시도 축사.txt";
    fetchOverride = (method, path) => (
      method === "POST" && path === "/api/projects/p1/files" ? json({ error: { code: "unavailable" } }, 500) : null
    );
    find(session, "utilSpeechOutput").value = "재시도 되는 본문";
    await find(session, "utilSpeechSave").dispatch("click");
    await sleep(30);
    const retryLine = find(session, "utilSpeechSaveState");
    const retryButton = retryLine.querySelector(".util-retry");
    observation.cases.speech500 = {
      text: text(retryLine),
      hasRetry: Boolean(retryButton),
      buttonLabel: retryButton ? text(retryButton).trim() : null,
    };
    if (!retryButton) throw new Error("retry button missing on a 5xx save failure");
    fetchOverride = null;
    await retryButton.dispatch("click");
    await sleep(40);
    const retried = storedFiles.find((f) => f.name === retryName && f.doc_kind === "speech" && !f.doc_version_of) || null;
    observation.cases.speech500Retry = {
      lineHidden: Boolean(find(session, "utilSpeechSaveState").hidden),
      stored: retried ? { name: retried.name, kind: retried.doc_kind, content: retried.content } : null,
      saveButtonLabel: text(find(session, "utilSpeechSave")).trim(),
    };

    // ── SNS·회의정리: each tab owns its own status line ────────────────────
    await openTool(session, "sns");
    const snsForm = find(session, "utilSnsForm");
    snsForm.querySelector("[name=event]").value = "상태별 안내 SNS";
    snsForm.querySelector("[name=content]").value = "본문";
    await snsForm.dispatch("submit");
    await sleep(20);
    fetchOverride = (method, path) => (
      method === "POST" && path === "/api/projects/p1/files" ? json({ error: { code: "forbidden" } }, 403) : null
    );
    find(session, "utilSnsOutput").value = "SNS 저장 실패 본문";
    await find(session, "utilSnsSave").dispatch("click");
    await sleep(30);
    const snsLine = find(session, "utilSnsSaveState");
    observation.cases.sns403 = {
      text: text(snsLine),
      hidden: Boolean(snsLine.hidden),
      hasRetry: Boolean(snsLine.querySelector(".util-retry")),
      ariaLive: snsLine.getAttribute("aria-live"),
    };
    fetchOverride = null;

    await openTool(session, "meeting");
    const meetingForm = find(session, "utilMeetingForm");
    meetingForm.querySelector("[name=title]").value = "상태별 안내 회의";
    meetingForm.querySelector("[name=content]").value = "본문";
    await meetingForm.dispatch("submit");
    await sleep(20);
    fetchOverride = (method, path) => (
      method === "POST" && path === "/api/projects/p1/files" ? json({ error: { code: "not_found" } }, 404) : null
    );
    find(session, "utilMeetingOutput").value = "회의 저장 실패 본문";
    await find(session, "utilMeetingSave").dispatch("click");
    await sleep(30);
    const meetingLine = find(session, "utilMeetingSaveState");
    observation.cases.meeting404 = {
      text: text(meetingLine),
      hidden: Boolean(meetingLine.hidden),
      hasRetry: Boolean(meetingLine.querySelector(".util-retry")),
      ariaLive: meetingLine.getAttribute("aria-live"),
    };
    fetchOverride = null;

    // ── 409 with no choice: the ask waits, nothing is stored, no line lies ──
    await openTool(session, "speech");
    speechForm.querySelector("[name=event]").value = "선택 없이는 저장 없음";
    speechForm.querySelector("[name=message]").value = "본문";
    await speechForm.dispatch("submit");
    await sleep(20);
    find(session, "utilSpeechOutput").value = "첫 저장 본문";
    await find(session, "utilSpeechSave").dispatch("click");
    await sleep(40);
    const firstStored = storedFiles.filter((f) => f.doc_kind === "speech" && !f.doc_version_of).length;
    find(session, "utilSpeechOutput").value = "다시 저장하려는 본문";
    const writesBefore = requests.filter((r) => r.method === "POST" || r.method === "PUT").length;
    // The ask suspends the save until a button is pressed — dispatch without
    // awaiting it, then give the 409 round trip time to land.
    void find(session, "utilSpeechSave").dispatch("click");
    await sleep(60);
    const ask = session.root.querySelector(".util-save-choice");
    const writesAfter = requests.filter((r) => r.method === "POST" || r.method === "PUT").length;
    const storedAfter = storedFiles.filter((f) => f.doc_kind === "speech" && !f.doc_version_of).length;
    observation.noChoice409 = {
      askShown: Boolean(ask),
      askText: ask ? text(ask.querySelector(".util-save-choice-text")) : null,
      askLabels: ask ? labels(ask.querySelectorAll("button")) : [],
      statusLineHidden: Boolean(find(session, "utilSpeechSaveState").hidden),
      rowsBefore: firstStored,
      rowsAfter: storedAfter,
      writeRequestsBefore: writesBefore,
      writeRequestsAfter: writesAfter,
    };

    observation.alerts = alerts.slice();
    observation.pageErrors = pageErrors;
    return observation;
  },

  async meeting_period() {
    storedFiles.push(
      { id:"mp1", name:"first.txt", doc_kind:"meeting", content:"회의 일시: 2026-10-10T10:00\n내용", created_at:"2026-09-01T12:00:00Z" },
      { id:"mp2", name:"second.txt", doc_kind:"meeting", content:"날짜 없음", created_at:"2026-10-15T12:00:00Z" },
      { id:"mp3", name:"third.txt", doc_kind:"meeting", content:"회의 일시: 2026-11-10\n내용", created_at:"2026-10-12T12:00:00Z" }
    );
    const session = spawnSession();
    await openTool(session, "meeting");
    await sleep(40);
    const start = find(session, "utilBookPeriodStart"), end = find(session, "utilBookPeriodEnd");
    const selected = () => Array.from(find(session, "utilMeetingArchive").querySelectorAll(".util-book-check")).filter((cb) => cb.checked).map((cb) => cb.value);
    start.value = "2026-10-01"; end.value = "2026-10-31";
    await end.dispatch("change"); await sleep(40);
    const initial = selected();
    const check = find(session, "utilMeetingArchive").querySelectorAll(".util-book-check").find((cb) => cb.value === "mp2");
    check.checked = false; await check.dispatch("change");
    const down = find(session, "utilMeetingArchive").querySelectorAll(".util-record-move").find((b) => b.dataset.move === "1" && !b.disabled);
    await down.dispatch("click");
    const manual = selected();
    const order = Array.from(find(session, "utilMeetingArchive").querySelectorAll(".util-book-check")).map((cb) => cb.value);
    start.value = "2025-01-01"; end.value = "2025-01-31";
    await end.dispatch("change"); await sleep(40);
    return { initial, manual, order, empty: text(find(session, "utilBookPeriodStatus")), emptySelected: selected(),
      quickLabels: labels(find(session, "utilBookPeriod").querySelectorAll("button")), pageErrors };
  },

  async meeting() {
    const session = spawnSession();
    await openTool(session, "meeting");
    const form = find(session, "utilMeetingForm");
    const field = (name) => form.querySelector(`[name=${name}]`);
    field("title").value = "10월 주민 민원 회의";
    field("when").value = "2026-10-24T10:00";
    field("attendees").value = "비서실장, 지역 담당";
    field("content").value = "항구 도로 보수 일정과 버스 노선 조정을 논의했습니다.";

    await form.dispatch("submit");
    await sleep(20);
    const prompt = chatPayloads[chatPayloads.length - 1].messages[0].content;
    const generated = find(session, "utilMeetingOutput").value;

    const edited = generated + "\n\n[편집: 후속 일정 확정]";
    find(session, "utilMeetingOutput").value = edited;
    await find(session, "utilMeetingSave").dispatch("click");
    await sleep(40);

    const archive = find(session, "utilMeetingArchive");
    const archiveButtons = archive.querySelectorAll("button");
    const fileButton = archiveButtons.find((b) => text(b).includes(".txt")) || null;
    let reopened = null;
    if (fileButton) {
      // Clear the editor first so a "restore" cannot be the draft already there.
      find(session, "utilMeetingOutput").value = "";
      await fileButton.dispatch("click");
      await sleep(20);
      reopened = find(session, "utilMeetingOutput").value;
    }

    // 활동집: select the stored record and generate the book draft from it.
    const checks = archive.querySelectorAll(".util-book-check");
    const bookBtn = session.root.querySelector("#utilBookGenerate");
    let bookPrompt = null;
    let bookOutput = null;
    if (checks.length && bookBtn) {
      checks[0].checked = true;
      await bookBtn.dispatch("click");
      await sleep(40);
      bookPrompt = chatPayloads[chatPayloads.length - 1].messages[0].content;
      bookOutput = find(session, "utilBookOutput").value;
    }

    // #5608: record order — a second stored record must be reorderable, and
    // the book prompt must carry the records in the arranged order.
    field("title").value = "11월 마을 총회";
    field("content").value = "마을 회관 리모델링 예산을 심의했습니다.";
    await form.dispatch("submit");
    await sleep(20);
    const secondEdited = find(session, "utilMeetingOutput").value + "\n[편집: 총회 기록]";
    find(session, "utilMeetingOutput").value = secondEdited;
    await find(session, "utilMeetingSave").dispatch("click");
    await sleep(40);

    const archive2 = find(session, "utilMeetingArchive");
    let rowNames = archive2.querySelectorAll(".util-record-move").map ? null : null;
    const moveButtons = Array.from(archive2.querySelectorAll(".util-record-move"));
    let orderBefore = null;
    let orderAfter = null;
    if (moveButtons.length >= 2) {
      const rowNameAt = (i) => archive2.querySelectorAll(".util-book-check")[i].getAttribute("aria-label") || "";
      orderBefore = archive2.querySelectorAll(".util-book-check").map ? null : null;
      const namesBefore = Array.from(archive2.querySelectorAll(".util-book-check")).map((cb) => cb.getAttribute("aria-label"));
      // move the first row down: 10월→11월 becomes 11월→10월
      const firstRowDown = moveButtons.find((b) => b.dataset.move === "1" && !b.disabled);
      if (firstRowDown) {
        await firstRowDown.dispatch("click");
        await sleep(20);
      }
      const namesAfter = Array.from(find(session, "utilMeetingArchive").querySelectorAll(".util-book-check")).map((cb) => cb.getAttribute("aria-label"));
      orderBefore = namesBefore;
      orderAfter = namesAfter;
    }

    // #5608: the arranged order must drive the book prompt's record sequence.
    // Check both records and generate: the prompt must list 11월 first.
    const archive3 = find(session, "utilMeetingArchive");
    const checks2 = archive3.querySelectorAll(".util-book-check");
    let bookOrderPrompt = null;
    if (checks2.length >= 2) {
      checks2.forEach((cb) => { cb.checked = true; });
      const gen2 = session.root.querySelector("#utilBookGenerate");
      await gen2.dispatch("click");
      await sleep(40);
      bookOrderPrompt = chatPayloads[chatPayloads.length - 1].messages[0].content;
    }

    // #5608: the book draft persists under its own name rule and reopens on
    // re-entry — a fresh session lists the stored book and restores it.
    const bookSaveBtn = session.root.querySelector("#utilBookSave");
    let bookSavedName = null;
    if (bookSaveBtn) {
      const draft = find(session, "utilBookOutput").value;
      if (draft && draft.indexOf("생성 실패") !== 0) {
        await bookSaveBtn.dispatch("click");
        await sleep(40);
        const bookFile = storedFiles.filter((f) => f.name.indexOf("활동집 - ") === 0).pop() || null;
        bookSavedName = bookFile ? bookFile.name : null;
      }
    }

    const reentry = spawnSession();
    await openTool(reentry, "meeting");
    await sleep(40);
    const reentryArchive = find(reentry, "utilMeetingArchive");
    const reentryBookButtons = reentryArchive.querySelectorAll(".util-book-open");
    let reentryBookRestored = null;
    if (reentryBookButtons.length) {
      await reentryBookButtons[0].dispatch("click");
      await sleep(20);
      reentryBookRestored = find(reentry, "utilBookOutput").value;
    }
    const reentryRecordButtons = Array.from(reentryArchive.querySelectorAll("button")).filter((b) => text(b).includes(".txt"));

    // Per-name record bodies so the meeting-save contract stays checkable
    // now that the scenario stores two records and one book.
    const savedRecordBodies = {};
    storedFiles.filter((f) => f.name.endsWith(".txt") && f.name.indexOf("활동집 - ") !== 0).forEach((f) => { savedRecordBodies[f.name] = f.content; });

    return {
      formBuild: formShape(session, "utilMeetingPanel", "utilMeetingForm", "utilMeetingSaveState"),
      prompt,
      generated,
      edited,
      savedName: storedFiles.length ? storedFiles[storedFiles.length - 1].name : null,
      savedBody: storedFiles.length ? storedFiles[storedFiles.length - 1].content : null,
      savedRecordNames: Object.keys(savedRecordBodies),
      savedRecordBodies,
      archiveLabels: labels(archiveButtons),
      archiveHasCheckbox: checks.length > 0,
      reopened,
      bookPrompt,
      bookOutput,
      orderBefore,
      orderAfter,
      bookOrderPromptCarriesArrangedOrder: bookOrderPrompt ? (bookOrderPrompt.indexOf("11월 마을 총회.txt") < bookOrderPrompt.indexOf("10월 주민 민원 회의.txt")) : null,
      bookSavedName,
      reentryBookListCount: reentryBookButtons.length,
      reentryBookRestored,
      reentryRecordCount: reentryRecordButtons.length,
      endpoints: endpointSet(),
      alerts,
      pageErrors,
    };
  },

  // #5908: the quick-run toolbox cards. The four util cards must land on the
  // same panels/switch the submenu drives; the two Claw cards must route to
  // the existing Claw workspace (and, for 견적서, preselect its existing chip)
  // instead of inventing a second engine here.
  async tools() {
    const session = spawnSession();
    await session.navBtn.dispatch("click");
    await sleep(10);
    const grid = find(session, "utilToolGrid");
    const buttons = grid.querySelectorAll("[data-util-tool]");
    const keys = buttons.map((b) => b.getAttribute("data-util-tool"));

    const panelIds = ["utilSpeechPanel", "utilSnsPanel", "utilMeetingPanel", "utilPdfmdPanel"];
    const visiblePanels = () => panelIds.filter((id) => !find(session, id).hidden);
    const activeSubmenu = () => session.byId.utilSubmenu.querySelectorAll(".util-submenu-item")
      .filter((i) => i.classList.contains("active"))
      .map((i) => i.dataset.util);

    await buttons.find((b) => b.getAttribute("data-util-tool") === "speech").dispatch("click");
    await sleep(10);
    const visibleAfterSpeech = visiblePanels();
    const activeSubAfterSpeech = activeSubmenu();

    await buttons.find((b) => b.getAttribute("data-util-tool") === "pdfmd").dispatch("click");
    await sleep(10);
    const visibleAfterPdfmd = visiblePanels();

    await buttons.find((b) => b.getAttribute("data-util-tool") === "claw-quote").dispatch("click");
    await sleep(10);
    const afterQuote = { clawNav: session.clawNavClicks.length, chip: session.clawChipClicks.length };

    await buttons.find((b) => b.getAttribute("data-util-tool") === "claw-excel").dispatch("click");
    await sleep(10);
    const afterExcel = { clawNav: session.clawNavClicks.length, chip: session.clawChipClicks.length };

    return {
      keys,
      visibleAfterSpeech,
      activeSubAfterSpeech,
      visibleAfterPdfmd,
      afterQuote,
      afterExcel,
      pageErrors,
    };
  },

  async shared() {
    const session = spawnSession();
    const perTool = {};
    for (const key of ["speech", "sns", "meeting"]) {
      const before = requests.length;
      await openTool(session, key);
      const form = find(session, key === "speech" ? "utilSpeechForm" : key === "sns" ? "utilSnsForm" : "utilMeetingForm");
      const field = (name) => form.querySelector(`[name=${name}]`);
      if (key === "speech") field("event").value = "공통 계약 검증";
      if (key === "sns") { field("event").value = "공통 계약 검증"; field("content").value = "본문"; }
      if (key === "meeting") { field("title").value = "공통 계약 검증"; field("content").value = "내용"; }
      await form.dispatch("submit");
      await sleep(20);
      perTool[key] = requests.slice(before).map((r) => r.method + " " + r.url);
    }
    return {
      perTool,
      endpoints: endpointSet(),
      chatPayloads,
      credentials: Array.from(new Set(requests.map((r) => r.credentials))),
      projectWrites: storedFiles.length,
      alerts,
      pageErrors,
    };
  },
};

(async () => {
  if (!SCENARIOS[scenario]) throw new Error("unknown scenario: " + scenario);
  const observation = await SCENARIOS[scenario]();
  console.log(JSON.stringify({ ok: true, scenario, observation }));
})().catch((error) => {
  console.log(JSON.stringify({ ok: false, scenario, error: String((error && error.stack) || error), alerts }));
  process.exit(1);
});
