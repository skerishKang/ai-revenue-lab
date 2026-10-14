// Browser-only TTS primitive (#4649). No provider endpoint or credentials.
// An explicit UI Start action is required before speaking; default is OFF.
(function (root) {
  "use strict";
  const MAX_CHUNK = 180;
  const MAX_QUEUE = 8;
  const MAX_TEXT = MAX_CHUNK * MAX_QUEUE;

  function safeText(value) {
    if (typeof value !== "string") return "";
    return value.replace(/```[\s\S]*?```/g, " code block omitted ")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/^#{1,6}\s+/gm, "")
      .replace(/[*_~]/g, "")
      .replace(/\s+/g, " ").trim().slice(0, 10000);
  }
  function supported() {
    return !!(root && root.speechSynthesis && root.SpeechSynthesisUtterance);
  }
  function chunksOf(value) {
    const words = String(value || "").trim().split(/\s+/);
    const result = [];
    let row = "";
    words.forEach(function (word) {
      while (word.length > MAX_CHUNK) {
        if (row) { result.push(row); row = ""; }
        result.push(word.slice(0, MAX_CHUNK));
        word = word.slice(MAX_CHUNK);
      }
      if (!word) return;
      if (row && row.length + word.length + 1 > MAX_CHUNK) {
        result.push(row);
        row = word;
      } else {
        row = row ? row + " " + word : word;
      }
    });
    if (row) result.push(row);
    return result;
  }
  function create(opts) {
    opts = opts || {};
    const lang = opts.lang || "ko-KR";
    const rate = opts.rate == null ? 1 : opts.rate;
    const pitch = opts.pitch == null ? 1 : opts.pitch;
    const volume = opts.volume == null ? 1 : opts.volume;
    const onStatus = typeof opts.onStatus === "function" ? opts.onStatus : function () {};
    const onStart = typeof opts.onStart === "function" ? opts.onStart : function () {};
    const onEnd = typeof opts.onEnd === "function" ? opts.onEnd : function () {};
    const onError = typeof opts.onError === "function" ? opts.onError : function () {};
    let preferredVoiceName = String(opts.voiceName || "");
    let userStartSeen = false, busy = false, generation = 0, queue = [];
    function report(status) {
      try { onStatus({status: status, supported: supported(), busy: busy,
        queue: queue.length, userStartSatisfied: userStartSeen,
        speaking: supported() ? !!root.speechSynthesis.speaking : false}); }
      catch (_) { /* UI observation is optional */ }
    }
    function error(reason) {
      try { onError({reason: reason}); } catch (_) { /* no transport side effects */ }
      report(reason);
    }
    function availableVoices() {
      if (!supported()) return [];
      try { return root.speechSynthesis.getVoices() || []; } catch (_) { return []; }
    }
    function findVoice() {
      const voices = availableVoices();
      const match = function (v) {
        return v && String(v.lang || "").toLowerCase().split("-")[0] ===
          lang.toLowerCase().split("-")[0];
      };
      if (preferredVoiceName) {
        const selected = voices.find(function (v) { return v.name === preferredVoiceName && match(v); });
        if (selected) return selected;
      }
      return voices.find(function (v) { return v.lang === lang; }) ||
        voices.find(match) || null;
    }
    function finish() {
      busy = false;
      const next = queue.shift();
      if (next) { run(next); return; }
      report("ended");
      try { onEnd(); } catch (_) {}
    }
    function run(text) {
      if (!supported() || !userStartSeen) { error("not-started-or-unsupported"); return false; }
      const voice = findVoice();
      if (!voice) { error("no-matching-voice"); return false; }
      if (busy) { queue.push(text); return true; }
      busy = true;
      const thisGeneration = ++generation;
      const utterance = new root.SpeechSynthesisUtterance(text);
      utterance.lang = lang;
      utterance.voice = voice;
      utterance.rate = rate;
      utterance.pitch = pitch;
      utterance.volume = volume;
      utterance.onstart = function () {
        if (thisGeneration !== generation) return;
        report("speaking");
        try { onStart({text: text, voice: voice.name}); } catch (_) {}
      };
      utterance.onend = function () {
        if (thisGeneration !== generation) return;
        finish();
      };
      utterance.onerror = function (event) {
        if (thisGeneration !== generation) return;
        // Error is NOT successful playback completion; do not chain or reopen mic.
        ++generation; queue = []; busy = false;
        error(event && event.error ? event.error : "speech-error");
      };
      try {
        root.speechSynthesis.speak(utterance);
        return true;
      } catch (_) {
        if (thisGeneration === generation) {
          ++generation; queue = []; busy = false;
          error("speech-throw");
        }
        return false;
      }
    }
    function speakText(value) {
      const text = safeText(value);
      if (!text) return false;
      if (!supported() || !userStartSeen) { error("not-started-or-unsupported"); return false; }
      if (!findVoice()) { error("no-matching-voice"); return false; }
      if (text.length > MAX_TEXT) { error("text-too-long"); return false; }
      const chunks = chunksOf(text);
      if (chunks.length + queue.length + (busy ? 1 : 0) > MAX_QUEUE) {
        error("queue-full"); return false;
      }
      chunks.forEach(function (chunk) { run(chunk); });
      return true;
    }
    function cancel() {
      ++generation; queue = []; busy = false;
      if (supported()) { try { root.speechSynthesis.cancel(); } catch (_) {} }
      report("cancelled");
    }
    function stopOutput() { userStartSeen = false; cancel(); }
    function start() { userStartSeen = true; report("started"); }
    function setVoiceName(value) { preferredVoiceName = String(value || ""); report("voice-selected"); }
    const api = {
      isSupported: supported, availableVoices: availableVoices, speakText: speakText,
      cancel: cancel, start: start, stopOutput: stopOutput, setVoiceName: setVoiceName,
      getState: function () { return {
        supported: supported(), busy: busy, queued: queue.length,
        userStartSatisfied: userStartSeen, lang: lang,
        voiceName: preferredVoiceName || "(browser-selected)"
      }; }
    };
    return api;
  }
  const api = {create: create, safeText: safeText, supported: supported};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  (typeof globalThis !== "undefined" ? globalThis : root).PadiemVoiceTTSOutput = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
