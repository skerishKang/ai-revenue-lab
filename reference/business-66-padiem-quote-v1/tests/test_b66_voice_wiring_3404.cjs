/* #3404: B66 "한번에 말하기" 음성 wiring 단위 테스트
 *
 * 실제 마이크·음성 합성·서버 호출은 사용하지 않는다. fetch/DOM/MediaRecorder만
 * 스텁해서 STT 게이트, Mode A(전사→입력창), Mode B(정확히 1회 자동 전송)를 검증한다.
 *
 * 두 가지 MediaRecorder 타이밍을 모두 검증한다:
 *   sync  - ondataavailable/onstop이 동기로 호출되는 단순 fake
 *   async - 실제 브라우저처럼 ondataavailable/onstop/FileReader/fetch가 모두
 *           stop() 반환 이후에 도착하는 fake
 * async 쪽이 #3404 회귀를 잡는다: 마이크를 끈 뒤 도착하는 최종 전사가
 * 입력창에 반영되어야 한다.
 */
"use strict";

const TRANSCRIPT = "테스트 전사문입니다";
const IDENTITY_KEY = "test-key-1";

let wiredModule = null;
function loadModule() {
  if (!wiredModule) wiredModule = require("../b66-voice-wiring.js");
  return wiredModule;
}

/* ---------- 가짜 DOM ---------- */
function makeEl(tag, doc) {
  const el = {
    tagName: String(tag).toUpperCase(),
    id: "",
    _attrs: Object.create(null),
    _listeners: Object.create(null),
    _text: "",
    _value: "",
    disabled: false,
    parentNode: null,
    nextSibling: null,
    children: [],
    setAttribute(k, v) { this._attrs[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null; },
    addEventListener(name, fn) { (this._listeners[name] = this._listeners[name] || []).push(fn); },
    removeEventListener(name, fn) {
      const arr = this._listeners[name];
      if (!arr) return;
      const i = arr.indexOf(fn);
      if (i >= 0) arr.splice(i, 1);
    },
    insertBefore(child, ref) {
      const idx = ref ? this.children.indexOf(ref) : -1;
      if (idx >= 0) this.children.splice(idx, 0, child); else this.children.push(child);
      child.parentNode = this;
      if (child.id && doc) doc._els.set(child.id, child);
      const pos = this.children.indexOf(child);
      child.nextSibling = this.children[pos + 1] || null;
      return child;
    },
    removeChild(child) {
      const i = this.children.indexOf(child);
      if (i >= 0) this.children.splice(i, 1);
      child.parentNode = null;
      if (child.id && doc) doc._els.delete(child.id);
      return child;
    },
    dispatchEvent() { return true; },
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); },
    get value() { return this._value; },
    set value(v) { this._value = String(v); },
    click() {
      if (this.disabled) return; // 실제 브라우저는 disabled 버튼의 click 핸들러를 호출하지 않는다.
      (this._listeners.click || []).slice().forEach((fn) => fn());
    },
  };
  return el;
}

function makeDoc() {
  const doc = {
    readyState: "complete",
    documentElement: { lang: "ko" },
    hidden: false,
    _els: new Map(),
    getElementById(id) { return this._els.get(id) || null; },
    querySelector() { return null; },
    createElement(tag) { return makeEl(tag, doc); },
    addEventListener() {},
    removeEventListener() {},
  };
  doc.body = makeEl("div", doc);
  ["easyVoiceMic", "easyComposer", "easySend", "easyComposerNote"].forEach((id) => {
    const el = makeEl(id === "easyComposer" ? "textarea" : "div", doc);
    el.id = id;
    el.parentNode = doc.body;
    el.disabled = true;
    doc._els.set(id, el);
    doc.body.children.push(el);
  });
  return doc;
}

