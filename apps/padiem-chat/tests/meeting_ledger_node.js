"use strict";
// #4647 meeting ledger browser behavior, executed against the real meeting-capture.js
// with a stub DOM and a recorded fetch. No network, no Drive call, no model call.
const assert = require("node:assert/strict");
const meeting = require("../static/meeting-capture.js");

class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = []; this.handlers = {}; this.attributes = {};
    this.textContent = ""; this.value = ""; this.className = "";
    this.hidden = false; this.disabled = false; this.checked = false;
    this.style = { display: "" };
    this.dataset = {};
    this.classList = { add() {}, remove() {}, contains: () => false };
  }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.children.push(node); return node; }
  replaceChildren(...nodes) { this.children = nodes; }
  remove() { this.removed = true; }
  focus() {}
  click() { const fn = this.handlers.click; if (fn) return fn({ target: this }); return undefined; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(kind, fn) { this.handlers[kind] = fn; }
  dispatchEvent() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
  get body() { return this; }
}

function harness() {
  const ids = {};
  const make = (tag, id) => { const el = new El(tag); if (id) el.id = id; ids[id] = el; return el; };
  const shell = new El("div");
  shell.dataset = {};
  const doc = {
    documentElement: { lang: "ko" },
    body: new El("body"),
    getElementById: (id) => (id in ids ? ids[id] : null),
    createElement: (tag) => new El(tag),
    createTextNode: (value) => { const node = new El("#text"); node.textContent = String(value); return node; },
    addEventListener() {},
    querySelector: (selector) => (selector === ".app-shell" ? shell : null),
  };
  for (const id of ["meetingNavButton", "meetingView", "meetingStatus", "meetingTranscript",
                    "meetingStart", "meetingStop", "meetingInterim", "meetingDownloadAudio",
                    "meetingDownloadText", "meetingDraftInClaw", "meetingSaveAudioDrive",
                    "meetingSaveTextDrive", "meetingRecordsList", "meetingRecordsEmpty",
                    "meetingRecordsStatus", "meetingRecordsDetail", "meetingTitleInput",
                    "meetingSaveTitle", "mobileMenu", "sidebarScrim", "clawNavButton",
                    "messageInput", "composerForm"]) make("div", id);
  make("radio", null);
  ids.meetingView.querySelectorAll = () => [];

  const requests = [];
  const responses = new Map();
  let confirmAnswer = true;
  const win = {
    document: doc,
    MediaRecorder: class { static isTypeSupported() { return true; } constructor() { this.state = "inactive"; } start() { this.state = "recording"; } stop() { this.state = "inactive"; this.ondataavailable?.({ data: new Blob(["audio-bytes"], { type: "audio/webm" }) }); this.onstop?.({}); } },
    SpeechRecognition: class { start() {} stop() { this.onend?.(); } abort() { this.onend?.(); } },
    navigator: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [] }) } },
    fetch: async (url, options) => {
      const key = options.method + " " + url;
      requests.push({ key, method: options.method, url,
        body: options.body === undefined ? null : JSON.parse(options.body),
        credentials: options.credentials, cache: options.cache });
      const canned = responses.get(key);
      if (canned) return canned;
      return { ok: true, status: 200, json: async () => responses.get("default")
        ? responses.get("default")(options) : { ok: true, meetings: [] } };
    },
    confirm: () => confirmAnswer,
    CustomEvent: class { constructor(name) { this.type = name; } },
    Event: class { constructor(name) { this.type = name; } },
    setTimeout: () => 0, clearTimeout: () => {}, URL: { createObjectURL: () => "blob:x", revokeObjectURL: () => {} },
    AbortController,
    addEventListener(kind, fn) { (this._listeners ||= {})[kind] = fn; },
    dispatchEvent() {},
  };
  const respond = (key, value) => responses.set(key, {
    ok: value.ok !== false, status: value.status || 200, json: async () => value,
  });
  const api = meeting.mount(win, doc);
  const signIn = () => win._listeners["padiem:auth-state"]({ detail: { authenticated: true } });
  // The page reads the checked mode with querySelector and disables the radios
  // with querySelectorAll, so both must be backed by one real element.
  const checked = new El("input");
  checked.name = "meetingMode";
  const setMode = (value) => {
    checked.value = value; checked.checked = true;
    ids.meetingView.querySelector = (selector) =>
      (String(selector).includes("meetingMode") && String(selector).includes(":checked") ? checked : null);
    ids.meetingView.querySelectorAll = (selector) =>
      (String(selector).includes("meetingMode") ? [checked] : []);
  };
  const flush = () => new Promise((resolve) => setImmediate(() => setImmediate(resolve)));
  return { api, doc, ids, win, requests, respond, setConfirm: (value) => { confirmAnswer = value; },
    signIn, setMode, flush, shell };
}

function check(condition, label) { assert.ok(condition, label); }

