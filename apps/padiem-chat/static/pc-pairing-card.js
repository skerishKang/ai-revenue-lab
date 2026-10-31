// #5573 PR-3 — the owner's own PC pairing card, inside the EXISTING computer card.
//
// What this is, after the 2026-10-29 owner redesign: one surface that makes the
// one real action unmistakable — download the connect program, run it, and the
// PC joins this account by itself. While the person runs the installer the card
// polls its own pairing list every few seconds and turns into "연결됨 ✓ (PC
// 이름)" the moment the server sees the PC; no reload, no second button.
//
// What the screen no longer shows, by owner decision (2026-10-29): the mesh
// node identity, the per-PC drive/path lists, and the folder approve/revoke
// controls. The server features stay — the routes, the store and the actions
// below are untouched — the screen simply stops carrying them; the card is a
// connect-and-name surface now, and the drive scope work keeps its own lane.
//
// What this is NOT: an authority. Every answer here is a server answer, the
// session cookie is the only credential the browser sends, and no state this
// card renders makes a PC executable — the server's link directory and the
// dispatch lane decide that. When the server says it is not ready (migration
// 072 not applied) the card says so instead of showing an empty success.
//
// The install affordance is one button: "이 PC 연결하기" hands the signed-in
// account's own connect program to the browser, with that account's tag already
// inside it, and the person double-clicks it. The PowerShell file stays one
// disclosure away ("다른 설치 방법") for a PC where an unsigned program cannot
// run. Nothing here shows or asks for a pairing code — the code stays on the
// server and only the tag derived from it travels to the PC, which is how a
// click, and not a typed value, is enough to bind a PC to an account.
(() => {
  "use strict";

  const PAIRINGS = "/api/pc/pairings";
  const INSTALL_FILE = "/api/pc/pairings/install-file";
  const INSTALL_FILENAME = "padiem-pc-connect.ps1";
  const INSTALL_EXE = "/api/pc/pairings/install-exe";
  const INSTALL_EXE_FILENAME = "padiem-pc-connect.exe";
  const LABEL_SUFFIX = "/label";
  const MAX_RESPONSE_BYTES = 32768;
  // Twelve seconds is right for a server answer and wrong for a 20-kilobyte program
  // a person may be pulling over an office connection.
  const PROGRAM_TIMEOUT_MS = 60000;
  const MAX_PROGRAM_BYTES = 262144;
  const REQUEST_TIMEOUT_MS = 12000;
  // While the person runs the installer, the card re-reads its own pairing
  // list on this cadence. The window key is a test seam: the browser cadence
  // is the four-second default.
  const POLL_INTERVAL_DEFAULT_MS = 4000;
  const POLL_MAX_ROUNDS = 45;
  const CARD_ID = "connectorComputerCard";
  const SECTION_ID = "pcPairingSection";
  const COPY = Object.freeze({
    ko: {
      heading: "이 계정과 연결된 PC",
      help: "지금 쓰는 Windows PC에서 설치 파일을 한 번 실행하면 이 계정에 저절로 연결됩니다.",
      connect: "이 PC 연결하기",
      connecting: "PC 연결 파일을 준비하고 있습니다.",
      connected: "설치 파일을 내려받았습니다. 아래 실행 방법대로 진행하세요.",
      connectedDone: "연결됨 ✓",
      stepsTitle: "이렇게 실행하세요",
      step1: "받은 파일을 실행하세요.",
      step2: "Windows가 '알 수 없는 게시자' 창을 보여 주면 [추가 정보]를 누른 뒤 [실행]을 누르세요.",
      step3: "사용자 계정 컨트롤에서 [예]를 누르면 설치와 서버 연결이 한 번에 끝납니다.",
      wait: "연결을 확인하고 있습니다 — 몇 초마다 자동으로 확인합니다.",
      connectScript: "설치 파일로 받기 (.ps1)",
      connectingScript: "PowerShell 설치 파일을 준비하고 있습니다.",
      alternateSummary: "다른 설치 방법",
      alternateHelp: "회사 보안 프로그램이 프로그램 실행을 막으면 이 파일을 받아 실행하세요.",
      issue: "새 연결 코드",
      issuing: "코드를 발급하고 있습니다.",
      empty: "연결된 PC가 없습니다.",
      unnamed: "이름 없는 PC",
      loading: "서버에서 연결 목록을 확인하고 있습니다.",
      failed: "연결 목록을 확인하지 못했습니다. 다시 시도해 주세요.",
      login: "로그인한 뒤 PC를 연결할 수 있습니다.",
      notReady: "PC 연결 기능은 아직 준비 중입니다. 잠시 후 다시 시도해 주세요.",
      unavailable: "PC 연결 서비스를 확인하는 중이에요 · 다시 시도",
      revokedLink: "연결을 끊었습니다. 이 PC의 폴더 범위도 함께 사라집니다.",
      pausedLink: "이 PC를 잠시 멈췄습니다. 다시 시작할 때까지 작업이 전달되지 않습니다.",
      resumedLink: "이 PC를 다시 시작했습니다.",
      menuLabel: "더 보기",
      rename: "이름 바꾸기",
      nameSave: "저장",
      cancel: "취소",
      namePlaceholder: "PC 이름",
      pause: "잠시 멈춤",
      resume: "다시 시작",
      revoke: "연결 끊기",
      disconnectConfirm: "이 PC와의 연결을 끊을까요? 이 PC의 폴더 범위도 함께 사라집니다.",
      revokedRoot: "사용할 폴더에서 뺐습니다.",
      approved: "사용할 폴더에 추가했습니다.",
      refused: "서버가 이 요청을 받아들이지 않았습니다.",
      linkState: {
        active: "연결됨",
        pending_verification: "확인 대기 중",
        revoked: "연결 해제",
        paused: "멈춤",
      },
      name: "PC 이름",
      renamed: "PC 이름을 저장했습니다.",
    },
    en: {
      heading: "PCs connected to this account",
      help: "Run the installer once on this Windows PC and the PC joins this account by itself.",
      connect: "Connect this PC",
      connecting: "Preparing the PC connect file.",
      connected: "Install file downloaded. Follow the run steps below.",
      connectedDone: "Connected ✓",
      stepsTitle: "How to run it",
      step1: "Run the downloaded file.",
      step2: "If Windows warns about an unknown publisher, choose More info, then Run.",
      step3: "Choose Yes on the user-account prompt and the install and pairing finish together.",
      wait: "Checking the connection — re-checked automatically every few seconds.",
      connectScript: "Download the PowerShell file (.ps1)",
      connectingScript: "Preparing the PowerShell install file.",
      alternateSummary: "Other install methods",
      alternateHelp: "If company security blocks running programs, download and run this file.",
      issue: "New pairing code",
      issuing: "Issuing a code.",
      empty: "No connected PC yet.",
      unnamed: "Unnamed PC",
      loading: "Checking your links with the server.",
      failed: "Could not read your links. Please retry.",
      login: "Sign in to connect a PC.",
      notReady: "PC pairing is not ready yet. Please try again shortly.",
      unavailable: "Checking the PC connection service · try again",
      revokedLink: "Disconnected. Its folder scope is gone with it.",
      pausedLink: "PC paused. No work is sent to it until you resume it.",
      resumedLink: "PC resumed.",
      menuLabel: "More",
      rename: "Rename",
      nameSave: "Save",
      cancel: "Cancel",
      namePlaceholder: "PC name",
      pause: "Pause",
      resume: "Resume",
      revoke: "Disconnect",
      disconnectConfirm: "Disconnect this PC? Its folder scope is removed with it.",
      revokedRoot: "Removed from the folders in use.",
      approved: "Added to the folders in use.",
      refused: "The server refused this request.",
      linkState: {
        active: "Connected",
        pending_verification: "Waiting for confirmation",
        revoked: "Revoked",
        paused: "Paused",
      },
      name: "PC name",
      renamed: "PC name saved.",
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

  function messageFor(result, t) {
    if (result.status === 401) return t.login;
    if (result.code === "pc_pairing_not_ready") return t.notReady;
    if (result.code === "pc_pairing_install_url_missing") return t.notReady;
    if (result.code === "pc_pairing_unavailable") return t.unavailable;
    return t.failed;
  }

  function saveFile(name, text) {
    // The file is handed over as a download the browser owns; nothing about the
    // pairing travels in a URL, a query string or a page navigation.
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const link = element("a", "pc-pairing-download");
    link.href = url;
    link.download = name;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function downloadProgram(url, name) {
    // The program is bytes, not text. Reading it through the text path above would
    // rewrite every byte that is not valid UTF-8, and the PC would be handed a file
    // that does not run - so the download the person double-clicks has its own
    // reader here, with the same origin and the same session cookie.
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
      const link = element("a", "pc-pairing-download");
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

  function install(card, t) {
    const section = element("div", "pc-pairing");
    section.id = SECTION_ID;
    const heading = element("h4", "pc-pairing-heading", t.heading);
    const help = element("p", "pc-pairing-help", t.help);
    const connectButton = element("button", "pc-pairing-connect connector-retry", t.connect);
    connectButton.type = "button";
    // The one run guide: hidden until a download actually landed, so the empty
    // card is one line and one button, exactly what the redesign asks for.
    const steps = element("div", "pc-pairing-steps");
    steps.hidden = true;
    const stepsTitle = element("p", "pc-pairing-steps-title", t.stepsTitle);
    const stepsList = element("ol", "pc-pairing-steps-list");
    const step1 = element("li", "pc-pairing-step", t.step1);
    const step2 = element("li", "pc-pairing-step", t.step2);
    const step3 = element("li", "pc-pairing-step", t.step3);
    stepsList.append(step1, step2, step3);
    const wait = element("p", "pc-pairing-wait", t.wait);
    wait.hidden = true;
    steps.append(stepsTitle, stepsList, wait);
    // The script lane is the same pairing for a PC where policy blocks the
    // program; it is one disclosure away instead of a second offer.
    const alternate = element("details", "pc-pairing-alternate");
    const alternateSummary = element("summary", "pc-pairing-alternate-summary", t.alternateSummary);
    const alternateHelp = element("p", "pc-pairing-alternate-help", t.alternateHelp);
    const scriptButton = element("button", "pc-pairing-connect-script connector-retry", t.connectScript);
    scriptButton.type = "button";
    alternate.append(alternateSummary, alternateHelp, scriptButton);
    const status = element("p", "pc-pairing-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    const list = element("ul", "pc-pairing-list");
    // Kept, not deleted: the code path is still the way a PC pairs when nobody
    // can run the install file. It is simply no longer this card's offer.
    const issueButton = element("button", "pc-pairing-issue", t.issue);
    issueButton.type = "button";
    issueButton.hidden = true;
    section.append(heading, help, connectButton, steps, alternate, status, list, issueButton);
    card.append(section);
    return {
      section, heading, help, connectButton, steps, stepsTitle, wait, status, list,
      scriptButton, issueButton, alternate,
    };
  }

  function linkRow(link, t, actions, closeMenus) {
    const row = element("li", "pc-pairing-link");
    // The mesh node identity stays off the screen: the owner names the PC, and
    // the name is what a chat request addresses.
    const name = element("span", "pc-pairing-name", link.label || t.unnamed);
    name.title = name.textContent;
    const state = element("span", "pc-pairing-state",
      t.linkState[link.state] || link.state || "");
    // A paused link arrives with state "paused": it is still connected, and the
    // server's own word is the only source of what the row says.
    state.dataset.state = String(link.state || "");
    const menu = element("div", "pc-pairing-menu");
    const toggle = element("button", "pc-pairing-menu-toggle", "⋯");
    toggle.type = "button";
    toggle.setAttribute("aria-haspopup", "true");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", `${t.menuLabel}: ${name.textContent}`);
    const panel = element("div", "pc-pairing-menu-panel");
    panel.hidden = true;
    const renameButton = element("button", "pc-pairing-menu-rename", t.rename);
    renameButton.type = "button";
    const pauseResumeButton = element(
      "button",
      link.state === "paused" ? "pc-pairing-menu-resume" : "pc-pairing-menu-pause",
      link.state === "paused" ? t.resume : t.pause,
    );
    pauseResumeButton.type = "button";
    const dropLink = element("button", "pc-pairing-menu-revoke", t.revoke);
    dropLink.type = "button";
    panel.append(renameButton, pauseResumeButton, dropLink);
    menu.append(toggle, panel);
    // The rename editor replaces the menu: one input, save and cancel, and the
    // row's name repaints from the server answer.
    const editor = element("div", "pc-pairing-rename-editor");
    editor.hidden = true;
    const nameField = element("input", "pc-pairing-name-input");
    nameField.type = "text";
    nameField.value = link.label || "";
    nameField.maxLength = 128;
    nameField.placeholder = t.namePlaceholder;
    nameField.setAttribute("aria-label", t.name);
    const nameSave = element("button", "pc-pairing-name-save connector-retry", t.nameSave);
    nameSave.type = "button";
    const nameCancel = element("button", "pc-pairing-name-cancel connector-retry", t.cancel);
    nameCancel.type = "button";
    editor.append(nameField, nameSave, nameCancel);
    row.append(name, state, menu, editor);

    toggle.addEventListener("click", () => {
      const opening = panel.hidden;
      closeMenus();
      panel.hidden = !opening;
      toggle.setAttribute("aria-expanded", String(opening));
    });
    renameButton.addEventListener("click", () => {
      closeMenus();
      editor.hidden = false;
      nameField.focus();
    });
    nameCancel.addEventListener("click", () => {
      nameField.value = link.label || "";
      editor.hidden = true;
    });
    nameSave.addEventListener("click", async () => {
      const saved = await actions.renameLink(link, nameField.value);
      if (saved) editor.hidden = true;
    });
    pauseResumeButton.addEventListener("click", async () => {
      closeMenus();
      if (link.state === "paused") await actions.resumeLink(link);
      else await actions.pauseLink(link);
    });
    dropLink.addEventListener("click", async () => {
      // The one destructive action keeps one confirmation; the other two are
      // reversible states, so they act at once.
      if (!window.confirm(t.disconnectConfirm)) return;
      closeMenus();
      await actions.revokeLink(link);
    });
    return row;
  }

  function start() {
    const card = document.getElementById(CARD_ID);
    if (!card || document.getElementById(SECTION_ID)) return;
    let t = locale();
    const view = install(card, t);
    let lastLinks = [];
    let poll = null;

    const say = (ok, text, code) => {
      view.status.textContent = text || "";
      view.status.dataset.state = ok ? "ok" : "error";
      if (code) view.status.dataset.code = code;
      else delete view.status.dataset.code;
    };

    function closeMenus() {
      for (const panel of view.section.querySelectorAll(".pc-pairing-menu-panel")) {
        panel.hidden = true;
      }
      for (const toggle of view.section.querySelectorAll(".pc-pairing-menu-toggle")) {
        toggle.setAttribute("aria-expanded", "false");
      }
    }
    // One click outside any open menu closes it; Escape does the same.
    view.section.addEventListener("click", (event) => {
      const target = event && event.target;
      if (target && typeof target.closest === "function"
          && target.closest(".pc-pairing-menu")) return;
      closeMenus();
    });
    view.section.addEventListener("keydown", (event) => {
      if (event && event.key === "Escape") closeMenus();
    });

    function stopPoll() {
      if (poll) clearInterval(poll.id);
      poll = null;
      view.wait.hidden = true;
    }

    // The connect wait: re-read the pairing list on a short cadence until the
    // server sees a PC this account did not have when the download started.
    function startPoll() {
      stopPoll();
      const baseline = new Set(lastLinks.map((link) => link.link_id));
      const handle = { id: 0, rounds: 0 };
      const tick = async () => {
        if (!view.section.isConnected) {
          stopPoll();
          return;
        }
        handle.rounds += 1;
        await load(true);
        const fresh = lastLinks.find((link) =>
          !baseline.has(link.link_id) && link.state !== "revoked");
        if (fresh) {
          stopPoll();
          const label = fresh.label || "";
          say(true, label ? `${t.connectedDone} (${label})` : t.connectedDone);
          return;
        }
        if (handle.rounds >= POLL_MAX_ROUNDS) stopPoll();
      };
      handle.id = setInterval(tick, Number(window.PADIEM_PC_PAIRING_POLL_MS) || POLL_INTERVAL_DEFAULT_MS);
      poll = handle;
      view.wait.hidden = false;
    }

    async function load(silent) {
      if (!silent) say(true, t.loading);
      const result = await request(PAIRINGS, { method: "GET" });
      if (!result.ok) {
        view.list.replaceChildren();
        say(false, messageFor(result, t), result.code || undefined);
        return;
      }
      lastLinks = Array.isArray(result.body?.links) ? result.body.links : [];
      draw();
      if (!silent) say(true, "");
    }

    function draw() {
      view.list.replaceChildren();
      const shown = lastLinks.filter((link) => link.state !== "revoked");
      view.section.dataset.empty = shown.length ? "false" : "true";
      view.help.hidden = shown.length > 0;
      if (!shown.length) {
        view.list.append(element("li", "pc-pairing-none", t.empty));
        return;
      }
      for (const link of shown) {
        view.list.append(linkRow(link, t, actions, closeMenus));
      }
    }

    const actions = {
      async connect() {
        stopPoll();
        closeMenus();
        say(true, t.connecting);
        const program = await downloadProgram(INSTALL_EXE, INSTALL_EXE_FILENAME);
        if (program.ok) {
          view.steps.hidden = false;
          await load(true);
          say(true, t.connected);
          startPoll();
          return true;
        }
        // Only one refusal is worth falling back on: this build has no reviewed
        // program in it. A login that is not valid, or a deployment with no
        // installer link, is the same answer the script lane would give, and
        // silently switching files would hide it.
        if (program.code !== "pc_pairing_connect_exe_unavailable") {
          say(false, messageFor(program, t), program.code || undefined);
          return false;
        }
        return actions.connectScript();
      },
      async connectScript() {
        stopPoll();
        closeMenus();
        say(true, t.connectingScript);
        const result = await request(INSTALL_FILE, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "text/plain" },
          body: "{}",
        });
        if (!result.ok || !result.text) {
          say(false, messageFor(result, t), result.code || undefined);
          return false;
        }
        saveFile(INSTALL_FILENAME, result.text);
        view.steps.hidden = false;
        await load(true);
        say(true, t.connected);
        startPoll();
        return true;
      },
      async issue() {
        say(true, t.issuing);
        const result = await request(PAIRINGS, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        if (!result.ok) {
          say(false, messageFor(result, t), result.code || undefined);
          return null;
        }
        // The code is the PC's possession proof. It is returned to whoever
        // called this function and is never written into the page.
        const pairing = result.body?.pairing;
        await load(true);
        return pairing && typeof pairing.code === "string" ? pairing : null;
      },
      async renameLink(link, name) {
        if (typeof name !== "string" || !name.trim()) {
          say(false, t.refused);
          return false;
        }
        const result = await request(
          `${PAIRINGS}/${encodeURIComponent(link.link_id)}${LABEL_SUFFIX}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ label: name.trim() }),
          },
        );
        if (!result.ok) {
          say(false, messageFor(result, t), result.code || undefined);
          return false;
        }
        await load(true);
        say(true, t.renamed);
        return true;
      },
      async revokeLink(link) {
        const result = await request(`${PAIRINGS}/${encodeURIComponent(link.link_id)}`, {
          method: "DELETE",
        });
        if (!result.ok) {
          say(false, messageFor(result, t), result.code || undefined);
          return;
        }
        await load(true);
        say(true, t.revokedLink);
      },
      async pauseLink(link) {
        const result = await request(
          `${PAIRINGS}/${encodeURIComponent(link.link_id)}/pause`,
          { method: "POST" },
        );
        if (!result.ok) {
          say(false, messageFor(result, t), result.code || undefined);
          return;
        }
        await load(true);
        say(true, t.pausedLink);
      },
      async resumeLink(link) {
        const result = await request(
          `${PAIRINGS}/${encodeURIComponent(link.link_id)}/resume`,
          { method: "POST" },
        );
        if (!result.ok) {
          say(false, messageFor(result, t), result.code || undefined);
          return;
        }
        await load(true);
        say(true, t.resumedLink);
      },
      // Kept without a screen (owner decision 2026-10-29): the drive-scope
      // features stay server-side and callable, but this card is a connect-
      // and-name surface now, so no control renders for them.
      async revokeRoot(link, root) {
        const result = await request(
          `${PAIRINGS}/${encodeURIComponent(link.link_id)}/roots/${encodeURIComponent(root.root_ref)}`,
          { method: "DELETE" },
        );
        if (!result.ok) {
          say(false, messageFor(result, t), result.code || undefined);
          return;
        }
        await load(true);
        say(true, t.revokedRoot);
      },
      async approveRoot(link, path) {
        if (typeof path !== "string" || !path.trim()) {
          say(false, t.refused);
          return;
        }
        const result = await request(
          `${PAIRINGS}/${encodeURIComponent(link.link_id)}/roots`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path }),
          },
        );
        if (!result.ok) {
          say(false, `${t.refused} ${t.linkState[link.state] || ""}`.trim(),
            result.code || undefined);
          return;
        }
        await load(true);
        say(true, t.approved);
      },
    };

    view.connectButton.addEventListener("click", () => { void actions.connect(); });
    view.scriptButton.addEventListener("click", () => { void actions.connectScript(); });
    view.issueButton.addEventListener("click", () => { void actions.issue(); });
    window.addEventListener("pageshow", () => { void load(); });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") void load(true);
    });
    new MutationObserver(() => {
      const next = locale();
      if (next === t) return;
      t = next;
      view.heading.textContent = t.heading;
      view.help.textContent = t.help;
      view.connectButton.textContent = t.connect;
      view.stepsTitle.textContent = t.stepsTitle;
      view.wait.textContent = t.wait;
      view.scriptButton.textContent = t.connectScript;
      view.issueButton.textContent = t.issue;
      draw();
    }).observe(document.documentElement, {
      attributes: true, attributeFilter: ["lang"],
    });
    void load();
    return actions;
  }

  if (typeof window === "undefined" || typeof document === "undefined") return;
  const boot = () => { window.padiemPcPairing = start() || null; };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
