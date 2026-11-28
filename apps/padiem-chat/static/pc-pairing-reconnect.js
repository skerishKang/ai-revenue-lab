// #8898 — the offline PC row's own 다시 연결 action, as its own module.
//
// The pairing card (pc-pairing-card.js) draws the rows and stays under its
// #7216 size cap; this module watches the drawn list and gives exactly the
// offline rows — state "active" whose Mesh agent is not connected, which the
// card already paints as the 오프라인 badge — a visible row-level button.
//
// What clicking it does: nothing new on the server. It calls the card's own
// public connect action (window.padiemPcPairing.connect), the same flow as
// 이 PC 연결하기: a fresh connect program download, the 10-minute clock, and
// the self-checking wait. When the new link lands, the server supersedes the
// owner's older links for the same machine name (#6694 C), so reconnecting
// never leaves a duplicate ghost row. Nothing here promises a remote
// wake-up — the person at that PC runs the program.
(() => {
  "use strict";

  const SECTION_ID = "pcPairingSection";
  const BUTTON_CLASS = "pc-pairing-reconnect";
  const COPY = Object.freeze({
    ko: {
      reconnect: "다시 연결",
      help: "연결 프로그램을 다시 내려받아 그 PC에서 열면 연결이 새로 만들어지고 옛 연결 기록은 저절로 정리됩니다.",
    },
    en: {
      reconnect: "Reconnect",
      help: "Download the connect program again and run it on that PC; a new connection is made and the old record is cleaned up automatically.",
    },
  });

  const copy = () => COPY[
    String(document.documentElement.lang || "ko").toLowerCase().startsWith("en") ? "en" : "ko"];

  function paint(section) {
    const t = copy();
    for (const row of section.querySelectorAll(".pc-pairing-link")) {
      const badge = row.querySelector(".pc-pairing-state");
      const offline = badge ? badge.dataset.state === "offline" : false;
      const button = row.querySelector("." + BUTTON_CLASS);
      if (!offline) {
        if (button) button.remove();
        continue;
      }
      if (button) {
        // Compare before writing: a same-value write is still a mutation and
        // would call this observer forever.
        if (button.textContent !== t.reconnect) button.textContent = t.reconnect;
        if (button.title !== t.help) button.title = t.help;
        continue;
      }
      const name = row.querySelector(".pc-pairing-name");
      const node = document.createElement("button");
      node.type = "button";
      node.className = BUTTON_CLASS + " connector-retry";
      node.textContent = t.reconnect;
      node.title = t.help;
      node.setAttribute("aria-label", t.reconnect + ": " + (name ? name.textContent : ""));
      node.addEventListener("click", () => {
        const pairing = window.padiemPcPairing;
        if (pairing && typeof pairing.connect === "function") void pairing.connect();
      });
      const menu = row.querySelector(".pc-pairing-menu");
      row.insertBefore(node, menu || null);
    }
  }

  function start() {
    const section = document.getElementById(SECTION_ID);
    if (!section) return;
    // The card repaints the list on every load; the observer re-paints the
    // buttons after each draw. Idempotent by the comparisons above.
    new MutationObserver(() => paint(section)).observe(section, { childList: true, subtree: true });
    paint(section);
  }

  if (typeof window === "undefined" || typeof document === "undefined") return;
  const boot = () => { window.padiemPcReconnect = start() || null; };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
