// Connector vocabulary — one place for the display names and the four
// connection states every connector surface reads: the Chat home card, the
// Claw home tiles, the Connectors page cards and the composer chip. The
// runtime authority is untouched; this module only decides which words a
// state is shown with, so the same state never speaks two ways.
(() => {
  "use strict";

  const NAMES = Object.freeze({
    computer: Object.freeze({ ko: "내 컴퓨터", en: "My computer" }),
    drive: Object.freeze({ ko: "Google Drive", en: "Google Drive" }),
    github: Object.freeze({ ko: "GitHub", en: "GitHub" }),
    gmail: Object.freeze({ ko: "Gmail", en: "Gmail" }),
    slack: Object.freeze({ ko: "Slack", en: "Slack" }),
    telegram: Object.freeze({ ko: "Telegram", en: "Telegram" }),
    calendar: Object.freeze({ ko: "Google Calendar", en: "Google Calendar" }),
  });

  // The four states. A surface that has one of these states shows exactly
  // this line; no surface invents its own sentence for the same state.
  const STATUS = Object.freeze({
    connected: Object.freeze({ ko: "● 연결됨", en: "● Connected" }),
    disconnected: Object.freeze({ ko: "○ 연결 안 됨", en: "○ Not connected" }),
    checking: Object.freeze({ ko: "확인 중…", en: "Checking…" }),
    failed: Object.freeze({ ko: "확인 실패 · 다시 시도", en: "Check failed · Try again" }),
  });

  function lang() {
    return String(document.documentElement.lang || "ko").toLowerCase().startsWith("en") ? "en" : "ko";
  }

  function pick(table, key) {
    const item = table[key];
    return item ? item[lang()] : "";
  }

  window.PadiemConnectorVocabulary = Object.freeze({
    names: NAMES,
    statuses: STATUS,
    name: (key) => pick(NAMES, key),
    status: (key) => pick(STATUS, key),
  });
})();
