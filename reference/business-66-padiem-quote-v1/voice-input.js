/* B66 · Quote Beta — Voice input controller and composer glue (#3404)
   Owns the conversation state machine and the mic affordance. Quote interpretation is
   never performed here: the only way text leaves this module is by staging it into the
   existing composer and asking the existing send path to run. */

(() => {
  "use strict";

  const STATE = {
    IDLE: "IDLE",
    LISTENING: "LISTENING",
    TRANSCRIBING: "TRANSCRIBING",
    FINALIZED: "FINALIZED",
    REVIEW_READY: "REVIEW_READY",
    AUTO_SUBMIT_READY: "AUTO_SUBMIT_READY",
    B66_PROCESSING: "B66_PROCESSING",
    ASSISTANT_RESPONDING: "ASSISTANT_RESPONDING",
    WAITING_NEXT_TURN: "WAITING_NEXT_TURN",
    STOPPED: "STOPPED",
    ERROR: "ERROR"
  };

  const MODE = { REVIEW: "REVIEW", AUTO: "AUTO" };
  const DEFAULT_MODE = MODE.REVIEW;

  function requireHost(host) {
    if (!host ||
      typeof host.stageText !== "function" ||
      typeof host.clearStagedText !== "function" ||
      typeof host.canSubmit !== "function" ||
      typeof host.submitStaged !== "function") {
      throw new Error("voice_host_incomplete");
    }
    return host;
  }

  function createVoiceController(options) {
    const opts = options || {};
    const host = requireHost(opts.host);
    const machine = opts.machine;
    const transport = opts.transport;
    const audio = opts.audio;
    const onChange = typeof opts.onChange === "function" ? opts.onChange : () => {};
    const onNotice = typeof opts.onNotice === "function" ? opts.onNotice : () => {};
    const onPreview = typeof opts.onPreview === "function" ? opts.onPreview : () => {};

    let state = STATE.IDLE;
    let mode = opts.mode === MODE.AUTO ? MODE.AUTO : DEFAULT_MODE;
    let live = false;
    let lastStaged = null;
    let startedUtterances = 0;
    const submitted = [];

    function setState(next) {
      if (state === next) return;
      state = next;
      onChange({ state, mode, live, lastStaged: lastStaged && lastStaged.utteranceId });
    }

    function wasSubmitted(utteranceId) {
      return submitted.indexOf(utteranceId) !== -1;
    }

    function markSubmitted(utteranceId) {
      submitted.push(utteranceId);
      if (submitted.length > 64) submitted.shift();
    }

    /* A committed utterance is staged verbatim. Numbers are never adjusted here: an
       amount the transcript got wrong is corrected by the existing B66 follow-up flow,
       not silently by this module. */
    function stage(committed) {
      lastStaged = committed;
      host.stageText(committed.text);
      onPreview({ text: committed.text, utteranceId: committed.utteranceId, staged: true });
      setState(STATE.FINALIZED);
      return committed;
    }

    function deliver(committed) {
      if (!committed || !committed.utteranceId) return null;
      /* A transcript that lands after the session was torn down has no place in the
         conversation: it is neither staged nor submitted, and the drop is announced
         rather than silently swallowed. */
      if (!live && (state === STATE.ERROR || state === STATE.STOPPED)) {
        onNotice({ code: "late_transcript_dropped", utteranceId: committed.utteranceId });
        return null;
      }
      if (wasSubmitted(committed.utteranceId)) {
        onNotice({ code: "duplicate_utterance_suppressed", utteranceId: committed.utteranceId });
        return null;
      }
      /* Evaluated before staging: after staging, the composer always holds the text
         this module just wrote, which would block every automatic send. */
      const hadUnsentTranscript = typeof host.hasUnsentStagedText === "function" &&
        host.hasUnsentStagedText();
      stage(committed);
      if (mode === MODE.AUTO) {
        setState(STATE.AUTO_SUBMIT_READY);
        if (hadUnsentTranscript) {
          /* Two voice utterances must never travel as one submit, so an unsent
             staged transcript holds the next one back for the user to resolve. */
          setState(STATE.REVIEW_READY);
          onNotice({ code: "auto_submit_deferred_pending", utteranceId: committed.utteranceId });
          return committed;
        }
        if (!host.canSubmit()) {
          /* No deferred submit and no retry: the text stays editable and the user
             decides when B66 is ready for it. */
          setState(STATE.REVIEW_READY);
          onNotice({ code: "auto_submit_skipped_busy", utteranceId: committed.utteranceId });
          return committed;
        }
        markSubmitted(committed.utteranceId);
        setState(STATE.B66_PROCESSING);
        host.submitStaged();
        return committed;
      }
      setState(STATE.REVIEW_READY);
      return committed;
    }

    if (machine && typeof machine.on === "function") {
      machine.on("final", deliver);
      machine.on("interim", (payload) => {
        onPreview({ text: payload && payload.text, utteranceId: payload && payload.utteranceId, staged: false });
        if (state !== STATE.B66_PROCESSING && state !== STATE.REVIEW_READY) setState(STATE.LISTENING);
      });
      /* An ended turn with no transcript is announced, never guessed at and never
         auto-submitted: B66 keeps no second-provider audio recovery, so the honest
         outcome is that the user is asked to say it again. The next turn is opened by
         the transport's onTurnEnd, which fires for empty turns too, so this handler
         only reports. */
      machine.on("empty", (payload) => {
        onNotice({ code: "turn_empty", utteranceId: payload && payload.utteranceId });
      });
    }

    function beginTurn() {
      if (machine && typeof machine.openTurn === "function") machine.openTurn();
      startedUtterances += 1;
    }

    async function start() {
      if (live) return { started: false, reason: "already_listening" };
      if (!transport || !audio) throw new Error("voice_transport_unavailable");
      setState(STATE.TRANSCRIBING);
      try {
        await transport.connect({
          onTurnEnd: () => {
            if (state === STATE.B66_PROCESSING) return;
            setState(STATE.WAITING_NEXT_TURN);
            beginTurn();
          },
          onReconnected: () => {
            if (live) beginTurn();
          },
          onError: (error) => fail(error)
        });
        await audio.start();
        live = true;
        beginTurn();
        setState(STATE.LISTENING);
        return { started: true, utterance: startedUtterances };
      } catch (error) {
        live = false;
        return fail(error);
      }
    }

    function fail(error) {
      live = false;
      const code = (error && (error.code || error.reason)) || "voice_unavailable";
      /* A failure mid-session must not leave the microphone hot or the session half
         open. Teardown is unconditional here, and any staged text stays exactly as
         editable text so the user can still send or discard it by hand. */
      if (audio && typeof audio.stop === "function") audio.stop();
      if (transport && typeof transport.close === "function") transport.close();
      if (machine && typeof machine.reset === "function") machine.reset();
      setState(STATE.ERROR);
      onNotice({ code: String(code), fatal: true });
      return { started: false, reason: String(code) };
    }

    function stop(options) {
      const opts2 = options || {};
      live = false;
      if (audio && typeof audio.stop === "function") audio.stop();
      if (transport && typeof transport.close === "function") transport.close();
      if (machine && typeof machine.reset === "function") machine.reset();
      if (opts2.discard && lastStaged && typeof host.clearStagedText === "function") {
        host.clearStagedText(lastStaged.utteranceId);
        lastStaged = null;
      }
      setState(STATE.STOPPED);
      return { stopped: true, discarded: Boolean(opts2.discard) };
    }

    /* Host busy -> idle is what closes a turn: the assistant answer has been rendered
       and the composer is editable again, so MODE B may listen again. */
    function onHostIdle() {
      if (state !== STATE.B66_PROCESSING) return { resumed: false, reason: "not_processing" };
      setState(STATE.ASSISTANT_RESPONDING);
      setState(STATE.WAITING_NEXT_TURN);
      if (live) beginTurn();
      return { resumed: live };
    }

    function setMode(next) {
      const value = next === MODE.AUTO ? MODE.AUTO : MODE.REVIEW;
      if (value === mode) return { mode };
      mode = value;
      onChange({ state, mode, live, lastStaged: lastStaged && lastStaged.utteranceId });
      return { mode };
    }

    return {
      STATE,
      MODE,
      start,
      stop,
      onHostIdle,
      setMode,
      getState: () => state,
      getMode: () => mode,
      isLive: () => live,
      submittedCount: () => submitted.length,
      utteranceCount: () => startedUtterances
    };
  }

  const STATUS_TEXT = {
    IDLE: "",
    LISTENING: "듣는 중… 말한 내용은 아래 입력창에 먼저 표시됩니다.",
    TRANSCRIBING: "음성 연결을 준비하는 중…",
    FINALIZED: "전사 완료. 내용을 확인한 뒤 보내세요.",
    REVIEW_READY: "내용을 수정한 뒤 보내기 버튼이나 Enter로 전송하세요.",
    AUTO_SUBMIT_READY: "전사를 견적 대화로 보내는 중…",
    B66_PROCESSING: "견적을 만드는 중이라 음성은 잠시 멈춥니다.",
    ASSISTANT_RESPONDING: "답변 확인 중…",
    WAITING_NEXT_TURN: "다음 내용을 말하면 이어서 전송됩니다.",
    STOPPED: "음성 입력을 멈췄습니다.",
    ERROR: "음성 입력을 사용할 수 없어 텍스트로 계속합니다."
  };

  const NOTICE_TEXT = {
    auto_submit_skipped_busy: "견적이 답하는 중이라 자동으로 보내지 않았습니다. 확인 후 보내기 버튼을 눌러 주세요.",
    auto_submit_deferred_pending: "아직 보내지 않은 전사가 있어 자동으로 이어서 보내지 않았습니다. 입력창을 확인한 뒤 전송해 주세요.",
    duplicate_utterance_suppressed: "같은 발화는 한 번만 보냅니다.",
    microphone_denied: "마이크 권한이 없어 텍스트로 입력해 주세요.",
    voice_config_unavailable: "음성 전사 설정이 아직 없어 텍스트로 입력해 주세요.",
    voice_token_unavailable: "음성 연결 자격을 받지 못해 텍스트로 입력해 주세요.",
    voice_token_missing: "음성 연결 자격을 받지 못해 텍스트로 입력해 주세요.",
    voice_token_unparsable: "음성 연결 응답을 읽을 수 없어 텍스트로 입력해 주세요.",
    sdk_unavailable: "음성 인식 구성요소를 불러올 수 없어 텍스트로 입력해 주세요.",
    sdk_live_unsupported: "이 브라우저에서는 음성 인식을 사용할 수 없어 텍스트로 입력해 주세요.",
    voice_connection_failed: "음성 연결이 끊겨 텍스트로 입력해 주세요.",
    voice_connection_closed: "음성 연결이 끊겨 텍스트로 입력해 주세요.",
    fallback_browser_stt: "브라우저 음성 인식으로 이어갑니다. 인식 정확도는 다를 수 있습니다.",
    browser_stt_unavailable: "브라우저 음성 인식도 사용할 수 없어 텍스트로 입력해 주세요.",
    browser_stt_not_allowed: "마이크 권한이 차단되어 음성 입력을 이어가지 못합니다. 텍스트로 입력해 주세요.",
    browser_stt_network: "브라우저 음성 인식에 네트워크 오류가 발생했습니다. 텍스트로 입력해 주세요.",
    browser_stt_service_not_allowed: "브라우저 음성 인식 서비스를 사용할 수 없습니다. 텍스트로 입력해 주세요.",
    browser_stt_language_not_supported: "이 언어는 브라우저 음성 인식을 지원하지 않습니다. 텍스트로 입력해 주세요.",
    browser_stt_restart_limit: "브라우저 음성 인식이 계속 중단되어 종료합니다. 텍스트로 입력해 주세요.",
    /* §5: an empty turn is never presented as a success and never recovered silently. */
    turn_empty: "이번 발화는 음성이 잡히지 않았습니다. 자동으로 보내지 않았으니 다시 말씀해 주세요.",
    late_transcript_dropped: "음성 입력을 멈춘 뒤 도착한 전사는 보내지 않았습니다."
  };

  function textOf(value, limit) {
    return String(value == null ? "" : value).trim().slice(0, limit || 240);
  }

  function createDomBindings(config) {
    const opts = config || {};
    const doc = opts.document;
    const host = requireHost(opts.host);
    const controller = opts.controller;
    if (!doc || !controller) throw new Error("voice_dom_incomplete");

    const mic = doc.getElementById("easyVoiceMic");
    const status = doc.getElementById("easyVoiceStatus");
    const reviewToggle = doc.getElementById("easyVoiceModeReview");
    const autoToggle = doc.getElementById("easyVoiceModeAuto");

    function render(state) {
      if (!status) return;
      const message = textOf(STATUS_TEXT[state] || "", 240);
      status.hidden = message === "";
      status.textContent = message;
    }

    function renderMode(mode) {
      if (reviewToggle) {
        reviewToggle.classList.toggle("is-active", mode === MODE.REVIEW);
        reviewToggle.setAttribute("aria-pressed", mode === MODE.REVIEW ? "true" : "false");
      }
      if (autoToggle) {
        autoToggle.classList.toggle("is-active", mode === MODE.AUTO);
        autoToggle.setAttribute("aria-pressed", mode === MODE.AUTO ? "true" : "false");
      }
    }

    function busy() {
      return controller.getState() === STATE.B66_PROCESSING;
    }

    /* Interim text is preview material: it is written to the status line and never
       into the composer, so it cannot become authoritative input. */
    function showPreview(preview) {
      if (!status || !preview || preview.staged) return { shown: false };
      const text = textOf(preview.text, 180);
      if (!text) return { shown: false };
      status.hidden = false;
      status.textContent = text;
      return { shown: true };
    }

    if (mic) {
      mic.addEventListener("click", async () => {
        if (busy() || controller.isLive()) {
          const stopped = controller.stop({ discard: false });
          if (mic) mic.setAttribute("aria-pressed", "false");
          return stopped;
        }
        if (mic) mic.setAttribute("aria-pressed", "true");
        const started = await controller.start();
        if (!started.started && mic) mic.setAttribute("aria-pressed", "false");
        return started;
      });
    }

    if (reviewToggle) {
      reviewToggle.addEventListener("click", () => renderMode(controller.setMode(MODE.REVIEW).mode));
    }
    if (autoToggle) {
      autoToggle.addEventListener("click", () => renderMode(controller.setMode(MODE.AUTO).mode));
    }

    doc.addEventListener("b66:easy-input-ready", () => controller.onHostIdle());
    doc.addEventListener("b66:easy-busy", () => render(STATE.B66_PROCESSING));

    renderMode(controller.getMode());
    render(controller.getState());

    return {
      render,
      renderMode,
      showPreview,
      onNotice(notice) {
        const message = NOTICE_TEXT[notice && notice.code] || "";
        if (!message || !status) return { shown: false };
        status.hidden = false;
        status.textContent = textOf(message, 240);
        return { shown: true };
      }
    };
  }

  function init(config) {
    const opts = config || {};
    const doc = opts.document || (typeof document !== "undefined" ? document : null);
    const win = opts.window || (typeof window !== "undefined" ? window : null);
    const host = requireHost(opts.host);
    if (!doc || !win) throw new Error("voice_dom_unavailable");

    const stt = win.B66VoiceStt;
    if (!stt || typeof stt.createTranscriptMachine !== "function") throw new Error("voice_stt_missing");

    const machine = stt.createTranscriptMachine({
      nextId: stt.createIdSource(win.crypto || null)
    });

    let transport = null;
    let audio = null;
    const bindings = { current: null };

    function buildTransport() {
      if (opts.transportFactory) return opts.transportFactory({ machine, window: win, host });
      if (typeof stt.createFallbackChainTransport !== "function") {
        throw new Error("voice_transport_unavailable");
      }
      const Recognizer = win.SpeechRecognition || win.webkitSpeechRecognition || null;
      return stt.createFallbackChainTransport({
        machine,
        onNotice: (notice) => bindings.current && bindings.current.onNotice(notice),
        /* The Live session is opened by the pinned same-origin SDK bundle, never by a
           hand-assembled socket. The loader is injectable so tests never touch a network. */
        primaryFactory: (context) => stt.createSdkLiveTransport({
          machine: context.machine,
          onNotice: context.onNotice,
          tokenEndpoint: opts.tokenEndpoint || "/api/b66/voice/token",
          fetcher: typeof win.fetch === "function" ? win.fetch.bind(win) : null,
          sdkLoader: opts.sdkLoader
        }),
        fallbackFactory: typeof stt.createBrowserFallbackTransport === "function" && Recognizer
          ? (context) => stt.createBrowserFallbackTransport({
            machine: context.machine,
            recognizerFactory: () => new Recognizer(),
            language: (win.navigator && win.navigator.language) || "ko-KR"
          })
          : null
      });
    }

    const controller = createVoiceController({
      host,
      machine,
      mode: opts.mode,
      get transport() {
        if (!transport) transport = buildTransport();
        return transport;
      },
      get audio() {
        if (!audio) audio = stt.createPcmSource({
          mediaStreamFactory: (constraints) => win.navigator.mediaDevices.getUserMedia(constraints),
          audioContextFactory: (contextOptions) => new win.AudioContext(contextOptions),
          onChunk: (chunk) => {
            const activeTransport = transport;
            if (activeTransport && typeof activeTransport.sendAudio === "function") {
              activeTransport.sendAudio(chunk);
            }
          }
        });
        return audio;
      },
      onChange: ({ state }) => bindings.current && bindings.current.render(state),
      onNotice: (notice) => bindings.current && bindings.current.onNotice(notice),
      onPreview: (preview) => bindings.current && bindings.current.showPreview(preview)
    });

    bindings.current = createDomBindings({ document: doc, host, controller });
    return { controller, bindings: bindings.current, machine };
  }

  window.B66VoiceInput = {
    STATE,
    MODE,
    DEFAULT_MODE,
    STATUS_TEXT,
    NOTICE_TEXT,
    createVoiceController,
    createDomBindings,
    init
  };
})();
