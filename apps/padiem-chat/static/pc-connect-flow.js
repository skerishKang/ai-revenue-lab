// #5573 step 1 — the ONE "connect this computer" flow (2026-10-29 redesign).
//
// The owner's call: connecting a PC must finish on the first screen, not after
// finding the Connectors dialog. So every entry — the composer chip, the
// first-screen computer card, later the PC-request guidance — lands here:
//
//   no PC yet  -> a small modal: one title, one sentence, one button. Pressing
//                 it downloads the account's own connect program at once, the
//                 modal tells the two presses that remain ([file] -> [예]), and
//                 it re-reads the pairing list every few seconds; the moment
//                 the server sees the new PC it says "연결됐어요 ✓ (이름)" and
//                 closes itself two seconds later.
//   PC present -> no modal at all. One line: "내 PC 연결됨 ✓".
//
// The flow persists nothing in the browser: no storage entry, no cookie. The
// server's pairing list is the only memory, and every surface re-reads it.
//
// What this is NOT: an authority. Every answer is a server answer from
// /api/pc/pairings, the session cookie is the only credential sent, no state
// here makes a PC executable, and a pairing code never reaches this surface —
// the tag inside the downloaded program is the only proof that travels.
(() => {
  "use strict";

  const PAIRINGS = "/api/pc/pairings";
  const INSTALL_FILE = "/api/pc/pairings/install-file";
  const INSTALL_FILENAME = "padiem-pc-connect.ps1";
  const INSTALL_EXE = "/api/pc/pairings/install-exe";
  const INSTALL_EXE_FILENAME = "padiem-pc-connect.exe";
  const MAX_RESPONSE_BYTES = 32768;
  const PROGRAM_TIMEOUT_MS = 60000;
  const MAX_PROGRAM_BYTES = 262144;
  const REQUEST_TIMEOUT_MS = 12000;
  // The modal re-reads its own pairing list while the person runs the installer.
  // The window keys are test seams; the browser cadence is the four-second
  // default and the self-close is the two-second beat the owner asked for.
  const POLL_INTERVAL_DEFAULT_MS = 4000;
  const POLL_MAX_ROUNDS = 45;
  const CLOSE_DELAY_DEFAULT_MS = 2000;
  const STATE_EVENT = "padiem:pc-pairing-state";
  const CONNECTED_EVENT = "padiem:pc-connected";
  const STARTER_ID = "pcConnectStarter";
  const CHIP_ID = "composerPcStatus";

  // The shared connector vocabulary owns the four state lines and the name;
  // this module only decides when a state is true.
  function vocabStatus(key, fallback) {
    const v = window.PadiemConnectorVocabulary;
    return v && typeof v.status === "function" ? (v.status(key) || fallback) : fallback;
  }
  function vocabName(key, fallback) {
    const v = window.PadiemConnectorVocabulary;
    return v && typeof v.name === "function" ? (v.name(key) || fallback) : fallback;
  }
  const COPY = Object.freeze({
    ko: {
      title: "이 컴퓨터를 연결할게요",
      desc: "처음 한 번만 작은 프로그램을 설치해요.",
      install: "설치하고 연결하기",
      installing: "설치 파일을 준비하고 있습니다.",
      running: "받은 파일을 눌러 주세요 → [예]를 누르면 끝나요",
      warn: "경고가 뜨면 [추가 정보] → [실행]",
      wait: "연결을 확인하고 있습니다 — 몇 초마다 자동으로 확인합니다.",
      done: "연결됐어요 ✓",
      login: "로그인한 뒤 다시 시도해 주세요.",
      notReady: "PC 연결 기능은 아직 준비 중입니다. 잠시 후 다시 시도해 주세요.",
      failed: "연결 파일을 준비하지 못했습니다. 다시 시도해 주세요.",
      close: "닫기",
      toast: "내 컴퓨터 연결됨 ✓",
      popoverTitle: "내 컴퓨터",
      popoverEmpty: "연결된 PC가 없습니다.",
      unnamed: "이름 없는 PC",
      connectedChip: "내 PC 연결됨",
      connectChip: "연결하기",
      starterConnected: "● 내 PC 연결됨",
      starterDisconnected: "○ 연결 안 됨",
      // Fallbacks only. The shared connector vocabulary owns these four lines;
      // these exist for the moment before it loads, and say the same words.
      starterChecking: "확인 중…",
      starterFailed: "확인 실패 · 다시 시도",
    },
    en: {
      title: "Let's connect this computer",
      desc: "A small install runs once, the first time only.",
      install: "Install and connect",
      installing: "Preparing the install file.",
      running: "Open the downloaded file → choose Yes, and you're done",
      warn: "If a warning appears, choose More info → Run",
      wait: "Checking the connection — re-checked automatically every few seconds.",
      done: "Connected ✓",
      login: "Sign in and try again.",
      notReady: "PC pairing is not ready yet. Please try again shortly.",
      failed: "Could not prepare the connect file. Please retry.",
      close: "Close",
      toast: "My computer connected ✓",
      popoverTitle: "My computer",
      popoverEmpty: "No connected PC yet.",
      unnamed: "Unnamed PC",
      connectedChip: "My PC connected",
      connectChip: "Connect",
      starterConnected: "● My PC connected",
      starterDisconnected: "○ Not connected",
      starterChecking: "Checking…",
      starterFailed: "Check failed · Try again",
    },
  });

  function locale() {
    const lang = (document.documentElement.lang || "ko").toLowerCase();
    return COPY[lang.startsWith("en") ? "en" : "ko"];
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    // Every server value reaches the DOM as text, never as markup.
    if (text !== undefined) node.textContent = String(text);
    return node;
  }

  async function request(url, options) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        credentials: "same-origin",
        signal: controller.signal,
        headers: { Accept: "application/json" },
        ...options,
      });
      const reader = response.body?.getReader?.();
      let raw = "";
      if (reader) {
        while (true) {
          const done = await reader.read();
          if (done.done) break;
          raw += new TextDecoder().decode(done.value, { stream: true });
          if (raw.length > MAX_RESPONSE_BYTES) {
            await reader.cancel();
            return { ok: false, code: "pc_pairing_too_large", status: 0, body: null };
          }
        }
      }
      let body = null;
      try {
        body = raw ? JSON.parse(raw) : null;
      } catch (notJson) {
        body = null;
      }
      const code = body?.error?.code;
      return {
        ok: response.ok,
        status: response.status,
        code: typeof code === "string" ? code : null,
        body,
        // The install file is not JSON: the text is what the owner downloads,
        // so it is carried as-is rather than dropped by the parse above.
        text: raw,
      };
    } catch (networkError) {
      return { ok: false, code: null, status: 0, body: null, text: "" };
    } finally {
      clearTimeout(timer);
    }
  }

  function saveFile(name, text) {
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const link = element("a");
    link.href = url;
    link.download = name;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function downloadProgram(url, name) {
    // The program is bytes, not text: reading it through the text path would
    // rewrite every byte that is not valid UTF-8 and hand over a file that
    // does not run. Same origin, same session cookie.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), PROGRAM_TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        signal: controller.signal,
        headers: { "Content-Type": "application/json", Accept: "application/octet-stream" },
        body: "{}",
      });
      if (!response.ok) {
        let code = null;
        try {
          const refused = await response.json();
          code = typeof refused?.error?.code === "string" ? refused.error.code : null;
        } catch (notJson) {
          code = null;
        }
        return { ok: false, status: response.status, code };
      }
      const bytes = await response.arrayBuffer();
      if (!bytes || !bytes.byteLength || bytes.byteLength > MAX_PROGRAM_BYTES) {
        return { ok: false, status: 0, code: "pc_pairing_too_large" };
      }
      const objectUrl = URL.createObjectURL(
        new Blob([bytes], { type: "application/octet-stream" }),
      );
      const link = element("a");
      link.href = objectUrl;
      link.download = name;
      link.click();
      URL.revokeObjectURL(objectUrl);
      return { ok: true, status: response.status, code: null };
    } catch (networkError) {
      return { ok: false, status: 0, code: null };
    } finally {
      clearTimeout(timer);
    }
  }

  const state = {
    links: [],
    read: "idle", // idle | ok | not_ready | unavailable
    everRead: false, // display only: has any read answered this session
    polling: null,
  };

  function activeLinks() {
    return state.links.filter((link) => link && link.state === "active");
  }

  function classifiedState() {
    if (state.read === "ok") return activeLinks().length ? "connected" : "disconnected";
    if (state.read === "not_ready") return "preparing";
    if (state.read === "unavailable") return "unavailable";
    return "connecting";
  }

  // Which of the four shared vocabulary lines a read result deserves. This does
  // not decide what counts as connected — classifiedState() keeps doing that
  // alone. It only stops the card from calling a state it never read
  // "연결 안 됨": a refused or failed lookup says the check failed, and a
  // session with no answer yet says it is still checking.
  function displayState() {
    const kind = classifiedState();
    if (kind === "connected" || kind === "disconnected") return kind;
    if (kind === "connecting") return "checking";
    return state.everRead ? "failed" : "checking";
  }

  function publish() {
    const detail = { state: classifiedState(), links: state.links.slice(), read: state.read };
    try {
      window.dispatchEvent(new CustomEvent(STATE_EVENT, { detail }));
    } catch (eventError) {
      /* a listener must never break the flow */
    }
    paintSurfaces();
  }

  async function readPairings() {
    const result = await request(PAIRINGS, { method: "GET" });
    if (result.ok && result.body && Array.isArray(result.body.links)) {
      state.links = result.body.links;
      state.read = "ok";
      state.everRead = true;
    } else if (result.code === "pc_pairing_not_ready" || result.status === 503) {
      state.read = "not_ready";
    } else {
      state.read = "unavailable";
    }
    publish();
    return result;
  }

  function refusalMessage(result, t) {
    if (result.status === 401) return t.login;
    if (result.code === "pc_pairing_not_ready"
      || result.code === "pc_pairing_install_url_missing") return t.notReady;
    return t.failed;
  }

  /* -- the surfaces this module repaints (chip affordance, starter card) ----- */

  function paintSurfaces() {
    const t = locale();
    const connected = classifiedState() === "connected";
    const chip = document.getElementById(CHIP_ID);
    if (chip) {
      let action = chip.querySelector(".pc-connect-chip-action");
      if (!action) {
        action = element("span", "pc-connect-chip-action");
        chip.append(action);
      }
      action.textContent = t.connectChip;
      // The affordance is an instruction to go connect, so it appears only when
      // the pairing list was actually read and answered "no PC". A read still in
      // flight or refused must not tell the owner to connect — the status label
      // next to it (owned by the composer connection status view) already says
      // 확인 중/확인 실패 honestly, and this attribute carries the same word.
      const shown = displayState();
      action.hidden = shown !== "disconnected";
      if (connected) chip.dataset.pcConnect = "connected";
      else chip.dataset.pcConnect = classifiedState();
      chip.dataset.pcConnectDisplay = shown;
    }
    const starter = document.getElementById(STARTER_ID);
    if (starter) {
      const line = starter.querySelector("[data-pc-connect-state]");
      if (line) {
        const shown = displayState();
        const fallback = {
          connected: t.starterConnected,
          disconnected: t.starterDisconnected,
          checking: t.starterChecking,
          failed: t.starterFailed,
        }[shown];
        line.textContent = vocabStatus(shown, fallback);
      }
    }
  }

  /* -- the modal -------------------------------------------------------------- */

  const view = { modal: null, parts: null };

  function installModal() {
    if (view.modal) return view;
    const t = locale();
    const backdrop = element("div", "pc-connect-backdrop");
    backdrop.hidden = true;
    const modal = element("div", "pc-connect-modal");
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "pcConnectModalTitle");
    const close = element("button", "pc-connect-close", "×");
    close.type = "button";
    close.setAttribute("aria-label", t.close);
    const title = element("h2", "pc-connect-modal-title", t.title);
    title.id = "pcConnectModalTitle";
    const desc = element("p", "pc-connect-modal-desc", t.desc);
    const install = element("button", "pc-connect-install", t.install);
    install.type = "button";
    const run = element("p", "pc-connect-run", t.running);
    run.hidden = true;
    const warn = element("p", "pc-connect-warn", t.warn);
    warn.hidden = true;
    const wait = element("p", "pc-connect-wait", t.wait);
    wait.hidden = true;
    const done = element("p", "pc-connect-done");
    done.hidden = true;
    const refusal = element("p", "pc-connect-refusal");
    refusal.setAttribute("role", "alert");
    modal.append(close, title, desc, install, run, warn, wait, done, refusal);
    backdrop.append(modal);
    document.body.append(backdrop);
    view.modal = backdrop;
    view.parts = { modal, close, title, desc, install, run, warn, wait, done, refusal };

    close.addEventListener("click", () => closeModal());
    backdrop.addEventListener("click", (event) => {
      if (event && event.target === backdrop) closeModal();
    });
    document.addEventListener("keydown", (event) => {
      if (event && event.key === "Escape" && !backdrop.hidden) closeModal();
    });
    install.addEventListener("click", () => { void startConnect(); });
    return view;
  }

  function showPhase(which) {
    const p = view.parts;
    p.install.hidden = which !== "offer";
    p.run.hidden = which !== "running";
    p.warn.hidden = which !== "running";
    p.wait.hidden = which !== "running";
    p.done.hidden = which !== "done";
    if (which !== "refusal") p.refusal.textContent = "";
    p.done.textContent = "";
  }

  function openModal() {
    const v = installModal();
    view.lastFocus = document.activeElement;
    v.parts.title.textContent = locale().title;
    v.parts.desc.textContent = locale().desc;
    v.parts.install.textContent = locale().install;
    v.parts.install.disabled = false;
    v.parts.close.setAttribute("aria-label", locale().close);
    showPhase("offer");
    v.modal.hidden = false;
    v.parts.install.focus({ preventScroll: true });
  }

  function closeModal() {
    stopPoll();
    if (!view.modal) return;
    view.modal.hidden = true;
    if (view.lastFocus && typeof view.lastFocus.focus === "function") {
      view.lastFocus.focus({ preventScroll: true });
    }
  }

  function stopPoll() {
    if (state.polling) clearInterval(state.polling.id);
    state.polling = null;
  }

  function startPoll(baselineIds) {
    stopPoll();
    const handle = { id: 0, rounds: 0 };
    const t = locale();
    const tick = async () => {
      if (!view.modal || view.modal.hidden) {
        stopPoll();
        return;
      }
      handle.rounds += 1;
      await readPairings();
      const fresh = state.links.find((link) =>
        link && link.state === "active" && !baselineIds.has(link.link_id));
      if (fresh) {
        stopPoll();
        showPhase("done");
        const label = fresh.label || "";
        view.parts.done.textContent = label
          ? `${t.done} (${label})` : t.done;
        try {
          window.dispatchEvent(new CustomEvent(CONNECTED_EVENT, { detail: { link: fresh } }));
        } catch (eventError) { /* a listener must never break the flow */ }
        const delay = Number(window.PADIEM_PC_CONNECT_CLOSE_MS);
        setTimeout(() => {
          if (view.modal && !view.modal.hidden) closeModal();
        }, Number.isFinite(delay) && delay >= 0 ? delay : CLOSE_DELAY_DEFAULT_MS);
        return;
      }
      if (handle.rounds >= POLL_MAX_ROUNDS) stopPoll();
    };
    handle.id = setInterval(tick, Number(window.PADIEM_PC_CONNECT_POLL_MS) || POLL_INTERVAL_DEFAULT_MS);
    state.polling = handle;
  }

  async function startConnect() {
    const p = view.parts;
    const t = locale();
    p.refusal.textContent = t.installing;
    p.install.disabled = true;
    const baseline = new Set(state.links.map((link) => link.link_id));
    const program = await downloadProgram(INSTALL_EXE, INSTALL_EXE_FILENAME);
    p.install.disabled = false;
    if (program.ok) {
      p.refusal.textContent = "";
      showPhase("running");
      startPoll(baseline);
      return true;
    }
    // Only one refusal is worth falling back on: this build carries no reviewed
    // program. Any other answer is the same the script lane would give, and
    // silently switching files would hide it.
    if (program.code === "pc_pairing_connect_exe_unavailable") {
      const script = await request(INSTALL_FILE, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/plain" },
        body: "{}",
      });
      if (script.ok && script.text) {
        saveFile(INSTALL_FILENAME, script.text);
        showPhase("running");
        startPoll(baseline);
        return true;
      }
      p.refusal.textContent = refusalMessage(script, t);
      return false;
    }
    p.refusal.textContent = refusalMessage(program, t);
    return false;
  }

  /* -- the one-line notice (a PC is already connected: no modal) -------------- */

  function toast(text) {
    let note = document.querySelector(".pc-connect-note");
    if (!note) {
      note = element("p", "pc-connect-note");
      note.setAttribute("role", "status");
      document.body.append(note);
    }
    note.textContent = text;
    note.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { note.hidden = true; }, 3000);
  }

  /* -- the PC-list popover ----------------------------------------------------- */

  const popoverView = { root: null };

  function installPopover() {
    if (popoverView.root) return popoverView;
    const root = element("div", "pc-connect-popover");
    root.hidden = true;
    const title = element("p", "pc-connect-popover-title", vocabName("computer", locale().popoverTitle));
    const list = element("ul", "pc-pairing-list");
    const empty = element("p", "pc-connect-popover-empty", locale().popoverEmpty);
    root.append(title, list, empty);
    document.body.append(root);
    popoverView.root = root;
    popoverView.list = list;
    popoverView.empty = empty;
    popoverView.title = title;
    document.addEventListener("click", (event) => {
      const target = event && event.target;
      if (target && typeof target.closest === "function"
        && (target.closest(".pc-connect-popover") || target.closest(`#${CHIP_ID}`))) return;
      hidePopover();
    });
    document.addEventListener("keydown", (event) => {
      if (event && event.key === "Escape") hidePopover();
    });
    return popoverView;
  }

  function hidePopover() {
    if (!popoverView.root) return;
    popoverView.root.hidden = true;
    if (popoverView.trigger) {
      popoverView.trigger.setAttribute("aria-expanded", "false");
      popoverView.trigger = null;
    }
  }

  function popoverStateLabel(link) {
    // One colour-per-state vocabulary, the same words the Connectors card's
    // pairing list uses, so a PC reads the same in both places.
    const t = locale();
    const labels = {
      active: ["연결됨", "Connected"],
      paused: ["멈춤", "Paused"],
      pending_verification: ["확인 대기 중", "Waiting"],
      revoked: ["연결 해제", "Revoked"],
    };
    const pair = labels[link.state];
    if (!pair) return link.state || "";
    return (document.documentElement.lang || "ko").toLowerCase().startsWith("en")
      ? pair[1] : pair[0];
  }

  function paintPopover() {
    const v = installPopover();
    const t = locale();
    v.title.textContent = vocabName("computer", t.popoverTitle);
    v.empty.textContent = t.popoverEmpty;
    v.list.replaceChildren();
    const shown = state.links.filter((link) => link && link.state !== "revoked");
    if (!shown.length) {
      v.empty.hidden = false;
      return;
    }
    v.empty.hidden = true;
    for (const link of shown) {
      const row = element("li", "pc-pairing-link");
      const name = element("span", "pc-pairing-name", link.label || t.unnamed);
      name.title = name.textContent;
      const badge = element("span", "pc-pairing-state", popoverStateLabel(link));
      badge.dataset.state = String(link.state || "");
      row.append(name, badge);
      v.list.append(row);
    }
  }

  function togglePopover(trigger) {
    const v = installPopover();
    if (!v.root.hidden && popoverView.trigger === trigger) {
      hidePopover();
      return;
    }
    paintPopover();
    v.root.hidden = false;
    const box = trigger.getBoundingClientRect();
    const width = v.root.getBoundingClientRect().width || 264;
    const left = Math.max(8, Math.min(box.right - width, window.innerWidth - width - 8));
    v.root.style.left = Math.round(left) + "px";
    v.root.style.top = Math.round(Math.max(8, box.top - 8)) + "px";
    v.root.style.transform = "translateY(-100%)";
    if (trigger) {
      trigger.setAttribute("aria-expanded", "true");
      popoverView.trigger = trigger;
    }
  }

  /* -- the one entry every surface calls --------------------------------------- */

  async function open() {
    const t = locale();
    await readPairings();
    if (classifiedState() === "connected") {
      toast(t.toast);
      return "connected";
    }
    openModal();
    return "modal";
  }

  /* -- wiring the first-screen surfaces ---------------------------------------- */

  function wireStarter() {
    const starter = document.getElementById(STARTER_ID);
    if (!starter || starter.dataset.pcConnectFlow === "true") return;
    starter.dataset.pcConnectFlow = "true";
    starter.addEventListener("click", () => { void open(); });
  }

  function wireLangRepaint() {
    new MutationObserver(() => {
      paintSurfaces();
      if (view.modal && !view.modal.hidden) {
        const t = locale();
        view.parts.title.textContent = t.title;
        view.parts.desc.textContent = t.desc;
        view.parts.install.textContent = t.install;
        view.parts.run.textContent = t.running;
        view.parts.warn.textContent = t.warn;
        view.parts.wait.textContent = t.wait;
        view.parts.close.setAttribute("aria-label", t.close);
      }
      if (popoverView.root && !popoverView.root.hidden) paintPopover();
    }).observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
  }

  if (typeof window === "undefined" || typeof document === "undefined") return;
  const boot = () => {
    window.PadiemPcConnectFlow = {
      open,
      openModal: () => openModal(),
      closeModal,
      togglePopover,
      refresh: () => readPairings(),
      current: () => ({ state: classifiedState(), links: state.links.slice() }),
    };
    wireStarter();
    wireLangRepaint();
    void readPairings();
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
