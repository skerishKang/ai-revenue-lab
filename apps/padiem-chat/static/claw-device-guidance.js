// #4139 S3 — pre-connection guidance, state legend and recovery UX for the
// Claw "내 컴퓨터" (My computers) surface.
//
// NON-AUTHORITY / ZERO-NETWORK CONTRACT (must stay true)
//   NO_TRANSPORT      This module never calls fetch/XHR/WebSocket and never
//                     reads a raw server payload. It adds no second read of
//                     the device directory; the single directory authority
//                     (claw-device-manager.js) remains the only reader.
//   NO_PAIRING        It never mints, signs, parses, stores or opens a pairing
//                     token or deep link. No credential is handled here.
//   NO_SELECTION      It never selects a device, requests approval, issues a
//                     command or grants execution authority.
//   NO_PERSISTENCE    Nothing is written to any browser storage, to a cookie
//                     jar, or to the URL.
//   PRESENTATION_ONLY It renders static guidance, plus an honest count summary
//                     and recovery hints derived *only* from the state chips
//                     the directory authority already rendered from verified
//                     server evidence. It never asserts ONLINE on its own.
//
// Why it exists: a user must be able to understand the feature and recover from
// a broken connection before any PC is ever connected. The directory panel
// answers "which PCs are confirmed?"; this panel answers "how do I connect one,
// what do the states mean, and what do I do when one is offline or revoked?".
//
// COPY CONTRACT (reviewed): a server-confirmed connection is NOT execution
// authority. Every "connected" wording must say so and must name the separate
// product-specific permission and approval, and the desktop install/registration
// path must not be presented as already available to the public.
(() => {
  "use strict";

  const COPY = Object.freeze({
    ko: {
      toggle: "컴퓨터 연결 방법 안내",
      title: "내 컴퓨터 연결 안내",
      close: "닫기",
      intro: "이 계정에 연결된 PC의 연결 상태를 확인하는 기능입니다. 연결 확인과 실제 작업 실행 권한은 서로 다릅니다.",
      stepsTitle: "연결 순서",
      step1: "작업할 PC에 Padiem 데스크톱을 설치합니다.",
      step2: "그 PC에서 이 계정과 같은 계정으로 로그인합니다.",
      step3: "그 PC에서 컴퓨터 연결을 승인합니다.",
      stepsNote: "위 순서를 마치기 전에는 연결된 컴퓨터가 없는 것으로 표시됩니다.",
      stepsAvailability: "Padiem 데스크톱 설치·등록은 아직 정식 공개 전입니다. 공개되면 이 화면에서 연결 상태를 확인할 수 있습니다.",
      legendTitle: "연결 상태 표시의 뜻",
      legendConnected: "연결됨 — 서버가 이 PC의 연결을 확인했습니다. 연결 확인은 실행 권한이 아닙니다. 실제 작업 실행에는 제품별 권한과 별도의 승인이 필요합니다.",
      legendOffline: "오프라인 — PC 전원이 꺼져 있거나 Padiem 데스크톱이 응답하지 않습니다.",
      legendRevoked: "연결 해제 — 이 계정에서 이 PC의 연결 권한이 해제되었습니다.",
      legendAction: "연결 확인 필요 — 이 연결을 아직 확인하지 못했습니다. 다시 확인해 주세요.",
      summaryTitle: "현재 확인된 상태",
      summaryConnected: "연결됨",
      summaryOffline: "오프라인",
      summaryRevoked: "연결 해제",
      summaryAction: "확인 필요",
      recoveryTitle: "다시 연결하는 방법",
      recoveryOffline: "PC 전원과 Padiem 데스크톱 실행 상태를 확인한 뒤 ‘연결 상태 새로고침’을 눌러 주세요.",
      recoveryRevoked: "해당 PC에서 Padiem 데스크톱을 열고 같은 계정으로 연결을 다시 승인해 주세요.",
      recoveryAction: "해당 PC에서 Padiem 데스크톱을 열고 연결 상태를 다시 확인해 주세요.",
      troubleTitle: "연결이 계속 확인되지 않을 때",
      troubleAuth: "먼저 로그인하면 이 목록을 확인할 수 있습니다.",
      troubleUnavailable: "이 환경에서는 컴퓨터 연결 기능이 아직 켜져 있지 않습니다. 준비되면 같은 화면에서 다시 확인할 수 있습니다.",
      troubleFailed: "잠시 후 ‘연결 상태 새로고침’을 눌러 다시 확인해 주세요.",
      authorityNote: "연결 상태는 서버가 확인한 사실입니다. 작업 실행 권한은 제품별 권한과 별도의 승인으로 따로 결정되며, 이 안내는 실행 권한을 부여하지 않습니다.",
      note: "이 안내는 연결 방법만 설명합니다. 어떤 PC도 자동으로 연결하거나 선택하지 않습니다.",
    },
    en: {
      toggle: "How to connect a computer",
      title: "How to connect a computer",
      close: "Close",
      intro: "This shows the connection status of the PCs linked to this account. A confirmed connection is not the same as permission to run work.",
      stepsTitle: "Connection steps",
      step1: "Install Padiem Desktop on the PC you want to use.",
      step2: "Sign in on that PC with the same account.",
      step3: "Approve the computer connection on that PC.",
      stepsNote: "Until those steps are done, no computer is shown as connected.",
      stepsAvailability: "Installing and registering Padiem Desktop is not publicly available yet. Once it is, you can check the connection status on this screen.",
      legendTitle: "What the status labels mean",
      legendConnected: "Connected — the server confirmed this PC's connection. A confirmed connection is not execution authority: running work still needs product-specific permission and separate approval.",
      legendOffline: "Offline — the PC is powered off or Padiem Desktop is not responding.",
      legendRevoked: "Disconnected — this account's connection to that PC was revoked.",
      legendAction: "Needs verification — the connection status could not be confirmed. Please check again.",
      summaryTitle: "Confirmed right now",
      summaryConnected: "Connected",
      summaryOffline: "Offline",
      summaryRevoked: "Disconnected",
      summaryAction: "Needs verification",
      recoveryTitle: "How to reconnect",
      recoveryOffline: "Check that the PC is on and Padiem Desktop is running, then press ‘Refresh connection status’.",
      recoveryRevoked: "Open Padiem Desktop on that PC and approve the connection again with the same account.",
      recoveryAction: "Open Padiem Desktop on that PC and check the connection status again.",
      troubleTitle: "If the connection still cannot be confirmed",
      troubleAuth: "Sign in first, then check again.",
      troubleUnavailable: "The computer connection feature is not enabled in this environment yet. You can check again here once it is.",
      troubleFailed: "Wait a moment and press ‘Refresh connection status’ to check again.",
      authorityNote: "Connection status is a server-confirmed fact. Permission to run work is decided separately by product-specific authority and separate approval, and this guide grants no execution authority.",
      note: "This guide only explains how to connect. It never connects or selects a PC automatically.",
    },
  });

  // Mirrors the canonical device lifecycle vocabulary the directory already
  // uses. Kept local and presentation-only; it is not a second state authority.
  const SUMMARY_ORDER = Object.freeze(["CONNECTED", "OFFLINE", "REVOKED", "ACTION_REQUIRED"]);
  const SUMMARY_LABEL_KEY = Object.freeze({
    CONNECTED: "summaryConnected",
    OFFLINE: "summaryOffline",
    REVOKED: "summaryRevoked",
    ACTION_REQUIRED: "summaryAction",
  });
  const RECOVERY_LABEL_KEY = Object.freeze({
    OFFLINE: "recoveryOffline",
    REVOKED: "recoveryRevoked",
    ACTION_REQUIRED: "recoveryAction",
  });
  // Order recovery hints by what the user should act on first.
  const RECOVERY_ORDER = Object.freeze(["REVOKED", "ACTION_REQUIRED", "OFFLINE"]);

  function locale() {
    const current = window.__padiemLocale && typeof window.__padiemLocale.getCurrent === "function"
      ? window.__padiemLocale.getCurrent()
      : document.documentElement.lang;
    return current === "en" ? COPY.en : COPY.ko;
  }

  function element(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (typeof text === "string") el.textContent = text;
    return el;
  }

  function heading(text) {
    return element("h3", "claw-device-guidance-sub", text);
  }

  function list(className, id) {
    const ul = element("ul", className);
    if (id) ul.id = id;
    return ul;
  }

  function items(target, values) {
    target.replaceChildren();
    for (const value of values) target.appendChild(element("li", "", value));
  }

  function install() {
    const shell = document.querySelector(".app-shell");
    const workspace = document.getElementById("clawWorkspace");
    if (!shell || !workspace) return;

    const root = element("section", "claw-device-guidance");
    root.id = "clawDeviceGuidance";
    root.hidden = true;
    const toggle = element("button", "claw-device-guidance-toggle");
    toggle.id = "clawDeviceGuidanceToggle";
    toggle.type = "button";
    toggle.setAttribute("aria-controls", "clawDeviceGuidancePanel");
    toggle.setAttribute("aria-expanded", "false");
    const panel = element("section", "claw-device-guidance-panel");
    panel.id = "clawDeviceGuidancePanel";
    panel.setAttribute("aria-labelledby", "clawDeviceGuidanceTitle");
    panel.hidden = true;

    const head = element("div", "claw-device-guidance-head");
    const title = element("h2", "claw-device-guidance-title", "");
    title.id = "clawDeviceGuidanceTitle";
    const close = element("button", "claw-device-guidance-close");
    close.type = "button";
    head.append(title, close);

    const intro = element("p", "claw-device-guidance-intro");

    const summary = element("div", "claw-device-guidance-summary");
    summary.id = "clawDeviceGuidanceSummary";
    summary.hidden = true;
    summary.setAttribute("role", "status");
    summary.setAttribute("aria-live", "polite");
    const summaryTitle = heading("");
    const summaryList = list("claw-device-guidance-summary-list", "clawDeviceGuidanceSummaryList");
    summary.append(summaryTitle, summaryList);

    const stepsTitle = heading("");
    const steps = element("ol", "claw-device-guidance-steps");
    steps.id = "clawDeviceGuidanceSteps";
    const stepsNote = element("p", "claw-device-guidance-hint");
    stepsNote.id = "clawDeviceGuidanceStepsNote";
    // Honest availability of the desktop install/registration path: it must
    // never read as an immediately usable feature.
    const availabilityNote = element("p", "claw-device-guidance-hint");
    availabilityNote.id = "clawDeviceGuidanceAvailability";

    const legendTitle = heading("");
    const legend = list("claw-device-guidance-legend", "clawDeviceGuidanceLegend");
    // Connection status and execution authority are different things.
    const authorityNote = element("p", "claw-device-guidance-hint");
    authorityNote.id = "clawDeviceGuidanceAuthority";

    const recovery = element("div", "claw-device-guidance-recovery");
    recovery.id = "clawDeviceGuidanceRecovery";
    recovery.hidden = true;
    const recoveryTitle = heading("");
    const recoveryList = list("claw-device-guidance-recovery-list", "clawDeviceGuidanceRecoveryList");
    recovery.append(recoveryTitle, recoveryList);

    const trouble = element("div", "claw-device-guidance-trouble");
    const troubleTitle = heading("");
    const troubleList = list("claw-device-guidance-trouble-list", "clawDeviceGuidanceTroubleList");
    trouble.append(troubleTitle, troubleList);

    const note = element("p", "claw-device-guidance-note");

    panel.append(
      head, intro, summary, stepsTitle, steps, stepsNote, availabilityNote,
      legendTitle, legend, authorityNote, recovery, trouble, note,
    );
    root.append(toggle, panel);
    // Guidance sits after the directory panel when it is present, so the
    // directory stays the primary surface and this reads as its explanation.
    const manager = workspace.querySelector("#clawDeviceManager");
    const tagline = workspace.querySelector(".claw-workspace-tagline");
    if (manager && manager.parentNode === workspace) {
      manager.parentNode.insertBefore(root, manager.nextSibling);
    } else {
      workspace.insertBefore(root, tagline || workspace.firstChild);
    }

    let opened = false;
    // The panel body is built lazily on first open. Leaving the hidden panel
    // empty keeps this module from adding a second block of page text for
    // users (and tests) that never open the guide.
    let populated = false;

    function isClaw() {
      return shell.getAttribute("data-state") === "claw";
    }

    function renderToggle() {
      toggle.textContent = locale().toggle;
    }

    // Guidance text: registration flow, state legend and the honest
    // service-level troubleshooting reference.
    function renderBody() {
      const t = locale();
      title.textContent = t.title;
      close.textContent = t.close;
      intro.textContent = t.intro;
      stepsTitle.textContent = t.stepsTitle;
      items(steps, [t.step1, t.step2, t.step3]);
      stepsNote.textContent = t.stepsNote;
      availabilityNote.textContent = t.stepsAvailability;
      legendTitle.textContent = t.legendTitle;
      items(legend, [t.legendConnected, t.legendOffline, t.legendRevoked, t.legendAction]);
      authorityNote.textContent = t.authorityNote;
      recoveryTitle.textContent = t.recoveryTitle;
      troubleTitle.textContent = t.troubleTitle;
      items(troubleList, [t.troubleAuth, t.troubleUnavailable, t.troubleFailed]);
      note.textContent = t.note;
      summaryTitle.textContent = t.summaryTitle;
      renderEvidence();
    }

    function populate() {
      if (populated) return;
      populated = true;
      renderBody();
    }

    // Derive counts and recovery hints from the state chips the directory
    // authority already rendered. Reading its DOM is deliberate: this module
    // must not re-read the endpoint and must not re-interpret a raw payload.
    function renderEvidence() {
      // Nothing to keep fresh until the body exists; this also keeps the
      // hidden panel byte-empty before the first open.
      if (!populated) return;
      const t = locale();
      const chips = document.querySelectorAll(
        "#clawDeviceManagerList .claw-device-manager-state[data-state]"
      );
      const counts = new Map();
      for (const chip of chips) {
        const state = chip.getAttribute("data-state");
        if (!SUMMARY_ORDER.includes(state)) continue;
        counts.set(state, (counts.get(state) || 0) + 1);
      }
      if (!counts.size) {
        summary.hidden = true;
        summaryList.replaceChildren();
        recovery.hidden = true;
        recoveryList.replaceChildren();
        return;
      }
      const rows = [];
      for (const state of SUMMARY_ORDER) {
        if (!counts.has(state)) continue;
        rows.push(t[SUMMARY_LABEL_KEY[state]] + " " + counts.get(state));
      }
      items(summaryList, rows);
      summary.hidden = false;

      const hints = [];
      for (const state of RECOVERY_ORDER) {
        if (counts.has(state)) hints.push(t[RECOVERY_LABEL_KEY[state]]);
      }
      items(recoveryList, hints);
      recovery.hidden = hints.length === 0;
    }

    function closePanel() {
      opened = false;
      panel.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      toggle.focus();
    }

    function sync() {
      if (isClaw()) {
        root.hidden = false;
        return;
      }
      root.hidden = true;
      if (opened) closePanel();
    }

    toggle.addEventListener("click", () => {
      if (!isClaw()) return;
      if (opened) {
        closePanel();
        return;
      }
      opened = true;
      panel.hidden = false;
      toggle.setAttribute("aria-expanded", "true");
      populate();
      // Presentation only: no request is issued when the guide opens.
      renderEvidence();
    });
    close.addEventListener("click", closePanel);
    root.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && opened) {
        event.preventDefault();
        closePanel();
      }
    });

    // The directory owns the rows; this only re-reads what it already rendered.
    const directoryList = document.getElementById("clawDeviceManagerList");
    if (directoryList) {
      new MutationObserver(renderEvidence).observe(directoryList, {
        childList: true, subtree: true, attributes: true, attributeFilter: ["data-state"],
      });
    }
    new MutationObserver(sync).observe(shell, { attributes: true, attributeFilter: ["data-state"] });
    new MutationObserver(() => {
      renderToggle();
      if (populated) renderBody();
    }).observe(document.documentElement, {
      attributes: true, attributeFilter: ["lang"],
    });
    renderToggle();
    sync();
  }

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }
})();
