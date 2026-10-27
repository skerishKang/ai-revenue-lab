// #5573 PR-3 — the owner's own PC pairing card, inside the EXISTING computer card.
//
// What this is: one surface for "connect this PC" (download the install file),
// the links this account already has, the folders each link allows, and the two
// destructive actions the owner is entitled to (revoke a folder, revoke a link).
//
// What this is NOT: an authority. Every answer here is a server answer, the
// session cookie is the only credential the browser sends, and no state this
// card renders makes a PC executable — the server's link directory and the
// dispatch lane decide that. When the server says it is not ready (migration
// 072 not applied) the card says so instead of showing an empty success.
//
// The install affordance is one button: "connect this PC" hands the signed-in
// account's own install file to the browser, with that account's tag already
// inside it. Nothing here shows or asks for a pairing code — the code stays on
// the server and only the tag derived from it travels to the PC, which is how a
// click, and not a typed value, is enough to bind a PC to an account.
(() => {
  "use strict";

  const PAIRINGS = "/api/pc/pairings";
  const INSTALL_FILE = "/api/pc/pairings/install-file";
  const INSTALL_FILENAME = "padiem-pc-connect.ps1";
  const LABEL_SUFFIX = "/label";
  const MAX_RESPONSE_BYTES = 32768;
  const REQUEST_TIMEOUT_MS = 12000;
  const CARD_ID = "connectorComputerCard";
  const SECTION_ID = "pcPairingSection";
  const COPY = Object.freeze({
    ko: {
      heading: "이 계정과 연결된 PC",
      help: "이 PC의 Windows에 설치할 파일을 내려받아 실행하면 이 계정에 자동으로 연결됩니다. 연결 코드는 입력하지 않습니다.",
      connect: "이 PC 연결",
      connecting: "PC 연결 파일을 준비하고 있습니다.",
      connected: "설치 파일을 내려받았습니다. 설치가 끝나면 아래 목록에 이 PC가 자동으로 나타납니다.",
      issue: "새 연결 코드",
      issuing: "코드를 발급하고 있습니다.",
      empty: "연결된 PC가 없습니다. '이 PC 연결'로 PC를 연결하세요.",
      loading: "서버에서 연결 목록을 확인하고 있습니다.",
      failed: "연결 목록을 확인하지 못했습니다. 다시 시도해 주세요.",
      login: "로그인한 뒤 PC를 연결할 수 있습니다.",
      notReady: "PC 연결 기능은 아직 준비 중입니다. 잠시 후 다시 시도해 주세요.",
      unavailable: "PC 연결을 현재 처리할 수 없습니다.",
      revokedLink: "연결을 해제했습니다. 이 PC의 폴더 승인도 함께 사라집니다.",
      pausedLink: "이 PC를 잠시 멈췄습니다. 다시 시작할 때까지 작업이 전달되지 않습니다.",
      resumedLink: "이 PC를 다시 시작했습니다.",
      pause: "일시 중지",
      resume: "다시 시작",
      revokedRoot: "폴더 승인을 해제했습니다.",
      approved: "폴더를 승인했습니다.",
      refused: "서버가 이 요청을 받아들이지 않았습니다.",
      linkState: {
        active: "연결됨",
        pending_verification: "서버 확인 대기 중",
        revoked: "연결 해제",
        paused: "일시 중지됨",
      },
      rootLabel: "폴더",
      rootPath: "경로",
      rootAdd: "이 PC의 폴더 승인",
      name: "PC 이름",
      nameSave: "이름 저장",
      renamed: "PC 이름을 저장했습니다. 채팅에서 그 이름으로 이 PC를 고를 수 있습니다.",
      rootPlaceholder: "C:\\Users\\내이름\\문서",
      revoke: "해제",
      folderRevoke: "승인 해제",
      node: "PC 식별",
    },
    en: {
      heading: "PCs connected to this account",
      help: "Download the file that installs on this PC's Windows and run it, and the PC joins this account by itself. No pairing code to type.",
      connect: "Connect this PC",
      connecting: "Preparing the PC connect file.",
      connected: "Install file downloaded. This PC will appear below once the server sees it.",
      issue: "New pairing code",
      issuing: "Issuing a code.",
      empty: "No connected PC yet. Use 'Connect this PC' to add one.",
      loading: "Checking your links with the server.",
      failed: "Could not read your links. Please retry.",
      login: "Sign in to connect a PC.",
      notReady: "PC pairing is not ready yet. Please try again shortly.",
      unavailable: "PC pairing cannot be handled right now.",
      revokedLink: "Link revoked. Its folder approvals are gone with it.",
      pausedLink: "PC paused. No work is sent to it until you resume it.",
      resumedLink: "PC resumed.",
      pause: "Pause",
      resume: "Resume",
      revokedRoot: "Folder approval revoked.",
      approved: "Folder approved.",
      refused: "The server refused this request.",
      linkState: {
        active: "Connected",
        pending_verification: "Waiting for server confirmation",
        revoked: "Revoked",
        paused: "Paused",
      },
      rootLabel: "Folder",
      rootPath: "Path",
      rootAdd: "Approve a folder on this PC",
      name: "PC name",
      nameSave: "Save name",
      renamed: "PC name saved. A chat request can choose this PC by that name.",
      rootPlaceholder: "C:\\Users\\me\\Documents",
      revoke: "Revoke",
      folderRevoke: "Revoke",
      node: "PC identity",
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

  function install(card, t) {
    const section = element("div", "pc-pairing");
    section.id = SECTION_ID;
    const heading = element("h4", "pc-pairing-heading", t.heading);
    const help = element("p", "pc-pairing-help", t.help);
    const status = element("p", "pc-pairing-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    const connectButton = element("button", "pc-pairing-connect", t.connect);
    connectButton.type = "button";
    // Kept, not deleted: the code path is still the way a PC pairs when nobody
    // can run the install file. It is simply no longer this card's offer.
    const issueButton = element("button", "pc-pairing-issue", t.issue);
    issueButton.type = "button";
    issueButton.hidden = true;
    const list = element("ul", "pc-pairing-list");
    section.append(heading, help, connectButton, issueButton, status, list);
    card.append(section);
    return { section, heading, help, status, list, connectButton, issueButton };
  }

  function linkRow(link, t, actions) {
    const row = element("li", "pc-pairing-link");
    const name = element(
      "strong", "pc-pairing-name", link.label || link.mesh_node_id || t.node,
    );
    const state = element("span", "pc-pairing-state",
      t.linkState[link.state] || link.state || "");
    // A paused link arrives with state "paused": it is still connected, and the
    // server's own word is the only source of what the row says.
    state.dataset.state = String(link.state || "");
    row.append(name, state);
    if (link.mesh_node_id) {
      row.append(element("small", "pc-pairing-node", `${t.node}: ${link.mesh_node_id}`));
    }
    const roots = element("div", "pc-pairing-roots");
    if (Array.isArray(link.roots) && link.roots.length) {
      for (const root of link.roots) {
        const item = element("div", "pc-pairing-root");
        item.append(element("span", "", `${t.rootLabel}: ${root.label ?? ""}`));
        item.append(element("span", "pc-pairing-root-path", `${t.rootPath}: ${root.path ?? ""}`));
        const drop = element("button", "pc-pairing-root-revoke", t.folderRevoke);
        drop.type = "button";
        drop.addEventListener("click", () => actions.revokeRoot(link, root));
        item.append(drop);
        roots.append(item);
      }
    } else {
      roots.append(element("span", "pc-pairing-roots-empty", t.empty));
    }
    const pathField = element("input", "pc-pairing-path");
    pathField.type = "text";
    pathField.placeholder = t.rootPlaceholder;
    pathField.setAttribute("aria-label", t.rootAdd);
    const addButton = element("button", "pc-pairing-root-add", t.rootAdd);
    addButton.type = "button";
    addButton.addEventListener("click", () => actions.approveRoot(link, pathField.value));
    // The owner's own name for this machine. Once a second PC is linked it is
    // how a chat request says which one was meant, so the card has to be able
    // to set it. It names nothing the server did not already prove about this
    // row, and it changes no identity and no authority.
    const nameField = element("input", "pc-pairing-name-input");
    nameField.type = "text";
    nameField.value = link.label || "";
    nameField.maxLength = 128;
    nameField.setAttribute("aria-label", t.name);
    const nameButton = element("button", "pc-pairing-name-save", t.nameSave);
    nameButton.type = "button";
    nameButton.addEventListener("click", () => actions.renameLink(link, nameField.value));
    const pauseLinkButton = element("button", "pc-pairing-pause", t.pause);
    pauseLinkButton.type = "button";
    pauseLinkButton.addEventListener("click", () => actions.pauseLink(link));
    const resumeLinkButton = element("button", "pc-pairing-resume", t.resume);
    resumeLinkButton.type = "button";
    resumeLinkButton.addEventListener("click", () => actions.resumeLink(link));
    const dropLink = element("button", "pc-pairing-revoke", t.revoke);
    dropLink.type = "button";
    dropLink.addEventListener("click", () => actions.revokeLink(link));
    row.append(nameField, nameButton, roots, pathField, addButton, pauseLinkButton, resumeLinkButton, dropLink);
    return row;
  }

  function start() {
    const card = document.getElementById(CARD_ID);
    if (!card || document.getElementById(SECTION_ID)) return;
    let t = locale();
    const view = install(card, t);
    let lastLinks = [];

    const say = (ok, text, code) => {
      view.status.textContent = text || "";
      view.status.dataset.state = ok ? "ok" : "error";
      if (code) view.status.dataset.code = code;
    };

    async function load() {
      say(true, t.loading);
      const result = await request(PAIRINGS, { method: "GET" });
      if (!result.ok) {
        view.list.replaceChildren();
        say(false, messageFor(result, t), result.code || undefined);
        return;
      }
      lastLinks = Array.isArray(result.body?.links) ? result.body.links : [];
      draw();
      say(true, "");
    }

    function draw() {
      view.list.replaceChildren();
      if (!lastLinks.length) {
        const none = element("li", "pc-pairing-none", t.empty);
        view.list.append(none);
        return;
      }
      for (const link of lastLinks) {
        if (link.state === "revoked") continue;
        view.list.append(linkRow(link, t, actions));
      }
      if (!view.list.children.length) {
        view.list.append(element("li", "pc-pairing-none", t.empty));
      }
    }

    const actions = {
      async connect() {
        say(true, t.connecting);
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
        await load();
        say(true, t.connected);
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
        await load();
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
        await load();
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
        await load();
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
        await load();
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
        await load();
        say(true, t.resumedLink);
      },
      async revokeRoot(link, root) {
        const result = await request(
          `${PAIRINGS}/${encodeURIComponent(link.link_id)}/roots/${encodeURIComponent(root.root_ref)}`,
          { method: "DELETE" },
        );
        if (!result.ok) {
          say(false, messageFor(result, t), result.code || undefined);
          return;
        }
        await load();
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
        await load();
        say(true, t.approved);
      },
    };

    view.connectButton.addEventListener("click", () => { void actions.connect(); });
    view.issueButton.addEventListener("click", () => { void actions.issue(); });
    window.addEventListener("pageshow", () => { void load(); });
    new MutationObserver(() => {
      const next = locale();
      if (next === t) return;
      t = next;
      view.heading.textContent = t.heading;
      view.help.textContent = t.help;
      view.connectButton.textContent = t.connect;
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