/* ---------- 가짜 브라우저 API ---------- */
function FakeBlob(parts, opts) {
  this.parts = parts || [];
  this.type = (opts && opts.type) || "";
  this.size = this.parts.length ? 1 : 0;
}
function FakeFileReader(timing) {
  this.onload = null;
  this.onerror = null;
  this.result = null;
  const self = this;
  this.readAsDataURL = function () {
    const finish = function () {
      self.result = "data:audio/webm;base64,YXVkaW8=";
      if (self.onload) self.onload();
    };
    if (timing === "async") setTimeout(finish, 3); else finish();
  };
}
function FakeAudioContext() {
  this.createMediaStreamSource = function () { return { connect: function () {} }; };
  this.createAnalyser = function () {
    return { fftSize: 1024, getFloatTimeDomainData: function (buf) { for (let i = 0; i < buf.length; i += 1) buf[i] = 0; } };
  };
  this.close = function () {};
}
function makeMediaRecorder(timing, opts, env) {
  opts = opts || {};
  return function FakeMediaRecorder() {
    const rec = this;
    this.state = "inactive";
    this.ondataavailable = null;
    this.onstop = null;
    this.startCalls = 0;
    this.chunksSent = 0;
    // stop() 호출 시점의 상태를 그대로 기록해 #3404 진단 항목을 직접 검증한다.
    this.probe = { chunksAtStop: 0, requestDataCalls: 0, onstopCalls: 0, flushedOnStop: false };
    const deliver = function (blob) {
      rec.chunksSent += 1;
      if (rec.ondataavailable) rec.ondataavailable({ data: blob });
    };
    this.start = function () {
      rec.startCalls += 1;
      rec.state = "recording";
      if (timing === "async") setTimeout(function () { if (opts.emitChunks !== false) deliver(new FakeBlob(["chunk"], { type: "audio/webm" })); }, 5);
      else if (opts.emitChunks !== false) deliver(new FakeBlob(["chunk"], { type: "audio/webm" }));
    };
    this.requestData = function () {
      if (rec.state === "inactive") return;
      rec.probe.requestDataCalls += 1;
      if (timing === "async") setTimeout(function () { if (opts.emitChunks !== false) deliver(new FakeBlob(["chunk"], { type: "audio/webm" })); }, 5);
      else if (opts.emitChunks !== false) deliver(new FakeBlob(["chunk"], { type: "audio/webm" }));
    };
    this.stop = function () {
      rec.probe.chunksAtStop = rec.chunksSent;
      rec.state = "inactive";
      const finish = function () { rec.probe.onstopCalls += 1; if (rec.onstop) rec.onstop(); };
      if (timing === "async") setTimeout(finish, 15); else finish();
    };
    if (env.recorders) env.recorders.push(rec);
  };
}

function makeEnv(config) {
  const cfg = config || {};
  const timing = cfg.timing === "async" ? "async" : "sync";
  const doc = makeDoc();
  const fetchCalls = [];
  const mic = doc.getElementById("easyVoiceMic");
  const composer = doc.getElementById("easyComposer");
  const send = doc.getElementById("easySend");
  let sendClickedCount = 0;
  send.addEventListener("click", function () { sendClickedCount += 1; });

  const fetchImpl = function (url, init) {
    fetchCalls.push({ url: url, init: init });
    const path = typeof url === "string" ? url : (url && url.pathname) || url;
    const respond = function (resolve) {
      if (path === "/api/padiem/voice/identity") {
        const status = cfg.identityStatus || 200;
        const body = status === 200 ? { identity_key: cfg.identityKey || IDENTITY_KEY } : { error: { code: "unauthenticated" } };
        resolve(new Response(JSON.stringify(body), { status: status, headers: { "content-type": "application/json" } }));
        return;
      }
      if (path === "/api/padiem/voice/transcribe") {
        let utteranceId = null;
        try { utteranceId = JSON.parse(init.body || "{}").utterance_id; } catch (e) {}
        resolve(new Response(JSON.stringify({ text: TRANSCRIPT, utterance_id: utteranceId }), { status: 200, headers: { "content-type": "application/json" } }));
        return;
      }
      resolve(new Response(JSON.stringify({ ok: false }), { status: 404, headers: { "content-type": "application/json" } }));
    };
    return new Promise(function (resolve) {
      if (timing === "async") setTimeout(function () { respond(resolve); }, 10);
      else respond(resolve);
    });
  };

  const env = {
    doc: doc, fetchCalls: fetchCalls, recorders: [], timing: timing,
  };

  const win = {
    document: doc,
    fetch: fetchImpl,
    navigator: { mediaDevices: { getUserMedia: async function () { return { getTracks: function () { return []; } }; } } },
    MediaRecorder: makeMediaRecorder(timing, { emitChunks: cfg.emitChunks !== false }, env),
    AudioContext: FakeAudioContext,
    Blob: FakeBlob,
    AbortController: function () { this.signal = { aborted: false }; this.abort = function () { this.signal.aborted = true; }; },
    Event: function (type) { this.type = type; },
    CustomEvent: function (type, init) { this.type = type; this.detail = (init && init.detail) || null; },
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    requestAnimationFrame: function (fn) { return setTimeout(fn, 16); },
    cancelAnimationFrame: function (id) { clearTimeout(id); },
    dispatchEvent: function () { return true; },
  };
  if (win.MediaRecorder) win.MediaRecorder.isTypeSupported = function () { return true; };

  env.win = win;
  env.mic = mic;
  env.composer = composer;
  env.send = send;
  env.sendCount = function () { return sendClickedCount; };
  env.transcribeCalls = function () { return fetchCalls.filter(function (c) { return c.url === "/api/padiem/voice/transcribe"; }); };
  return env;
}

