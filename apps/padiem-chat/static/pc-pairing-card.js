// #5573 PR-3 — the owner's own PC pairing card, inside the EXISTING computer card.
//
// What this is: one surface for "connect my PC" (issue a one-time code), the
// links this account already has, the folders each link allows, and the two
// destructive actions the owner is entitled to (revoke a folder, revoke a link).
//
// What this is NOT: an authority. Every answer here is a server answer, the
// session cookie is the only credential the browser sends, and no state this
// card renders makes a PC executable — the server's link directory and the
// dispatch lane decide that. When the server says it is not ready (migration
// 072 not applied) the card says so instead of showing an empty success.
//
// The install affordance is the one the card already carries: Windows only, one
// sentence, and never the pairing code inside a URL. The code is typed into
// what gets installed, which is how it stays a possession proof.
(() => {
  "use strict";

  const PAIRINGS = "/api/pc/pairings";
  const MAX_RESPONSE_BYTES = 32768;
  const REQUEST_TIMEOUT_MS = 12000;
  const CARD_ID = "connectorComputerCard";
  const SECTION_ID = "pcPairingSection";
  const COPY = Object.freeze({
    ko: {
      heading: "이 계정과 연결된 PC",
      help: "코드는 10분 동안 한 번만 쓸 수 있습니다. PC에서 코드를 입력하면 이 계정에 연결됩니다.",
      issue: "새 연결 코드",
      issuing: "코드를 발급하고 있습니다.",
      code: "연결 코드",
      expires: "만료",
      install: "Windows 설치 프로그램",
      installHint: "설치 후 이 코드를 입력하세요.",
      empty: "연결된 PC가 없습니다. 새 연결 코드로 PC를 연결하세요.",
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
      paused: "일시 중지됨",
      revokedRoot: "폴더 승인을 해제했습니다.",
      approved: "폴더를 승인했습니다.",
      refused: "서버가 이 요청을 받아들이지 않았습니다.",
      linkState: {
        active: "연결됨",
        pending_verification: "서버 확인 대기 중",
        revoked: "연결 해제",
      },
      rootLabel: "폴더",
      rootPath: "경로",
      rootAdd: "이 PC의 폴더 승인",
      rootPlaceholder: "C:\\Users\\내이름\\문서",
      revoke: "해제",
      folderRevoke: "승인 해제",
      node: "PC 식별",
      waiting: "연결되면 이 목록에 나타납니다.",
    },
    en: {
      heading: "PCs connected to this account",
      help: "A code works once for ten minutes. Enter it on the PC to connect it to this account.",
      issue: "New pairing code",
      issuing: "Issuing a code.",
      code: "Pairing code",
      expires: "Expires",
      install: "Windows installer",
      installHint: "Enter this code after installing.",
      empty: "No connected PC yet. Start with a new pairing code.",
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
      paused: "Paused",
      revokedRoot: "Folder approval revoked.",
      approved: "Folder approved.",
      refused: "The server refused this request.",
      linkState: {
        active: "Connected",
        pending_verification: "Waiting for server confirmation",
        revoked: "Revoked",
      },
      rootLabel: "Folder",
      rootPath: "Path",
      rootAdd: "Approve a folder on this PC",
      rootPlaceholder: "C:\\Users\\me\\Documents",
      revoke: "Revoke",
      folderRevoke: "Revoke",
      node: "PC identity",
      waiting: "It will appear here once the PC connects.",
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
      };
    } catch (networkError) {
      return { ok: false, code: null, status: 0, body: null };
    } finally {
      clearTimeout(timer);
    }
  }

  function messageFor(result, t) {
    if (result.status === 401) return t.login;
    if (result.code === "pc_pairing_not_ready") return t.notReady;
    if (result.code === "pc_pairing_unavailable") return t.unavailable;
    return t.failed;
  }

  function install(card, t) {
    const section = element("div", "pc-pairing");
    section.id = SECTION_ID;
    const heading = element("h4", "pc-pairing-heading", t.heading);
    const help = element("p", "pc-pairing-help", t.help);
    const status = element("p", "pc-pairing-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    const issueButton = element("button", "pc-pairing-issue", t.issue);
    issueButton.type = "button";
    const codeLine = element("p", "pc-pairing-code-line");
    codeLine.hidden = true;
    const list = element("ul", "pc-pairing-list");
    section.append(heading, help, issueButton, codeLine, status, list);
    card.append(section);
    return { section, heading, help, status, codeLine, list, issueButton };
  }

  function renderCode(result, t, show) {
    const pairing = result.body?.pairing;
    if (!pairing || typeof pairing.code !== "string") {
      show(false, messageFor(result, t));
      return;
    }
    show(true, "", {
      code: pairing.code,
      tag: pairing.install_tag,
      expires: String(pairing.expires_at || "").replace("T", " ").slice(0, 16),
    });
  }

  function linkRow(link, t, actions) {
    const row = element("li", "pc-pairing-link");
    const name = element(
      "strong", "pc-pairing-name", link.label || link.mesh_node_id || t.node,
    );
    const paused = link.paused === true;
    const state = element("span", "pc-pairing-state",
      paused ? t.paused : (t.linkState[link.state] || link.state || ""));
    // A paused link is still connected: the pause is reported on top of the
    // link's own state, never by rewriting it.
    state.dataset.state = paused ? "paused" : String(link.state || "");
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
    const pauseLinkButton = element("button", "pc-pairing-pause", t.pause);
    pauseLinkButton.type = "button";
    pauseLinkButton.addEventListener("click", () => actions.pauseLink(link));
    const resumeLinkButton = element("button", "pc-pairing-resume", t.resume);
    resumeLinkButton.type = "button";
    resumeLinkButton.addEventListener("click", () => actions.resumeLink(link));
    const dropLink = element("button", "pc-pairing-revoke", t.revoke);
    dropLink.type = "button";
    dropLink.addEventListener("click", () => actions.revokeLink(link));
    row.append(roots, pathField, addButton, pauseLinkButton, resumeLinkButton, dropLink);
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
      async issue() {
        say(true, t.issuing);
        const result = await request(PAIRINGS, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        if (!result.ok) {
          view.codeLine.hidden = true;
          say(false, messageFor(result, t), result.code || undefined);
          return;
        }
        renderCode(result, t, (shown, text, pairing) => {
          view.codeLine.hidden = !shown;
          if (!shown) {
            say(false, text);
            return;
          }
          view.codeLine.replaceChildren(
            element("span", "pc-pairing-code-label", `${t.code}: `),
            element("code", "pc-pairing-code", pairing.code),
            element("span", "pc-pairing-install", `${t.install} · ${t.installHint}`),
            element("span", "pc-pairing-waiting", `${t.waiting} (${t.expires} ${pairing.expires})`),
          );
          say(true, "");
        });
        await load();
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

    view.issueButton.addEventListener("click", () => { void actions.issue(); });
    window.addEventListener("pageshow", () => { void load(); });
    new MutationObserver(() => {
      const next = locale();
      if (next === t) return;
      t = next;
      view.heading.textContent = t.heading;
      view.help.textContent = t.help;
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
