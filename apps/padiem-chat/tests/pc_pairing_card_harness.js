// #5573 browser harness for pc-pairing-card.js, run by node from pytest.
// A minimal DOM and a scripted fetch: the module is exercised for real. The
// checks are the 2026-10-29 owner redesign's contract — one offer, one run
// guide, a self-updating wait, a two-PC list with a per-row menu, and the
// identity/folder-approval UI that stays off the screen while its server
// features stay in the module.
const fs = require("node:fs");
const vm = require("node:vm");

const SOURCE = process.argv[2];
const script = fs.readFileSync(SOURCE, "utf8");

class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.attrs = {};
    this.dataset = {};
    this.text = "";
    this.hidden = false;
    this.listeners = {};
    this.className = "";
    this.parent = null;
    this.isConnected = true;
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
  addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
  focus() {}
  click() {
    // An anchor with a download attribute is the browser's own file hand-off:
    // the harness records what was handed over instead of navigating.
    if (this.download) (globalThis.downloads ||= []).push({ name: this.download, url: this.href });
    for (const h of this.listeners.click || []) h({});
  }
  matchesClass(cls) { return String(this.className || "").split(/\s+/).includes(cls); }
  querySelectorAll(sel) {
    const cls = String(sel).replace(/^\./, "");
    return this.ids().filter((n) => n.matchesClass(cls));
  }
  closest(sel) {
    const cls = String(sel).replace(/^\./, "");
    let node = this;
    while (node) {
      if (node.matchesClass(cls)) return node;
      node = node.parent;
    }
    return null;
  }
  allText() { return [this.text, ...this.children.map((c) => c.allText())].join(" "); }
  ids() { return [this, ...this.children.flatMap((c) => c.ids())]; }
}

