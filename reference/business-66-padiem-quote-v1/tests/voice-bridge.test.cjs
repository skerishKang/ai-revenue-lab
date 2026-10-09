/* B66 voice connection regression (#3404) — the reused Global Classroom engine is tested
   upstream; this file only proves the quote-side connection: mic control, final transcript
   reaching the existing composer, review vs auto send, one submit per utterance, refusal of
   the unapproved fallback, and a browser that cannot load the artifact. */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("path");
const vm = require("node:vm");

const SRC = path.join(__dirname, "..");

function loadBridge() {
  const elements = {};
  const removed = [];
  const doc = {
    elements,
    removed,
    head: { children: [], appendChild(node) { this.children.push(node); if (node.onload) node.onload(); } },
    body: { children: [], appendChild(node) { this.children.push(node); } },
    createElement: (tag) => ({
      tag, hidden: false, id: "", attrs: {}, removedFrom: null,
      setAttribute(k, v) { this.attrs[k] = v; },
      appendChild() {},
      remove() { this.removedFrom = doc.body; removed.push(this); }
    }),
    getElementById: (id) => elements[id] || null,
    addEventListener() {}
  };
  const makeEl = (id) => {
    const listeners = [];
    return elements[id] || (elements[id] = {
      id, listeners, attrs: { "aria-pressed": "false" }, classes: [], hidden: false, textContent: "",
      addEventListener(type, handler) { if (type === "click") listeners.push(handler); },
      setAttribute(name, value) { this.attrs[name] = value; },
      getAttribute(name) { return this.attrs[name]; },
      classList: { toggle() {} },
      click() { return listeners[listeners.length - 1](); }
    });
  };
  ["easyVoiceMic", "easyVoiceStatus", "easyVoiceModeReview", "easyVoiceModeAuto"].forEach(makeEl);
  const net = { calls: [] };
  const sandbox = {
    window: {}, document: doc, console, Date, Math, Number, String, Boolean, Object, Array,
    JSON, Error, Promise, Set, Map, RegExp, Symbol,
    setTimeout, clearTimeout,
    /* The connection layer may never talk to the network itself: the engine owns the token
       route, and the Groq refusal must not cost a request. */
    fetch: (target) => {
      net.calls.push(String(target && target.url ? target.url : target));
      return Promise.reject(new Error("harness_network_disabled"));
    }
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(SRC, "voice-quote-bridge.js"), "utf8"), sandbox);
  return { Bridge: sandbox.window.B66VoiceBridge, doc, sandbox, net };
}

function createHost() {
  const log = [];
  const host = {
    log, value: "", staged: null, disabled: false, notes: [],
    stageText(text) {
      const value = String(text || "").trim();
      if (!value) return { staged: false, reason: "empty_transcript" };
      host.value = host.value ? host.value + " " + value : value;
      host.staged = host.value;
      return { staged: true };
    },
    clearStagedText() { host.value = ""; host.staged = null; return { cleared: true }; },
    hasUnsentStagedText() { return Boolean(host.staged) && host.value === host.staged; },
    canSubmit() { return !host.disabled; },
    submitStaged() {
      if (!host.canSubmit()) return { submitted: false, reason: "input_not_ready" };
      log.push("INPUT:" + host.value.trim());
      host.value = "";
      host.staged = null;
      return { submitted: true };
    },
    note(text) { host.notes.push(text); }
  };
  return host;
}

/* Stands in for the artifact: the real engine is upstream's, so the fake records exactly
   what B66 asks of it and nothing more. */
function fakeEngine(state) {
  return () => Promise.resolve({
    createApi: ({ publish }) => ({
      publish,
      setEngine() {},
      start: () => { state.starts += 1; return Promise.resolve(); },
      stop: () => { state.stops += 1; return { stopped: true }; },
      isMounted: () => true
    }),
    mount: (api) => { state.mounts += 1; state.api = api; return { unmount() {} }; }
  });
}

/* Stands in for the artifact the way the real seam behaves: every mount creates its own api
   and its own publish sink, an engine start that the harness releases by hand, and stops
   counted per api instance — so an old attempt can only ever disturb its own resources. */
