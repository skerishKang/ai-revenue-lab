/* #4647: Meeting capture is independent of Chat/Claw message/STT transport.
 * Browser MediaRecorder + SpeechRecognition; no provider keys or server uploads.
 * Media belongs to the user until a separately authorized Drive WRITE seam exists.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module && module.exports) module.exports = api;
  if (root) root.PadiemMeetingCapture = api;
  if (root && root.document) api.mount(root, root.document);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const MODES = Object.freeze(["record", "transcribe", "both"]);
  const MAX_AUDIO_BYTES = 180 * 1024 * 1024;
  const MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
  const MEETING_INTENT = /^(?:(?:지금|이제|곧|오늘)\s*)?(?:(?:회의|미팅).{0,35})?(?:회의록\s*(?:준비|작성|만들)|녹음\s*(?:준비|시작)|전사\s*(?:준비|시작))(?:해\s*줘|해\s*주세요|해줘|해라|해|\s*부탁해|\s*시작해|\s*줘|\s*주세요)?[.!?\s]*$/u;

  function isMeetingIntent(text) {
    return typeof text === "string" && MEETING_INTENT.test(text.trim());
  }
  function chooseMime(Recorder) {
    if (!Recorder || typeof Recorder.isTypeSupported !== "function") return "";
    return MIME_TYPES.find((type) => Recorder.isTypeSupported(type)) || "";
  }
  function createController(host) {
    const report = typeof host.report === "function" ? host.report : () => {};
    const change = typeof host.change === "function" ? host.change : () => {};
    let active = false, pending = false, mode = "", stream = null, recorder = null;
    let recognizer = null, stopPromise = null, restartTimer = null, recognitionFailed = false;
    let recognitionEndResolver = null, committedIndices = new Set();
    let parts = [], bytes = 0, lines = [], interim = "", artifact = null, startedAt = 0;
    const snapshot = () => Object.freeze({
      active, pending, mode, transcript: lines.join("\n"), interim, artifact,
      startedAt, bytes, recognitionFailed,
    });
    const notify = () => change(snapshot());
    const stopTracks = () => {
      if (stream?.getTracks) stream.getTracks().forEach((track) => track.stop());
      stream = null;
    };
    async function start(selected) {
      if (!MODES.includes(selected)) throw new Error("invalid_meeting_mode");
      if (active || pending) throw new Error("meeting_already_active");
      const Recorder = host.MediaRecorder, Recognition = host.SpeechRecognition;
      if (selected !== "transcribe" && typeof Recorder !== "function") throw new Error("recording_not_supported");
      if (selected !== "record" && typeof Recognition !== "function") throw new Error("live_transcription_not_supported");
      pending = true;
      mode = selected;
      lines = []; interim = ""; parts = []; bytes = 0; artifact = null;
      committedIndices = new Set();
      recognitionFailed = false;
      try {
        if (selected !== "transcribe") {
          if (!host.mediaDevices?.getUserMedia) throw new Error("microphone_not_supported");
          stream = await host.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
          const mimeType = chooseMime(Recorder);
          recorder = mimeType ? new Recorder(stream, { mimeType }) : new Recorder(stream);
          recorder.ondataavailable = (event) => {
            if (!event?.data?.size) return;
            parts.push(event.data);
            bytes += event.data.size;
            if (bytes >= MAX_AUDIO_BYTES && active) {
              report("recording_size_limit");
              void stop();
            }
          };
          recorder.onerror = () => report("recording_error");
          recorder.start(10000);
        }
        active = true;
        startedAt = Date.now();
        if (selected !== "record") {
          recognizer = new Recognition();
          recognizer.lang = "ko-KR";
          recognizer.continuous = true;
          recognizer.interimResults = true;
          recognizer.onresult = (event) => {
            let provisional = "";
            for (let i = event.resultIndex || 0; i < event.results.length; i += 1) {
              const row = event.results[i];
              const value = String(row?.[0]?.transcript || "").trim();
              if (!value) continue;
              if (row.isFinal) {
                if (!committedIndices.has(i)) { lines.push(value); committedIndices.add(i); }
              } else provisional += (provisional ? " " : "") + value;
            }
            interim = provisional;
            notify();
          };
          recognizer.onerror = (event) => {
            recognitionFailed = true;
            interim = "";
            report("transcription_error:" + String(event?.error || "unknown"));
            if (mode === "transcribe") void stop();
            notify();
          };
          recognizer.onend = () => {
            if (recognitionEndResolver) { recognitionEndResolver(); recognitionEndResolver = null; }
            if (active && !recognitionFailed && mode !== "record") {
              committedIndices = new Set();
              restartTimer = setTimeout(() => {
                restartTimer = null;
                if (!active || recognitionFailed) return;
                try { recognizer.start(); }
                catch (_) { recognitionFailed = true; report("transcription_restart_failed"); notify(); }
              }, 350);
            }
          };
          try { recognizer.start(); }
          catch (error) {
            recognitionFailed = true;
            report("transcription_start_failed");
            if (selected === "transcribe") throw error;
          }
        }
        if (!recognitionFailed) report(selected === "record" ? "recording" : "meeting_active");
        return snapshot();
      } catch (error) {
        active = false;
        try { recognizer?.abort?.(); } catch (_) {}
        try { if (recorder?.state !== "inactive") recorder?.stop?.(); } catch (_) {}
        stopTracks(); recorder = null; recognizer = null;
        report("meeting_start_failed");
        throw error;
      } finally {
        pending = false;
        notify();
      }
    }
    async function stop() {
      if (stopPromise) return stopPromise;
      if (!active) return snapshot();
      active = false;
      clearTimeout(restartTimer);
      restartTimer = null;
      let recognitionDone = Promise.resolve();
      if (recognizer) {
        const currentRecognition = recognizer;
        recognitionDone = new Promise((resolve) => {
          const timeout = setTimeout(() => { recognitionEndResolver = null; resolve(); }, 1200);
          recognitionEndResolver = () => { clearTimeout(timeout); resolve(); };
        });
        try { currentRecognition.stop(); }
        catch (_) { recognitionEndResolver?.(); recognitionEndResolver = null; }
        recognizer = null;
      }
      stopPromise = (async () => {
        await recognitionDone;
        if (recorder) {
          const current = recorder;
          if (current.state !== "inactive") {
            await new Promise((resolve) => {
              const prior = current.onstop;
              current.onstop = (event) => { if (typeof prior === "function") prior(event); resolve(); };
              try { current.stop(); } catch (_) { resolve(); }
            });
          }
          if (parts.length) artifact = new Blob(parts, { type: current.mimeType || "audio/webm" });
          recorder = null;
        }
        stopTracks();
        interim = "";
        report(recognitionFailed ? "meeting_stopped_with_transcription_error" : "meeting_stopped");
        notify();
        return snapshot();
      })();
      try { return await stopPromise; }
      finally { stopPromise = null; }
    }
    function discard() {
      if (active || pending || stopPromise) throw new Error("meeting_active");
      parts = []; lines = []; interim = ""; artifact = null; bytes = 0; startedAt = 0; mode = "";
      recognitionFailed = false;
      notify();
    }
    return Object.freeze({ start, stop, discard, snapshot });
  }

  function mount(win, doc) {
    // The first-class sidebar entry and central workspace are static HTML.
    // Never append a second nav button or create a modal at runtime.
    const trigger = doc.getElementById("meetingNavButton");
    const dialog = doc.getElementById("meetingView");
    if (!trigger || !dialog) return null;
    const find = (id) => doc.getElementById(id);
    const status = find("meetingStatus"), text = find("meetingTranscript");
    const startButton = find("meetingStart"), stopButton = find("meetingStop");
    const downloadAudio = find("meetingDownloadAudio"), downloadText = find("meetingDownloadText");
    const closeButton = find("meetingClose"), interim = find("meetingInterim");
    const draftInClaw = find("meetingDraftInClaw");
    const driveAudio = find("meetingSaveAudioDrive"), driveText = find("meetingSaveTextDrive");
    let uploadInFlight = false;
    let uploadAbort = null;
    let signedIn = false, audio = null;
    const statuses = {
      recording: "녹음 중 · 마이크가 켜져 있습니다.",
      meeting_active: "회의 진행 중 · 마이크가 켜져 있습니다.",
      meeting_stopped: "회의 종료 · 결과를 확인하고 다운로드하세요.",
      meeting_stopped_with_transcription_error: "회의 종료 · 전사가 일부 중단됐습니다. 녹음 파일을 확인하세요.",
      recording_error: "녹음 장치 오류가 발생했습니다. 자료를 확인하세요.",
      recording_size_limit: "녹음 용량 한도에 도달하여 종료합니다.",
      meeting_start_failed: "마이크를 시작하지 못했습니다. 권한 또는 브라우저를 확인하세요.",
      transcription_start_failed: "실시간 전사 시작에 실패했습니다. 녹음이 켜져 있다면 계속 기록됩니다.",
      transcription_restart_failed: "실시간 전사가 중단됐습니다. 녹음이 켜져 있다면 계속 기록됩니다.",
    };
    const say = (value) => {
      status.textContent = statuses[value] || (value.startsWith("transcription_error")
        ? "실시간 전사가 중단됐습니다. 녹음이 켜져 있다면 계속 기록됩니다."
        : value);
    };
    const controller = createController({
      MediaRecorder: win.MediaRecorder,
      SpeechRecognition: win.SpeechRecognition || win.webkitSpeechRecognition,
      mediaDevices: win.navigator?.mediaDevices,
      report: say,
      change: (state) => {
        startButton.disabled = state.active || state.pending || !signedIn;
        stopButton.disabled = !state.active;
        dialog.querySelectorAll('input[name="meetingMode"]').forEach((radio) => { radio.disabled = state.active || state.pending; });
        if (!state.active && state.artifact) audio = state.artifact;
        // Preserve user edits after stop; the recognizer owns text only while active.
        if (state.active) text.value = state.transcript;
        interim.textContent = state.interim ? "인식 중: " + state.interim : "";
        downloadAudio.disabled = state.active || !audio;
        downloadText.disabled = state.active || !text.value.trim();
        draftInClaw.disabled = state.active || !text.value.trim() || !signedIn;
        driveAudio.disabled = state.active || !audio || !signedIn || uploadInFlight;
        driveText.disabled = state.active || !text.value.trim() || !signedIn || uploadInFlight;
      },
    });
    function download(blob, name) {
      const url = win.URL.createObjectURL(blob);
      const anchor = doc.createElement("a");
      anchor.href = url; anchor.download = name;
      anchor.style.display = "none"; doc.body.appendChild(anchor);
      anchor.click(); anchor.remove();
      win.setTimeout(() => win.URL.revokeObjectURL(url), 60000);
    }
    function open() {
      if (!signedIn) { say("PADIEM 로그인 후 회의록을 이용할 수 있습니다."); return false; }
      const shell = doc.querySelector(".app-shell");
      if (!shell) return false;
      shell.dataset.state = "meeting";
      dialog.hidden = false;
      trigger.setAttribute("aria-current", "page");
      // Use the same app.js view synchronizer as Claw, Calendar, Connectors.
      win.dispatchEvent(new win.CustomEvent("padiem:meeting-open"));
      shell?.classList.remove("sidebar-open");
      find("mobileMenu")?.setAttribute("aria-expanded", "false");
      if (find("sidebarScrim")) find("sidebarScrim").hidden = true;
      return true;
    }
    trigger.addEventListener("click", open);
    // Keep the recording controls in view; changing sidebar workspaces while
    // microphone capture is live could otherwise conceal the active recorder.
    doc.addEventListener("click", (event) => {
      if (!controller.snapshot().active && !uploadInFlight) return;
      const nav = event.target?.closest?.(".side-nav .side-item, #newChatButton");
      if (!nav || nav === trigger) return;
      event.preventDefault();
      event.stopImmediatePropagation?.();
      say("회의 녹음 또는 업로드를 종료한 뒤 다른 화면으로 이동할 수 있습니다.");
    }, true);
    win.addEventListener("beforeunload", (event) => {
      if (!controller.snapshot().active && !uploadInFlight) return;
      event.preventDefault();
      event.returnValue = "";
    });
    win.addEventListener("padiem:auth-state", (event) => {
      signedIn = event?.detail?.authenticated === true;
      trigger.disabled = !signedIn;
      startButton.disabled = !signedIn || controller.snapshot().active;
      if (!signedIn) {
        uploadAbort?.abort();
        audio = null; text.value = ""; interim.textContent = "";
        dialog.hidden = true;
        trigger.setAttribute("aria-current", "false");
        const discard = () => {
          audio = null; text.value = ""; downloadAudio.disabled = true; downloadText.disabled = true;
          draftInClaw.disabled = true;
          driveAudio.disabled = true; driveText.disabled = true;
          controller.discard();
        };
        if (controller.snapshot().active) void controller.stop().then(discard);
        else discard();
        say("로그아웃되어 회의 데이터를 지웠습니다.");
      }
    });
    closeButton.addEventListener("click", () => {
      if (controller.snapshot().active || uploadInFlight) {
        say("회의 녹음이나 저장을 종료한 뒤 Claw로 돌아갈 수 있습니다.");
        return;
      }
      find("clawNavButton")?.click();
    });
    startButton.addEventListener("click", async () => {
      if (!signedIn || uploadInFlight) return;
      if ((audio || text.value.trim()) && typeof win.confirm === "function" &&
          !win.confirm("이전 회의 결과가 지워집니다. 파일을 보관했습니까?")) return;
      audio = null; text.value = ""; downloadAudio.disabled = true; downloadText.disabled = true;
      const selected = dialog.querySelector('input[name="meetingMode"]:checked')?.value;
      startButton.disabled = true;
      try { await controller.start(selected); }
      catch (error) { say(error.message === "live_transcription_not_supported" ? "이 브라우저는 실시간 받아쓰기를 지원하지 않습니다." : statuses.meeting_start_failed); }
      finally { if (!controller.snapshot().active) startButton.disabled = !signedIn; }
    });
    stopButton.addEventListener("click", async () => {
      stopButton.disabled = true;
      const state = await controller.stop();
      text.value = state.transcript;
      audio = state.artifact;
      downloadAudio.disabled = !audio;
      downloadText.disabled = !text.value.trim();
      draftInClaw.disabled = !text.value.trim();
      driveAudio.disabled = !audio;
      driveText.disabled = !text.value.trim();
    });
    text.addEventListener("input", () => {
      const unavailable = controller.snapshot().active || !text.value.trim();
      downloadText.disabled = unavailable;
      draftInClaw.disabled = unavailable || !signedIn;
      driveText.disabled = unavailable || !signedIn || uploadInFlight;
    });
    draftInClaw.addEventListener("click", () => {
      if (!signedIn || uploadInFlight || controller.snapshot().active || !text.value.trim()) return;
      const composer = find("messageInput");
      const clawNav = find("clawNavButton");
      const prompt = "다음 회의 전사문을 바탕으로 회의록 초안을 작성해 주세요. 원문에 없는 사실·담당자·기한을 추정하지 말고, 주요 논의·결정사항·할 일 후보·미정 사항을 구분해 주세요.\\n\\n" + text.value.trim();
      if (!composer || !clawNav || prompt.length > 9000 || (composer.maxLength > 0 && prompt.length > composer.maxLength)) {
        say("전사문이 너무 길거나 Claw 입력창을 열 수 없습니다. TXT를 내려받아 파일로 전달하세요.");
        return;
      }
      clawNav.click();
      if (doc.querySelector(".app-shell")?.dataset.state !== "claw") { say("Claw 화면을 열 수 없습니다."); return; }
      composer.value = prompt;
      composer.dispatchEvent(new win.Event("input", { bubbles: true }));
      // setNavActive() from the Claw navigation hides the meeting workbench.
      composer.focus?.();
      // Human chooses Send through the existing authorized composer form, never automatic.
    });
    async function storeInDrive(kind) {
      if (!signedIn || uploadInFlight || controller.snapshot().active) return;
      const blob = kind === "audio"
        ? (audio ? new Blob([audio], { type: audio.type.split(";", 1)[0] }) : null)
        : (text.value.trim() ? new Blob([text.value], { type: "text/plain" }) : null);
      if (!blob) return;
      const provider = win.PadiemMeetingDriveUpload;
      if (!provider?.upload) { say("Google Drive 업로드를 사용할 수 없습니다. 다운로드하여 보관해 주세요."); return; }
      uploadInFlight = true;
      uploadAbort = new win.AbortController();
      startButton.disabled = true;
      driveAudio.disabled = true;
      driveText.disabled = true;
      say("Google Drive에 저장하는 중입니다. 파일은 PADIEM 서버에 저장되지 않습니다.");
      try {
        const result = await provider.upload(blob, { signal: uploadAbort.signal });
        if (!signedIn) return;
        // Report success only on real Drive files.create receipt, never on local completion.
        status.replaceChildren(doc.createTextNode("고객 Google Drive 저장 완료 · "));
        const link = doc.createElement("a");
        link.href = "https://drive.google.com/file/d/" + encodeURIComponent(result.fileId) + "/view";
        link.target = "_blank"; link.rel = "noopener noreferrer";
        link.textContent = "Google Drive에서 열기";
        status.append(link);
      } catch (error) {
        if (!signedIn) return;
        const code = error?.code || "";
        say(code === "drive_write_unavailable"
          ? "Google Drive 쓰기 권한이 아직 연결되지 않았습니다. 파일을 먼저 다운로드하여 보관해 주세요."
          : "Google Drive 저장에 실패했습니다. 녹음·전사 원본은 이 화면에 남아 있습니다. 파일을 다운로드해 보관해 주세요.");
      } finally {
        uploadInFlight = false;
        uploadAbort = null;
        startButton.disabled = !signedIn || controller.snapshot().active;
        driveAudio.disabled = !signedIn || !audio || controller.snapshot().active;
        driveText.disabled = !signedIn || !text.value.trim() || controller.snapshot().active;
      }
    }
    driveAudio.addEventListener("click", () => { void storeInDrive("audio"); });
    driveText.addEventListener("click", () => { void storeInDrive("text"); });
    downloadAudio.addEventListener("click", () => {
      if (audio && !controller.snapshot().active) {
        download(audio, "padiem-meeting-" + Date.now() + (audio.type.includes("mp4") ? ".m4a" : ".webm"));
      }
    });
    downloadText.addEventListener("click", () => {
      if (text.value.trim() && !controller.snapshot().active) {
        download(new Blob([text.value], { type: "text/plain;charset=utf-8" }), "padiem-meeting-" + Date.now() + ".txt");
      }
    });
    // Called from the shared Claw form before any model request. Only explicit meeting setup
    // intents are diverted. Other prompts continue to the existing P01 route.
    function tryOpenFromClaw(value) {
      const shell = doc.querySelector(".app-shell");
      if (!signedIn || shell?.dataset.state !== "claw" || !isMeetingIntent(value)) return false;
      return open();
    }
    return Object.freeze({ open, tryOpenFromClaw, controller });
  }
  return Object.freeze({ MODES, isMeetingIntent, chooseMime, createController, mount });
});
