// #3650 — the local/nonprod "Connect this computer" initiating affordance.
//
// WHAT THIS FILE IS
//   A tiny nonprod-only companion to the #3084 panel and the #3094 adapter.
//   When the server composition explicitly installed a connect port
//   (`POST /api/claw/local-access/connect` answers `available: true`), this
//   module renders ONE "Connect this computer" affordance; clicking it asks
//   the server for a freshly minted canonical pairing challenge and hands the
//   returned `padiem://` deep link to the OS handler.
//
// NON-AUTHORITY CONTRACT (must stay true)
//   PAIRING_AUTHORITY=NO        It never mints, signs, parses, decodes or
//                               stores a pairing token. The deep link arrives
//                               fully formed from the same-origin server and
//                               is treated as an opaque bearer value.
//   TRANSPORT_AUTHORITY=NO      One same-origin availability GET per refresh
//                               and one user-activated POST per click. No
//                               WebSocket, no timer-based polling.
//   NONPROD_SURFACE=INVISIBLE   When the probe answers `available: false` (the
//                               production composition, and every composition
//                               that did not install a connect port) nothing
//                               is rendered and this file is inert.
//   SINGLE_MINT_PER_CLICK       One click performs exactly one POST. Failures
//                               are reported as bounded text and never retried
//                               from here: a second mint requires a second
//                               explicit click.
//
// FAILURE POSTURE
//   The deep link itself never enters storage, a log or the DOM. Bounded
//   status text (no error bodies, no upstream detail) is the only feedback a
//   failed attempt leaves behind.
(() => {
  "use strict";

  const CONNECT_ENDPOINT = "/api/claw/local-access/connect";
  const STATUS_PROBE_VERSION = "claw-local-connect/1";
  const ALLOWED_SCHEME = "padiem://";
  const MAX_HANDOFF_LENGTH = 512;

  const STATUS_TEXT = Object.freeze({
    ko: {
      cta: "이 컴퓨터 연결",
      aria: "이 컴퓨터를 이 대화에 연결",
      minting: "연결을 준비하는 중입니다.",
      refused: "지금은 연결을 시작할 수 없습니다. 잠시 후 다시 시도해 주세요.",
      unavailable: "이 환경에서는 컴퓨터 연결을 시작할 수 없습니다.",
    },
    en: {
      cta: "Connect this computer",
      aria: "Connect this computer to this conversation",
      minting: "Preparing the connection.",
      refused: "The connection could not be started right now. Please try again shortly.",
      unavailable: "This environment cannot start a computer connection.",
    },
  });

  function locale() {
    const current = window.__padiemLocale && typeof window.__padiemLocale.getCurrent === "function"
      ? window.__padiemLocale.getCurrent()
      : null;
    return current === "en" ? STATUS_TEXT.en : STATUS_TEXT.ko;
  }

  function cleanString(value, maxLength) {
    if (typeof value !== "string") return null;
    const trimmed = value.trim();
    if (!trimmed) return null;
    return trimmed.length > maxLength ? trimmed.slice(0, maxLength) : trimmed;
  }

  // The same bounded open-guard the #3094 adapter applies: scheme prefix test
  // plus a length bound, never a parse. A value outside the shape the desktop
  // shell expects is dropped whole.
  function openableHandoff(value) {
    const cleaned = cleanString(value, MAX_HANDOFF_LENGTH);
    if (!cleaned) return null;
    if (!cleaned.toLowerCase().startsWith(ALLOWED_SCHEME)) return null;
    if (/[\u0000-\u001f\u007f]/.test(cleaned)) return null;
    return cleaned;
  }

  function liveConversationId() {
    const seam = window.__padiemClawLocalHandoff;
    if (seam && typeof seam.getConversationId === "function") {
      return cleanString(seam.getConversationId(), 128);
    }
    return null;
  }

  function setStatus(note, text) {
    if (!note) return;
    note.textContent = text;
    note.hidden = !text;
  }

  async function probeAvailability() {
    try {
      const response = await fetch(`${CONNECT_ENDPOINT}`, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response || !response.ok) return false;
      const parsed = await response.json();
      return parsed && parsed.ok === true && parsed.available === true
        && parsed.projectionVersion === STATUS_PROBE_VERSION;
    } catch {
      return false;
    }
  }

  async function requestHandoff(note, cta) {
    const copy = locale();
    setStatus(note, copy.minting);
    cta.disabled = true;
    let value = null;
    let failedCopy = copy.refused;
    try {
      const body = {};
      const conversationId = liveConversationId();
      if (conversationId) body.conversationId = conversationId;
      const response = await fetch(CONNECT_ENDPOINT, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      });
      if (response && response.ok) {
        const parsed = await response.json();
        if (parsed && parsed.ok === true && parsed.projectionVersion === STATUS_PROBE_VERSION) {
          value = openableHandoff(
            parsed.handoff && typeof parsed.handoff === "object" ? parsed.handoff.value : null
          );
        } else if (parsed && parsed.error && parsed.error.code === "local_connect_unconfigured") {
          failedCopy = copy.unavailable;
        }
      }
    } catch {
      value = null;
    }
    cta.disabled = false;
    if (!value) {
      setStatus(note, failedCopy);
      return;
    }
    setStatus(note, "");
    // One click, one mint, one open. The OS handler (#3092) receives the link
    // from here; nothing is claimed about whether the open succeeded.
    window.location.assign(value);
  }

  function render(affordance, visible) {
    if (!affordance) return;
    affordance.hidden = !visible;
    if (!visible && affordance.parentNode) affordance.parentNode.removeChild(affordance);
  }

  function buildAffordance() {
    const copy = locale();
    const holder = document.createElement("div");
    holder.className = "claw-local-connect";
    holder.setAttribute("data-claw-local-connect-contract", STATUS_PROBE_VERSION);
    const cta = document.createElement("button");
    cta.type = "button";
    cta.className = "claw-local-connect-cta";
    cta.textContent = copy.cta;
    cta.setAttribute("aria-label", copy.aria);
    const note = document.createElement("p");
    note.className = "claw-local-connect-note";
    note.hidden = true;
    holder.appendChild(cta);
    holder.appendChild(note);
    cta.addEventListener("click", () => {
      void requestHandoff(note, cta);
    });
    return holder;
  }

  async function refresh(host) {
    const anchor = host.document.getElementById("clawLocalHandoff");
    if (!anchor || !anchor.parentNode) return;
    const existing = host.document.querySelector(".claw-local-connect");
    const available = await probeAvailability();
    if (!available) {
      render(existing, false);
      return;
    }
    if (existing) return; // already rendered; each mint requires a fresh click
    const affordance = buildAffordance();
    anchor.parentNode.insertBefore(affordance, anchor.nextSibling);
  }

  const host = typeof window === "undefined" ? null : window;
  if (host) {
    const start = () => {
      void refresh(host);
    };
    if (host.document.readyState === "loading") {
      host.document.addEventListener("DOMContentLoaded", start);
    } else {
      start();
    }
    // Coming back from the desktop app is exactly when the affordance state
    // may have changed. An event, not a timer.
    host.document.addEventListener("visibilitychange", () => {
      if (host.document.visibilityState === "visible") start();
    });
  }
})();
