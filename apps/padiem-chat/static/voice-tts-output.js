// Default browser TTS output module for #4649.
// Uses only window.speechSynthesis / SpeechSynthesisUtterance. No paid
// provider API, key, or external network call is ever used here.
(function (global) {
  "use strict";

  function safeText(value) {
    if (typeof value !== "string") return "";
    // SpeechSynthesis needs plain text. Keep a simple, bounded text payload.
    return value
      .replace(/```[\s\S]*?```/g, " code block omitted ")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/^#{1,6}\s+/gm, "")
      .replace(/[*_~]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 10000);
  }

  function supported() {
    return (
      typeof global !== "undefined" &&
      typeof global.speechSynthesis !== "undefined" &&
      typeof global.SpeechSynthesisUtterance !== "undefined"
    );
  }

  function create(options) {
    const opts = options || {};
    const lang = opts.lang || "ko-KR";
    const rate = opts.rate != null ? opts.rate : 1.0;
    const pitch = opts.pitch != null ? opts.pitch : 1.0;
    const volume = opts.volume != null ? opts.volume : 1.0;
    const onStatus = typeof opts.onStatus === "function" ? opts.onStatus : function () {};
    const onEnd = typeof opts.onEnd === "function" ? opts.onEnd : function () {};
    const onError = typeof opts.onError === "function" ? opts.onError : function () {};
    const onStart = typeof opts.onStart === "function" ? opts.onStart : function () {};

    let queue = [];
    let busy = false;
    let playGeneration = 0;
    let userStartSeen = false;
    let preferredVoiceName = opts.voiceName || "";


    function report(status) {
      onStatus({
        supported: supported(),
        status: status,
        busy: busy,
        queue: queue.length,
        speaking: supported() ? global.speechSynthesis.speaking : false,
        userStartSatisfied: userStartSeen,
        voiceName: preferredVoiceName || "(browser-selected)",
      });
    }

    function availableVoices() {
      if (!supported()) return [];
      try {
        return global.speechSynthesis.getVoices() || [];
      } catch (error) {
        return [];
      }
    }

    function findVoice() {
      const voices = availableVoices();
      if (!voices.length) return null;
      if (preferredVoiceName) {
        const match = voices.find(function (voice) {
          return voice.name === preferredVoiceName;
        });
        if (match) return match;
      }
      const exact = voices.find(function (voice) {
        return voice.lang === lang;
      });
      if (exact) return exact;
      const prefix = lang.split("-")[0];
      const partial = voices.find(function (voice) {
        return String(voice.lang || "").split("-")[0] === prefix;
      });
      return partial || voices[0] || null;
    }

    function finishCurrent() {
      busy = false;
      const next = queue.shift();
      if (next) {
        run(next, true);
        return;
      }
      report("ended");
      onEnd();
    }

    function run(text, alreadyQueued) {
      if (!supported() || !text) {
        report("unsupported");
        return false;
      }
      if (!userStartSeen) {
        report("needs-user-gesture");
        onError({ reason: "user-gesture-required", text: text });
        return false;
      }
      if (busy) {
        queue.push(text);
        return true;
      }
      busy = true;
      const currentGeneration = ++playGeneration;
      const utterance = new global.SpeechSynthesisUtterance(text);
      utterance.lang = lang;
      utterance.rate = rate;
      utterance.pitch = pitch;
      utterance.volume = volume;
      const voice = findVoice();
      if (voice) utterance.voice = voice;
      onStart({ text: text, voice: voice ? voice.name : null });
      report("speaking");
      utterance.onend = function () {
        if (currentGeneration !== playGeneration) return;
        finishCurrent();
      };
      utterance.onerror = function (event) {
        if (currentGeneration !== playGeneration) return;
        const reason = event && event.error ? event.error : "unknown";
        onError({ reason: reason, text: text });
        finishCurrent();
      };
      try {
        global.speechSynthesis.speak(utterance);
        return true;
      } catch (error) {
        onError({ reason: "speak-failed", error: error });
        finishCurrent();
        return false;
      }
    }

    function chunkText(value) {
      const chunks = [];
      const parts = String(value || "").split(/(?<=[.!??])\s+/);
      let current = "";
      parts.forEach(function (part) {
        if (!part) return;
        if ((current + " " + part).trim().length > 180) {
          if (current.trim()) chunks.push(current.trim());
          current = part;
        } else {
          current = (current ? current + " " : "") + part;
        }
      });
      if (current.trim()) chunks.push(current.trim());
      return chunks.length ? chunks : [String(value || "").trim()];
    }

    function speakText(value) {
      const text = safeText(value);
      if (!text) return false;
      if (!supported()) return false;
      const chunks = chunkText(text).slice(0, 8);
      let ok = true;
      chunks.forEach(function (chunk, index) {
        ok = run(chunk, index !== 0) && ok;
      });
      return ok;
    }

    function cancel() {
      playGeneration += 1;
      if (supported()) {
        try {
          global.speechSynthesis.cancel();
        } catch (error) {
          // Best effort only.
        }
      }
      queue = [];
      busy = false;
      report("cancelled");
    }

    function setVoiceName(name) {
      preferredVoiceName = String(name || "");
      report("voice-selected");
    }

    function setUserGestureSeen(seen) {
      userGestureSeen = seen === true;
      report("start-state");
    }

    return {
      isSupported: supported,
      availableVoices: availableVoices,
      speakText: speakText,
      cancel: cancel,
      start: function () { userStartSeen = true; report("started"); },
      stopOutput: function () { userStartSeen = false; cancel(); },
      setUserStartSeen: setUserGestureSeen,
      getState: function () {
        return {
          supported: supported(),
          speaking: supported() ? global.speechSynthesis.speaking : false,
          busy: busy,
          queued: queue.length,
          lang: lang,
          userStartSatisfied: userStartSeen,
          voiceName: preferredVoiceName || "(browser-selected)",
        };
      },
    };
  }

  const exported = { create: create, safeText: safeText, supported: supported };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = exported;
  }
  (typeof globalThis !== "undefined" ? globalThis : global).PadiemVoiceTTSOutput = exported;
})(typeof globalThis !== "undefined" ? globalThis : this);