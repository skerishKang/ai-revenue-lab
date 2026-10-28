// #5895 browser harness for pc-file-exchange.js, run by node from pytest.
//
// A minimal DOM and a scripted fetch: the shipped module is exercised for real, and
// the checks are the ones the owner's flow depends on — the dialog opens with the
// owner's own folder, a folder click goes back to the server, a search is addressed by
// name, the chosen file arrives as text or as a file, several PCs and several folders
// are asked about instead of guessed, saving names the file and takes the PC's own
// account line, and a PC that takes thirty rounds of polling is still simply working.
const fs = require("node:fs");
const vm = require("node:vm");

const SOURCE = process.argv[2];
const LOCALE = process.argv[3];
const script = fs.readFileSync(SOURCE, "utf8");
const localeText = fs.readFileSync(LOCALE, "utf8");

const ko = localeText.split("\n    en: {")[0];

function copyOf(key) {
  const match = new RegExp(`"${key}": "([^"]*)"`).exec(ko);
  if (!match) throw new Error(`${key} is missing from the Korean labels`);
  return match[1];
}

class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.attrs = {};
    this.dataset = {};
    this.raw = "";
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.listeners = {};
    this.className = "";
    this.parentNode = null;
  }
  set textContent(value) { this.raw = String(value); this.children = []; }
  get textContent() { return this.raw; }
  set innerText(value) { this.raw = String(value); }
  append(...nodes) {
    for (const node of nodes) {
      if (!node) continue;
      node.parentNode = this;
      this.children.push(node);
    }
  }
  replaceChildren(...nodes) { this.children = []; this.raw = ""; this.append(...nodes); }
  removeChild(node) {
    this.children = this.children.filter((child) => child !== node);
    if (node && node.parentNode === this) node.parentNode = null;
    return node;
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name]; }
  addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
  focus() { this.attrs.focused = "true"; }
  click() { for (const handler of this.listeners.click || []) handler({ preventDefault() {} }); }
  allText() { return [this.raw, ...this.children.map((child) => child.allText())].join(" "); }
  ids() { return [this, ...this.children.flatMap((child) => child.ids())]; }
  find(predicate) { return this.ids().find(predicate) || null; }
  byClass(name) { return this.find((node) => node.className === name); }
  allWithClass(name) { return this.ids().filter((node) => node.className === name); }
}