function makeDom(responses) {
  const card = new El("div");
  card.attrs.id = "connectorComputerCard";
  const root = new El("html");
  root.lang = "ko";
  const calls = [];
  const downloads = [];
  const confirmState = { value: false };
  const byId = { connectorComputerCard: card };
  const document = {
    documentElement: root,
    readyState: "complete",
    createElement: (tag) => new El(tag),
    getElementById: (id) => byId[id] || card.ids().find((n) => n.attrs.id === id) || null,
    addEventListener: () => {},
  };
  const fetchImpl = async (url, options) => {
    calls.push({ url, method: options?.method || "GET", body: options?.body });
    const method = options?.method || "GET";
    let reply = responses[`${method} ${url}`];
    if (reply === undefined) reply = responses[`${method} *`];
    if (reply === undefined) reply = { status: 500, body: {} };
    // A key may carry a function of the call count: the pairing poll re-reads
    // the same URL until the server "sees" the new PC, so the fixture has to
    // be able to change its answer between reads.
    if (typeof reply === "function") reply = reply(calls.length);
    // A reply may carry `text` instead of a JSON body: the install file is a
    // file, and the card must treat it as one. `bytes` is the connect program -
    // the card must hand those exact bytes over, not a text decoding of them.
    const payload = typeof reply.text === "string"
      ? reply.text : JSON.stringify(reply.body ?? {});
    const encoded = new TextEncoder().encode(typeof reply.bytes === "string" ? reply.bytes : payload);
    return {
      ok: reply.status >= 200 && reply.status < 300,
      status: reply.status,
      arrayBuffer: async () => encoded.buffer.slice(encoded.byteOffset,
        encoded.byteOffset + encoded.byteLength),
      json: async () => {
        if (typeof reply.bytes === "string") throw new Error("not json");
        return reply.body ?? {};
      },
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
  const window = {
    addEventListener: () => {},
    padiemPcPairing: undefined,
    // The poll cadence is a test seam in the module; one millisecond makes the
    // wait run on node's own timers within a settle window.
    PADIEM_PC_PAIRING_POLL_MS: 1,
    confirm: () => confirmState.value,
  };
  let objectUrls = 0;
  const sandbox = {
    document, window, fetch: fetchImpl, calls,
    AbortController, TextDecoder, TextEncoder,
    setTimeout, clearTimeout, setInterval, clearInterval,
    Blob: class { constructor(parts) { this.parts = parts; } },
    URL: {
      createObjectURL: (blob) => { objectUrls += 1; (globalThis.blobs ||= {})[`blob:${objectUrls}`] = blob; return `blob:${objectUrls}`; },
      revokeObjectURL: () => {},
    },
    MutationObserver: class { observe() {} },
    console, JSON, Object, Array, Promise, String, Number, Math, encodeURIComponent,
  };
  globalThis.downloads = downloads;
  globalThis.blobs = {};
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(script, sandbox);
  return { card, calls, downloads, blobs: globalThis.blobs, sandbox, document, confirmState };
}

const NODE_ID = "node/meshdomain/mesh-pc-09";
const LINK = {
  link_id: "pclink_0123456789abcdef0123456789abcdef",
  mesh_node_id: NODE_ID,
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
  const scriptText = "# PADIEM PC 자동 연결\n$PairingTag = 'pd-1234abcd'\n";
  // The shape the route really hands back: program bytes, then the account's tag
  // and the deployment's own installer link written behind them.
  const programBytes = "MZ\u0090\u0003!PE\u0000\u0000 PADIEM PC CONNECT\r\n"
    + "PADIEMTRAILER:PADIEM-PC-CONNECT-1\r\nPADIEMTAG:pd-1234abcd\r\n"
    + "PADIEMURL:https://mesh.example.net/meshagents?id=101\r\n";

  // -- the empty card: one line, one button, one self-updating wait ----------
  let seen = [];
  const first = makeDom({
    "GET *": () => ({ status: 200, body: { ok: true, links: seen, codes: [] } }),
    "POST /api/pc/pairings": { status: 201, body: { ok: true, pairing: {
      code_id: "pcpair_abc", code: "K7QM2XTR9F4B", install_tag: "pd-1234abcd",
      expires_at: "2026-10-27T01:10:00Z" } } },
    "POST /api/pc/pairings/install-file": { status: 200, text: scriptText },
    "POST /api/pc/pairings/install-exe": { status: 200, bytes: programBytes },
  });
  await settle();
  const section = first.card.ids().find((n) => n.attrs.id === "pcPairingSection");
  check("section mounted inside the existing computer card", section);
  check("the primary offer is one big connect-this-PC button",
    section.ids().some((n) => String(n.className || "").includes("pc-pairing-connect")
      && n.allText() === "이 PC 연결하기")
    && section.allText().includes("Windows"),
    section.allText());
  check("no macOS or Linux copy", !/macOS|Mac\b|Linux/i.test(section.allText()), section.allText());
  const paired = await first.sandbox.window.padiemPcPairing.issue();
  check("the code path still works as a function",
    paired && paired.code === "K7QM2XTR9F4B", JSON.stringify(paired));
  check("the code is never rendered", !section.allText().includes("K7QM2XTR9F4B"),
    section.allText());
  check("the code button is kept and hidden",
    section.ids().some((n) => (n.className || "") === "pc-pairing-issue" && n.hidden === true),
    JSON.stringify(section.ids().map((n) => n.className)));
  check("one click hands the connect program to the browser",
    await first.sandbox.window.padiemPcPairing.connect() === true
    && first.downloads.length === 1
    && first.downloads[0].name === "padiem-pc-connect.exe"
    && new TextDecoder().decode(first.blobs[first.downloads[0].url]?.parts?.[0] ?? new ArrayBuffer(0))
      .includes("PADIEMTAG:pd-1234abcd"),
    JSON.stringify(first.downloads));
  const stepsBox = section.ids().find((n) => (n.className || "") === "pc-pairing-steps");
  check("the run guide appears after the download and names the three presses",
    stepsBox && stepsBox.hidden === false
    && stepsBox.allText().includes("알 수 없는 게시자")
    && stepsBox.allText().includes("[추가 정보]") && stepsBox.allText().includes("[실행]")
    && stepsBox.allText().includes("[예]"),
    stepsBox ? stepsBox.allText() : "no steps");
  const waitLine = section.ids().find((n) => (n.className || "") === "pc-pairing-wait");
  check("the wait line says the card re-checks by itself",
    waitLine && waitLine.hidden === false && waitLine.allText().includes("자동으로"),
    waitLine ? waitLine.allText() : "no wait line");
  check("the download is said, not the code",
    section.ids().find((n) => (n.className || "") === "pc-pairing-status")
      .allText().includes("설치 파일을 내려받았습니다")
    && !section.allText().includes("K7QM2XTR9F4B"),
    section.allText());

  // The server now sees the PC the person just installed: the wait turns into
  // the connected line by itself, without a reload or a second click.
  seen = [LINK];
  await dwell(80);
  check("the wait turns into 연결됨 ✓ by itself when the server sees the PC",
    section.ids().find((n) => (n.className || "") === "pc-pairing-status")
      .allText().includes("연결됨 ✓")
    && section.allText().includes("(집 PC)"),
    section.allText());
  check("the fresh PC is drawn into the list",
    section.allText().includes("집 PC") && section.allText().includes("연결됨"),
    section.allText());

  // -- the list: two PCs, one row menu each, and what stays off the screen ---
  const listed = makeDom({
    "GET *": { status: 200, body: { ok: true, links: [LINK, PAUSED_LINK], codes: [] } },
    [`DELETE /api/pc/pairings/${LINK.link_id}`]: { status: 200, body: { ok: true, revoked: true } },
    [`POST /api/pc/pairings/${LINK.link_id}/pause`]: { status: 200,
      body: { ok: true, link: { ...LINK, paused: true } } },
    [`POST /api/pc/pairings/${PAUSED_LINK.link_id}/resume`]: { status: 200,
      body: { ok: true, link: { ...PAUSED_LINK, paused: false, paused_at: null } } },
    [`POST /api/pc/pairings/${LINK.link_id}/label`]: { status: 200, body: { ok: true,
      link: { ...LINK, label: "직장 PC" } } },
    [`POST /api/pc/pairings/install-file`]: { status: 200, text: scriptText },
    [`POST /api/pc/pairings/install-exe`]: { status: 200, bytes: programBytes },
  });
  await settle();
  const shown = listed.card.ids().find((n) => n.attrs.id === "pcPairingSection");
  check("two PCs are listed with their server state badges",
    shown.allText().includes("집 PC") && shown.allText().includes("연결됨")
    && shown.allText().includes("회사 노트북") && shown.allText().includes("멈춤"),
    shown.allText());
  check("the mesh node identity never reaches the screen",
    !shown.allText().includes("node/meshdomain")
    && !shown.ids().some((n) => String(n.className || "").includes("pc-pairing-node")),
    shown.allText());
  check("drive lists and the folder approval UI stay off the screen",
    !shown.ids().some((n) => String(n.className || "").split(/\s+/).some((cls) => [
      "pc-pairing-roots", "pc-pairing-root", "pc-pairing-path",
      "pc-pairing-root-add", "pc-pairing-root-revoke"].includes(cls))),
    JSON.stringify(shown.ids().map((n) => n.className)));
  check("the script lane stays one disclosure away",
    shown.ids().some((n) => (n.className || "") === "pc-pairing-alternate")
    && await listed.sandbox.window.padiemPcPairing.connectScript() === true
    && listed.downloads.some((d) => d.name === "padiem-pc-connect.ps1"),
    JSON.stringify(listed.downloads));

  const activeRow = shown.ids().find((n) => (n.className || "") === "pc-pairing-link"
    && n.allText().includes("집 PC"));
  const toggle = activeRow.ids().find((n) => (n.className || "") === "pc-pairing-menu-toggle");
  const panel = activeRow.ids().find((n) => (n.className || "") === "pc-pairing-menu-panel");
  toggle.click();
  check("the row menu opens from its ⋯ toggle",
    panel.hidden === false && toggle.attrs["aria-expanded"] === "true",
    JSON.stringify({ hidden: panel.hidden, expanded: toggle.attrs["aria-expanded"] }));

  const nameField = activeRow.ids().find((n) => (n.className || "") === "pc-pairing-name-input");
  const nameSave = activeRow.ids().find((n) => n.matchesClass("pc-pairing-name-save"));
  activeRow.ids().find((n) => (n.className || "") === "pc-pairing-menu-rename").click();
  check("rename opens the inline editor",
    activeRow.ids().find((n) => (n.className || "") === "pc-pairing-rename-editor").hidden === false);
  nameField.value = "직장 PC";
  nameSave.click();
  await settle();
  check("rename posts the label route",
    listed.calls.some((call) => call.method === "POST"
      && call.url === "/api/pc/pairings/" + LINK.link_id + "/label"
      && JSON.parse(call.body).label === "직장 PC"),
    JSON.stringify(listed.calls));

  const pauseButton = shown.ids().find((n) => (n.className || "") === "pc-pairing-menu-pause");
  pauseButton.click();
  await settle();
  check("pause posts to that link's pause route",
    listed.calls.some((call) => call.method === "POST"
      && call.url === "/api/pc/pairings/" + LINK.link_id + "/pause"),
    JSON.stringify(listed.calls));
  const resumeButton = shown.ids().find((n) => (n.className || "") === "pc-pairing-menu-resume");
  resumeButton.click();
  await settle();
  check("the paused PC's menu offers 다시 시작 and posts the resume route",
    listed.calls.some((call) => call.method === "POST"
      && call.url === "/api/pc/pairings/" + PAUSED_LINK.link_id + "/resume"),
    JSON.stringify(listed.calls));

  listed.confirmState.value = false;
  shown.ids().find((n) => (n.className || "") === "pc-pairing-menu-revoke").click();
  await settle();
  check("a declined disconnect deletes nothing",
    !listed.calls.some((call) => call.method === "DELETE"), JSON.stringify(listed.calls));
  listed.confirmState.value = true;
  shown.ids().find((n) => (n.className || "") === "pc-pairing-menu-revoke").click();
  await settle();
  check("a confirmed disconnect deletes the link",
    listed.calls.some((call) => call.method === "DELETE"
      && call.url === "/api/pc/pairings/" + LINK.link_id), JSON.stringify(listed.calls));

  // -- the refusals read as refusals ----------------------------------------
  const notReady = makeDom({
    "GET *": { status: 503, body: { ok: false, error: { code: "pc_pairing_not_ready" } } },
  });
  await settle();
  const waiting = notReady.card.ids().find((n) => n.attrs.id === "pcPairingSection");
  check("an unapplied migration reads as 준비 중",
    waiting.allText().includes("아직 준비 중"), waiting.allText());
  check("nothing is drawn as connected", !waiting.allText().includes("연결됨"), waiting.allText());

  const refused = makeDom({
    "GET *": { status: 200, body: { ok: true, links: [LINK], codes: [] } },
    [`DELETE /api/pc/pairings/${LINK.link_id}`]: { status: 403,
      body: { ok: false, error: { code: "pc_pairing_link_not_found" } } },
  });
  await settle();
  refused.confirmState.value = true;
  const refusedSection = refused.card.ids().find((n) => n.attrs.id === "pcPairingSection");
  refusedSection.ids().find((n) => (n.className || "") === "pc-pairing-menu-revoke").click();
  await settle();
  check("a server refusal is said as a refusal",
    (refusedSection.status || refusedSection).ids()
      .find((n) => (n.className || "") === "pc-pairing-status").allText().length > 0
    && refused.calls.some((call) => call.method === "DELETE"),
    JSON.stringify(refused.calls));

  const noFile = makeDom({
    "GET *": { status: 200, body: { ok: true, links: [], codes: [] } },
    "POST /api/pc/pairings/install-file": { status: 503,
      body: { ok: false, error: { code: "pc_pairing_install_url_missing" } } },
    "POST /api/pc/pairings/install-exe": { status: 503,
      body: { ok: false, error: { code: "pc_pairing_install_url_missing" } } },
  });
  await settle();
  const waitingFile = noFile.card.ids().find((n) => n.attrs.id === "pcPairingSection");
  check("an unconfigured install link reads as 준비 중",
    await noFile.sandbox.window.padiemPcPairing.connect() === false
    && waitingFile.allText().includes("아직 준비 중")
    && noFile.downloads.length === 0, waitingFile.allText());

  // A build that carries no reviewed program still connects a PC: the script lane
  // is the same pairing, and the card switches without asking.
  const noProgram = makeDom({
    "GET *": { status: 200, body: { ok: true, links: [], codes: [] } },
    "POST /api/pc/pairings/install-file": { status: 200, text: scriptText },
    "POST /api/pc/pairings/install-exe": { status: 503,
      body: { ok: false, error: { code: "pc_pairing_connect_exe_unavailable" } } },
  });
  await settle();
  check("a missing program falls back to the install file",
    await noProgram.sandbox.window.padiemPcPairing.connect() === true
    && noProgram.downloads.length === 1
    && noProgram.downloads[0].name === "padiem-pc-connect.ps1",
    JSON.stringify(noProgram.downloads));

  // Only that one refusal is worth falling back on. A session that is not valid
  // must not quietly hand over a different file.
  const signedOut = makeDom({
    "GET *": { status: 200, body: { ok: true, links: [], codes: [] } },
    "POST /api/pc/pairings/install-file": { status: 200, text: scriptText },
    "POST /api/pc/pairings/install-exe": { status: 401,
      body: { ok: false, error: { code: "unauthorized" } } },
  });
  await settle();
  check("a refused sign-in is said and downloads nothing",
    await signedOut.sandbox.window.padiemPcPairing.connect() === false
    && signedOut.downloads.length === 0
    && signedOut.card.ids().find((n) => (n.className || "") === "pc-pairing-status")
      .allText().includes("로그인"),
    JSON.stringify(signedOut.downloads));

  // -- the standing security contracts --------------------------------------
  check("the code never reaches a URL",
    first.calls.every((call) => !call.url.includes("K7QM2XTR9F4B")),
    JSON.stringify(first.calls));
  check("every call is the pairing surface",
    first.calls.every((call) => call.url.startsWith("/api/pc/pairings")),
    JSON.stringify(first.calls));

  const failures = results.filter((row) => !row.ok);
  for (const row of results) {
    console.log(`PC_PAIRING_CARD_CHECK ${row.name} ${row.ok ? "PASS" : "FAIL " + row.detail}`);
  }
  console.log(failures.length ? "PC_PAIRING_CARD=FAIL" : "PC_PAIRING_CARD=PASS");
  process.exitCode = failures.length ? 1 : 0;
}

void main();
