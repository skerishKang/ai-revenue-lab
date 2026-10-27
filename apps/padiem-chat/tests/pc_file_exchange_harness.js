// #5895 browser harness for pc-file-exchange.js, run by node from pytest.
//
// A minimal DOM and a scripted fetch: the shipped module is exercised for real, and
// the checks are the ones the owner's flow depends on — the dialog opens with the
// owner's own folder, a folder click goes back to the server, a search is addressed by
// name, the chosen file arrives as text or as a file, several PCs are asked about
// instead of guessed, and a PC that takes thirty rounds of polling is still simply
// working.
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
    // part is still waiting, before the next answer arrives.
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
    setInterval: () => 1,
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

const LINK_ONE = "pclink_" + "1".repeat(32);
const LINK_TWO = "pclink_" + "2".repeat(32);
const DISPATCH = "dsp_" + "a".repeat(32);

const working = { status: 200, body: { ok: true, state: "working", dispatch_id: DISPATCH, poll_seconds: 0.001 } };
const staged = (kind) => ({ status: 200, body: {
  ok: true, state: "working", dispatch_id: DISPATCH, run_id: "chat_pcq_" + "b".repeat(32),
  conversation_id: "chat_" + "c".repeat(32), poll_seconds: 0.001, kind,
} });
const listed = { status: 200, body: { ok: true, state: "ready", dispatch_id: DISPATCH, items: [
  { name: "견적", kind: "folder", size_bytes: null, modified_at: "2026-10-01T00:00:00Z" },
  { name: "1분기.md", kind: "file", size_bytes: 2048, modified_at: "2026-10-02T00:00:00Z" },
] } };
const found = { status: 200, body: { ok: true, state: "ready", dispatch_id: DISPATCH, found: [
  { name: "명함.png", kind: "file", size_bytes: 100, folder: "D:/그림", path: "D:/그림/명함.png" },
] } };
const fetched = { status: 200, body: { ok: true, state: "ready", dispatch_id: DISPATCH,
  content_kind: "text", content: "본문입니다", file_id: DISPATCH, size_bytes: 12 } };

const results = [];
const settle = async (rounds = 20) => {
  for (let index = 0; index < rounds; index += 1) await new Promise((resolve) => setImmediate(resolve));
};
function check(name, condition, detail) {
  results.push({ name, ok: Boolean(condition), detail: condition ? "" : String(detail ?? "") });
}
const browseCalls = (calls) => calls.filter((call) => call.url === "/api/pc/browse");
const dialogOf = (dom) => dom.body.byClass("pc-exchange-dialog");
const entriesOf = (dom) => dom.body.allWithClass("pc-exchange-entry");
const buttonOf = (dom, className) => dom.body.find((node) => node.className === className);

