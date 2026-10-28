// #5573 step 1 browser harness for pc-connect-flow.js, run by node from pytest.
// A minimal DOM and a scripted fetch: the one connect flow is exercised for
// real. The checks are the 2026-10-29 owner redesign's contract — a first-time
// account (zero PCs) gets one modal whose single press downloads the connect
// program and whose wait closes itself when the server sees the PC; an account
// that already has a PC never sees the modal, only one line; and the popover
// carries names and states and nothing else.
const fs = require("node:fs");
const vm = require("node:vm");

const SOURCE = process.argv[2];
const script = fs.readFileSync(SOURCE, "utf8");

class El {
  constructor(tag, className, text) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.attrs = {};
    this.dataset = {};
    this.text = "";
    this.hidden = false;
    this.listeners = {};
    this.className = "";
    this.style = {};
    this.parent = null;
    this.isConnected = true;
    if (className) this.className = String(className);
    if (text !== undefined) this.textContent = text;
  }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map((c) => c.textContent).join(""); }
  set id(value) { this.attrs.id = String(value); }
  get id() { return this.attrs.id || ""; }
  append(...nodes) {
    for (const n of nodes) if (n) { n.parent = this; this.children.push(n); }
  }
  replaceChildren(...nodes) { this.children = []; this.text = ""; this.append(...nodes); }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name] === undefined ? null : this.attrs[name]; }
  addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
  focus() {}
  getBoundingClientRect() {
    return { top: 8, left: 8, right: 200, bottom: 40, width: 192, height: 32 };
  }
  click() {
    // An anchor with a download attribute is the browser's own file hand-off:
    // the harness records what was handed over instead of navigating.
    if (this.download) (globalThis.downloads ||= []).push({ name: this.download, url: this.href });
    for (const h of this.listeners.click || []) h({});
  }
  matchesClass(cls) { return String(this.className || "").split(/\s+/).includes(cls); }
  matchesAttr(sel) {
    const bracket = sel.match(/^\[([a-zA-Z-]+)(?:="([^"]*)")?\]$/);
    if (!bracket) return false;
    const value = this.attrs[bracket[1]];
    if (bracket[2] === undefined) return value !== undefined;
    return String(value) === bracket[2];
  }
  matchesSelector(sel) {
    if (sel.startsWith("#")) return this.attrs.id === sel.slice(1);
    if (sel.startsWith(".")) return this.matchesClass(sel.slice(1));
    return this.matchesAttr(sel);
  }
  querySelectorAll(sel) { return this.ids().filter((n) => n.matchesSelector(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  allText() { return [this.text, ...this.children.map((c) => c.allText())].join(" "); }
  ids() { return [this, ...this.children.flatMap((c) => c.ids())]; }
}

function makeDom(responses, options = {}) {
  const body = new El("body");
  const chip = new El("button");
  chip.id = "composerPcStatus";
  const face = new El("span", "composer-pc-status-face");
  const label = new El("span");
  face.append(label);
  chip.append(face);
  const starter = new El("button");
  starter.id = "pcConnectStarter";
  const strong = new El("strong", null, "컴퓨터 연결");
  const small = new El("small", null, "연결 상태를 확인하는 중…");
  small.setAttribute("data-pc-connect-state", "");
  const starterInner = new El("span");
  starterInner.append(strong, small);
  starter.append(starterInner);
  body.append(chip, starter);
  const root = new El("html");
  root.lang = options.lang || "ko";
  const calls = [];
  const downloads = [];
  const store = options.store || {};
  const events = [];
  const windowListeners = {};
  const documentObj = {
    documentElement: root,
    readyState: "complete",
    activeElement: null,
    body,
    createElement: (tag) => new El(tag),
    getElementById: (id) => body.ids().find((n) => n.attrs.id === id) || null,
    querySelector: (sel) => body.querySelectorAll(sel)[0] || null,
    addEventListener: () => {},
  };
  const fetchImpl = async (url, options2) => {
    calls.push({ url, method: options2?.method || "GET", body: options2?.body });
    const method = options2?.method || "GET";
    let reply = responses[`${method} ${url}`];
    if (reply === undefined) reply = responses[`${method} *`];
    if (reply === undefined) reply = { status: 404, body: {} };
    if (typeof reply === "function") reply = reply(calls.length);
    const payload = typeof reply.text === "string"
      ? reply.text : JSON.stringify(reply.body ?? {});
    const encoded = new TextEncoder().encode(typeof reply.bytes === "string" ? reply.bytes : payload);
    return {
      ok: reply.status >= 200 && reply.status < 300,
      status: reply.status,
      json: async () => {
        if (typeof reply.bytes === "string") throw new Error("not json");
        return reply.body ?? {};
      },
      arrayBuffer: async () => encoded.buffer.slice(encoded.byteOffset,
        encoded.byteOffset + encoded.byteLength),
      body: {
        getReader: () => {
          let sent = false;
          return {
            read: async () => (sent ? { done: true }
              : (sent = true, { done: false, value: encoded })),
            cancel: async () => {},
          };
        },
      },
    };
  };
  const windowObj = {
    addEventListener: (type, handler) => { (windowListeners[type] ||= []).push(handler); },
    dispatchEvent: (event) => {
      events.push(event);
      for (const handler of windowListeners[event.type] || []) handler(event);
      return true;
    },
    innerWidth: 1280,
    padiemPcConnectFlow: undefined,
    PADIEM_PC_CONNECT_POLL_MS: 1,
    PADIEM_PC_CONNECT_CLOSE_MS: 5,
    localStorage: {
      getItem: (key) => (key in store ? store[key] : null),
      setItem: (key, value) => { store[key] = value; },
    },
  };
  let objectUrls = 0;
  const sandbox = {
    document: documentObj, window: windowObj, fetch: fetchImpl, calls,
    AbortController, TextDecoder, TextEncoder, CustomEvent,
    setTimeout, clearTimeout, setInterval, clearInterval,
    Blob: class { constructor(parts) { this.parts = parts; } },
    URL: {
      createObjectURL: (blob) => { objectUrls += 1; (globalThis.blobs ||= {})[`blob:${objectUrls}`] = blob; return `blob:${objectUrls}`; },
      revokeObjectURL: () => {},
    },
    MutationObserver: class { observe() {} },
    console, JSON, Object, Array, Promise, String, Number, Math, Date, encodeURIComponent,
  };
  globalThis.downloads = downloads;
  globalThis.blobs = {};
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(script, sandbox);
  return { body, chip, starter, calls, downloads, store, events, sandbox, window: windowObj,
    blobs: globalThis.blobs };
}

const LINK = {
  link_id: "pclink_0123456789abcdef0123456789abcdef",
  mesh_node_id: "node/meshdomain/mesh-pc-09",
  label: "집 PC",
  state: "active",
  roots: [{ root_ref: "pcroot_0123456789abcdef", label: "견적", path: "C:/Users/me/견적",
            state: "active", approved_at: "2026-10-27T01:00:00Z" }],
};
const PAUSED_LINK = {
  link_id: "pclink_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  mesh_node_id: "node/meshdomain/mesh-pc-10",
  label: "회사 노트북",
  state: "paused",
  roots: [],
};

const results = [];
const settle = async (rounds = 8) => {
  for (let index = 0; index < rounds; index += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
};
const dwell = async (ms = 60) => { await new Promise((resolve) => setTimeout(resolve, ms)); };
function check(name, condition, detail) {
  results.push({ name, ok: Boolean(condition), detail: condition ? "" : String(detail ?? "") });
}

async function main() {
  const programBytes = "MZ\u0090\u0003!PE\u0000\u0000 PADIEM PC CONNECT\r\n"
    + "PADIEMTRAILER:PADIEM-PC-CONNECT-1\r\nPADIEMTAG:pd-1234abcd\r\n"
    + "PADIEMURL:https://mesh.example.net/meshagents?id=101\r\n";
  const scriptText = "# PADIEM PC 자동 연결\n$PairingTag = 'pd-1234abcd'\n";

  // -- the first-time account: zero PCs --------------------------------------
  let seen = [];
  const first = makeDom({
    "GET *": () => ({ status: 200, body: { ok: true, links: seen, codes: [] } }),
    "POST /api/pc/pairings/install-exe": { status: 200, bytes: programBytes },
    "POST /api/pc/pairings/install-file": { status: 200, text: scriptText },
  });
  await settle();
  check("boot publishes the PC-list state (disconnected for an empty list)",
    first.events.some((event) => event.type === "padiem:pc-pairing-state"
      && event.detail && event.detail.state === "disconnected" && event.detail.read === "ok"),
    JSON.stringify(first.events.map((event) => event.type)));
  const chipAction = first.chip.querySelector(".pc-connect-chip-action");
  check("the composer chip gains the connect affordance when no PC is connected",
    chipAction && chipAction.allText().includes("연결하기") && chipAction.hidden === false,
    chipAction ? JSON.stringify({ text: chipAction.allText(), hidden: chipAction.hidden }) : "no affordance");
  check("the starter card's status line is painted from the PC list",
    (first.starter.querySelector("[data-pc-connect-state]") || { allText: () => "" }).allText()
      .includes("연결 안 됨") === true,
    first.starter.allText());

  const openResult = await first.window.PadiemPcConnectFlow.open();
  const modal = first.body.querySelectorAll(".pc-connect-backdrop")[0] || null;
  check("open() with no PC shows the modal with the owner's three lines",
    openResult === "modal"
    && modal && modal.hidden === false
    && modal.allText().includes("이 컴퓨터를 연결할게요")
    && modal.allText().includes("처음 한 번만 작은 프로그램을 설치해요")
    && modal.allText().includes("설치하고 연결하기"),
    modal ? modal.allText() : "no modal");

  const installButton = modal.querySelector(".pc-connect-install");
  installButton.click();
  await settle();
  check("one press downloads the connect program with the account tag",
    first.downloads.length === 1
    && first.downloads[0].name === "padiem-pc-connect.exe"
    && new TextDecoder().decode(first.blobs[first.downloads[0].url]?.parts?.[0] ?? new ArrayBuffer(0))
      .includes("PADIEMTAG:pd-1234abcd"),
    JSON.stringify(first.downloads));
  const runLine = modal.querySelector(".pc-connect-run");
  const warnLine = modal.querySelector(".pc-connect-warn");
  const waitLine = modal.querySelector(".pc-connect-wait");
  check("the modal then tells the two remaining presses",
    runLine && runLine.hidden === false && runLine.allText().includes("[예]를 누르면 끝나요")
    && warnLine && warnLine.hidden === false && warnLine.allText().includes("[추가 정보] → [실행]"),
    modal.allText());
  check("the wait says the card re-checks by itself",
    waitLine && waitLine.hidden === false && waitLine.allText().includes("자동으로"),
    modal.allText());

  seen = [LINK];
  await dwell(80);
  const doneLine = modal.querySelector(".pc-connect-done");
  check("the wait turns into 연결됐어요 ✓ (이름) by itself when the server sees the PC",
    doneLine && doneLine.hidden === false && doneLine.allText().includes("연결됐어요 ✓")
      && doneLine.allText().includes("(집 PC)"),
    modal.allText());
  check("the flow leaves no browser persistence behind (the server list is the only memory)",
    (() => { try { return Object.keys(first.store).length === 0; } catch (_) { return false; } })(),
    JSON.stringify(first.store));
  check("the connected event fires for the request lane",
    first.events.some((event) => event.type === "padiem:pc-connected"
      && event.detail && event.detail.link && event.detail.link.link_id === LINK.link_id),
    JSON.stringify(first.events.map((event) => event.type)));
  await dwell(30);
  check("the modal closes itself without a click",
    modal.hidden === true, JSON.stringify({ hidden: modal.hidden }));

  // -- the account that already has a PC --------------------------------------
  const second = makeDom({
    "GET *": { status: 200, body: { ok: true, links: [LINK], codes: [] } },
    "POST /api/pc/pairings/install-exe": { status: 200, bytes: programBytes },
  });
  await settle();
  check("open() with a connected PC never opens the modal — one line instead",
    await second.window.PadiemPcConnectFlow.open() === "connected"
    && !second.body.querySelectorAll(".pc-connect-backdrop").some((n) => n.hidden === false)
    && second.downloads.length === 0
    && (second.body.querySelector(".pc-connect-note") || { allText: () => "" }).allText().includes("내 PC 연결됨 ✓"),
    JSON.stringify({ downloads: second.downloads, note: (second.body.querySelector(".pc-connect-note") || { allText: () => "" }).allText() }));
  check("the chip's connect affordance hides once a PC is connected",
    (second.chip.querySelector(".pc-connect-chip-action") || {}).hidden === true,
    JSON.stringify(second.chip.allText()));

  // -- refusals read as refusals ----------------------------------------------
  const noProgram = makeDom({
    "GET *": { status: 200, body: { ok: true, links: [], codes: [] } },
    "POST /api/pc/pairings/install-exe": { status: 503,
      body: { ok: false, error: { code: "pc_pairing_connect_exe_unavailable" } } },
    "POST /api/pc/pairings/install-file": { status: 200, text: scriptText },
  });
  await settle();
  await noProgram.window.PadiemPcConnectFlow.open();
  noProgram.body.querySelectorAll(".pc-connect-backdrop")[0].querySelector(".pc-connect-install").click();
  await settle();
  check("a missing program falls back to the .ps1 install file",
    noProgram.downloads.length === 1 && noProgram.downloads[0].name === "padiem-pc-connect.ps1"
    && noProgram.body.querySelectorAll(".pc-connect-backdrop")[0].allText().includes("[예]를 누르면 끝나요"),
    JSON.stringify(noProgram.downloads));

  const signedOut = makeDom({
    "GET *": { status: 200, body: { ok: true, links: [], codes: [] } },
    "POST /api/pc/pairings/install-exe": { status: 401,
      body: { ok: false, error: { code: "unauthorized" } } },
  });
  await settle();
  await signedOut.window.PadiemPcConnectFlow.open();
  signedOut.body.querySelectorAll(".pc-connect-backdrop")[0].querySelector(".pc-connect-install").click();
  await settle();
  check("a refused sign-in is said and downloads nothing",
    signedOut.downloads.length === 0
    && signedOut.body.querySelectorAll(".pc-connect-backdrop")[0].allText().includes("로그인"),
    JSON.stringify(signedOut.downloads));

  const notReady = makeDom({
    "GET *": { status: 200, body: { ok: true, links: [], codes: [] } },
    "POST /api/pc/pairings/install-exe": { status: 503,
      body: { ok: false, error: { code: "pc_pairing_not_ready" } } },
  });
  await settle();
  await notReady.window.PadiemPcConnectFlow.open();
  notReady.body.querySelectorAll(".pc-connect-backdrop")[0].querySelector(".pc-connect-install").click();
  await settle();
  const notReadyModal = notReady.body.querySelectorAll(".pc-connect-backdrop")[0];
  check("a not-ready server reads as 준비 중, never as 연결됐어요",
    notReadyModal.allText().includes("아직 준비 중")
    && !notReadyModal.allText().includes("연결됐어요"),
    notReadyModal.allText());

  // -- the popover: names and states, nothing else -----------------------------
  const listed = makeDom({
    "GET *": { status: 200, body: { ok: true, links: [LINK, PAUSED_LINK], codes: [] } },
  });
  await settle();
  listed.window.PadiemPcConnectFlow.togglePopover(listed.chip);
  const popover = listed.body.querySelectorAll(".pc-connect-popover")[0];
  check("the popover lists the PCs with their states and nothing else",
    popover && popover.hidden === false
    && popover.allText().includes("집 PC") && popover.allText().includes("연결됨")
    && popover.allText().includes("회사 노트북") && popover.allText().includes("멈춤"),
    popover ? popover.allText() : "no popover");
  check("the popover carries no identity, drive or folder field",
    !popover.allText().includes("node/meshdomain")
    && !popover.allText().includes("C:/Users")
    && !popover.ids().some((n) => String(n.className || "").split(/\s+/).some((cls) => [
      "pc-pairing-roots", "pc-pairing-root", "pc-pairing-path",
      "pc-pairing-menu", "pc-pairing-node"].includes(cls))),
    JSON.stringify(popover.ids().map((n) => n.className)));

  // -- the standing security contracts -----------------------------------------
  check("every call is the pairing surface",
    first.calls.every((call) => call.url.startsWith("/api/pc/pairings")),
    JSON.stringify(first.calls));
  check("no pairing code ever reaches a URL",
    [...first.calls, ...listed.calls].every((call) => !call.url.includes("pd-1234abcd")
      && !call.url.includes("K7QM2XTR9F4B")),
    JSON.stringify([...first.calls, ...listed.calls]));

  const failures = results.filter((row) => !row.ok);
  for (const row of results) {
    console.log(`PC_CONNECT_FLOW_CHECK ${row.name} ${row.ok ? "PASS" : "FAIL " + row.detail}`);
  }
  console.log(failures.length ? "PC_CONNECT_FLOW=FAIL" : "PC_CONNECT_FLOW=PASS");
  process.exitCode = failures.length ? 1 : 0;
}

void main();