function makeDom(responses) {
  const body = new El("body");
  const document = {
    documentElement: { lang: "ko" },
    readyState: "complete",
    createElement: (tag) => new El(tag),
    getElementById: () => null,
    addEventListener: () => {},
    activeElement: null,
    body,
  };
  const calls = [];
  const fetchImpl = async (url, options) => {
    const method = (options && options.method) || "GET";
    calls.push({ url, method, body: options && options.body });
    const key = url.split("?")[0];
    const queue = responses[key];
    const chosen = Array.isArray(queue) ? (queue.length > 1 ? queue.shift() : queue[0]) : queue;
    // An entry may be a function: that is how a check looks at the screen while the
    // part is still waiting, and how each staged call gets its own dispatch id.
    const reply = (typeof chosen === "function" ? chosen({ url, method, body: options && options.body }) : chosen)
      || { status: 500, body: { ok: false } };
    return {
      ok: reply.status >= 200 && reply.status < 300,
      status: reply.status,
      json: async () => reply.body,
    };
  };
  const sandbox = {
    document,
    fetch: fetchImpl,
    setInterval: (run) => { run(); return 1; },
    clearInterval: () => {},
    setTimeout: (run) => { run(); return 1; },
    clearTimeout: () => {},
    Date: { now: () => 1_780_000_000_000 },
    URLSearchParams: class { constructor(init) { this.init = init; } toString() { return Object.entries(this.init).map(([k, v]) => `${k}=${v}`).join("&"); } },
    JSON, Object, Array, Promise, String, Number, Math, RegExp, Error, Boolean,
    console,
    __padiemLocale: { text: (key, variables) => copyOf(key).replace(/\{[a-z]+\}/g, (_m, name) => String((variables || {})[name] ?? "")) },
    PadiemChatLifecycle: { elapsedClockText: (ms) => String(Math.floor(ms / 1000)) + "s" },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(script, sandbox);
  return { body, calls, sandbox, window: sandbox, El };
}

const SWEEP_RUN = "chat_pcq_" + "d".repeat(32);
const LINK_ONE = "pclink_" + "1".repeat(32);
const LINK_TWO = "pclink_" + "2".repeat(32);
const FETCHED = "dsp_" + "a".repeat(32);
const SAVED_TO = "C:/Users/qa/축사.txt";

let sequence = 0;
const nextDispatch = () => "dsp_" + (sequence += 1).toString(16).padStart(32, "0");

// Each staged answer owns one dispatch id for its whole operation, because the waiting
// loop follows the id the server handed back — a fixture that reused one id everywhere
// would still pass if the part watched somebody else's answer.
function staged(runId) {
  const id = nextDispatch();
  const run = runId || ("chat_pcq_" + id.slice(4));
  return () => ({ status: 200, body: {
    ok: true, state: "working", dispatch_id: id, run_id: run,
    conversation_id: "chat_" + "c".repeat(32), poll_seconds: 0.001,
  } });
}
const working = () => ({ status: 200, body: { ok: true, state: "working", poll_seconds: 0.001 } });
const listed = () => ({ status: 200, body: { ok: true, state: "ready", items: [
  { name: "견적", kind: "folder", size_bytes: null, modified_at: "2026-10-01T00:00:00Z" },
  { name: "1분기.md", kind: "file", size_bytes: 2048, modified_at: "2026-10-02T00:00:00Z" },
] } });
const found = () => ({ status: 200, body: { ok: true, state: "ready", found: [
  { name: "명함.png", kind: "file", size_bytes: 100, folder: "D:/그림", path: "D:/그림/명함.png" },
] } });
const fetched = () => ({ status: 200, body: { ok: true, state: "ready",
  content_kind: "text", content: "본문입니다", file_id: FETCHED, size_bytes: 12 } });
const saved = () => ({ status: 200, body: { ok: true, state: "ready", saved: {
  ok: true, op: "write", reason: null, target: SAVED_TO,
  backup: "C:/.padiem-backup/2026-10-28/축사.txt", bytes: 18,
} } });
const refused = () => ({ status: 200, body: { ok: false, state: "ready", saved: {
  ok: false, op: "write", reason: "backup_failed", target: SAVED_TO, backup: null, bytes: 0,
} } });

// The first look answers the matches at that level and the folders left to look in, and
// each folder answered afterwards carries only its own matches: that is what lets the
// screen show part of a search while the rest is still being looked through.
const seeded = () => ({ status: 200, body: { ok: true, state: "ready", found: [
  { name: "명함.png", kind: "file", size_bytes: 100, folder: "C:/Users/qa",
    path: "C:/Users/qa/명함.png" },
], folders: ["C:/Users/qa/2026", "C:/Users/qa/사진"] } });
const swept = (name, folder) => () => ({ status: 200, body: { ok: true, state: "ready", found: [
  { name: name, kind: "file", size_bytes: 120, folder: folder, path: folder + "/" + name },
] } });
const cancelled = { status: 200, body: { ok: true, state: "cancelled", stopped: 1 } };

const results = [];
const settle = async (rounds = 20) => {
  for (let index = 0; index < rounds; index += 1) await new Promise((resolve) => setImmediate(resolve));
};
function check(name, condition, detail) {
  results.push({ name, ok: Boolean(condition), detail: condition ? "" : String(detail ?? "") });
}
const browseCalls = (calls) => calls.filter((call) => call.url === "/api/pc/browse");
const bodyOf = (call) => JSON.parse(call.body);
const dialogOf = (dom) => dom.body.byClass("pc-exchange-dialog");
const entriesOf = (dom) => dom.body.allWithClass("pc-exchange-entry");
const buttonOf = (dom, className) => dom.body.find((node) => node.className === className);
const stripOf = (dom) => dom.body.find((node) => node.className === "pc-exchange-pcs" && !node.hidden);
const statusOf = (dom) => dom.body.find((node) => node.className === "pc-exchange-status" && !node.hidden);

async function main() {
  // ── one PC: the dialog opens on the owner's own folder, then drills in ──
  const dom = makeDom({
    "/api/pc/browse": [staged(), staged(), staged()],
    "/api/pc/result": [working, () => { duringWait = dialogOf(dom).allText(); return working(); }, listed],
  });
  let duringWait = "";
  dom.window.PadiemPcFileExchange.open({ onSelect: () => {} });
  await settle();
  check("at the root, 이전 폴더 sits disabled — the owner is already at the top",
    buttonOf(dom, "pc-exchange-back").disabled === true,
    String(buttonOf(dom, "pc-exchange-back").disabled));
  check("opening asks the owner's PC for one folder listing",
    browseCalls(dom.calls).length === 1
    && bodyOf(browseCalls(dom.calls)[0]).path === "."
    && !("link_id" in bodyOf(browseCalls(dom.calls)[0])),
    JSON.stringify(dom.calls));
  check("the entries the PC reported are shown by name",
    entriesOf(dom).map((node) => node.allText()).join("|").includes("1분기.md"),
    dialogOf(dom).allText());
  // The screen the owner is looking at while the PC works: still working, with the
  // time that has passed. Not a failure, not a technical state, not a give-up clock.
  check("while the PC is still answering, the dialog says so in the owner's words",
    duringWait.includes("PC에서 작업 중") && duringWait.includes("경과"), duringWait);
  check("the waiting line is the shipped copy, not a code name",
    duringWait.includes(copyOf("pc-exchange-working").split("{elapsed}")[0].trim())
    && !/dispatch|HTTP|path/i.test(duringWait), duringWait);

  buttonOf(dom, "pc-exchange-entry").click();
  await settle();
  check("a folder click asks again for that folder",
    browseCalls(dom.calls).length === 2
    && bodyOf(browseCalls(dom.calls)[1]).path === "견적",
    JSON.stringify(browseCalls(dom.calls).map((call) => call.body)));
  check("stepping into a folder re-enables 이전 폴더",
    buttonOf(dom, "pc-exchange-back").disabled === false,
    String(buttonOf(dom, "pc-exchange-back").disabled));

  buttonOf(dom, "pc-exchange-back").click();
  await settle();
  check("이전 폴더 asks the PC for the folder the owner came from",
    browseCalls(dom.calls).length === 3
    && bodyOf(browseCalls(dom.calls)[2]).path === "."
    && entriesOf(dom).some((node) => node.allText().includes("1분기.md")),
    JSON.stringify(browseCalls(dom.calls).map((call) => call.body)));
  check("back at the root, 이전 폴더 is disabled again",
    buttonOf(dom, "pc-exchange-back").disabled === true,
    String(buttonOf(dom, "pc-exchange-back").disabled));
  // Disabled also means quiet: a press at the root asks the PC for nothing.
  const browsesAtRoot = browseCalls(dom.calls).length;
  buttonOf(dom, "pc-exchange-back").click();
  await settle();
  check("a press on the disabled root 이전 폴더 asks the PC for nothing",
    browseCalls(dom.calls).length === browsesAtRoot,
    JSON.stringify(browseCalls(dom.calls).map((call) => call.body)));

  // ── searching by name: the sweep walks the folders and the list grows as it goes ──
  let duringSweep = -1;
  const search = makeDom({
    "/api/pc/browse": [staged()],
    "/api/pc/find": [staged(SWEEP_RUN), staged(SWEEP_RUN), staged(SWEEP_RUN)],
    "/api/pc/result": [
      working, listed,
      working, seeded,
      working, swept("견적서.xlsx", "C:/Users/qa/2026"),
      working, () => { duringSweep = entriesOf(search).length; return working(); },
      working, swept("명함.png", "C:/Users/qa/사진"),
      working, fetched,
    ],
    "/api/pc/fetch": [staged()],
  });
  let chosen = null;
  search.window.PadiemPcFileExchange.open({ onSelect: (item) => { chosen = item; } });
  await settle();
  const searchBox = search.body.find((node) => node.tagName === "INPUT");
  searchBox.value = "명함";
  buttonOf(search, "pc-exchange-search-button").click();
  await settle(60);
  const findCalls = search.calls.filter((call) => call.url === "/api/pc/find").map(bodyOf);
  check("the search is asked of the PC by name",
    findCalls.length > 0 && findCalls.every((call) => call.name === "명함"),
    JSON.stringify(findCalls));
  check("the first look is asked without naming a folder",
    findCalls[0].folder === undefined && findCalls[0].run_id === undefined,
    JSON.stringify(findCalls[0]));
  check("the sweep then asks one folder at a time inside the same operation",
    findCalls[1].folder === "C:/Users/qa/2026"
    && findCalls[2].folder === "C:/Users/qa/사진"
    && findCalls[1].run_id === findCalls[2].run_id
    && findCalls[1].run_id === SWEEP_RUN && findCalls[2].run_id === SWEEP_RUN,
    JSON.stringify(findCalls));
  check("the folder still waiting travels with the request",
    findCalls[1].remaining.length === 1 && findCalls[1].remaining[0] === "C:/Users/qa/사진"
    && findCalls[2].remaining.length === 0,
    JSON.stringify(findCalls));
  check("the matches of every folder looked through stay on the screen",
    entriesOf(search).length === 3
    && entriesOf(search).map((node) => node.allText()).join("|").includes("견적서.xlsx"),
    `rows=${entriesOf(search).length}`);
  // The whole point of dividing the search: the owner is never shown an empty screen
  // while the rest of the drive is still being looked through.
  check("part of the answer is shown while the next folder is still being searched",
    duringSweep === 2, `rows_while_sweeping=${duringSweep}`);
  check("the search ends in the owner's words, not a spinner",
    statusOf(search) === null
    || statusOf(search).allText() === copyOf("pc-exchange-searched"),
    statusOf(search) ? statusOf(search).allText() : "no status");
  check("a found file shows the folder it came from",
    entriesOf(search).map((node) => node.allText()).join("|").includes("C:/Users/qa/2026"),
    dialogOf(search).allText());

  entriesOf(search)[entriesOf(search).length - 1].click();
  buttonOf(search, "pc-exchange-pick").click();
  await settle();
  check("choosing a file asks the PC for that one file",
    search.calls.some((call) => call.url === "/api/pc/fetch"
      && bodyOf(call).path === "C:/Users/qa/사진/명함.png"),
    JSON.stringify(search.calls.map((call) => call.body)));
  check("the menu is handed the text and the addressable id",
    chosen && chosen.name === "명함.png" && chosen.kind === "text"
    && chosen.content === "본문입니다" && chosen.fileId === FETCHED,
    JSON.stringify(chosen));
  check("picking a file closes the dialog", !search.body.byClass("pc-exchange-dialog"), "");

  // ── several PCs: the owner is asked, never guessed for ──
  const many = makeDom({
    "/api/pc/browse": [{ status: 409, body: { ok: false, error: { code: "pc_link_selection_required" },
      links: [{ link_id: LINK_ONE, label: "사무실 PC" }, { link_id: LINK_TWO, label: "집 PC" }] } },
      staged()],
    "/api/pc/result": [working, listed],
  });
  many.window.PadiemPcFileExchange.open({ onSelect: () => {} });
  await settle();
  const pcs = stripOf(many);
  check("two PCs become a choice in the owner's own words",
    pcs && pcs.allText().includes("사무실 PC") && pcs.allText().includes("집 PC"),
    JSON.stringify(many.calls));
  check("the PC question is asked in the words the screen ships",
    pcs && pcs.getAttribute("aria-label") === copyOf("pc-exchange-choose-pc"),
    pcs && pcs.getAttribute("aria-label"));
  check("nothing is listed on a PC until the owner names one",
    browseCalls(many.calls).length === 1, JSON.stringify(many.calls));
  pcs.children[1].click();
  await settle();
  check("the chosen PC is the one the listing is asked of",
    browseCalls(many.calls).length === 2
    && bodyOf(browseCalls(many.calls)[1]).link_id === LINK_TWO,
    JSON.stringify(many.calls.map((call) => call.body)));

  // ── several folders on one PC: the owner names one, and nothing is guessed ──
  const drives = makeDom({
    "/api/pc/browse": [{ status: 409, body: {
      ok: false, error: { code: "pc_folder_selection_required" },
      folders: [{ label: "C:", path: "C:/" }, { label: "바탕화면", path: "바탕화면/" }],
    } }, staged()],
    "/api/pc/result": [working, listed],
  });
  drives.window.PadiemPcFileExchange.open({ onSelect: () => {} });
  await settle();
  const folderStrip = stripOf(drives);
  check("two folders on one PC become a choice the owner can read",
    folderStrip && folderStrip.allText().includes("C:") && folderStrip.allText().includes("바탕화면"),
    folderStrip ? folderStrip.allText() : "no folder strip");
  check("the folder question is asked in the words the screen ships",
    folderStrip && folderStrip.getAttribute("aria-label") === copyOf("pc-exchange-choose-folder"),
    folderStrip && folderStrip.getAttribute("aria-label"));
  check("no folder is opened until the owner names one",
    browseCalls(drives.calls).length === 1, JSON.stringify(drives.calls));
  folderStrip.children[1].click();
  await settle();
  check("the folder the owner named is the one the listing is asked of",
    browseCalls(drives.calls).length === 2
    && bodyOf(browseCalls(drives.calls)[1]).path === "바탕화면/"
    && entriesOf(drives).some((node) => node.allText().includes("1분기.md")),
    JSON.stringify(drives.calls.map((call) => call.body)));

  // ── saving back: the owner names the file, the PC answers with its own account ──
  const save = makeDom({
    "/api/pc/browse": [staged(), staged()],
    "/api/pc/result": [working, listed, working, listed, working, saved],
    "/api/pc/save": [staged()],
  });
  let written = null;
  save.window.PadiemPcFileExchange.open({
    mode: "save", content: "본문입니다", fileName: "축사.txt", onSave: (row) => { written = row; },
  });
  await settle();
  const naming = save.body.find((node) => node.className === "pc-exchange-filename");
  check("the save dialog asks for a name and never for a confirmation",
    dialogOf(save).allText().includes(copyOf("pc-exchange-save-title").trim())
    && naming && naming.value === "축사.txt"
    && !dialogOf(save).allText().includes("확인"),
    dialogOf(save).allText());
  check("the save dialog does not offer a search for a file to open",
    save.body.find((node) => node.className === "pc-exchange-search").hidden === true
    && save.body.find((node) => node.className === "pc-exchange-search-button").hidden === true,
    "search still offered");
  check("the folder list is still browsed when saving",
    entriesOf(save).some((node) => node.allText().includes("견적")), dialogOf(save).allText());

  entriesOf(save)[0].click();
  await settle();
  check("saving into a folder asks the PC for that folder",
    browseCalls(save.calls).length === 2
    && bodyOf(browseCalls(save.calls)[1]).path === "견적",
    JSON.stringify(save.calls.map((call) => call.body)));
  buttonOf(save, "pc-exchange-save").click();
  await settle();
  check("saving sends the name the owner wrote and the text the menu holds",
    save.calls.some((call) => call.url === "/api/pc/save"
      && bodyOf(call).path === "견적/축사.txt" && bodyOf(call).content === "본문입니다"),
    JSON.stringify(save.calls.map((call) => call.body)));
  check("the menu is handed the PC's own account of what it wrote",
    written && written.target === SAVED_TO && written.backup === "C:/.padiem-backup/2026-10-28/축사.txt",
    JSON.stringify(written));
  check("saving closes the dialog", !save.body.byClass("pc-exchange-dialog"), "");

  // ── a write the PC refused is told to the owner, not dressed up as saved ──
  const failed = makeDom({
    "/api/pc/browse": [staged()],
    "/api/pc/result": [working, listed, working, refused],
    "/api/pc/save": [staged()],
  });
  let savedAnyway = null;
  failed.window.PadiemPcFileExchange.open({
    mode: "save", content: "본문입니다", fileName: "축사.txt", onSave: () => { savedAnyway = true; },
  });
  await settle();
  buttonOf(failed, "pc-exchange-save").click();
  await settle();
  const failStatus = statusOf(failed);
  check("a refused write is told plainly and the menu is not told it saved",
    failStatus && failStatus.allText() === copyOf("pc-exchange-save-failed") && savedAnyway === null,
    failStatus ? failStatus.allText() : "no status");

  // ── 그만: the owner stops the sweep, and the folders not yet looked in are stopped ──
  let sweptAfterStop = -1;
  const stopping = makeDom({
    "/api/pc/browse": [staged()],
    "/api/pc/find": [staged(SWEEP_RUN), staged(SWEEP_RUN), staged(SWEEP_RUN)],
    "/api/pc/result": [
      working, listed,
      working, seeded,
      working, () => {
        buttonOf(stopping, "pc-exchange-stop").click();
        sweptAfterStop = stopping.calls.filter((call) => call.url === "/api/pc/find").length;
        return working();
      },
    ],
    "/api/pc/cancel": [cancelled],
  });
  stopping.window.PadiemPcFileExchange.open({ onSelect: () => {} });
  await settle();
  stopping.body.find((node) => node.tagName === "INPUT").value = "명함";
  buttonOf(stopping, "pc-exchange-search-button").click();
  await settle(40);
  const stoppedCalls = stopping.calls.filter((call) => call.url === "/api/pc/find").map(bodyOf);
  const cancelCalls = stopping.calls.filter((call) => call.url === "/api/pc/cancel").map(bodyOf);
  check("그만 cancels the search the owner started",
    cancelCalls.length === 1 && cancelCalls[0].run_id === SWEEP_RUN,
    JSON.stringify({ cancelCalls, stoppedCalls }));
  check("그만 asks for no folder after it",
    stoppedCalls.length === sweptAfterStop,
    `find calls=${stoppedCalls.length} at stop=${sweptAfterStop}`);
  check("그만 keeps what had already been found on the screen",
    entriesOf(stopping).some((node) => node.allText().includes("명함.png")),
    dialogOf(stopping).allText());
  const stoppedStatus = statusOf(stopping);
  check("그만 is told in the owner's own words and the dialog stays open",
    stoppedStatus && stoppedStatus.allText() === copyOf("pc-exchange-stopped")
    && stopping.window.PadiemPcFileExchange.isOpen() === true
    && stopping.window.PadiemPcFileExchange.current().sweeping === false,
    stoppedStatus ? stoppedStatus.allText() : "no status");

  // ── the search is not allowed to hold the PC: a listing goes between the folders ──
  const queue = makeDom({
    "/api/pc/browse": [staged(), staged(), staged()],
    "/api/pc/find": [staged(SWEEP_RUN), staged(SWEEP_RUN), staged(SWEEP_RUN)],
    "/api/pc/result": [
      working, listed,
      working, listed,
      working, seeded,
      working, () => {
        // The owner steps out of the folder while its first subtree is still being
        // looked through: that listing must be what the PC does next.
        buttonOf(queue, "pc-exchange-back").click();
        return working();
      },
      working, listed,
    ],
    "/api/pc/cancel": [cancelled],
  });
  queue.window.PadiemPcFileExchange.open({ onSelect: () => {} });
  await settle();
  buttonOf(queue, "pc-exchange-entry").click();          // into 견적
  await settle();
  queue.body.find((node) => node.tagName === "INPUT").value = "명함";
  buttonOf(queue, "pc-exchange-search-button").click();
  await settle(40);
  const queueBrowse = browseCalls(queue.calls).map(bodyOf);
  check("a folder listing asked during a search is asked of the PC at once",
    queueBrowse.length === 3 && queueBrowse[1].path === "견적"
    && queueBrowse[2].path === "."
    && bodyOf(queue.calls.filter((call) => call.url === "/api/pc/cancel")[0]).run_id === SWEEP_RUN
    && queue.calls.filter((call) => call.url === "/api/pc/cancel").length === 1
    && entriesOf(queue).some((node) => node.allText().includes("1분기.md")),
    JSON.stringify(queue.calls.map((call) => call.url)));
  check("the search that was stepped out of asks for no further folder",
    queue.calls.filter((call) => call.url === "/api/pc/find").length === 2,
    JSON.stringify(queue.calls.map((call) => call.url)));

  // ── no give-up: thirty rounds of "still working" is still working ──
  const slow = makeDom({
    "/api/pc/browse": [staged()],
    "/api/pc/result": Array.from({ length: 30 }, () => working).concat([listed]),
  });
  slow.window.PadiemPcFileExchange.open({ onSelect: () => {} });
  await settle(80);
  const polls = slow.calls.filter((call) => call.url.startsWith("/api/pc/result"));
  check("a PC that takes minutes is the same operation, not a failure",
    polls.length >= 30 && slow.window.PadiemPcFileExchange.isOpen() === true
    && entriesOf(slow).some((node) => node.allText().includes("견적")),
    `polls=${polls.length}`);

  // ── the screen splits the answer; it never shortens it ──
  const manyItems = Array.from({ length: 100 }, (_unused, index) => ({
    name: `파일 ${index}.md`, kind: "file", size_bytes: 10, modified_at: null,
  }));
  const wide = makeDom({
    "/api/pc/browse": [staged()],
    "/api/pc/result": [working, () => ({ status: 200, body: { ok: true, state: "ready", items: manyItems } })],
  });
  wide.window.PadiemPcFileExchange.open({ onSelect: () => {} });
  await settle();
  check("the first screen shows part of a long answer",
    entriesOf(wide).length === 60 && buttonOf(wide, "pc-exchange-more").hidden === false,
    `rows=${entriesOf(wide).length}`);
  buttonOf(wide, "pc-exchange-more").click();
  await settle();
  check("더 보기 shows the rest of the same answer",
    entriesOf(wide).length === 100, `rows=${entriesOf(wide).length}`);

  // ── a PC that answers nothing is said as such, in plain words ──
  const silent = makeDom({
    "/api/pc/browse": [staged()],
    "/api/pc/result": [working, { status: 410, body: { ok: false, error: { code: "pc_dispatch_expired" } } }],
  });
  silent.window.PadiemPcFileExchange.open({ onSelect: () => {} });
  await settle();
  const status = statusOf(silent);
  check("an operation the PC never answered is told to the owner plainly",
    status && status.allText() === copyOf("pc-exchange-no-answer")
    && !/코드|dispatch|HTTP|path/i.test(status.allText()),
    status && status.allText());

  // ── the part itself: one entry point, no jargon, no extra confirmation ──
  check("one function opens both halves of the part, and the copy carries no technical term",
    typeof makeDom({ "/api/pc/browse": [staged()], "/api/pc/result": [working] })
      .window.PadiemPcFileExchange.open === "function"
    && ["pc-exchange-import-title", "pc-exchange-import-note", "pc-exchange-save-title",
        "pc-exchange-save-note", "pc-exchange-save-name", "pc-exchange-save-button",
        "pc-exchange-choose-pc", "pc-exchange-choose-folder", "pc-exchange-up",
        "pc-exchange-search", "pc-exchange-more", "pc-exchange-close", "pc-exchange-open-file",
        "pc-exchange-working", "pc-exchange-no-pc", "pc-exchange-no-answer",
        "pc-exchange-save-failed"].every((key) => !/디스패치|라우트|JSON|HTTP|엔드포인트|path_relative|경로/i
          .test(copyOf(key))),
    "");
  check("the part asks for nothing but its own eight calls",
    JSON.stringify([...script.matchAll(/"\/api\/[a-z/_]+"/g)].map((m) => m[0]).sort()) ===
      JSON.stringify(['"/api/pc/browse"', '"/api/pc/cancel"', '"/api/pc/delete"',
                      '"/api/pc/fetch"', '"/api/pc/find"', '"/api/pc/move"',
                      '"/api/pc/result"', '"/api/pc/save"']),
    JSON.stringify([...script.matchAll(/"\/api\/[a-z/_]+"/g)].map((m) => m[0])));
  for (const forbidden of ["confirm(", "alert(", "setTimeout(fetch", "maxAttempts", "max_wait"]) {
    check(`the part contains no ${forbidden}`, !script.includes(forbidden), forbidden);
  }

  const failures = results.filter((row) => !row.ok);
  for (const row of results) {
    console.log(`PC_FILE_EXCHANGE_CHECK ${row.name} ${row.ok ? "PASS" : "FAIL " + row.detail}`);
  }
  console.log(failures.length ? "PC_FILE_EXCHANGE=FAIL" : "PC_FILE_EXCHANGE=PASS");
  process.exitCode = failures.length ? 1 : 0;
}

void main();