async function main() {
  // ── one PC: the dialog opens on the owner's own folder, then drills in ──
  const dom = makeDom({
    "/api/pc/browse": [staged("browse"), staged("browse"), staged("browse")],
    "/api/pc/result": [
      working,
      () => { duringWait = dialogOf(dom).allText(); return working; },
      listed,
    ],
  });
  let picked = null;
  dom.window.PadiemPcFileExchange.open({ onSelect: (item) => { picked = item; } });
  await settle();
  check("opening asks the owner's PC for one folder listing",
    browseCalls(dom.calls).length === 1
    && JSON.parse(browseCalls(dom.calls)[0].body).path === "."
    && !("link_id" in JSON.parse(browseCalls(dom.calls)[0].body)),
    JSON.stringify(dom.calls));
  check("the entries the PC reported are shown by name",
    entriesOf(dom).map((node) => node.allText()).join("|").includes("1분기.md"),
    dialogOf(dom).allText());
  // The screen the owner is looking at while the PC works: still working, with the
  // time that has passed. Not a failure, not a technical state, not a deadline.
  let duringWait = "";
  const waiting = makeDom({
    "/api/pc/browse": [staged("browse")],
    "/api/pc/result": [
      working,
      () => { duringWait = dialogOf(waiting).allText(); return working; },
      listed,
    ],
  });
  waiting.window.PadiemPcFileExchange.open({ onSelect: () => {} });
  await settle();
  check("while the PC is still answering, the dialog says so in the owner's words",
    duringWait.includes("PC에서 작업 중") && duringWait.includes("경과"), duringWait);
  check("the waiting line is the shipped copy, not a code name",
    duringWait.includes(copyOf("pc-exchange-working").split("{elapsed}")[0].trim())
    && !/dispatch|HTTP|path/i.test(duringWait), duringWait);

  buttonOf(dom, "pc-exchange-entry").click();
  await settle();
  check("a folder click asks again for that folder",
    browseCalls(dom.calls).length === 2
    && JSON.parse(browseCalls(dom.calls)[1].body).path === "견적",
    JSON.stringify(browseCalls(dom.calls).map((call) => call.body)));

  buttonOf(dom, "pc-exchange-back").click();
  await settle();
  check("이전 폴더 asks the PC for the folder the owner came from",
    browseCalls(dom.calls).length === 3
    && JSON.parse(browseCalls(dom.calls)[2].body).path === "."
    && entriesOf(dom).some((node) => node.allText().includes("1분기.md")),
    JSON.stringify(browseCalls(dom.calls).map((call) => call.body)));

  // ── searching by name, then choosing a file ──
  const search = makeDom({
    "/api/pc/browse": [staged("browse")],
    "/api/pc/find": [staged("find")],
    "/api/pc/result": [working, listed, working, found, working, fetched],
    "/api/pc/fetch": [staged("fetch")],
  });
  let chosen = null;
  search.window.PadiemPcFileExchange.open({ onSelect: (item) => { chosen = item; } });
  await settle();
  const searchBox = search.body.find((node) => node.tagName === "INPUT");
  searchBox.value = "명함";
  buttonOf(search, "pc-exchange-search-button").click();
  await settle();
  check("the search is asked of the PC by name",
    search.calls.some((call) => call.url === "/api/pc/find"
      && JSON.parse(call.body).name === "명함"),
    JSON.stringify(search.calls.map((call) => call.url)));
  check("a found file shows the folder it came from",
    entriesOf(search).map((node) => node.allText()).join("|").includes("D:/그림"),
    dialogOf(search).allText());

  entriesOf(search)[0].click();
  buttonOf(search, "pc-exchange-pick").click();
  await settle();
  check("choosing a file asks the PC for that one file",
    search.calls.some((call) => call.url === "/api/pc/fetch"
      && JSON.parse(call.body).path === "D:/그림/명함.png"),
    JSON.stringify(search.calls.map((call) => call.body)));
  check("the menu is handed the text and the addressable id",
    chosen && chosen.name === "명함.png" && chosen.kind === "text"
    && chosen.content === "본문입니다" && chosen.fileId === DISPATCH,
    JSON.stringify(chosen));
  check("picking a file closes the dialog",
    !search.body.byClass("pc-exchange-dialog"), "");

  // ── several PCs: the owner is asked, never guessed for ──
  const many = makeDom({
    "/api/pc/browse": [{ status: 409, body: { ok: false, error: { code: "pc_link_selection_required" },
      links: [{ link_id: LINK_ONE, label: "사무실 PC" }, { link_id: LINK_TWO, label: "집 PC" }] } },
      staged("browse")],
    "/api/pc/result": [working, listed],
  });
  many.window.PadiemPcFileExchange.open({ onSelect: () => {} });
  await settle();
  const pcs = many.body.find((node) => node.className === "pc-exchange-pcs" && !node.hidden);
  check("two PCs become a choice in the owner's own words",
    pcs && pcs.allText().includes("사무실 PC") && pcs.allText().includes("집 PC"),
    JSON.stringify(many.calls));
  check("nothing is listed on a PC until the owner names one",
    browseCalls(many.calls).length === 1, JSON.stringify(many.calls));
  pcs.children[1].click();
  await settle();
  check("the chosen PC is the one the listing is asked of",
    browseCalls(many.calls).length === 2
    && JSON.parse(browseCalls(many.calls)[1].body).link_id === LINK_TWO,
    JSON.stringify(many.calls.map((call) => call.body)));

  // ── several folders on one PC: the owner names one, and nothing is guessed ──
  const drives = makeDom({
    "/api/pc/browse": [{ status: 409, body: {
      ok: false, error: { code: "pc_folder_selection_required" },
      folders: [{ label: "C:", path: "C:/" }, { label: "바탕화면", path: "바탕화면/" }],
    } }, staged("browse")],
    "/api/pc/result": [working, listed],
  });
  drives.window.PadiemPcFileExchange.open({ onSelect: () => {} });
  await settle();
  const folderStrip = drives.body.find((node) => node.className === "pc-exchange-pcs" && !node.hidden);
  check("two folders on one PC become a choice the owner can read",
    folderStrip && folderStrip.allText().includes("C:") && folderStrip.allText().includes("바탕화면"),
    folderStrip ? folderStrip.allText() : "no folder strip");
  check("no folder is opened until the owner names one",
    browseCalls(drives.calls).length === 1, JSON.stringify(drives.calls));
  folderStrip.children[1].click();
  await settle();
  check("the folder the owner named is the one the listing is asked of",
    browseCalls(drives.calls).length === 2
    && JSON.parse(browseCalls(drives.calls)[1].body).path === "바탕화면/"
    && entriesOf(drives).some((node) => node.allText().includes("1분기.md")),
    JSON.stringify(drives.calls.map((call) => call.body)));

  // ── no give-up: thirty rounds of "still working" is still working ──
  const slow = makeDom({
    "/api/pc/browse": [staged("browse")],
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
    "/api/pc/browse": [staged("browse")],
    "/api/pc/result": [working, { status: 200, body: { ok: true, state: "ready", dispatch_id: DISPATCH, items: manyItems } }],
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
    "/api/pc/browse": [staged("browse")],
    "/api/pc/result": [working, { status: 410, body: { ok: false, error: { code: "pc_dispatch_expired" } } }],
  });
  silent.window.PadiemPcFileExchange.open({ onSelect: () => {} });
  await settle();
  const status = silent.body.find((node) => node.className === "pc-exchange-status" && !node.hidden);
  check("an operation the PC never answered is told to the owner plainly",
    status && status.allText() === copyOf("pc-exchange-no-answer")
    && !/코드|dispatch|HTTP|path/i.test(status.allText()),
    status && status.allText());

  // ── the part itself: one entry point, no jargon, no extra confirmation ──
  check("one function opens the part, and the copy carries no technical term",
    typeof makeDom({ "/api/pc/browse": [staged("browse")], "/api/pc/result": [working] })
      .window.PadiemPcFileExchange.open === "function"
    && !/디스패치|라우트|JSON|HTTP|엔드포인트|path_relative/i.test(
      ["pc-exchange-import-title", "pc-exchange-import-note", "pc-exchange-choose-pc",
       "pc-exchange-up", "pc-exchange-search", "pc-exchange-more", "pc-exchange-close",
       "pc-exchange-open-file", "pc-exchange-working", "pc-exchange-no-pc",
       "pc-exchange-no-answer"].map(copyOf).join(" "),
    ), "");
  check("the part asks for nothing but its own four calls",
    JSON.stringify([...script.matchAll(/"\/api\/[a-z/_]+"/g)].map((m) => m[0])) ===
      JSON.stringify(['"/api/pc/browse"', '"/api/pc/find"', '"/api/pc/fetch"', '"/api/pc/result"']),
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