/* 모듈은 전역 document 없이 로드해야 autoInit가 중복 초기화하지 않는다. */
loadModule();

async function waitFor(predicate, label, timeoutMs) {
  const limit = typeof timeoutMs === "number" ? timeoutMs : 1500;
  const startedAt = Date.now();
  while (Date.now() - startedAt < limit) {
    if (predicate()) return true;
    await sleep(5);
  }
  throw new Error("TIMEOUT: " + label);
}
function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
function assert(cond, msg) {
  if (!cond) throw new Error("ASSERT FAILED: " + msg);
  console.log("ok - " + msg);
}

async function startWiring(env) {
  globalThis.document = env.doc;
  globalThis.FileReader = function () { FakeFileReader.call(this, env.timing); };
  const wiring = loadModule().createB66VoiceWiring({ win: env.win, doc: env.doc });
  if (!wiring) throw new Error("wiring 생성 실패");
  return wiring;
}

/* ---------- 시나리오 ---------- */
async function scenarioModeA(env) {
  const wiring = await startWiring(env);
  assert(env.mic.disabled === true, "[" + env.timing + "] 신원 확인 전: 마이크 비활성");
  await waitFor(function () { return env.mic.disabled === false; }, "STT 게이트 개방");
  assert(env.mic.disabled === false, "[" + env.timing + "] 신원 확인 후: 마이크 활성");
  assert(wiring.getState().sttAvailable === true, "[" + env.timing + "] sttAvailable=true");

  const liveToggle = env.doc.getElementById("easyVoiceLiveToggle");
  assert(!!liveToggle, "[" + env.timing + "] 라이브 토글 버튼 존재");
  assert(liveToggle.disabled === false, "[" + env.timing + "] 라이브 토글 활성");
  assert(liveToggle.getAttribute("aria-pressed") === "false", "[" + env.timing + "] 라이브 모드 기본 꺼짐");

  env.mic.click();
  await waitFor(function () { return env.mic.getAttribute("data-voice-state") === "listening"; }, "마이크 캡처 시작");
  assert(env.mic.getAttribute("aria-pressed") === "true", "[" + env.timing + "] 마이크 시작 상태 반영");
  await sleep(30); // async MediaRecorder가 첫 청크를 보낼 시간을 준다.

  env.mic.click();
  await waitFor(function () { return env.composer.value === TRANSCRIPT; }, "Mode A 전사 반영");

  assert(env.composer.value === TRANSCRIPT, "[" + env.timing + "] Mode A: 전사문이 입력창에 기록됨");
  assert(env.sendCount() === 0, "[" + env.timing + "] Mode A: 자동 전송 없음");
  assert(env.transcribeCalls().length === 1, "[" + env.timing + "] Mode A: transcribe 정확히 1회");

  // #3404 진단: stop 경로가 빈 청크로 조기 반환하지 않고 실제로 flush 했는지.
  const rec = env.recorders[0];
  assert(!!rec, "[" + env.timing + "] MediaRecorder 생성됨");
  assert(rec.startCalls === 1, "[" + env.timing + "] start() 1회 (ondataavailable 이전 등록 경로)");
  assert(rec.chunksSent >= 1, "[" + env.timing + "] start() 이후 오디오 청크 도달");
  assert(rec.probe.chunksAtStop >= 1, "[" + env.timing + "] stop 직전 청크 보유");
  assert(rec.probe.requestDataCalls === 1, "[" + env.timing + "] stop 시 requestData 1회");
  assert(rec.probe.onstopCalls === 1, "[" + env.timing + "] onstop 1회 → flushChunk(true, true) 실행");
  const body = JSON.parse(env.transcribeCalls()[0].init.body);
  assert(/^u1-/.test(body.utterance_id), "[" + env.timing + "] transcribe 에 utterance_id 전달");
  assert(body.audio_base64.length > 0, "[" + env.timing + "] transcribe 에 오디오 base64 전달");
  wiring.destroy();
}

