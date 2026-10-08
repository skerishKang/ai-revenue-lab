/* B66 · Quote Beta — connection layer for the reused Global Classroom interview voice
   engine (#3404).

   There is no speech code in this file. The microphone, the Gemini Live session, the
   transcript merging, the browser fallback and the per-utterance identity all belong to
   `useInterviewLive.ts`, vendored unmodified into voice-interview/upstream/ and mounted by
   the same-origin artifact below. What lives here is only the quote-side connection: press
   the mic, put the final transcript into the existing composer, and decide whether the user
   or the machine sends it. */

(() => {
  "use strict";

  const ARTIFACT = "/vendor/b66-voice-interview-299c8e78.js";
  const MODE = { REVIEW: "REVIEW", AUTO: "AUTO" };
  const MAX_TRACKED_UTTERANCES = 64;
  /* React renders the seam and registers the hook's start/stop from an effect, both after
     this file's own call stack. Effects normally flush inside a frame; two seconds is a
     generous ceiling, not a guess at the frame rate. */
  const MOUNT_WAIT_MS = 2000;
  const MOUNT_POLL_MS = 16;

  const STATUS_TEXT = {
    loading: "음성 엔진을 불러오는 중…",
    listening: "듣는 중… 말한 내용은 아래 입력창에 먼저 표시됩니다.",
    review: "내용을 수정한 뒤 보내기 버튼이나 Enter로 전송하세요.",
    sent: "전사를 견적 대화로 보냈습니다. 다음 내용을 말씀하세요.",
    stopped: "음성 입력을 멈췄습니다.",
    browser: "브라우저 음성 인식으로 듣고 있습니다. 인식 정확도는 다를 수 있습니다.",
    refused: "추가 음성 서비스는 사용하지 않습니다. 텍스트로 계속 입력해 주세요.",
    unavailable: "음성 입력을 사용할 수 없어 텍스트로 계속합니다."
  };

  function createVoiceBridge(config) {
    const opts = config || {};
    const doc = opts.document;
    const win = opts.window;
    const host = opts.host;
    if (!doc || !win) throw new Error("voice_bridge_dom_unavailable");
    if (!host || typeof host.stageText !== "function" || typeof host.submitStaged !== "function" ||
      typeof host.canSubmit !== "function" || typeof host.hasUnsentStagedText !== "function") {
      throw new Error("voice_bridge_host_incomplete");
    }

    const loadEngine = typeof opts.engineLoader === "function" ? opts.engineLoader : null;
    const mount = typeof opts.mount === "function" ? opts.mount : null;
    const onStatus = typeof opts.onStatus === "function" ? opts.onStatus : (text) => {
      const status = doc.getElementById("easyVoiceStatus");
      if (!status) return;
      status.hidden = !text;
      status.textContent = text || "";
    };

    let mode = opts.mode === MODE.AUTO ? MODE.AUTO : MODE.REVIEW;
    let enginePromise = null;
    let running = false;
    /* One record per microphone attempt, numbered by `attempt`. The bridge only ever talks to
       `current`; a record that is no longer current owns its own engine handle, its own mount
       and its own publish sink, so a superseded session can neither open a microphone nor
       write a status line nor stop the session that replaced it. */
    let current = null;
    let attempt = 0;
    let announcedBrowser = false;
    const submitted = [];
    const stateListeners = [];

    /* `running` is the one fact the page's controls are drawn from, so it is only ever
       changed here — a button must not keep claiming a session the engine gave up on. */
    function setRunning(next) {
      if (running === next) return;
      running = next;
      for (const listener of stateListeners) listener({ running, mode });
    }

    function wasSubmitted(utteranceId) {
      return submitted.indexOf(utteranceId) !== -1;
    }

    function markSubmitted(utteranceId) {
      submitted.push(utteranceId);
      if (submitted.length > MAX_TRACKED_UTTERANCES) submitted.shift();
    }

    function loadArtifact() {
      if (loadEngine) return Promise.resolve(loadEngine());
      if (win.B66VoiceInterview) return Promise.resolve(win.B66VoiceInterview);
      if (enginePromise) return enginePromise;
      enginePromise = new Promise((resolve, reject) => {
        const script = doc.createElement("script");
        script.src = ARTIFACT;
        script.async = true;
        script.onload = () => {
          if (win.B66VoiceInterview) resolve(win.B66VoiceInterview);
          else reject(new Error("voice_engine_missing"));
        };
        script.onerror = () => reject(new Error("voice_engine_unavailable"));
        (doc.head || doc.body).appendChild(script);
      });
      return enginePromise;
    }

    /* One submit per final transcript. An empty utterance id (the engine had none yet)
        falls back to the text so a repeated final still cannot send twice. */
    function onFinal(event) {
      /* Only a session this bridge still considers open may reach the composer. */
      if (!running) return { staged: false, reason: "session_not_active" };
      const text = String(event.text || "").trim();
      if (!text) {
        onStatus(STATUS_TEXT.review);
        return { staged: false, reason: "empty_transcript" };
      }
      const key = String(event.utteranceId || "") || "text:" + text;
      if (wasSubmitted(key)) return { staged: false, reason: "duplicate_utterance" };
      /* Read the pending-transcript flag before staging: afterwards the composer always
         holds this text, which would block every automatic send. */
      const hadUnsent = host.hasUnsentStagedText();
      host.stageText(text);
      if (mode !== MODE.AUTO) {
        markSubmitted(key);
        onStatus(STATUS_TEXT.review);
        return { staged: true, sent: false, utteranceId: key };
      }
      if (hadUnsent) {
        onStatus("아직 보내지 않은 전사가 있어 자동으로 이어서 보내지 않았습니다. 입력창을 확인한 뒤 전송해 주세요.");
        return { staged: true, sent: false, deferred: "pending_transcript", utteranceId: key };
      }
      if (!host.canSubmit()) {
        onStatus("견적이 답하는 중이라 자동으로 보내지 않았습니다. 확인 후 보내기 버튼을 눌러 주세요.");
        return { staged: true, sent: false, deferred: "b66_busy", utteranceId: key };
      }
      markSubmitted(key);
      host.submitStaged();
      onStatus(STATUS_TEXT.sent);
      return { staged: true, sent: true, utteranceId: key };
    }

    function publish(event) {
      if (!event || typeof event !== "object") return { handled: false };
      switch (event.kind) {
        case "final":
          onFinal(event);
          return { handled: true };
        case "interim":
          /* Preview only, and only for the live attempt: a stale echo must not make the
             bridge believe it is listening again. */
          if (!running) return { handled: true };
          onStatus(STATUS_TEXT.listening);
          return { handled: true };
        case "utterance":
          return { handled: true };
        case "engine":
          if (!running) return { handled: true };
          setRunning(event.status === "live");
          if (event.backend === "browser" && !announcedBrowser) {
            announcedBrowser = true;
            onStatus(STATUS_TEXT.browser);
          }
          if (event.backend === "groq") onStatus(STATUS_TEXT.refused);
          if (!running) onStatus(STATUS_TEXT.stopped);
          return { handled: true };
        case "refused":
          /* The engine reported a fallback the owner has not approved: stop, and say so. */
          stop();
          onStatus(event.message || STATUS_TEXT.refused);
          return { handled: true };
        case "warning":
          if (event.message) onStatus(event.message);
          return { handled: true };
        case "fatal":
          /* The engine says this session is over: release it through the same path the
             button uses, so nothing is left half-open, then show its own reason. */
          stop();
          onStatus(event.message || STATUS_TEXT.unavailable);
          return { handled: true };
        default:
          return { handled: false };
      }
    }

    function waitForMount(mounted) {
      if (typeof mounted.isMounted !== "function" || mounted.isMounted()) return Promise.resolve();
      return new Promise((resolve, reject) => {
        const deadline = Date.now() + MOUNT_WAIT_MS;
        const poll = () => {
          if (mounted.isMounted()) { resolve(); return; }
          if (Date.now() >= deadline) { reject(new Error("voice_engine_mount_timeout")); return; }
          setTimeout(poll, MOUNT_POLL_MS);
        };
        poll();
      });
    }

    function mountRoot(rec) {
      if (opts.container) return opts.container;
      const holder = doc.createElement("div");
      holder.hidden = true;
      (doc.body || doc.documentElement).appendChild(holder);
      /* Only a holder this layer created is its to remove, and only once its attempt is done. */
      rec.root = holder;
      return holder;
    }

    /* A sink is stamped with the record that created it, so whatever an old session still has
       queued arrives as stale instead of being delivered as if it belonged to the live one. */
    function publishFor(rec, event) {
      if (rec !== current) return { handled: false, reason: "stale_attempt" };
      return publish(event);
    }

    function dispose(rec) {
      if (rec.disposed) return;
      rec.disposed = true;
      if (rec.handle && typeof rec.handle.unmount === "function") rec.handle.unmount();
      if (rec.root && typeof rec.root.remove === "function") rec.root.remove();
      rec.handle = null;
      rec.root = null;
      rec.api = null;
      if (current === rec) current = null;
    }

    function release(rec) {
      if (rec.api) rec.api.stop();
      dispose(rec);
    }

    function ensureMounted(rec) {
      return loadArtifact().then((engine) => {
        const created = engine.createApi({ publish: (event) => publishFor(rec, event) });
        rec.api = created;
        const doMount = mount || engine.mount;
        rec.handle = doMount(created, mountRoot(rec)) || null;
        return waitForMount(created).then(() => created);
      });
    }

    function start() {
      if (current && (current.connecting || running)) {
        return Promise.resolve({ started: false, reason: "already_running" });
      }
      if (current) release(current);
      attempt += 1;
      const rec = { id: attempt, api: null, handle: null, root: null, connecting: true, disposed: false };
      current = rec;
      announcedBrowser = false;
      onStatus(STATUS_TEXT.loading);
      return ensureMounted(rec).then((mounted) => {
        if (current !== rec) throw new Error("voice_start_cancelled");
        return mounted.start();
      }).then(() => {
        if (current === rec) {
          rec.connecting = false;
          setRunning(true);
          onStatus(STATUS_TEXT.listening);
          return { started: true };
        }
        release(rec);
        return { started: false, reason: "voice_start_cancelled" };
      }).catch((error) => {
        rec.connecting = false;
        if (current !== rec) {
          /* A failure of a session nobody is waiting for any more is that session's news
             alone: it may not clear the replacement's state or rewrite its status line. */
          release(rec);
          return { started: false, reason: "voice_start_cancelled" };
        }
        setRunning(false);
        onStatus(STATUS_TEXT.unavailable);
        dispose(rec);
        return { started: false, reason: String((error && error.message) || "voice_unavailable") };
      });
    }

    function stop() {
      /* Mic control stays the upstream hook's own stop(); it releases the stream, the
         AudioContext and the session. This layer only reflects that and stops routing. */
      const rec = current;
      current = null;
      if (rec) {
        if (rec.api) rec.api.stop();
        /* An attempt still connecting keeps its mount until its promise returns, so the
           session it opens late has its own handle to close — as itself, never as B's. */
        if (!rec.connecting) dispose(rec);
      }
      setRunning(false);
      onStatus(STATUS_TEXT.stopped);
      return { stopped: true };
    }

    function setMode(next) {
      mode = next === MODE.AUTO ? MODE.AUTO : MODE.REVIEW;
      return { mode };
    }

    return {
      MODE,
      STATUS_TEXT,
      start,
      stop,
      publish,
      setMode,
      getMode: () => mode,
      isRunning: () => running,
      isStarting: () => Boolean(current && current.connecting),
      onStateChange: (listener) => stateListeners.push(listener),
      submittedCount: () => submitted.length
    };
  }

  function bindDom(bridge, doc) {
    const mic = doc.getElementById("easyVoiceMic");
    const review = doc.getElementById("easyVoiceModeReview");
    const auto = doc.getElementById("easyVoiceModeAuto");

    function renderMode() {
      const isAuto = bridge.getMode() === bridge.MODE.AUTO;
      if (review) {
        review.classList.toggle("is-active", !isAuto);
        review.setAttribute("aria-pressed", isAuto ? "false" : "true");
      }
      if (auto) {
        auto.classList.toggle("is-active", isAuto);
        auto.setAttribute("aria-pressed", isAuto ? "true" : "false");
      }
    }

    if (mic) {
      mic.addEventListener("click", () => {
        if (bridge.isRunning() || bridge.isStarting()) {
          bridge.stop();
          mic.setAttribute("aria-pressed", "false");
          return { stopped: true };
        }
        mic.setAttribute("aria-pressed", "true");
        return bridge.start().then((result) => {
          if (!result.started) mic.setAttribute("aria-pressed", "false");
          return result;
        });
      });
    }
    if (mic && typeof bridge.onStateChange === "function") {
      /* The engine owns the session; the button only reports what the bridge knows of it. */
      bridge.onStateChange((state) => {
        mic.setAttribute("aria-pressed", state.running ? "true" : "false");
      });
    }
    if (review) review.addEventListener("click", () => { bridge.setMode(bridge.MODE.REVIEW); renderMode(); });
    if (auto) auto.addEventListener("click", () => { bridge.setMode(bridge.MODE.AUTO); renderMode(); });
    renderMode();
    return { renderMode };
  }

  function init(config) {
    const bridge = createVoiceBridge(config);
    const bindings = bindDom(bridge, config.document);
    return { bridge, bindings };
  }

  window.B66VoiceBridge = {
    ARTIFACT,
    MODE,
    STATUS_TEXT,
    createVoiceBridge,
    bindDom,
    init
  };
})();
