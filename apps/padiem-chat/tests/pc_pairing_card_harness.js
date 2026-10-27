// #5573 PR-3 browser harness for pc-pairing-card.js, run by node from pytest.
// A minimal DOM and a scripted fetch: the module is exercised for real, and the
// assertions are the ones the owner's flow depends on — a code that never lands
// in a URL, a refusal that renders as a refusal, and one Windows sentence only.
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
  }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map((c) => c.textContent).join(""); }
  set id(value) { this.attrs.id = String(value); }
  get id() { return this.attrs.id || ""; }
  append(...nodes) { for (const n of nodes) if (n) this.children.push(n); }
  replaceChildren(...nodes) { this.children = []; this.text = ""; this.append(...nodes); }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
  click() {
    // An anchor with a download attribute is the browser's own file hand-off:
    // the harness records what was handed over instead of navigating.
    if (this.download) (globalThis.downloads ||= []).push({ name: this.download, url: this.href });
    for (const h of this.listeners.click || []) h({});
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
    const reply = (responses[`${(options?.method || "GET")} ${url}`]
      || responses[`${(options?.method || "GET")} *`] || { status: 500, body: {} });
    // A reply may carry `text` instead of a JSON body: the install file is a
    // file, and the card must treat it as one.
    const payload = typeof reply.text === "string"
      ? reply.text : JSON.stringify(reply.body ?? {});
    return {
      ok: reply.status >= 200 && reply.status < 300,
      status: reply.status,
      body: {
        getReader: () => {
          let sent = false;
          return {
            read: async () => (sent ? { done: true }
              : (sent = true, { done: false, value: new TextEncoder().encode(payload) })),
            cancel: async () => {},
          };
        },
      },
    };
  };
  const window = {addEventListener: () => {}, padiemPcPairing: undefined};
  let objectUrls = 0;
  const sandbox = {
    document, window, fetch: fetchImpl, calls,
    AbortController, TextDecoder, TextEncoder, setTimeout, clearTimeout,
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
  return { card, calls, downloads, blobs: globalThis.blobs, sandbox, document };
}

const LINK = {
  link_id: "pclink_0123456789abcdef0123456789abcdef",
  mesh_node_id: "node/domain/mesh-pc-09",
  label: "집 PC",
  state: "active",
  roots: [{ root_ref: "pcroot_0123456789abcdef", label: "견적", path: "C:/Users/me/견적",
            state: "active", approved_at: "2026-10-27T01:00:00Z" }],
};

