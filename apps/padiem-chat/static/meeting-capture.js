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
    const sidebar = doc.querySelector("#workspaceNav") || doc.querySelector(".side-nav");
    if (!sidebar || doc.getElementById("meetingNavButton")) return null;
    const trigger = doc.createElement("button");
    trigger.type = "button";
    trigger.className = "side-item";
    trigger.id = "meetingNavButton";
    trigger.setAttribute("aria-controls", "meetingDialog");
    trigger.setAttribute("aria-haspopup", "dialog");
    trigger.disabled = true;
    trigger.innerHTML = '<span class="side-icon" aria-hidden="true">◉</span><span>회의록</span>';
    sidebar.appendChild(trigger);
    const css = doc.createElement("link");
    css.rel = "stylesheet"; css.href = "./meeting-capture.css";
    doc.head.appendChild(css);
    const dialog = doc.createElement("dialog");
    dialog.id = "meetingDialog";
    dialog.className = "meeting-dialog";
    dialog.setAttribute("aria-labelledby", "meetingTitle");
    dialog.innerHTML = [
      '<div class="meeting-panel">',
      ' <header class="meeting-header"><div><p>PADIEM CLAW</p><h2 id="meetingTitle">회의록</h2></div><button type="button" id="meetingClose" aria-label="회의록 닫기">×</button></header>',
      ' <p class="meeting-help">녹음·실시간 받아쓰기는 별도 기능입니다. 시작을 누르면 마이크 사용 권한을 요청합니다. 브라우저 음성 인식은 브라우저 제공자의 외부 서비스를 사용할 수 있습니다.</p>',
      ' <fieldset class="meeting-modes"><legend>회의 방식 선택</legend>',
      '  <label><input type="radio" name="meetingMode" value="record" checked> 녹음만</label>',
      '  <label><input type="radio" name="meetingMode" value="transcribe"> 실시간 전사만</label>',
      '  <label><input type="radio" name="meetingMode" value="both"> 녹음 + 실시간 전사</label>',
      ' </fieldset>',
      ' <div class="meeting-controls"><button type="button" id="meetingStart">회의 시작</button><button type="button" id="meetingStop" disabled>회의 종료</button></div>',
      ' <p class="meeting-status" id="meetingStatus" role="status" aria-live="polite">대기 중 · 아직 녹음하지 않았습니다.</p>',
      ' <label for="meetingTranscript">전사 원문 (편집 가능)</label><textarea id="meetingTranscript" rows="8" placeholder="실시간 전사 내용을 이곳에서 확인할 수 있습니다."></textarea>',
      ' <p id="meetingInterim" role="status" class="meeting-interim"></p>',
      ' <div class="meeting-exports"><button type="button" id="meetingDownloadAudio" disabled>녹음 파일 다운로드</button><button type="button" id="meetingDownloadText" disabled>전사 TXT 다운로드</button></div>',
      ' <p class="meeting-storage-note">Google Drive 직접 저장은 쓰기 권한 연결이 필요합니다. 현재는 파일을 기기에 다운로드해 보관할 수 있습니다. 서버에 원본을 올리지 않으며 새로고침하면 임시 기록이 사라집니다.</p>',
      '</div>',
    ].join("");
    doc.body.appendChild(dialog);
    const find = (id) => doc.getElementById(id);
    const status = find("meetingStatus"), text = find("meetingTranscript");
    const startButton = find("meetingStart"), stopButton = find("meetingStop");
    const downloadAudio = find("meetingDownloadAudio"), downloadText = find("meetingDownloadText");
    const closeButton = find("meetingClose"), interim = find("meetingInterim");
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
      if (!dialog.open && typeof dialog.showModal === "function") dialog.showModal();
      else if (!dialog.open) dialog.setAttribute("open", "");
      trigger.setAttribute("aria-expanded", "true");
      const shell = doc.querySelector(".app-shell");
      shell?.classList.remove("sidebar-open");
      find("mobileMenu")?.setAttribute("aria-expanded", "false");
      if (find("sidebarScrim")) find("sidebarScrim").hidden = true;
      return true;
    }
    trigger.addEventListener("click", open);
    win.addEventListener("beforeunload", (event) => {
      if (!controller.snapshot().active) return;
      event.preventDefault();
      event.returnValue = "";
    });
    win.addEventListener("padiem:auth-state", (event) => {
      signedIn = event?.detail?.authenticated === true;
      trigger.disabled = !signedIn;
      startButton.disabled = !signedIn || controller.snapshot().active;
      if (!signedIn) {
        audio = null; text.value = ""; interim.textContent = "";
        if (dialog.open) dialog.close?.();
        trigger.setAttribute("aria-expanded", "false");
        const discard = () => {
          audio = null; text.value = ""; downloadAudio.disabled = true; downloadText.disabled = true;
          controller.discard();
        };
        if (controller.snapshot().active) void controller.stop().then(discard);
        else discard();
        say("로그아웃되어 회의 데이터를 지웠습니다.");
      }
    });
    closeButton.addEventListener("click", () => {
      if (controller.snapshot().active) { say("녹음을 종료한 후 닫을 수 있습니다."); return; }
      dialog.close?.(); trigger.setAttribute("aria-expanded", "false"); trigger.focus();
    });
    dialog.addEventListener("cancel", (event) => {
      if (controller.snapshot().active) { event.preventDefault(); say("녹음을 종료한 후 닫을 수 있습니다."); }
    });
    dialog.addEventListener("close", () => trigger.setAttribute("aria-expanded", "false"));
    startButton.addEventListener("click", async () => {
      if (!signedIn) return;
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
    });
    text.addEventListener("input", () => { downloadText.disabled = controller.snapshot().active || !text.value.trim(); });
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