async function scenarioModeB(env) {
  const wiring = await startWiring(env);
  await waitFor(function () { return env.mic.disabled === false; }, "STT 게이트 개방");

  const liveToggle = env.doc.getElementById("easyVoiceLiveToggle");
  liveToggle.click();
  assert(liveToggle.getAttribute("aria-pressed") === "true", "[" + env.timing + "] 라이브 모드 켜짐");

  env.mic.click();
  await waitFor(function () { return env.mic.getAttribute("data-voice-state") === "listening"; }, "마이크 캡처 시작");
  await sleep(30);
  env.mic.click();
  await waitFor(function () { return env.sendCount() >= 1; }, "Mode B 자동 전송");

  assert(env.sendCount() === 1, "[" + env.timing + "] Mode B: 자동 전송 정확히 1회");
  assert(env.composer.value === TRANSCRIPT, "[" + env.timing + "] Mode B: 전사문이 입력창에 기록됨");
  assert(env.transcribeCalls().length === 1, "[" + env.timing + "] Mode B: transcribe 정확히 1회");

  // 추가 지연 후에도 재전송이 없어야 한다.
  await sleep(80);
  assert(env.sendCount() === 1, "[" + env.timing + "] Mode B: 중복 자동 전송 없음");
  wiring.destroy();
}

async function scenarioNoAudio(env) {
  const wiring = await startWiring(env);
  await waitFor(function () { return env.mic.disabled === false; }, "STT 게이트 개방");
  env.mic.click();
  await waitFor(function () { return env.mic.getAttribute("data-voice-state") === "listening"; }, "마이크 캡처 시작");
  await sleep(30);
  env.mic.click();
  await sleep(120);
  assert(env.transcribeCalls().length === 0, "[" + env.timing + "] 오디오 없음: transcribe 호출 없음");
  assert(env.composer.value === "", "[" + env.timing + "] 오디오 없음: 입력창 변경 없음");
  assert(env.sendCount() === 0, "[" + env.timing + "] 오디오 없음: 전송 없음");
  wiring.destroy();
}

async function scenarioUnavailable(env) {
  const wiring = await startWiring(env);
  await sleep(80);
  assert(env.mic.disabled === true, "[" + env.timing + "] 미인증 세션: 마이크 비활성 유지");
  env.mic.click();
  await sleep(40);
  assert(env.transcribeCalls().length === 0, "[" + env.timing + "] 미인증 세션: transcribe 호출 없음");
  assert(wiring.getState().sttAvailable === false, "[" + env.timing + "] 미인증 세션: sttAvailable=false");
  wiring.destroy();
}

async function main() {
  await scenarioModeA(makeEnv({ timing: "sync" }));
  await scenarioModeA(makeEnv({ timing: "async" }));
  await scenarioModeB(makeEnv({ timing: "sync" }));
  await scenarioModeB(makeEnv({ timing: "async" }));
  await scenarioNoAudio(makeEnv({ timing: "async", emitChunks: false }));
  await scenarioUnavailable(makeEnv({ timing: "async", identityStatus: 401 }));
  console.log("모든 단위 테스트 통과");
}

main().then(
  () => process.exit(0),
  (e) => { console.error(e && e.stack ? e.stack : e); process.exit(1); }
);