async function main() {
  // 1. Opening the page reads the ledger for the signed-in owner only.
  const h = harness();
  h.signIn();
  h.ids.meetingNavButton.click();
  await h.flush();
  check(h.requests.some((r) => r.key === "GET /api/claw/meetings"), "records load on open");

  // 2. Starting a meeting creates exactly one record; the body is title + mode only.
  h.ids.meetingTitleInput.value = "10월 운영 회의";
  h.setMode("record");
  h.respond("POST /api/claw/meetings", { ok: true, meeting: { meeting_ref: "mtg_" + "a".repeat(32) } });
  h.ids.meetingStart.click();
  await h.flush();
  const created = h.requests.filter((r) => r.method === "POST" && r.url === "/api/claw/meetings");
  check(created.length === 1, "exactly one meeting create");
  assert.deepEqual(Object.keys(created[0].body).sort(), ["mode", "title"]);
  check(created[0].body.mode === "record", "mode recorded");
  check(created[0].credentials === "same-origin" && created[0].cache === "no-store",
    "ledger calls stay same-origin and uncacheable");
  check(h.shell.dataset.state === "meeting", "central view opens, no modal");

  // 3. Stopping records the end state exactly once.
  h.respond("POST /api/claw/meetings/mtg_" + "a".repeat(32) + "/end", { ok: true, meeting: {} });
  h.ids.meetingStop.click();
  await h.flush();
  const ends = h.requests.filter((r) => r.url.endsWith("/end"));
  check(ends.length === 1, "one end call after stop");

  // 4. A real Drive receipt is stored as an artifact reference, never as content.
  const ref = "mtg_" + "a".repeat(32);
  h.respond("POST /api/claw/meetings/" + ref + "/artifacts", { ok: true, artifact: {} });
  h.win.PadiemMeetingDriveUpload = { upload: async () => ({ fileId: "Dr1vF1leId0000000", name: "padiem-meeting.txt" }) };
  h.ids.meetingTranscript.value = "김길동: 예산을 승인합니다.";
  h.ids.meetingSaveTextDrive.click();
  await h.flush();
  const artifacts = h.requests.filter((r) => r.url.endsWith("/artifacts"));
  check(artifacts.length === 1, "one artifact receipt after a real Drive success");
  // The receipt must attach to the meeting that was started and ended above,
  // not to a fresh one: the Drive save happens after the meeting has ended.
  check(artifacts[0].url === "/api/claw/meetings/" + ref + "/artifacts",
    "post-stop Drive receipt still belongs to the ended meeting");
  check(ends[0].url === "/api/claw/meetings/" + ref + "/end", "same meeting ended once");
  assert.deepEqual(Object.keys(artifacts[0].body).sort(),
    ["byte_size", "drive_file_id", "filename", "kind", "mime_type", "state"]);
  assert.equal(artifacts[0].body.kind, "transcript");
  assert.equal(artifacts[0].body.state, "drive_saved");
  assert.equal(artifacts[0].body.drive_file_id, "Dr1vF1leId0000000");
  check(!JSON.stringify(artifacts[0].body).includes("예산"), "transcript text never enters the ledger");
  check(!("workspace_id" in artifacts[0].body) && !("user_id" in artifacts[0].body),
    "no browser-supplied owner or workspace");

  // 5. A failed Drive upload must not fabricate a saved reference.
  const h2 = harness();
  h2.signIn();
  h2.respond("POST /api/claw/meetings", { ok: true, meeting: { meeting_ref: "mtg_" + "b".repeat(32) } });
  h2.setMode("both");
  h2.ids.meetingStart.click();
  await h2.flush();
  h2.win.PadiemMeetingDriveUpload = { upload: async () => { const e = new Error("no"); e.code = "drive_write_unavailable"; throw e; } };
  h2.ids.meetingTranscript.value = "전사 내용";
  h2.ids.meetingSaveTextDrive.click();
  await h2.flush();
  check(!h2.requests.some((r) => r.url.endsWith("/artifacts")), "no artifact row for a failed upload");

  // 6. Ledger outage cannot stop or fake a recording.
  const h3 = harness();
  h3.signIn();
  h3.respond("POST /api/claw/meetings", { ok: false, status: 503, error: { code: "meeting_records_unavailable" } });
  h3.setMode("record");
  h3.ids.meetingTitleInput.value = "기록 불가 상황";
  h3.ids.meetingStart.click();
  await h3.flush();
  check(h3.api.controller.snapshot().active === true, "recording continues when the ledger is down");
  check(h3.ids.meetingRecordsStatus.textContent.includes("녹음 자체는 계속됩니다"),
    "ledger failure is stated truthfully");
  h3.ids.meetingStop.click();
  await h3.flush();
  check(!h3.requests.some((r) => r.url.endsWith("/end")), "no end call for a meeting that was never recorded");

  // 7. Deletion asks the truthful question and refuses to claim Drive deletion.
  const h4 = harness();
  h4.signIn();
  h4.respond("GET /api/claw/meetings", { ok: true, meetings: [
    { meeting_ref: "mtg_" + "c".repeat(32), title: "정기 회의", mode: "record",
      status: "ended", started_at: null, ended_at: "2026-10-18T01:00:00+00:00",
      created_at: "x", updated_at: "y" }] });
  h4.ids.meetingNavButton.click();
  await new Promise((resolve) => setImmediate(resolve));
  const row = h4.ids.meetingRecordsList.children[0];
  check(row && row.children.length === 2, "one open action and one delete action per record");
  let asked = "";
  h4.win.confirm = (message) => { asked = message; return false; };
  row.children[1].click();
  await new Promise((resolve) => setImmediate(resolve));
  check(asked.includes("Google Drive") && asked.includes("삭제되지"), "confirm states Drive files survive");
  check(!h4.requests.some((r) => r.method === "DELETE"), "declined confirm sends no delete");

  asked = "";
  h4.win.confirm = (message) => { asked = message; return true; };
  h4.respond("DELETE /api/claw/meetings/mtg_" + "c".repeat(32),
    { ok: true, record_deleted: true, drive_files_deleted: false });
  row.children[1].click();
  await new Promise((resolve) => setImmediate(resolve));
  check(h4.requests.some((r) => r.method === "DELETE"), "accepted confirm deletes the record");
  check(h4.ids.meetingRecordsStatus.textContent.includes("Drive에 남아"), "success note keeps the Drive boundary");

  // A forged "drive deleted" answer must not be presented as success.
  const h5 = harness();
  h5.signIn();
  h5.respond("GET /api/claw/meetings", { ok: true, meetings: [
    { meeting_ref: "mtg_" + "d".repeat(32), title: "조작 응답", mode: "both", status: "ended",
      ended_at: null, created_at: "x", updated_at: "y" }] });
  h5.ids.meetingNavButton.click();
  await new Promise((resolve) => setImmediate(resolve));
  h5.win.confirm = () => true;
  h5.respond("DELETE /api/claw/meetings/mtg_" + "d".repeat(32),
    { ok: true, record_deleted: true, drive_files_deleted: true });
  h5.ids.meetingRecordsList.children[0].children[1].click();
  await new Promise((resolve) => setImmediate(resolve));
  check(h5.ids.meetingRecordsStatus.textContent.includes("삭제하지 못했습니다"),
    "an over-claiming response is refused, not displayed as success");

  // 8. Detail view links only real Drive files and says local-only for the rest.
  const h6 = harness();
  h6.signIn();
  const ref6 = "mtg_" + "e".repeat(32);
  h6.respond("GET /api/claw/meetings", { ok: true, meetings: [
    { meeting_ref: ref6, title: "혼합 저장", mode: "both", status: "ended", ended_at: "z",
      created_at: "x", updated_at: "y" }] });
  h6.respond("GET /api/claw/meetings/" + ref6, { ok: true,
    meeting: { meeting_ref: ref6, title: "혼합 저장", mode: "both", status: "ended" },
    artifacts: [
      { kind: "audio", state: "drive_saved", drive_file_id: "Dr1vF1leId0000000", filename: "a.webm" },
      { kind: "transcript", state: "local_only", drive_file_id: null, filename: "t.txt" }],
    actions: [{ kind: "decision", summary: "예산 승인", owner_label: "김담당",
      due_date: "2026-10-23", status: "candidate" }] });
  h6.ids.meetingNavButton.click();
  await new Promise((resolve) => setImmediate(resolve));
  h6.ids.meetingRecordsList.children[0].children[0].click();
  await new Promise((resolve) => setImmediate(resolve));
  const detailText = h6.ids.meetingRecordsDetail.children.map((n) => n.textContent).join(" | ");
  check(detailText.includes("이 기기에만 있음"), "local-only artifact is stated as local only");
  check(detailText.includes("후보: ") || detailText.includes("결정: 예산 승인 · 김담당"),
    "decision candidate shows owner and candidate state");
  const link = h6.ids.meetingRecordsDetail.children[1].children[1];
  check(link.href.includes("drive.google.com/file/d/Dr1vF1leId0000000/view"),
    "saved Drive file is addressed by its real id");
  check(link.rel === "noopener noreferrer" && link.target === "_blank", "external link hardening");

  console.log("MEETING_LEDGER_CREATE_END_RECEIPT=PASS");
  console.log("MEETING_LEDGER_NO_CONTENT_OR_SCOPE=PASS");
  console.log("MEETING_LEDGER_OUTAGE_KEEPS_CAPTURE=PASS");
  console.log("MEETING_LEDGER_DELETE_BOUNDARY=PASS");
  console.log("MEETING_LEDGER_DETAIL_TRUTHFUL_STATES=PASS");
}

main().catch((error) => { console.error(error && error.stack || error); process.exitCode = 1; });