function attemptEngine(state) {
  return () => Promise.resolve({
    createApi: ({ publish }) => {
      const sink = { publish, starts: 0, stops: 0, releases: [], unmounted: false };
      state.sinks.push(sink);
      return {
        publish,
        setEngine() {},
        start: () => {
          sink.starts += 1;
          return new Promise((resolve, reject) => { sink.releases.push({ resolve, reject }); });
        },
        stop: () => { sink.stops += 1; return { stopped: true }; },
        isMounted: () => true
      };
    },
    mount: (api) => {
      const sink = state.sinks[state.sinks.length - 1];
      state.mounts += 1;
      state.api = api;
      return { unmount() { sink.unmounted = true; state.unmounts += 1; } };
    }
  });
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

async function main() {
  /* --- the artifact is not loaded until the user asks for the microphone ---------- */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { starts: 0, stops: 0, mounts: 0 };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host, engineLoader: fakeEngine(state)
    });
    assert.equal(doc.head.children.length, 0, "no engine script on page load");
    await bridge.start();
    await bridge.start();
    assert.equal(state.starts, 1, "a second press does not start the mic twice");
    assert.equal(state.mounts, 1, "the engine is mounted exactly once");
    bridge.stop();
    assert.equal(state.stops, 1, "stop goes through the upstream engine's own stop()");
    assert.equal(bridge.isRunning(), false);
  }

  /* --- final transcript reaches the composer; interim never does ------------------ */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { starts: 0, stops: 0, mounts: 0 };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host, mode: "REVIEW", engineLoader: fakeEngine(state)
    });
    await bridge.start();
    bridge.publish({ kind: "interim", text: "대한건설에" });
    assert.equal(host.value, "", "interim is preview only, never input");
    assert.match(doc.elements.easyVoiceStatus.textContent, /듣는 중/);
    bridge.publish({ kind: "final", text: "대한건설에 배관 100미터, 미터당 18,000원", utteranceId: "u1" });
    assert.equal(host.value, "대한건설에 배관 100미터, 미터당 18,000원",
      "the engine's final transcript is staged into the existing composer");
    assert.deepEqual(host.log, [], "MODE A never sends by itself");
  }

  /* --- MODE B sends once per utterance, and respects a busy quote ---------------- */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { starts: 0, stops: 0, mounts: 0 };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host, mode: "AUTO", engineLoader: fakeEngine(state)
    });
    await bridge.start();
    bridge.publish({ kind: "final", text: "배관 100미터", utteranceId: "u1" });
    assert.deepEqual(host.log, ["INPUT:배관 100미터"], "one auto-submit through the existing path");
    bridge.publish({ kind: "final", text: "배관 100미터", utteranceId: "u1" });
    assert.equal(host.log.length, 1, "the same utterance never sends twice");
    bridge.publish({ kind: "final", text: "단가 18000원", utteranceId: "u1" });
    assert.equal(host.log.length, 1, "a repeated id is refused even with different text");

    host.disabled = true;
    bridge.publish({ kind: "final", text: "부가세 별도", utteranceId: "u2" });
    assert.equal(host.log.length, 1, "no auto-submit while B66 is processing");
    assert.match(doc.elements.easyVoiceStatus.textContent, /자동으로 보내지 않았습니다/);
    host.disabled = false;
    assert.equal(host.log.length, 1, "becoming idle must not flush a deferred submit");
  }

  /* --- AUTO never rides over a transcript the user has not sent yet -------------- */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { starts: 0, stops: 0, mounts: 0 };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host, mode: "AUTO", engineLoader: fakeEngine(state)
    });
    await bridge.start();
    host.stageText("직접 입력한 문구");
    bridge.publish({ kind: "final", text: "배관 100미터", utteranceId: "u9" });
    assert.equal(host.log.length, 0, "an unsent draft is never auto-submitted");
    assert.match(doc.elements.easyVoiceStatus.textContent, /아직 보내지 않은/);
    assert.equal(host.value.includes("배관 100미터"), true,
      "the transcript is still staged so the user can review the blend");
  }

  /* --- a press while the connection is still open cancels that attempt ------------ */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { starts: 0, stops: 0, mounts: 0, release: null };
    const api = {
      publish: () => {}, setEngine() {},
      /* The upstream start is the unsettled one: connect resolves only when the harness lets it. */
      start: () => { state.starts += 1; return new Promise((resolve) => { state.release = resolve; }); },
      stop: () => { state.stops += 1; return { stopped: true }; },
      isMounted: () => true
    };
    const engine = { createApi: () => api, mount: () => { state.mounts += 1; return { unmount() {} }; } };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host, engineLoader: () => Promise.resolve(engine)
    });
    Bridge.bindDom(bridge, doc);
    const mic = doc.elements.easyVoiceMic;
    const firstPress = mic.click();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(bridge.isStarting(), true, "the bridge knows an attempt is in flight");
    assert.equal(state.starts, 1, "the engine is already connecting");
    const secondPress = mic.click();
    assert.deepEqual(secondPress, { stopped: true },
      "a second press cancels the connecting attempt instead of queueing another one");
    assert.equal(mic.getAttribute("aria-pressed"), "false", "and the button reads off again");
    state.release();
    const firstResult = await firstPress;
    assert.equal(firstResult.started, false, "the cancelled attempt never reports a started session");
    assert.equal(bridge.isRunning(), false, "and it cannot light the microphone afterwards");
    assert.equal(state.starts, 1, "the engine was asked to start exactly once");
    /* One stop from the press itself, one from the session that arrived after it. */
    assert.equal(state.stops, 2, "the late session is released through the engine's own stop()");
  }

  /* --- a transcript that arrives after stop cannot reach the quote ---------------- */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { starts: 0, stops: 0, mounts: 0 };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host, mode: "AUTO", engineLoader: fakeEngine(state)
    });
    await bridge.start();
    bridge.stop();
    state.api.publish({ kind: "final", text: "단가 18000원", utteranceId: "late-1" });
    assert.equal(host.log.length, 0, "a stopped session cannot auto-submit into the quote");
    assert.equal(host.value, "", "and its late transcript is not staged into the composer either");
    assert.equal(bridge.submittedCount(), 0, "the stale utterance is not recorded as anything sent");
    /* The same through the layer's own public surface, not just the engine sink. */
    bridge.publish({ kind: "final", text: "다른 경로로 들어온 전사", utteranceId: "late-2" });
    assert.equal(host.log.length, 0, "no caller can smuggle a send into a stopped session");
    assert.equal(host.value, "", "and nothing lands in the composer that way either");
    state.api.publish({ kind: "interim", text: "뒤늦게 도착한 중간 전사" });
    assert.equal(bridge.isRunning(), false, "a stale echo cannot claim the microphone is live again");
    assert.equal(/듣는 중/.test(doc.elements.easyVoiceStatus.textContent), false,
      "and it cannot rewrite the status into listening either");
    await bridge.start();
    bridge.publish({ kind: "final", text: "배관 100미터", utteranceId: "fresh-1" });
    assert.deepEqual(host.log, ["INPUT:배관 100미터"], "the next real session still works normally");
  }

  /* --- the live session's own idle report closes the button ------------------------ */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { starts: 0, stops: 0, mounts: 0 };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host, engineLoader: fakeEngine(state)
    });
    Bridge.bindDom(bridge, doc);
    const mic = doc.elements.easyVoiceMic;
    await mic.click();
    assert.equal(mic.getAttribute("aria-pressed"), "true", "the live attempt reads on");
    state.api.publish({ kind: "engine", status: "idle", backend: "gemini" });
    assert.equal(bridge.isRunning(), false, "the engine's own idle report closes the session");
    assert.equal(mic.getAttribute("aria-pressed"), "false", "and the button follows it");
    assert.match(doc.elements.easyVoiceStatus.textContent, /멈췄습니다/);
  }

  /* --- start(A) -> stop(A) -> start(B): A's late completion cannot invade B ------- */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { sinks: [], mounts: 0, unmounts: 0, api: null };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host, mode: "AUTO", engineLoader: attemptEngine(state)
    });
    const a = bridge.start();
    await tick();
    bridge.stop();
    const b = bridge.start();
    await tick();
    assert.equal(state.sinks.length, 2, "the replacement attempt owns its own engine session");

    state.sinks[0].releases[0].resolve();
    const aResult = await a;
    assert.equal(aResult.started, false, "the superseded attempt reports nothing started");
    await tick();
    assert.equal(state.sinks[1].stops, 0, "and it cannot stop the session B is using");
    /* Its mount survives exactly as long as its own unsettled promise, so the session that
       opens late still has a handle of its own to close — and then it is gone. */
    assert.equal(state.sinks[0].unmounted, true, "the stopped attempt released its own mount");
    assert.equal(doc.removed.length, 1, "and only its own mount holder left the page");
    assert.equal(doc.body.children.length - doc.removed.length, 1, "B's mount is the one still attached");

    state.sinks[1].releases[0].resolve();
    await b;
    assert.equal(bridge.isRunning(), true, "B is listening");
    state.sinks[1].publish({ kind: "final", text: "배관 100미터", utteranceId: "uB" });
    assert.deepEqual(host.log, ["INPUT:배관 100미터"], "B's own transcript still reaches the quote");
  }

  /* --- A의 지연 실패는 B의 세션과 상태줄을 덮어쓸 수 없음 ------------------------- */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { sinks: [], mounts: 0, unmounts: 0, api: null };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host, mode: "AUTO", engineLoader: attemptEngine(state)
    });
    const a = bridge.start();
    await tick();
    bridge.stop();
    const b = bridge.start();
    await tick();
    state.sinks[1].releases[0].resolve();
    await b;
    assert.equal(bridge.isRunning(), true, "B is listening");
    const statusBefore = doc.elements.easyVoiceStatus.textContent;

    state.sinks[0].releases[0].reject(new Error("late A failure"));
    const aResult = await a;
    assert.equal(aResult.started, false, "the superseded attempt still reports failure");
    await tick();
    assert.equal(bridge.isRunning(), true, "A's late failure cannot drop B's session");
    assert.equal(doc.elements.easyVoiceStatus.textContent, statusBefore,
      "and it cannot rewrite the status line B is standing on");
    assert.equal(state.sinks[1].stops, 0, "B's engine was never stopped by A");
  }

  /* --- A의 지연 final/fatal/refused cannot be delivered as if it were B's ---------- */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { sinks: [], mounts: 0, unmounts: 0, api: null };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host, mode: "AUTO", engineLoader: attemptEngine(state)
    });
    const a = bridge.start();
    await tick();
    state.sinks[0].releases[0].resolve();
    await a;
    bridge.stop();
    const b = bridge.start();
    await tick();
    state.sinks[1].releases[0].resolve();
    await b;
    assert.equal(bridge.isRunning(), true, "B is the live session");

    /* Everything A still has queued arrives now, through A's own sink. */
    state.sinks[0].publish({ kind: "final", text: "이전 세션의 늦은 전사", utteranceId: "uA" });
    assert.equal(host.log.length, 0, "a superseded transcript cannot auto-submit into the quote");
    assert.equal(host.value, "", "and it cannot enter B's composer either");
    const statusBefore = doc.elements.easyVoiceStatus.textContent;
    state.sinks[0].publish({ kind: "interim", text: "이전 세션의 중간 전사" });
    assert.equal(doc.elements.easyVoiceStatus.textContent, statusBefore,
      "a superseded preview cannot rewrite B's status line");
    state.sinks[0].publish({ kind: "fatal", message: "이전 세션 치명 오류" });
    assert.equal(bridge.isRunning(), true, "a superseded fatal cannot stop B");
    assert.equal(state.sinks[1].stops, 0, "and it cannot reach B's engine");
    assert.equal(doc.elements.easyVoiceStatus.textContent.includes("이전 세션 치명 오류"), false,
      "nor can it put its own reason on B's status line");
    state.sinks[0].publish({ kind: "refused", message: "이전 세션의 groq 거부" });
    assert.equal(bridge.isRunning(), true, "a superseded refusal cannot tear B down");
    assert.equal(state.sinks[1].stops, 0);
    assert.equal(host.log.length, 0, "and still nothing was sent");

    /* B's own events are unaffected by all of that. */
    state.sinks[1].publish({ kind: "final", text: "단가 18000원", utteranceId: "uB" });
    assert.deepEqual(host.log, ["INPUT:단가 18000원"], "B's own transcript still works");
  }

  /* --- the first press waits for React's own mount pass -------------------------- */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { starts: 0, stops: 0, mounts: 0, polls: 0 };
    const api = {
      publish: () => {},
      setEngine() {},
      start: () => { state.starts += 1; return Promise.resolve(); },
      stop: () => { state.stops += 1; return { stopped: true }; },
      /* The seam registers its start/stop from an effect, so the engine only exists a
         couple of frames after render(). */
      isMounted: () => { state.polls += 1; return state.polls > 2; }
    };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host,
      engineLoader: () => Promise.resolve({
        createApi: () => api,
        mount: () => { state.mounts += 1; return { unmount() {} }; }
      })
    });
    const result = await bridge.start();
    assert.equal(result.started, true,
      "the press waits for the mount instead of firing at an engine that is not wired yet");
    assert.equal(state.starts, 1, "the upstream start runs exactly once");
    assert.equal(state.polls > 2, true, "the mount pass was really awaited");
  }

  /* --- a mount that never lands is a reported failure, not a hung microphone ----- */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { starts: 0 };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host,
      engineLoader: () => Promise.resolve({
        createApi: () => ({
          publish: () => {}, setEngine() {},
          start: () => { state.starts += 1; return Promise.resolve(); },
          stop: () => ({ stopped: true }),
          isMounted: () => false
        }),
        mount: () => ({ unmount() {} })
      })
    });
    const result = await bridge.start();
    assert.equal(result.started, false, "an engine that never mounts is reported");
    assert.match(String(result.reason), /mount_timeout/);
    assert.equal(state.starts, 0, "and no session was ever opened");
    assert.equal(bridge.isRunning(), false, "the bridge does not believe it is listening");
    assert.match(doc.elements.easyVoiceStatus.textContent, /텍스트로 계속/);
  }

  /* --- a late idle event cannot rewrite the message that the attempt failed ------- */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    let emit = null;
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host,
      engineLoader: () => Promise.resolve({
        createApi: (handlers) => {
          emit = handlers.publish;
          return {
            publish: handlers.publish, setEngine() {},
            start: () => Promise.reject(new Error("voice_engine_not_mounted")),
            stop: () => ({ stopped: true }),
            isMounted: () => true
          };
        },
        mount: () => ({ unmount() {} })
      })
    });
    const result = await bridge.start();
    assert.equal(result.started, false);
    assert.match(doc.elements.easyVoiceStatus.textContent, /텍스트로 계속/);
    emit({ kind: "engine", status: "idle", backend: "gemini" });
    assert.match(doc.elements.easyVoiceStatus.textContent, /텍스트로 계속/,
      "an idle echo after a failed attempt must not pretend the user merely stopped");
  }

  /* --- an unapproved fallback is refused, not ridden ----------------------------- */
  {
    const { Bridge, doc, net } = loadBridge();
    const host = createHost();
    const state = { starts: 0, stops: 0, mounts: 0 };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host, mode: "AUTO", engineLoader: fakeEngine(state)
    });
    await bridge.start();
    state.api.publish({ kind: "refused", reason: "groq_fallback_disabled", message: "추가 음성 서비스는 사용하지 않습니다." });
    assert.equal(state.stops, 1, "the refusal stops the engine session");
    assert.equal(host.log.length, 0, "and nothing is sent on the way out");
    assert.match(doc.elements.easyVoiceStatus.textContent, /추가 음성 서비스/);
    /* Stopping before the recorder can hand over a blob is what keeps the refused provider
       free: upstream posts its fallback audio only while the session is still desired. */
    assert.deepEqual(net.calls, [], "the refusal path costs no request, /api/transcribe included");
    state.api.publish({ kind: "engine", status: "live", backend: "groq" });
    assert.equal(bridge.isRunning(), false, "a groq echo after the refusal cannot reopen the session");
    assert.deepEqual(net.calls, [], "and it still costs no request");
  }

  /* --- a browser that cannot load the artifact keeps the text path --------------- */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host,
      engineLoader: () => Promise.reject(new Error("404 /vendor/b66-voice-interview-299c8e78.js"))
    });
    Bridge.bindDom(bridge, doc);
    const mic = doc.elements.easyVoiceMic;
    const result = await mic.click();
    assert.equal(result.started, false, "a failed load is reported, not swallowed");
    assert.equal(mic.getAttribute("aria-pressed"), "false",
      "a press that failed does not leave the microphone lit");
    assert.equal(bridge.isRunning(), false);
    assert.match(doc.elements.easyVoiceStatus.textContent, /텍스트로 계속/);
    assert.equal(host.log.length, 0, "and the quote path was never touched");
  }

  /* --- the button reflects only a session that actually runs --------------------- */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { starts: 0, stops: 0, mounts: 0 };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host, engineLoader: fakeEngine(state)
    });
    const bindings = Bridge.bindDom(bridge, doc);
    const mic = doc.elements.easyVoiceMic;
    await mic.click();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(mic.getAttribute("aria-pressed"), "true", "the press that started listening reads on");
    await mic.click();
    assert.equal(mic.getAttribute("aria-pressed"), "false", "the press that stopped reads off");
    doc.elements.easyVoiceModeAuto.click();
    assert.equal(bridge.getMode(), "AUTO", "the mode toggle reaches the bridge");
    assert.equal(doc.elements.easyVoiceModeAuto.getAttribute("aria-pressed"), "true");
    doc.elements.easyVoiceModeReview.click();
    assert.equal(bridge.getMode(), "REVIEW", "the review button puts the composer back in MODE A");
    assert.equal(doc.elements.easyVoiceModeReview.getAttribute("aria-pressed"), "true");
    assert.equal(typeof bindings.renderMode, "function");
  }

  /* --- the button never claims a session the engine has already lost ------------- */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { starts: 0, stops: 0, mounts: 0 };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host, engineLoader: fakeEngine(state)
    });
    Bridge.bindDom(bridge, doc);
    const mic = doc.elements.easyVoiceMic;
    await mic.click();
    assert.equal(mic.getAttribute("aria-pressed"), "true", "a live session reads on");
    /* The engine reports its own fatal error without being asked to stop. */
    state.api.publish({ kind: "fatal", message: "브라우저 음성 인식 오류: not-allowed" });
    assert.equal(bridge.isRunning(), false, "the bridge stops believing in the session");
    assert.equal(state.stops, 1, "the dead session is released through the engine's own stop()");
    assert.equal(mic.getAttribute("aria-pressed"), "false",
      "and the microphone button cannot keep claiming a session that just died");
    assert.match(doc.elements.easyVoiceStatus.textContent, /not-allowed/, "the engine's own reason is shown");
    await mic.click();
    assert.equal(state.starts, 2, "one more press can open a fresh session");
  }

  /* --- press A → cancel → press B, B settles first, A settles late ---------------- */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { sinks: [], mounts: 0, unmounts: 0, api: null };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host, engineLoader: attemptEngine(state)
    });
    Bridge.bindDom(bridge, doc);
    const mic = doc.elements.easyVoiceMic;
    const a = mic.click();
    await tick();
    assert.equal(mic.getAttribute("aria-pressed"), "true", "the press that is connecting reads on");
    mic.click();
    await tick();
    assert.equal(mic.getAttribute("aria-pressed"), "false", "the press that cancelled reads off");
    const b = mic.click();
    await tick();
    assert.equal(mic.getAttribute("aria-pressed"), "true", "the replacement press reads on again");

    state.sinks[1].releases[0].resolve();
    await b;
    assert.equal(bridge.isRunning(), true, "B is the live session");
    state.sinks[0].releases[0].reject(new Error("late A failure"));
    const aResult = await a;
    await tick();
    assert.equal(aResult.started, false, "A still reports its own cancellation");
    assert.equal(mic.getAttribute("aria-pressed"), "true",
      "but a superseded promise cannot darken the button of the session that is live");
    assert.equal(bridge.isRunning(), true, "B was never touched");
  }

  /* --- A settles while B is still connecting, and B then goes live ----------------- */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { sinks: [], mounts: 0, unmounts: 0, api: null };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host, engineLoader: attemptEngine(state)
    });
    Bridge.bindDom(bridge, doc);
    const mic = doc.elements.easyVoiceMic;
    const a = mic.click();
    await tick();
    mic.click();
    await tick();
    const b = mic.click();
    await tick();
    assert.equal(mic.getAttribute("aria-pressed"), "true", "B is connecting");

    state.sinks[0].releases[0].reject(new Error("late A failure"));
    const aResult = await a;
    await tick();
    assert.equal(aResult.started, false);
    assert.equal(mic.getAttribute("aria-pressed"), "true",
      "A finishing first cannot switch off a connection that is still in flight");

    state.sinks[1].releases[0].resolve();
    await b;
    assert.equal(bridge.isRunning(), true, "B is live");
    assert.equal(mic.getAttribute("aria-pressed"), "true", "and its button stayed on throughout");
  }

  /* --- a press whose own attempt really did fail still switches the button off ---- */
  {
    const { Bridge, doc } = loadBridge();
    const host = createHost();
    const state = { sinks: [], mounts: 0, unmounts: 0, api: null };
    const bridge = Bridge.createVoiceBridge({
      document: doc, window: {}, host, engineLoader: attemptEngine(state)
    });
    Bridge.bindDom(bridge, doc);
    const mic = doc.elements.easyVoiceMic;
    const a = mic.click();
    await tick();
    state.sinks[0].releases[0].reject(new Error("voice_engine_not_mounted"));
    const result = await a;
    assert.equal(result.started, false, "the failure is reported");
    assert.equal(mic.getAttribute("aria-pressed"), "false",
      "and the button of the attempt that actually failed does switch off");
  }

  /* --- the shipped artifact is the reused engine, not a local rewrite ------------ */
  {
    const { Bridge } = loadBridge();
    /* Comments in this file explain what the engine owns, so the guard reads code only. */
    const source = fs.readFileSync(path.join(SRC, "voice-quote-bridge.js"), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");
    assert.equal(/GoogleGenAI|BidiGenerateContent|getUserMedia|AudioContext|createScriptProcessor|interimInputTranscription|webkitSpeechRecognition/.test(source), false,
      "the bridge must not implement capture, the Live protocol or transcripts");
    const html = fs.readFileSync(path.join(SRC, "index.html"), "utf8");
    assert.equal(html.includes("voice-quote-bridge.js"), true, "the composer page wires the bridge");
    assert.equal(/<script[^>]+src="https?:/i.test(html), false, "still no external script origin");
    assert.equal(html.includes("voice-stt.js") || html.includes("voice-input.js"), false,
      "the retired custom engine is gone from the page");
    /* The connection has to point at something that ships, or the press silently 404s. */
    assert.equal(Bridge.ARTIFACT.startsWith("/vendor/"), true, "the engine loads same-origin");
    assert.ok(fs.existsSync(path.join(SRC, Bridge.ARTIFACT.replace(/^\//, ""))),
      `the bridge asks for ${Bridge.ARTIFACT}, which is not committed`);
  }

  console.log("B66_VOICE_BRIDGE=PASS");
}

const watchdog = setTimeout(() => {
  console.error("B66_VOICE_BRIDGE=TIMEOUT");
  console.error("MEANING=main() never settled; an await has neither resolved nor rejected");
  process.exit(1);
}, 30000);

main().then(
  () => clearTimeout(watchdog),
  (error) => {
    clearTimeout(watchdog);
    console.error("B66_VOICE_BRIDGE=FAIL");
    console.error(error && error.stack ? error.stack : String(error));
    process.exit(1);
  }
);