const results = [];
const settle = async (rounds = 8) => {
  for (let index = 0; index < rounds; index += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
};
function check(name, condition, detail) {
  results.push({ name, ok: Boolean(condition), detail: condition ? "" : String(detail ?? "") });
}

async function main() {
  const scriptText = "# PADIEM PC 자동 연결\n$PairingTag = 'pd-1234abcd'\n";
  const issued = {
    "GET *": { status: 200, body: { ok: true, links: [], codes: [] } },
    "POST /api/pc/pairings": { status: 201, body: { ok: true, pairing: {
      code_id: "pcpair_abc", code: "K7QM2XTR9F4B", install_tag: "pd-1234abcd",
      expires_at: "2026-10-27T01:10:00Z" } } },
    "POST /api/pc/pairings/install-file": { status: 200, text: scriptText },
  };
  const first = makeDom(issued);
  const section = first.card.ids().find((n) => n.attrs.id === "pcPairingSection");
  check("section mounted inside the existing computer card", section);
  check("the primary offer is connect-this-PC",
    section.allText().includes("이 PC 연결") && section.allText().includes("Windows"),
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
  check("one click hands the install file to the browser",
    await first.sandbox.window.padiemPcPairing.connect() === true
    && first.downloads.length === 1
    && first.downloads[0].name === "padiem-pc-connect.ps1"
    && (first.blobs[first.downloads[0].url]?.parts || [""])[0] === scriptText,
    JSON.stringify(first.downloads));
  check("the download is said, not the code",
    section.allText().includes("설치 파일을 내려받았습니다")
    && !section.allText().includes("K7QM2XTR9F4B"), section.allText());
  check("the code never reaches a URL",
    first.calls.every((call) => !call.url.includes("K7QM2XTR9F4B")), JSON.stringify(first.calls));
  check("every call is the pairing surface",
    first.calls.every((call) => call.url.startsWith("/api/pc/pairings")), JSON.stringify(first.calls));

  const listed = makeDom({
    "GET *": { status: 200, body: { ok: true, links: [LINK], codes: [] } },
    [`DELETE /api/pc/pairings/${LINK.link_id}`]: { status: 200, body: { ok: true, revoked: true } },
    [`POST /api/pc/pairings/${LINK.link_id}/pause`]: { status: 200,
      body: { ok: true, link: { ...LINK, paused: true,
        paused_at: "2026-10-27T01:30:00Z" } } },
    [`POST /api/pc/pairings/${LINK.link_id}/resume`]: { status: 200,
      body: { ok: true, link: { ...LINK, paused: false, paused_at: null } } },
    [`POST /api/pc/pairings/${LINK.link_id}/roots`]: { status: 201, body: { ok: true,
      root: { root_ref: "pcroot_ffff0000ffff0000", label: "경리", path: "C:/Users/me/경리",
              state: "active", approved_at: "2026-10-27T01:20:00Z" } } },
  });
  await settle();
  const shown = listed.card.ids().find((n) => n.attrs.id === "pcPairingSection");
  check("the linked PC is listed with its folder",
    shown.allText().includes("집 PC") && shown.allText().includes("견적"), shown.allText());
  check("connected state is said", shown.allText().includes("연결됨"), shown.allText());
  const revoke = shown.ids().find((n) => (n.className || "") === "pc-pairing-revoke");
  revoke.click();
  await settle();
  check("revoke is a DELETE on the encoded link",
    listed.calls.some((call) => call.method === "DELETE"
      && call.url === "/api/pc/pairings/" + LINK.link_id), JSON.stringify(listed.calls));
  const add = shown.ids().find((n) => (n.className || "") === "pc-pairing-root-add");
  const field = shown.ids().find((n) => n.tagName === "INPUT");
  field.value = "C:/Users/me/경리";
  add.click();
  await settle();
  check("approval posts the path to the roots route",
    listed.calls.some((call) => call.method === "POST"
      && call.url === "/api/pc/pairings/" + LINK.link_id + "/roots"
      && JSON.parse(call.body).path === "C:/Users/me/경리"), JSON.stringify(listed.calls));

  // Re-read the row after the re-render the two calls above caused, then use the
  // pause controls the owner sees on every connected PC.
  const pauseButton = shown.ids().find((n) => (n.className || "") === "pc-pairing-pause");
  const resumeButton = shown.ids().find((n) => (n.className || "") === "pc-pairing-resume");
  const liveRevoke = shown.ids().find((n) => (n.className || "") === "pc-pairing-revoke");
  check("each linked PC carries pause, resume and disconnect controls",
    Boolean(pauseButton && resumeButton && liveRevoke), shown.allText());
  pauseButton.click();
  await settle();
  check("pause posts to that link's pause route",
    listed.calls.some((call) => call.method === "POST"
      && call.url === "/api/pc/pairings/" + LINK.link_id + "/pause"),
    JSON.stringify(listed.calls));
  resumeButton.click();
  await settle();
  check("resume posts to that link's resume route",
    listed.calls.some((call) => call.method === "POST"
      && call.url === "/api/pc/pairings/" + LINK.link_id + "/resume"),
    JSON.stringify(listed.calls));

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
  const refusedSection = refused.card.ids().find((n) => n.attrs.id === "pcPairingSection");
  refusedSection.ids().find((n) => (n.className || "") === "pc-pairing-revoke").click();
  await settle();
  check("a server refusal is said as a refusal",
    (refusedSection.status || refusedSection).allText().length > 0
    && refused.calls.some((call) => call.method === "DELETE"),
    JSON.stringify(refused.calls));

  const noFile = makeDom({
    "GET *": { status: 200, body: { ok: true, links: [], codes: [] } },
    "POST /api/pc/pairings/install-file": { status: 503,
      body: { ok: false, error: { code: "pc_pairing_install_url_missing" } } },
  });
  await settle();
  const waitingFile = noFile.card.ids().find((n) => n.attrs.id === "pcPairingSection");
  check("an unconfigured install link reads as 준비 중",
    await noFile.sandbox.window.padiemPcPairing.connect() === false
    && waitingFile.allText().includes("아직 준비 중")
    && noFile.downloads.length === 0, waitingFile.allText());

  const failures = results.filter((row) => !row.ok);
  for (const row of results) {
    console.log(`PC_PAIRING_CARD_CHECK ${row.name} ${row.ok ? "PASS" : "FAIL " + row.detail}`);
  }
  console.log(failures.length ? "PC_PAIRING_CARD=FAIL" : "PC_PAIRING_CARD=PASS");
  process.exitCode = failures.length ? 1 : 0;
}

void main();
