/*
 * PADIEM 의원3종 — council apps modules (one IIFE, three independent tools).
 *
 * Shared contract layer + three product modules (speech / sns / meeting).
 * The shared layer re-states the SAME shipped contracts as the original
 * util-menu.js (apps/padiem-chat/static/util-menu.js, after PR #5916):
 *
 *   - generation:  POST /api/chat {messages:[{role:"user",content}],
 *     mode:"auto", tier, util:"speech"|"sns"|"meeting"}. The util scope is
 *     the #5916 routing label that keeps a declared utility out of the
 *     shared native-calendar branch (a meeting text containing
 *     확인/추가/일정 must reach the model, not the calendar clarify);
 *     unknown scopes are refused server-side before any model call. tier
 *     comes from window.PadiemTierSelection when it returns one of
 *     free/plus/pro/max/admin, otherwise "free". No timezone, no
 *     calendar_turn_id.
 *   - storage:     /api/projects, /api/projects/{pid}/files (text/plain JSON
 *     writes; details read back via data.file.content)
 *   - session:     cookie credentials on every call ("include"), signed-in
 *     state read from GET /api/auth/status (fail-closed gate like
 *     the retired councillor screen: tools stay locked until authenticated === true).
 *     A signed-out visit logs in INSIDE this page through the existing
 *     POST /api/auth/password/login credential contract (#5942); the visitor is
 *     never sent to the Chat home page, and the Google route is a plain link
 *     that returns to this entry through the server's signed state.
 *
 * Nothing here calls /api/b66*, /api/claw*, /auth/* POST routes or any other
 * path, and no second authority, store or model lane is introduced. The
 * three tools never reference each other, so each can ship as its own
 * product later; the entry page merely hosts all three.
 *
 * Storage (#A): every tool saves into ONE pinned project ("의원3종", created
 * once when genuinely absent and never after a failed read), stamps the
 * doc_kind its screen saved, and lists only its own kind. A name collision
 * asks 새 이름/덮어쓰기 through the same project-file contract as the Chat
 * util, and a save failure says the server's sentence.
 *
 * SNS photo storage follows the same #5728 composition contract: originals
 * upload through the project-file channel after the browser shrinks them
 * (static/photo-resize.js ships inside this app), and one version-2 roster
 * JSON — updated in place — carries order, positions and the saved draft.
 */
(() => {
  "use strict";

  // ── shared contract layer (same shape as util-menu.js 12-140) ────────────

  // ── #6046 콘텐츠 국가 ─────────────────────────────────────────────────
  // 국가는 **출력 언어와 표현**을 고르는 라벨이다(법적 관할·데이터 거주지 아님).
  // kr 은 지시문이 비어 있어 프롬프트가 지금과 문자 단위로 같고, 요청에도 country 를 싣지 않는다.
  const COUNTRY_KEY = "padiem-council-country";
  const COUNTRY_INSTRUCTIONS = Object.freeze({
    kr: "",
    us: "\n\nWrite the entire answer in natural English (US conventions). " +
        "Keep every personal name, date, place and amount exactly as given. " +
        "Do not invent a named member, a real person's activity, or an event that was not provided.",
    uk: "\n\nWrite the entire answer in natural English with British spelling and UK conventions. " +
        "Keep every personal name, date, place and amount exactly as given. " +
        "Do not invent a named member, a real person's activity, or an event that was not provided.",
    fr: "\n\nRédigez toute la réponse en français naturel. " +
        "Conservez exactement les noms, dates, lieux et montants fournis. " +
        "N'inventez ni élu nommé, ni activité, ni événement non fournis.",
  });
  function currentCountry() {
    try {
      const value = (window.localStorage && window.localStorage.getItem(COUNTRY_KEY)) || "";
      return Object.prototype.hasOwnProperty.call(COUNTRY_INSTRUCTIONS, value) ? value : "kr";
    } catch (_) { return "kr"; }
  }
  function countryInstruction(country) {
    return COUNTRY_INSTRUCTIONS[country] || "";
  }

  // ── 생성 실패 문구 ────────────────────────────────────────────────────────
  // Same local copy as util-menu.js (#5783/#6199): a generation failure is
  // said in Korean, and the sentence names what the person can do next. The
  // server's own free-text message is never echoed as if it were a product
  // sentence.
  const GEN_ERROR_COPY = Object.freeze({
    401: "로그인이 필요합니다. 다시 로그인해 주세요.",
    403: "이 계정에서는 할 수 없는 요청입니다. 로그인 상태를 확인해 주세요.",
    429: "요청이 잠시 많습니다. 조금 뒤에 다시 시도해 주세요.",
    500: "만드는 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.",
    502: "서버 연결이 잠시 끊겼습니다. 잠시 후 다시 시도해 주세요.",
    503: "서버가 잠시 과부하 상태입니다. 잠시 후 다시 시도해 주세요.",
    504: "서버 응답이 늦어집니다. 잠시 후 다시 시도해 주세요.",
  });
  const GEN_ERROR_FALLBACK = "생성에 실패했습니다. 잠시 후 다시 시도해 주세요.";
  const GEN_OFFLINE_COPY = "인터넷 연결을 확인해 주세요.";
  // 임시 완화(2026-11-02 한도 감사): 120초는 긴 생성을 시간으로 죽인다. 근본 해결은 진행 표시 전환.
  const GEN_TIMEOUT_MS = 300000;

  function generationFailureText(error) {
    if (error && error.emptyResult) return "생성 실패: 답을 받지 못했습니다. 다시 시도해 주세요.";
    const known = error && error.status ? GEN_ERROR_COPY[error.status] : null;
    const message = known || (error && error.message === GEN_OFFLINE_COPY ? GEN_OFFLINE_COPY : GEN_ERROR_FALLBACK);
    return "생성 실패: " + message;
  }

  function emptyResult() {
    const error = new Error("empty result");
    error.emptyResult = true;
    return error;
  }

  function streamError(data) {
    const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
    const error = new Error(GEN_ERROR_FALLBACK);
    error.code = code;
    if (code === "empty_upstream_answer") error.emptyResult = true;
    return error;
  }

  function parseSseBlock(block) {
    let event = "message";
    const dataLines = [];
    String(block).replace(/\r\n/g, "\n").split("\n").forEach((line) => {
      if (!line || line.startsWith(":")) return;
      const separator = line.indexOf(":");
      const field = separator >= 0 ? line.slice(0, separator) : line;
      let value = separator >= 0 ? line.slice(separator + 1) : "";
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") event = value;
      if (field === "data") dataLines.push(value);
    });
    if (!dataLines.length) return null;
    return { event: event, data: dataLines.join("\n") };
  }

  // #6556 streaming: the answer is painted as it arrives. The same reader
  // refuses a frame that says error, an unfinished stream and an empty answer,
  // so a partial stream is never presented as a complete draft.
  async function readStreamAnswer(res, onDelta) {
    const type = String(res.headers?.get?.("content-type") || "").toLowerCase();
    const streamType = /text\/event-stream|application\/(?:x-)?ndjson/.test(type);
    const ndjson = /application\/(?:x-)?ndjson/.test(type);
    if (!streamType || !res.body || typeof res.body.getReader !== "function") {
      // A server/proxy that answered the stream route with one JSON body is
      // still a complete answer; an empty one is still a failed generation.
      const data = await res.json().catch(() => null);
      if (!data || typeof data.answer !== "string" || !data.answer.trim()) throw emptyResult();
      return data.answer;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let answer = "";
    let done = false;
    function consume(text) {
      const frame = ndjson
        ? (text.trim() ? { event: "message", data: text.trim() } : null)
        : parseSseBlock(text);
      if (!frame) return;
      let data = null;
      try { data = JSON.parse(frame.data); } catch (_) { data = null; }
      if (frame.event === "error" || (data && data.error)) throw streamError(data);
      if (data && typeof data.delta === "string") {
        answer += data.delta;
        if (onDelta) onDelta(answer);
      }
      if (frame.event === "done" || (data && data.done === true)) done = true;
    }
    try {
      while (!done) {
        const item = await reader.read();
        if (item.done) break;
        buffer += decoder.decode(item.value, { stream: true });
        const boundary = ndjson ? /\r?\n/ : /\r?\n\r?\n/;
        let match = boundary.exec(buffer);
        while (match) {
          const text = buffer.slice(0, match.index);
          buffer = buffer.slice(match.index + match[0].length);
          consume(text);
          if (done) break;
          match = boundary.exec(buffer);
        }
      }
      buffer += decoder.decode();
      if (!done && buffer.trim()) consume(buffer);
    } finally {
      try { await reader.cancel(); } catch (_) { /* no-op */ }
    }
    if (!done && !answer.trim()) throw emptyResult();
    if (!answer.trim()) throw emptyResult();
    return answer;
  }

  async function apiChat(prompt, util, onDelta) {
    // Same rule as util-menu.js apiChat / app.js selectedProductTier().
    // The util scope (PR #5916 contract) is the request's routing label:
    // it keeps a declared utility out of the shared native-calendar branch
    // (including try_native_calendar_chat's own second classification) and
    // the server refuses unknown scopes before any model call. It grants no
    // identity, tier, entitlement or tool scope and is not an auth input.
    const selected = window.PadiemTierSelection?.get?.();
    const tier = ["free", "plus", "pro", "max", "admin"].includes(selected) ? selected : "free";
    const country = currentCountry();
    const content = prompt + countryInstruction(country);
    const payload = { messages: [{ role: "user", content: content }], tier };
    if (util) payload.util = util;
    // util-menu.js waits 120s and then aborts. A stalled upstream must end as
    // one Korean sentence, not as a page that never answers.
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), GEN_TIMEOUT_MS) : null;
    try {
      let res;
      try {
        res = await fetch("/api/chat/stream", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
          body: JSON.stringify(payload),
          ...(controller ? { signal: controller.signal } : {}),
        });
      } catch (_) {
        throw new Error(GEN_OFFLINE_COPY);
      }
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        if (res.status === 401) markSessionLost();
        const error = new Error(GEN_ERROR_COPY[res.status] || GEN_ERROR_FALLBACK);
        error.status = res.status;
        error.code = typeof data?.error?.code === "string" ? data.error.code : "";
        if (error.code === "empty_upstream_answer") error.emptyResult = true;
        throw error;
      }
      return await readStreamAnswer(res, onDelta);
    } finally {
      if (timer !== null) clearTimeout(timer);
    }
  }

  // ── 저장 프로젝트: "의원3종" 하나 ────────────────────────────────────────
  // The three tools share ONE project. A save must never land in whatever
  // project happens to be first: the pinned name is looked up, created once
  // when it is genuinely absent, and remembered. A read that failed is not
  // "there are no projects", so no create follows it.
  const COUNCIL_PROJECT_NAME = "의원3종";

  async function getProjects() {
    let res;
    try { res = await fetch("/api/projects", { credentials: "include" }); } catch (_) { return null; }
    if (!res.ok) return null;
    const data = await res.json().catch(() => null);
    return data && Array.isArray(data.projects) ? data.projects : null;
  }

  const councilProject = (() => {
    let currentPid = null;
    let pending = null;
    async function resolve() {
      const projects = await getProjects();
      if (projects === null) return null;
      const pinned = projects.find((p) => p && p.name === COUNCIL_PROJECT_NAME);
      if (pinned && pinned.id) return pinned.id;
      let res;
      try {
        res = await fetch("/api/projects", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: COUNCIL_PROJECT_NAME }),
        });
      } catch (_) { return null; }
      if (!res.ok) return null;
      const data = await res.json().catch(() => null);
      return data && data.project && data.project.id ? data.project.id : null;
    }
    return {
      get() { return currentPid; },
      ensure() {
        if (currentPid) return Promise.resolve(currentPid);
        // One shared promise for all three tools: opening two panels must not
        // race two GETs (or two creates) for the same project.
        if (!pending) {
          pending = resolve().then(
            (pid) => { currentPid = pid || null; if (!pid) pending = null; return pid; },
            () => { pending = null; return null; },
          );
        }
        return pending;
      },
    };
  })();

  // ── 저장 결과: 성공·충돌·실패를 구분한다 ──────────────────────────────────
  // The same shipped contract as util-menu.js (#5731): a stored writing
  // carries the kind its screen saved it as, a name already used by the same
  // kind comes back as 409 with the existing file, and the owner chooses
  // between a new name (default) and an overwrite that keeps the displaced
  // body as a version.
  async function saveProjectFile(pid, name, text, mediaType, docKind) {
    const body = { name: name, media_type: mediaType || "text/plain", text: text };
    if (docKind) body.doc_kind = docKind;
    if (currentCountry() !== "kr") body.country = currentCountry();
    let res;
    try {
      res = await fetch("/api/projects/" + pid + "/files", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (_) {
      return { failure: { status: 0 } };
    }
    if (res.status === 409) {
      const body = await res.json().catch(() => null);
      const existing = body && body.error && body.error.existing;
      return existing && existing.id ? { conflict: existing } : { failure: { status: res.status } };
    }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      const message = body && body.error && typeof body.error.message === "string" ? body.error.message : "";
      const size = res.status === 422 && !!(body && body.error && body.error.code === "project_file_limit");
      return { failure: { status: res.status, size: size, message: message } };
    }
    const data = await res.json().catch(() => null);
    return data && data.file ? { file: data.file } : { failure: { status: res.status } };
  }

  async function overwriteProjectFile(pid, fileId, text, docKind) {
    const body = { text: text };
    if (docKind) body.doc_kind = docKind;
    let res;
    try {
      res = await fetch(
        "/api/projects/" + encodeURIComponent(pid) + "/files/" + encodeURIComponent(fileId),
        {
          method: "PUT",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
    } catch (_) {
      return { failure: { status: 0 } };
    }
    if (!res.ok) return { failure: { status: res.status } };
    const data = await res.json().catch(() => null);
    return data && data.file ? { file: data.file, previous: data.previous || null } : { failure: { status: res.status } };
  }

  /** `행사.txt` -> `행사 (2).txt`: the offered default is a NEW file, never a silent overwrite. */
  function nextFreeName(name, taken) {
    const used = new Set((taken || []).map((item) => String(item || "")));
    if (!used.has(name)) return name;
    const stem = name.replace(/\.[^.]+$/, "");
    const ext = (name.match(/\.[^.]+$/) || [""])[0];
    let n = 2;
    while (used.has(stem + " (" + n + ")" + ext)) n += 1;
    return stem + " (" + n + ")" + ext;
  }

  function askSaveChoice(anchor, name, suggested) {
    return new Promise((resolve) => {
      const box = el("div", "council-save-choice");
      box.setAttribute("role", "group");
      box.setAttribute("aria-label", "같은 이름의 글이 이미 있습니다");
      box.appendChild(el("p", "council-save-choice-text", "같은 이름의 글이 이미 있습니다: " + name));
      const asNew = el("button", "council-save-as-new", "새 이름으로 저장 (" + suggested + ")");
      asNew.type = "button";
      const overwrite = el("button", "council-save-overwrite", "덮어쓰기 (이전 내용은 버전으로 남김)");
      overwrite.type = "button";
      const finish = (choice) => {
        if (box.parentNode) box.parentNode.removeChild(box);
        resolve(choice);
      };
      asNew.addEventListener("click", () => finish("new"));
      overwrite.addEventListener("click", () => finish("overwrite"));
      box.append(asNew, overwrite);
      const hostNode = anchor && anchor.parentNode ? anchor.parentNode : anchor;
      if (hostNode && typeof hostNode.appendChild === "function") hostNode.appendChild(box);
      else resolve(null);
    });
  }

  function saveFailureText(failure) {
    if (!failure) return "저장하지 못했습니다. 잠시 후 다시 시도해 주세요.";
    // #5783: a server sentence about why nothing was stored is shown as-is
    // only when the server actually said one; otherwise the local copy names
    // the concrete condition.
    if (failure.message) return "저장하지 못했습니다: " + failure.message;
    if (failure.status === 401) return "로그인이 필요합니다. 다시 로그인해 주세요.";
    if (failure.status === 403 || failure.status === 404) return "이 글을 저장할 권한이 없습니다.";
    if (failure.size || failure.status === 413) return "파일이 너무 커서 저장하지 못했습니다.";
    return "저장하지 못했습니다. 잠시 후 다시 시도해 주세요.";
  }

  async function saveCouncilText(options) {
    if (!options.pid) return { none: true };
    const first = await saveProjectFile(
      options.pid, options.name, options.text, "text/plain", options.kind,
    );
    if (first.failure) return first;
    if (!first.conflict) return { file: first.file };
    const files = await listProjectFiles(options.pid);
    const suggested = nextFreeName(options.name, files.map((f) => f.name));
    const choice = await askSaveChoice(options.anchor, options.name, suggested);
    if (choice === "overwrite") {
      const replaced = await overwriteProjectFile(options.pid, first.conflict.id, options.text, options.kind);
      return replaced.failure ? replaced : { file: replaced.file };
    }
    if (choice === "new") {
      const second = await saveProjectFile(options.pid, suggested, options.text, "text/plain", options.kind);
      return second.failure ? second : { file: second.file };
    }
    return { none: true };
  }

  async function listProjectFiles(pid) {
    const res = await fetch("/api/projects/" + pid + "/files", { credentials: "include" });
    if (!res.ok) return [];
    const data = await res.json();
    return (data && data.files) ? data.files : [];
  }

  async function fetchProjectFile(pid, fileId) {
    const res = await fetch("/api/projects/" + pid + "/files/" + encodeURIComponent(fileId), { credentials: "include" });
    if (!res.ok) return null;
    const data = await res.json();
    const content = data && data.file && (data.file.content || data.file.text);
    return typeof content === "string" ? content : null;
  }

  function downloadText(text, filename) {
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // 2026-11-01: 한글(HWPX)·워드(DOCX) 내려받기 — 결과 텍스트를 문서 구조로
  // 옮겨 브라우저에서 바로 만든다(static/document-export.js, 서버 왕복 없음).
  // 텍스트 규칙(파일명·내용)은 그대로다.
  let documentExportLoading = null;
  function loadDocumentExport() {
    if (window.PadiemDocumentExport) return Promise.resolve(window.PadiemDocumentExport);
    if (documentExportLoading) return documentExportLoading;
    documentExportLoading = new Promise((resolve, reject) => {
      const head = document.head || document.body;
      const script = document.createElement("script");
      script.src = "./static/document-export.js";
      // ?v=<content hash> from the served map; the bare URL stays the fallback.
      script.src = versionedAsset(script.src);
      script.addEventListener("load", () => {
        if (window.PadiemDocumentExport) resolve(window.PadiemDocumentExport);
        else reject(new Error("document-export-unavailable"));
      }, { once: true });
      script.addEventListener("error", () => reject(new Error("document-export-unavailable")), { once: true });
      head.appendChild(script);
    });
    return documentExportLoading;
  }

  function downloadBytes(bytes, filename, mime) {
    const blob = new Blob([bytes], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    // The harness export test reads the payload the anchor would deliver.
    a.__exportBytes = bytes;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function resultExportBlocks(kind, text, meta) {
    const lib = window.PadiemDocumentExport;
    if (kind === "book") {
      // 활동집: 첫 줄이 제목(북 파일명 규칙과 같은 줄), "N."·"제N장" 줄은
      // 소제목으로, 나머지는 문단으로 — 초안의 구조를 살린다.
      return lib.blocksFromText(text, { firstLineTitle: true, headings: true });
    }
    const blocks = [{ kind: "title", text: meta.title }];
    String(text || "").replace(/\r\n?/g, "\n").split("\n").forEach((line) => {
      const trimmed = line.trim();
      if (!trimmed) {
        if (blocks.length && blocks[blocks.length - 1].kind !== "blank") blocks.push({ kind: "blank" });
        return;
      }
      blocks.push({ kind: "para", text: trimmed });
    });
    return blocks;
  }

  function wireResultDownloads(options) {
    const wire = (format, button) => {
      if (!button) return;
      button.addEventListener("click", async () => {
        const text = options.text();
        if (!text) return;
        let lib;
        try { lib = await loadDocumentExport(); }
        catch (_) { return; }
        const blocks = resultExportBlocks(options.kind, text, { title: options.title() });
        const titleBlock = blocks.find((block) => block.kind === "title");
        const docTitle = (titleBlock && titleBlock.text) || options.title() || "문서";
        const bytes = format === "hwpx"
          ? lib.buildHwpx({ title: docTitle, creator: "PADIEM 의원3종", blocks })
          : lib.buildDocx({ title: docTitle, blocks });
        downloadBytes(bytes, options.baseName() + "." + format, lib.MIME[format]);
      });
    };
    wire("hwpx", options.hwpxBtn);
    wire("docx", options.docxBtn);
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  // #5728 binary photo upload — the SAME project-file channel as text
  // drafts (original bytes, owner/project scoped). The browser shrinks a big
  // photo BEFORE this call (static/photo-resize.js), so the uploaded bytes
  // keep the picture while staying inside the Worker's decode budget.
  async function uploadProjectImage(pid, blob, name, type) {
    const res = await fetch("/api/projects/" + pid + "/files", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Padiem-Filename": encodeURIComponent(name),
        "X-Padiem-Media-Type": type || "application/octet-stream",
      },
      body: blob,
    });
    if (!res.ok) return null;
    const data = await res.json().catch(() => null);
    return data && data.file ? data.file : null;
  }

  async function deleteProjectFile(pid, fileId) {
    const res = await fetch("/api/projects/" + pid + "/files/" + encodeURIComponent(fileId), {
      method: "DELETE",
      credentials: "include",
    });
    return res.ok || res.status === 404;
  }

  async function fetchOriginalDataUrl(pid, fileId) {
    const res = await fetch("/api/projects/" + pid + "/files/" + encodeURIComponent(fileId) + "/original", {
      credentials: "include",
    });
    if (!res.ok) return null;
    const blob = await res.blob();
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => resolve(null);
      reader.readAsDataURL(blob);
    });
  }

  // ── one file-name rule for the four stored document families (#5942) ──────
  // A book is a derived product, not a meeting record, and a draft SNS post is
  // not a speech manuscript. The prefixes below are the ones the Chat util
  // already writes (#5608), so a book saved from either surface lists in both;
  // no new store, table or media type is introduced.
  const BOOK_PREFIX = "활동집 - ";
  const SNS_POST_SUFFIX = "게시글.txt";
  const SNS_ROSTER_NAME = "SNS 사진 구성.json";

  function storedName(file) { return String((file && file.name) || ""); }
  function isStoredBook(file) { return storedName(file).startsWith(BOOK_PREFIX); }
  function isSnsPostFile(file) {
    const name = storedName(file);
    return name.endsWith(SNS_POST_SUFFIX) && !isStoredBook(file);
  }
  function isSnsRosterFile(file) { return storedName(file) === SNS_ROSTER_NAME; }
  /** Plain manuscripts: neither a book, an SNS post draft nor the photo roster. */
  // #6046 — 저장 문서의 국가가 선택 국가와 같은 것만 보인다.
  // 컬럼이 없는 기존 문서는 kr 로 읽어 한국어를 선택한 사용자 화면이 비지 않는다.
  function sameCountry(file) {
    return String((file && file.country) || "kr") === currentCountry();
  }

  function isManuscriptFile(file) {
    const name = storedName(file);
    return name.endsWith(".txt") && !isStoredBook(file) && !isSnsPostFile(file);
  }
  // #5731: a stored writing carries the kind its screen saved it as, so each
  // list asks for its own kind instead of reading every .txt in the project.
  // Documents stored before a kind was recorded keep the name rule above.
  function hasDocKind(file, kind) {
    return String((file && file.doc_kind) || "") === kind;
  }
  function isSpeechFile(file) {
    return hasDocKind(file, "speech") || (!(file && file.doc_kind) && isManuscriptFile(file));
  }
  function isMeetingFile(file) {
    return hasDocKind(file, "meeting") || (!(file && file.doc_kind) && isManuscriptFile(file));
  }
  function isBookFile(file) {
    return hasDocKind(file, "book") || (!(file && file.doc_kind) && isStoredBook(file));
  }
  /** The book file name comes from the draft's own first line, so an edited
   *  title re-saves under the edited name; unsafe characters are dropped. */
  function bookBaseName(text) {
    const firstLine = String(text || "").split("\n", 1)[0].replace(/^[0-9]+\.\s*/, "").trim();
    const safe = firstLine.replace(/[\\/:*?"<>|]/g, "").replace(/\.*$/, "").slice(0, 40).trim();
    return BOOK_PREFIX + (safe || "제목 미정");
  }
  function bookFileName(text) {
    return bookBaseName(text) + ".txt";
  }

  // ── 한 줄 안내와 결과 상자 ────────────────────────────────────────────────
  // "생성 중"과 실패 문구는 결과 본문이 아니라 그 위의 안내줄에 산다. A failure
  // therefore never looks like a draft, and the save button is disabled while
  // the line is not a success.
  function noticeLine(id) {
    const line = el("p", "council-tool-notice");
    line.id = id;
    line.hidden = true;
    line.setAttribute("role", "status");
    line.setAttribute("aria-live", "polite");
    return line;
  }
  function setNotice(line, text, tone) {
    if (!line) return;
    line.textContent = text || "";
    line.hidden = !text;
    if (text && tone) line.dataset.tone = tone;
    else if (line.dataset) delete line.dataset.tone;
  }
  // 복사(주 버튼)·저장·다운로드는 모두 결과 본문 바로 아래 한 줄이다.
  function resultPanel(options) {
    const result = el("div", "council-result");
    result.id = options.id;
    result.hidden = true;
    const heading = options.titleNode || (options.title ? el("h3", null, options.title) : null);
    if (heading) result.appendChild(heading);
    const output = document.createElement("textarea");
    output.id = options.outputId;
    output.rows = options.rows || 12;
    result.appendChild(output);
    // The SNS preview sits between the draft and its action row.
    if (options.afterOutput) result.appendChild(options.afterOutput);
    const actions = el("div", "council-actions");
    const copyBtn = el("button", "council-primary", "복사");
    copyBtn.type = "button";
    copyBtn.id = options.copyId;
    const saveBtn = el("button", "council-save", options.saveLabel || "저장");
    saveBtn.type = "button";
    saveBtn.id = options.saveId;
    // [한글(HWPX)] [워드(DOCX)] [텍스트] — 2026-11-01부터 세 가지.
    const dlHwpxBtn = el("button", null, "한글(HWPX)");
    dlHwpxBtn.type = "button";
    dlHwpxBtn.id = options.downloadHwpxId;
    dlHwpxBtn.setAttribute("aria-label", "한글(HWPX) 파일로 내려받기");
    const dlDocxBtn = el("button", null, "워드(DOCX)");
    dlDocxBtn.type = "button";
    dlDocxBtn.id = options.downloadDocxId;
    dlDocxBtn.setAttribute("aria-label", "워드(DOCX) 파일로 내려받기");
    const dlBtn = el("button", null, "텍스트");
    dlBtn.type = "button";
    dlBtn.id = options.downloadId;
    // #5895: the same draft can go to the owner's own PC, through the shared
    // file-exchange dialog. It always offers a NEW dated name.
    const pcSaveBtn = el("button", null, PC_REF_COPY.save);
    pcSaveBtn.type = "button";
    pcSaveBtn.id = options.pcSaveId;
    actions.append(copyBtn, saveBtn, dlHwpxBtn, dlDocxBtn, dlBtn, pcSaveBtn);
    result.appendChild(actions);
    return { result, output, copyBtn, saveBtn, dlHwpxBtn, dlDocxBtn, dlBtn, pcSaveBtn, actions };
  }

  function wireCopy(button, output) {
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(output.value);
        button.textContent = "복사됨";
        setTimeout(() => { button.textContent = "복사"; }, 1500);
      } catch (_) { /* clipboard refusal leaves the draft editable */ }
    });
  }

  // ── 파일 이름과 사진 줄이기 ─────────────────────────────────────────────
  function fileNamePart(value) {
    return String(value || "").replace(/[\\/:*?"<>|]/g, "").replace(/\s+/g, " ").trim();
  }
  function todayStamp() {
    const now = new Date();
    const pad = (n) => (n < 10 ? "0" + n : String(n));
    return now.getFullYear() + "-" + pad(now.getMonth() + 1) + "-" + pad(now.getDate());
  }
  /** 축사_행사명_날짜 — the event and date the form already carries. The
   *  download buttons append the extension; .txt keeps the original rule. */
  function speechBaseName(form) {
    const d = new FormData(form);
    const event = fileNamePart(d.get("event")) || "행사";
    const date = String(d.get("date") || "").trim() || todayStamp();
    return "축사_" + event + "_" + date;
  }
  function speechFileName(form) {
    return speechBaseName(form) + ".txt";
  }

  // #5728: the browser does the shrinking (static/photo-resize.js in THIS app
  // carries the Worker CPU reason). Loaded on first big photo, so a page that
  // never adds one touches no extra script.
  let photoResizeLoading = null;
  function loadPhotoResize() {
    if (window.PadiemPhotoResize) return Promise.resolve(window.PadiemPhotoResize);
    if (photoResizeLoading) return photoResizeLoading;
    photoResizeLoading = new Promise((resolve, reject) => {
      const head = document.head || document.body;
      const script = document.createElement("script");
      script.src = "./static/photo-resize.js";
      // ?v=<content hash> from the served map; the bare URL stays the fallback.
      script.src = versionedAsset(script.src);
      script.addEventListener("load", () => {
        if (window.PadiemPhotoResize) resolve(window.PadiemPhotoResize);
        else reject(new Error("photo-resize-unavailable"));
      }, { once: true });
      script.addEventListener("error", () => reject(new Error("photo-resize-unavailable")), { once: true });
      head.appendChild(script);
    });
    return photoResizeLoading;
  }

  function dataUrlToBlob(dataUrl) {
    const comma = String(dataUrl || "").indexOf(",");
    if (comma < 0) return null;
    const head = dataUrl.slice(0, comma);
    const body = dataUrl.slice(comma + 1);
    const isBase64 = head.indexOf(";base64") >= 0;
    const mime = (head.match(/^data:([^;,]+)/) || [])[1] || "image/jpeg";
    try {
      if (!isBase64) return new Blob([decodeURIComponent(body)], { type: mime });
      const binary = atob(body);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
      return new Blob([bytes], { type: mime });
    } catch (_error) {
      return null;
    }
  }

  // ── 내 PC 연결: 예전 글 가져오기 · 내 PC에 저장 (#5895) ───────────────────
  // The independent app keeps the same PC file exchange the Chat util uses:
  // the same pairing read, the same reference read, the same shared dialog and
  // the same save contract. No second connector, no second pairing screen.
  const COMPUTER_CONNECT_HREF = "/#padiem-connectors";
  const PC_REF_COPY = Object.freeze({
    pick: "내 PC에서 예전 글 가져오기",
    again: "내 PC에서 더 가져오기",
    remove: "빼기",
    preview: "가져온 글",
    unavailable: "PC 파일 창을 열지 못했습니다. 잠시 후 다시 시도해 주세요.",
    unreadable: "이 파일은 참고 글로 읽지 못했어요. 글자가 들어 있는 문서를 골라 주세요.",
    hwpEncrypted: "암호가 걸린 한글 파일은 읽을 수 없어요.",
    hwpDistributable: "배포용으로 저장된 한글 파일은 읽을 수 없어요.",
    laneDown: "파일 읽기 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    noPc: "컴퓨터를 연결하면 예전 글을 가져올 수 있습니다.",
    connect: "컴퓨터 연결하기",
    save: "내 PC에 저장",
    saveNoPc: "컴퓨터를 연결하면 내 PC에 저장할 수 있습니다.",
    saveUnavailable: "PC에 저장할 창을 열지 못했습니다. 잠시 후 다시 시도해 주세요.",
    saved: "내 PC에 저장했습니다.",
  });

  // The shared dialog reads its Korean copy from the host locale. This app
  // ships no Chat locale bundle, so it provides the dialog's own sentences —
  // and never overwrites a host locale that already exists.
  const PC_EXCHANGE_COPY_KO = Object.freeze({
    "pc-exchange-import-title": "내 PC에서 가져오기",
    "pc-exchange-import-note": "PC 안의 파일을 직접 보지 않고, 필요한 파일만 골라요.",
    "pc-exchange-save-title": "내 PC에 저장",
    "pc-exchange-save-note": "폴더를 고르고 파일 이름을 적어 주세요.",
    "pc-exchange-save-name": "파일 이름",
    "pc-exchange-save-button": "저장",
    "pc-exchange-save-failed": "PC에서 파일을 저장하지 못했어요. 잠시 후 다시 시도해 주세요.",
    "pc-exchange-move-button": "이동",
    "pc-exchange-delete-button": "삭제",
    "pc-exchange-move-failed": "PC에서 파일을 옮기지 못했어요. 잠시 후 다시 시도해 주세요.",
    "pc-exchange-delete-failed": "PC에서 파일을 지우지 못했어요. 잠시 후 다시 시도해 주세요.",
    "pc-exchange-stop": "그만",
    "pc-exchange-stopped": "그만뒀어요 — 이미 찾은 목록은 그대로 남아 있어요.",
    "pc-exchange-searching": "{folders}개 폴더를 봤습니다 — 지금까지 {files}개를 찾았습니다.",
    "pc-exchange-working": "PC에서 작업 중 — 경과 {elapsed}",
    "pc-exchange-searched": "허용한 폴더를 다 봤습니다.",
    "pc-exchange-searched-empty": "허용한 폴더를 다 봤는데 그 이름의 파일은 없었어요.",
    "pc-exchange-partial": "일부만 받았어요 · 다시 시도해 주세요",
    "pc-exchange-choose-pc": "어느 PC를 열까요?",
    "pc-exchange-choose-folder": "어느 폴더를 열까요?",
    "pc-exchange-my-pc": "내 PC",
    "pc-exchange-up": "이전 폴더",
    "pc-exchange-search-placeholder": "이름으로 찾기",
    "pc-exchange-search": "찾기",
    "pc-exchange-contents": "이 폴더의 내용",
    "pc-exchange-more": "더 보기",
    "pc-exchange-more-remaining": "더 보기 (남은 {count}개)",
    "pc-exchange-filter-scope": "받은 {received}개 / 전체 {total}개 중에서 찾는 중",
    "pc-exchange-search-all": "폴더 전체에서 찾기",
    "pc-exchange-folder-search-empty": "폴더 전체에서 찾았지만 없어요",
    "pc-exchange-close": "닫기",
    "pc-exchange-open-file": "이 파일 열기",
    "pc-exchange-no-pc": "아직 연결된 PC가 없어요. PC를 연결한 뒤 다시 시도해 주세요.",
    "pc-exchange-no-answer": "PC에서 답이 왔는지 확인하지 못했어요. 잠시 후 다시 시도해 주세요.",
  });

  function ensurePcLocale() {
    if (window.__padiemLocale && typeof window.__padiemLocale.text === "function") return;
    window.__padiemLocale = {
      text(key, variables) {
        const text = PC_EXCHANGE_COPY_KO[key];
        if (typeof text !== "string") return key;
        if (!variables) return text;
        return text.replace(/\{(\w+)\}/g, (match, name) =>
          (Object.prototype.hasOwnProperty.call(variables, name) ? String(variables[name]) : match));
      },
    };
  }

  let pcExchangeLoading = null;
  function loadPcExchange() {
    ensurePcLocale();
    if (window.PadiemPcFileExchange) return Promise.resolve(window.PadiemPcFileExchange);
    if (pcExchangeLoading) return pcExchangeLoading;
    pcExchangeLoading = new Promise((resolve, reject) => {
      const head = document.head || document.body;
      if (head && !document.querySelector("link[data-council-pc-exchange]")) {
        const css = document.createElement("link");
        css.rel = "stylesheet";
        css.href = "./static/pc-file-exchange.css";
        // ?v=<content hash> from the served map; the bare URL stays the fallback.
        css.href = versionedAsset(css.href);
        css.setAttribute("data-council-pc-exchange", "1");
        head.appendChild(css);
      }
      const script = document.createElement("script");
      script.src = "./static/pc-file-exchange.js";
      // ?v=<content hash> from the served map; the bare URL stays the fallback.
      script.src = versionedAsset(script.src);
      script.addEventListener("load", () => {
        if (window.PadiemPcFileExchange) resolve(window.PadiemPcFileExchange);
        else reject(new Error("pc-exchange-unavailable"));
      }, { once: true });
      script.addEventListener("error", () => reject(new Error("pc-exchange-unavailable")), { once: true });
      head.appendChild(script);
    });
    return pcExchangeLoading;
  }

  async function pcLinked() {
    try {
      const res = await fetch("/api/pc/pairings", { credentials: "include", cache: "no-store" });
      if (!res.ok) return null;
      const body = await res.json().catch(() => null);
      const links = body && Array.isArray(body.links) ? body.links : [];
      return links.some((link) => link && link.state === "active");
    } catch (_) {
      return null;
    }
  }

  function openComputerConnect() {
    try { window.location.assign(COMPUTER_CONNECT_HREF); } catch (_) {}
  }

  async function pcReferenceEntry(picked) {
    if (!picked) return null;
    if (typeof picked.content === "string" && picked.content.trim()) {
      return { name: picked.name || "가져온 글", text: picked.content };
    }
    if (!picked.fileId) return null;
    try {
      const res = await fetch("/api/pc/reference", {
        method: "POST",
        credentials: "include",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_id: picked.fileId }),
      });
      if (!res.ok) {
        const refused = await res.json().catch(() => null);
        const code = refused && refused.error && typeof refused.error.code === "string"
          ? refused.error.code : "";
        if (code === "hwp_encrypted") return { error: PC_REF_COPY.hwpEncrypted };
        if (code === "hwp_distributable") return { error: PC_REF_COPY.hwpDistributable };
        if (code === "file_lane_unavailable") return { error: PC_REF_COPY.laneDown };
        return null;
      }
      const body = await res.json().catch(() => null);
      if (!body || body.ok !== true || typeof body.text !== "string" || !body.text.trim()) return null;
      return {
        name: typeof body.name === "string" && body.name ? body.name : (picked.name || "가져온 글"),
        text: body.text,
      };
    } catch (_) {
      return null;
    }
  }

  // One section per tool: the pick button, the files the owner chose with their
  // preview, and — when no PC is linked — one calm sentence with the way to
  // connect, never an error.
  function createPcReferenceSection() {
    const box = el("div", "council-pc-ref");
    const pick = el("button", "council-pc-ref-pick", PC_REF_COPY.pick);
    pick.type = "button";
    const note = el("p", "council-pc-ref-note");
    note.hidden = true;
    const status = el("p", "council-pc-ref-status");
    status.hidden = true;
    const list = el("ul", "council-pc-ref-list");
    list.hidden = true;
    box.append(pick, note, list, status);
    const files = [];

    function say(text) {
      status.textContent = text || "";
      status.hidden = !text;
    }
    function showNoPc() {
      pick.hidden = true;
      note.textContent = PC_REF_COPY.noPc;
      const connect = el("a", "council-pc-ref-connect", PC_REF_COPY.connect);
      connect.href = COMPUTER_CONNECT_HREF;
      note.appendChild(connect);
      note.hidden = false;
    }
    function render() {
      list.replaceChildren();
      files.forEach((file, index) => {
        const item = el("li", "council-pc-ref-item");
        const head = el("div", "council-pc-ref-head");
        head.append(el("strong", "council-pc-ref-name", file.name));
        head.append(el("span", "council-pc-ref-chars", file.text.length.toLocaleString("ko-KR") + "자"));
        const drop = el("button", "council-pc-ref-remove", PC_REF_COPY.remove);
        drop.type = "button";
        drop.addEventListener("click", () => {
          files.splice(index, 1);
          render();
        });
        head.append(drop);
        item.append(head, el("pre", "council-pc-ref-preview", file.text));
        list.append(item);
      });
      list.hidden = files.length === 0;
      pick.textContent = files.length ? PC_REF_COPY.again : PC_REF_COPY.pick;
    }

    async function addPicked(picked) {
      say("");
      const entry = await pcReferenceEntry(picked);
      if (entry && typeof entry.error === "string") { say(entry.error); return; }
      if (!entry) { say(PC_REF_COPY.unreadable); return; }
      files.push(entry);
      render();
    }

    pick.addEventListener("click", async () => {
      say("");
      let component;
      try { component = await loadPcExchange(); } catch (_) { component = null; }
      if (!component || typeof component.open !== "function") {
        say(PC_REF_COPY.unavailable);
        return;
      }
      component.open({ onSelect: (picked) => { void addPicked(picked); } });
    });

    let checked = false;
    function check() {
      if (checked) return;
      checked = true;
      void pcLinked().then((linked) => {
        if (linked === false) showNoPc();
      });
    }

    return {
      box,
      check,
      read() {
        const lineBreak = String.fromCharCode(10);
        return files
          .map((file, index) => "[참고 글 " + (index + 1) + ": " + file.name + "]" + lineBreak + file.text)
          .join(lineBreak + lineBreak);
      },
    };
  }

  function pcSaveFileName(base) {
    const title = fileNamePart(base) || "글";
    return title + "_" + todayStamp() + ".txt";
  }

  // Returns "empty" | "no-pc" | "unavailable" | "opened". A save always offers
  // a NEW dated name; the original document is never the destination.
  async function saveTextToPc(text, baseName, onSaved) {
    const content = String(text || "").trim();
    if (!content) return "empty";
    const linked = await pcLinked();
    if (linked !== true) return "no-pc";
    let component;
    try { component = await loadPcExchange(); } catch (_) { component = null; }
    if (!component || typeof component.open !== "function") return "unavailable";
    component.open({
      mode: "save",
      content,
      fileName: pcSaveFileName(baseName),
      onSave: () => { if (onSaved) onSaved(); },
    });
    return "opened";
  }

  function wirePcSave(button, output, notice, baseName) {
    if (!button) return;
    button.addEventListener("click", async () => {
      const outcome = await saveTextToPc(output.value, baseName(), () => setNotice(notice, PC_REF_COPY.saved, "info"));
      if (outcome === "no-pc") {
        setNoticeWithLink(notice, PC_REF_COPY.saveNoPc, PC_REF_COPY.connect, COMPUTER_CONNECT_HREF);
      } else if (outcome === "unavailable") {
        setNotice(notice, PC_REF_COPY.saveUnavailable, "error");
      }
    });
  }

  function setNoticeWithLink(line, text, label, href) {
    if (!line) return;
    line.textContent = text;
    const link = el("a", "council-notice-link", label);
    link.href = href;
    line.appendChild(link);
    line.hidden = false;
    line.dataset.tone = "info";
  }

  // A failed generation carries its own 다시 시도 — the owner does not have to
  // find the form button again (#5895).
  function setNoticeWithRetry(line, text, run) {
    if (!line) return;
    line.textContent = text;
    const retry = el("button", "council-notice-retry", "다시 시도");
    retry.type = "button";
    retry.addEventListener("click", () => {
      setNotice(line, "");
      retry.disabled = true;
      run();
    });
    line.appendChild(retry);
    line.hidden = false;
    line.dataset.tone = "error";
  }

  // ── speech module (prompt template ported verbatim from util-menu.js) ────

  function buildSpeechPrompt(form, references) {
    const d = new FormData(form);
    const event = (d.get("event") || "").trim();
    const date = (d.get("date") || "").trim();
    const place = (d.get("place") || "").trim();
    const nature = (d.get("nature") || "").trim();
    const audience = (d.get("audience") || "").trim();
    const author = (d.get("author") || "").trim();
    const message = (d.get("message") || "").trim();
    const emphasis = (d.get("emphasis") || "").trim();
    const length = d.get("length") || "medium";
    const tone = d.get("tone") || "formal";
    const style = (d.get("style") || "").trim();
    const lengthMap = { short: "짧게(300자 내외)", medium: "보통(600자 내외)", long: "길게(1000자 내외)" };
    const toneMap = { formal: "공식적이고 격식 있는", warm: "따뜻하고 친근한", concise: "간결하고 명료한" };
    let prompt = "다음 행사 정보를 바탕으로 축사/인사말 초안을 작성해 주세요.\n\n";
    prompt += `행사명: ${event}\n`;
    if (date) prompt += `행사 날짜: ${date}\n`;
    if (place) prompt += `장소: ${place}\n`;
    if (nature) prompt += `행사 성격: ${nature}\n`;
    if (audience) prompt += `참석 대상: ${audience}\n`;
    if (author) prompt += `작성자/직책: ${author}\n`;
    if (message) prompt += `주요 메시지: ${message}\n`;
    if (emphasis) prompt += `강조 내용: ${emphasis}\n`;
    prompt += `분량: ${lengthMap[length] || "보통"}\n`;
    prompt += `말투: ${toneMap[tone] || "공식적"}\n`;
    if (style) prompt += `\n아래는 사용자의 기존 축사/인사말 샘플입니다. 이 문체와 어휘, 표현 특성을 반영하여 작성해 주세요:\n---\n${style}\n---\n`;
    // #5895: texts brought from the owner's PC are references, never copies.
    if (references) prompt += `\n아래는 사용자의 PC에서 가져온 예전 글입니다. 문체와 어휘, 글의 구성을 참고하되 그대로 옮기지 마세요:\n---\n${references}\n---\n`;
    prompt += "\n축사 초안을 작성해 주세요. 행사 성격에 맞는 공식 축사 형식으로 작성하고, 인사말과 마무리 인사를 포함해 주세요.";
    return prompt;
  }

  const speechModule = (() => {
    // #B8: only 행사명·참석 대상·직책과 이름·분량 face the writer first; the
    // rest of the form folds under "더 자세히". The last 직책과 이름 is
    // remembered on this host, so a repeat writer does not retype it.
    const AUTHOR_KEY = "padiem-council-speech-author";

    function field(name, label, type, required, placeholder, rows) {
      const l = el("label", null, label + " ");
      let input;
      if (type === "textarea") {
        input = document.createElement("textarea");
        input.rows = rows || 3;
      } else {
        input = document.createElement("input");
        input.type = type;
      }
      input.name = name;
      if (required) input.required = true;
      if (placeholder) input.placeholder = placeholder;
      l.appendChild(input);
      return l;
    }

    let pcSection = null;

    function buildForm(host) {
      const form = el("form", "council-form");
      form.id = "councilSpeechForm";

      const refFieldset = el("fieldset", "council-fieldset");
      refFieldset.appendChild(el("legend", null, "참고 글"));
      pcSection = createPcReferenceSection();
      refFieldset.appendChild(pcSection.box);
      form.appendChild(refFieldset);

      const primary = el("fieldset", "council-fieldset");
      primary.appendChild(el("legend", null, "행사 정보"));
      primary.append(
        field("event", "행사명", "text", true, "예: 제78주년 광복절 기념식"),
        field("audience", "참석 대상", "text", false, "예: 지역 주민 200명"),
        field("author", "직책과 이름", "text", false, "예: 지역구 국회의원 김의민"),
      );
      const lengthLabel = el("label", null, "분량 ");
      const lengthSel = document.createElement("select");
      lengthSel.name = "length";
      [["short", "1분"], ["medium", "3분"], ["long", "5분"]].forEach(([v, t]) => {
        const o = document.createElement("option");
        o.value = v; o.textContent = t;
        if (v === "medium") o.selected = true;
        lengthSel.appendChild(o);
      });
      lengthLabel.appendChild(lengthSel);
      primary.appendChild(lengthLabel);
      form.appendChild(primary);

      // The folded half keeps every field the prompt already read; folding is
      // presentation, not a new form contract.
      const more = document.createElement("details");
      more.className = "council-more";
      more.id = "councilSpeechMore";
      more.appendChild(el("summary", null, "더 자세히 (날짜·장소·메시지·말투)"));
      const moreBody = el("div", "council-more-body");
      moreBody.append(
        field("date", "행사 날짜", "date", false, ""),
        field("place", "장소", "text", false, "예: 시청 대강당"),
        field("nature", "행사 성격", "text", false, "예: 지역 행사"),
        field("message", "주요 메시지", "textarea", false, "예: 함께 성장하는 지역사회"),
        field("emphasis", "강조 내용", "textarea", false, "예: 상생과 배려", 2),
      );
      const toneLabel = el("label", null, "말투 ");
      const toneSel = document.createElement("select");
      toneSel.name = "tone";
      [["formal", "공식"], ["warm", "따뜻한"], ["concise", "간결"]].forEach(([v, t]) => {
        const o = document.createElement("option");
        o.value = v; o.textContent = t;
        if (v === "formal") o.selected = true;
        toneSel.appendChild(o);
      });
      toneLabel.appendChild(toneSel);
      moreBody.appendChild(toneLabel);
      const styleLabel = el("label", null, "기존 축사 샘플 (말투 반영) ");
      const styleTa = document.createElement("textarea");
      styleTa.name = "style";
      styleTa.rows = 4;
      styleTa.placeholder = "기존 축사/인사말 원문 붙여넣기";
      styleLabel.appendChild(styleTa);
      moreBody.appendChild(styleLabel);
      more.appendChild(moreBody);
      form.appendChild(more);

      const authorField = form.querySelector("[name=author]");
      try {
        const saved = store() && store().getItem(AUTHOR_KEY);
        if (saved && authorField) authorField.value = String(saved);
      } catch (_) { /* storage refusal leaves the field empty */ }
      if (authorField && authorField.addEventListener) {
        authorField.addEventListener("change", () => {
          try { if (store()) store().setItem(AUTHOR_KEY, String(authorField.value || "")); } catch (_) {}
        });
      }

      const formActions = el("div", "council-form-actions");
      const submitBtn = el("button", "council-generate", "초안 생성");
      submitBtn.type = "submit";
      submitBtn.id = "councilSpeechGenerate";
      formActions.append(submitBtn);
      form.appendChild(formActions);
      host.appendChild(form);

      const notice = noticeLine("councilSpeechNotice");
      host.appendChild(notice);

      const panel = resultPanel({
        id: "councilSpeechResult", outputId: "councilSpeechOutput", rows: 12,
        title: "생성 결과", copyId: "councilSpeechCopy",
        saveId: "councilSpeechSave", downloadId: "councilSpeechDownload",
        downloadHwpxId: "councilSpeechDownloadHwpx", downloadDocxId: "councilSpeechDownloadDocx",
        pcSaveId: "councilSpeechPcSave",
      });
      const { result, output, copyBtn, saveBtn, dlHwpxBtn, dlDocxBtn, dlBtn, pcSaveBtn } = panel;
      host.appendChild(result);

      // #5731 contract: the stored speech history is listed on tool re-entry
      // too (not only right after a save), and each row carries a “참고로
      // 선택” action that fills the style sample textarea with the stored
      // body — the next generation fences it as the sample, like a pasted
      // one. Reuse of the existing owner/project files, no second store.
      const savedList = el("div", "council-saved-list");
      savedList.id = "councilSpeechSaved";
      host.appendChild(savedList);

      let busy = false;
      let failed = false;
      function refreshSave() {
        saveBtn.disabled = busy || failed || !String(output.value || "").trim();
      }

      async function refreshSpeechList() {
        const pid = await councilProject.ensure();
        if (!pid) return;
        const files = await listProjectFiles(pid);
        const speechFiles = files.filter(isSpeechFile).filter(sameCountry);
        savedList.replaceChildren();
        savedList.appendChild(el("h3", null, "저장된 축사 원고"));
        if (!speechFiles.length) {
          savedList.appendChild(el("p", "council-empty", "저장된 축사가 없습니다."));
          return;
        }
        const ul = document.createElement("ul");
        speechFiles.forEach((f) => {
          const li = document.createElement("li");
          li.className = "council-saved-item";
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "council-saved-open";
          btn.textContent = f.name + " (" + (f.content_chars || 0) + "자)";
          btn.addEventListener("click", async () => {
            const content = await fetchProjectFile(pid, f.id);
            if (typeof content === "string") {
              output.value = content;
              result.hidden = false;
              failed = false;
              setNotice(notice, f.name + "를 열었습니다. 같은 이름으로 저장하면 새 이름/덮어쓰기를 묻습니다.", "info");
              refreshSave();
            } else {
              setNotice(notice, "저장된 축사의 본문을 읽을 수 없습니다.", "error");
            }
          });
          li.appendChild(btn);
          const useAsRef = document.createElement("button");
          useAsRef.type = "button";
          useAsRef.className = "council-speech-use-ref";
          useAsRef.dataset.fileId = f.id;
          useAsRef.textContent = "참고로 선택";
          useAsRef.addEventListener("click", async () => {
            const styleField = form.querySelector("[name=style]");
            if (!styleField) { setNotice(notice, "참고 원고 필드를 찾을 수 없습니다.", "error"); return; }
            const res = await fetch("/api/projects/" + encodeURIComponent(pid) + "/files/" + encodeURIComponent(f.id), { credentials: "include" });
            if (!res.ok) { setNotice(notice, "참고 원고를 불러오지 못했습니다.", "error"); return; }
            const data = await res.json().catch(() => null);
            const content = data && data.file && (data.file.content || data.file.text);
            if (typeof content !== "string" || !content.trim()) { setNotice(notice, "참고 원고의 본문을 읽을 수 없습니다.", "error"); return; }
            styleField.value = content;
            setNotice(notice, "참고 원고를 말투 샘플에 넣었습니다.", "info");
          });
          li.appendChild(useAsRef);
          ul.appendChild(li);
        });
        savedList.appendChild(ul);
      }

      async function runGeneration() {
        if (busy) return;
        busy = true;
        submitBtn.disabled = true;
        failed = false;
        refreshSave();
        setNotice(notice, "생성 중…", "busy");
        try {
          const answer = await apiChat(
            buildSpeechPrompt(form, pcSection ? pcSection.read() : ""), "speech",
            (partial) => {
              output.value = partial;
              result.hidden = false;
            },
          );
          output.value = answer;
          result.hidden = false;
          failed = false;
          setNotice(notice, "");
        } catch (err) {
          failed = true;
          setNoticeWithRetry(notice, generationFailureText(err), runGeneration);
          if (!String(output.value || "").trim()) result.hidden = true;
        } finally {
          busy = false;
          submitBtn.disabled = false;
          refreshSave();
        }
      }
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        void runGeneration();
      });
      wireCopy(copyBtn, output);
      dlBtn.addEventListener("click", () => {
        const text = String(output.value || "").trim();
        if (text) downloadText(text, speechFileName(form));
      });
      wireResultDownloads({
        hwpxBtn: dlHwpxBtn, docxBtn: dlDocxBtn, kind: "speech",
        baseName: () => speechBaseName(form),
        title: () => {
          const event = form.querySelector("[name=event]");
          return fileNamePart(event ? event.value : "") || "행사";
        },
        text: () => String(output.value || "").trim(),
      });
      wirePcSave(pcSaveBtn, output, notice, () => {
        const event = form.querySelector("[name=event]");
        return "축사_" + (fileNamePart(event ? event.value : "") || "행사");
      });
      saveBtn.addEventListener("click", async () => {
        const text = output.value.trim();
        if (!text || saveBtn.disabled) return;
        const pid = await councilProject.ensure();
        if (!pid) {
          setNotice(notice, "저장할 프로젝트를 찾지 못했습니다. 잠시 후 다시 시도해 주세요.", "error");
          return;
        }
        saveBtn.disabled = true;
        saveBtn.textContent = "저장 중…";
        const outcome = await saveCouncilText({
          pid, name: speechFileName(form), text, kind: "speech", anchor: saveBtn,
        });
        saveBtn.textContent = "저장";
        refreshSave();
        if (outcome.file) {
          saveBtn.textContent = "저장됨";
          setTimeout(() => { saveBtn.textContent = "저장"; }, 1500);
          setNotice(notice, "");
          await refreshSpeechList();
        } else if (outcome.failure) {
          setNotice(notice, saveFailureText(outcome.failure), "error");
        }
      });
      refreshSave();
      // Re-entry lists the stored history too (#5731).
      refreshSpeechList();
      onCountryChange(refreshSpeechList);
    }

    return {
      build(host) { buildForm(host); },
      buildPrompt: buildSpeechPrompt,
      // The PC check runs when the tool is actually opened, never at page load.
      onOpen() { if (pcSection) pcSection.check(); },
    };
  })();

  // ── sns module (prompt template ported verbatim from util-menu.js) ───────
  // Photo composition connected through the merged #5728/#5924 contract:
  // binary originals upload via the SAME project-file channel as text
  // drafts, one version-2 roster JSON carries the order/positions/saved
  // draft/platform, and re-entry restores the composition ONCE at build
  // time. No LOCAL 1 code is copied — the storage contract is the shipped
  // PADIEM one, re-stated against this app's own DOM.

  function buildSnsPrompt(form, platform, photos, references) {
    const d = new FormData(form);
    const event = (d.get("event") || "").trim();
    const whenwhere = (d.get("whenwhere") || "").trim();
    const content = (d.get("content") || "").trim();
    const memo = (d.get("memo") || "").trim();
    const audience = (d.get("audience") || "").trim();
    const tone = d.get("tone") || "professional";
    const toneMap = { casual: "캐주얼하고 친근한", professional: "전문적이고 신뢰감 있는", emotional: "감성적이고 따뜻한" };
    const platformGuide = {
      blog: "블로그 게시글: 800-1200자, 제목 포함, 소제목 구분, 상세한 설명",
      facebook: "페이스북 게시글: 300-500자, 친근한 톤, 이모지 적절히, 해시태그 3-5개",
      instagram: "인스타그램 게시글: 150-300자, 짧고 임팩트 있는, 해시태그 10-15개, 이모지 풍부",
    };
    let prompt = `다음 행사 정보를 바탕으로 ${platformGuide[platform]}을 작성해 주세요.\n\n`;
    prompt += `행사명: ${event}\n`;
    if (whenwhere) prompt += `날짜·장소: ${whenwhere}\n`;
    prompt += `주요 내용: ${content}\n`;
    if (photos && photos.length) {
      const names = photos.map((ph) => ph.name).join(", ");
      prompt += `첨부 사진: ${photos.length}장 (${names})\n`;
      prompt += platform === "blog"
        ? "사진은 본문 문단 사이에 삽입됩니다. 각 사진이 어느 내용과 이어지는지 참고해서 문단을 구성해 주세요.\n"
        : "사진은 본문과 구분된 게시물 미디어로 첨부됩니다. 본문에 이미지 위치 설명은 넣지 마세요.\n";
    }
    if (memo) prompt += `메모: ${memo}\n`;
    if (audience) prompt += `대상 독자: ${audience}\n`;
    prompt += `문체: ${toneMap[tone]}\n`;
    // #5895: texts brought from the owner's PC are references, never copies.
    if (references) prompt += `\n아래는 사용자의 PC에서 가져온 예전 글입니다. 문체와 어휘, 글의 구성을 참고하되 그대로 옮기지 마세요:\n---\n${references}\n---\n`;
    prompt += "\n제목, 본문, 해시태그를 구분하여 작성해 주세요.";
    return prompt;
  }

  const snsModule = (() => {
    let pcSection = null;

    function buildForm(host) {
      const form = el("form", "council-form");
      form.id = "councilSnsForm";
      const refFieldset = el("fieldset", "council-fieldset");
      refFieldset.appendChild(el("legend", null, "참고 글"));
      pcSection = createPcReferenceSection();
      refFieldset.appendChild(pcSection.box);
      form.appendChild(refFieldset);
      const fields = [
        ["event", "행사명", "text", true, "예: 주민 정원 사업 설명회"],
        ["whenwhere", "날짜·장소", "text", false, "예: 10월 30일 오후 2시, 구청 소회의실"],
        ["content", "주요 내용", "textarea", true, "예: 정원 사업 신청 방법과 지원 금액 안내"],
        ["memo", "메모", "textarea", false, "예: 참석자에게 강조할 한 가지"],
        ["audience", "대상 독자", "text", false, "예: 구내 상인"],
      ];
      fields.forEach(([name, label, type, req, placeholder]) => {
        const l = el("label", null, label + " ");
        let field;
        if (type === "textarea") {
          field = document.createElement("textarea");
          field.name = name;
          field.rows = name === "content" ? 3 : 2;
        } else {
          field = document.createElement("input");
          field.name = name;
          field.type = "text";
        }
        if (req) field.required = true;
        if (placeholder) field.placeholder = placeholder;
        l.appendChild(field);
        form.appendChild(l);
      });
      const toneLabel = el("label", null, "문체 ");
      const toneSel = document.createElement("select");
      toneSel.name = "tone";
      [["casual", "캐주얼"], ["professional", "전문적"], ["emotional", "감성적"]].forEach(([v, t]) => {
        const o = document.createElement("option");
        o.value = v; o.textContent = t;
        if (v === "professional") o.selected = true;
        toneSel.appendChild(o);
      });
      toneLabel.appendChild(toneSel);
      form.appendChild(toneLabel);

      // 플랫폼 이름은 결과 제목과 다운로드 파일 이름이 함께 읽는다.
      const title = el("h3", null, "블로그 게시글");
      title.id = "councilSnsTitle";

      const tabDiv = el("div", "council-sns-tabs");
      const tabNames = { blog: "블로그", facebook: "페이스북", instagram: "인스타그램" };
      let platform = "blog";
      Object.keys(tabNames).forEach((key) => {
        const b = el("button", "council-sns-tab" + (key === "blog" ? " active" : ""), tabNames[key]);
        b.type = "button";
        b.dataset.platform = key;
        b.addEventListener("click", () => {
          tabDiv.querySelectorAll(".council-sns-tab").forEach((x) => x.classList.remove("active"));
          b.classList.add("active");
          platform = key;
          title.textContent = tabNames[key] + " 게시글";
          renderPhotoList();
          renderPreview();
        });
        tabDiv.appendChild(b);
      });
      form.appendChild(tabDiv);

      // #5728: photo composition replaces the old direct photo-URL field.
      // Photos are picked locally (multiple, image/*), previewed as
      // thumbnails, removable and re-orderable. Blog places each photo
      // between chosen paragraphs; facebook/instagram treat them as
      // separate post media. Photos survive platform switches.
      const photos = [];
      const photoBox = el("div", "council-photos");
      photoBox.id = "councilSnsPhotoBox";
      const photoHead = el("div", "council-photos-head");
      const photoTitle = el("span", "council-photos-title", "사진");
      const photoAdd = el("button", "council-photo-add", "사진 추가");
      photoAdd.type = "button";
      photoAdd.id = "councilSnsPhotoAdd";
      const photoInput = document.createElement("input");
      photoInput.type = "file";
      photoInput.accept = "image/png,image/jpeg,image/webp";
      photoInput.multiple = true;
      photoInput.hidden = true;
      photoInput.id = "councilSnsPhotoInput";
      const photoCount = el("span", "council-photos-count", "0장");
      photoCount.id = "councilSnsPhotoCount";
      photoHead.append(photoTitle, photoAdd, photoInput, photoCount);
      const photoList = el("ul", "council-photo-list");
      photoList.id = "councilSnsPhotoList";
      const photoNote = el("p", "council-photo-note");
      photoNote.id = "councilSnsPhotoNote";
      photoBox.append(photoHead, photoList, photoNote);
      form.appendChild(photoBox);

      function photoNoteText() {
        if (platform === "blog") return "블로그는 각 사진을 본문 문단 사이에 삽입합니다. 미리보기에서 위치를 확인하세요.";
        if (platform === "instagram") return "인스타그램은 사진을 별도 미디어로 첨부합니다(이미지 중심 미리보기).";
        return "페이스북은 사진을 본문과 구분된 게시물 미디어로 첨부합니다.";
      }

      function readImageDataUrl(file) {
        return new Promise((resolve) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result || ""));
          reader.onerror = () => resolve("");
          reader.readAsDataURL(file);
        });
      }

      // #5728: shrink big photos BEFORE the upload. A resize that fails leaves
      // the original bytes alone — the upload still happens, so a resize
      // failure never costs the user their photo.
      async function preparePhoto(file) {
        const original = await readImageDataUrl(file);
        if (!original) return null;
        let type = file.type || "image/jpeg";
        // Only a real browser can decode and re-encode an image; a DOM without
        // Image (the Node harness) keeps the picked bytes and never waits.
        const canDecode = typeof window === "object" && typeof window.Image === "function";
        if (canDecode) {
          try {
            const shrink = await loadPhotoResize();
            const out = await shrink.resizeDataUrl(original, shrink.MAX_EDGE, type);
            if (out && out.resized && typeof out.dataUrl === "string") {
              const mime = (out.dataUrl.match(/^data:([^;,]+)/) || [])[1];
              if (mime) type = mime;
              return { blob: dataUrlToBlob(out.dataUrl) || file, type: type, dataUrl: out.dataUrl };
            }
          } catch (_error) { /* the original bytes are still uploaded */ }
        }
        return { blob: file, type: type, dataUrl: original };
      }

      // #5728: the roster is one small JSON file that carries the whole
      // persisted composition — the photo order, the blog insertion
      // positions, the saved draft text and the platform it was written
      // for (version 2). The photo originals themselves are already stored
      // (each add uploaded them). Rewrites replace the previous roster in
      // place, so a stale roster can never resurrect a photo the owner
      // deleted.
      const PHOTO_ROSTER_NAME = "SNS 사진 구성.json";
      // The last explicitly saved draft rides every roster rewrite, so a
      // later photo change never silently drops the saved text.
      let lastSavedDraft = null;
      // Roster writes serialize: two changes landing together must never
      // leave two roster files behind (an older one would win a name lookup
      // and silently revert the newer order or position).
      let rosterWriteChain = Promise.resolve();
      function writePhotoRoster(pid, savedDraft) {
        if (!pid) return;
        const carriedDraft = savedDraft === undefined ? lastSavedDraft : savedDraft;
        rosterWriteChain = rosterWriteChain.then(async () => {
          const roster = { version: 2, photos: photos
            .map((p) => ({ fileId: String(p.id), name: p.name, position: p.position })) };
          // The saved draft rides with the roster so re-entry restores the
          // text too; the last explicit 저장 wins.
          if (carriedDraft && carriedDraft.text) {
            roster.draft = { text: carriedDraft.text, platform: carriedDraft.platform || platform };
          }
          const existing = await listProjectFiles(pid);
          const previous = existing.find((f) => f.name === PHOTO_ROSTER_NAME);
          // The roster is one record that is updated in place. Rewriting it
          // through PUT keeps its id and never leaves a second copy behind.
          if (previous) {
            await overwriteProjectFile(pid, previous.id, JSON.stringify(roster));
          } else {
            await saveProjectFile(pid, PHOTO_ROSTER_NAME, JSON.stringify(roster), "application/json");
          }
        }).catch(() => { /* the composition keeps working; the roster stays last-known */ });
        return rosterWriteChain;
      }

      function renderPhotoList() {
        photoCount.textContent = photos.length + "장";
        photoNote.textContent = photoNoteText();
        photoList.replaceChildren();
        photos.forEach((item) => {
          const li = el("li", "council-photo-item");
          const img = document.createElement("img");
          img.className = "council-photo-thumb";
          img.src = item.dataUrl;
          img.alt = item.name;
          const nameSpan = el("span", "council-photo-name", item.name);
          const controls = el("div", "council-photo-controls");
          if (platform === "blog") {
            const posLabel = el("label", "council-photo-pos", "삽입 위치 ");
            const sel = document.createElement("select");
            sel.className = "council-photo-pos-select";
            sel.dataset.photoId = String(item.id);
            const opts = [["auto", "자동"], ["0", "맨 앞"], ["end", "문단 끝"]];
            opts.forEach(([v, t]) => { const o = document.createElement("option"); o.value = v; o.textContent = t; sel.appendChild(o); });
             sel.value = item.position;
             sel.addEventListener("change", async () => { item.position = sel.value; renderPreview(); await writePhotoRoster(councilProject.get()); });
            posLabel.appendChild(sel);
            controls.appendChild(posLabel);
          }
          const up = el("button", "council-photo-move", "↑"); up.type = "button"; up.dataset.move = "-1"; up.dataset.photoId = String(item.id);
          const down = el("button", "council-photo-move", "↓"); down.type = "button"; down.dataset.move = "1"; down.dataset.photoId = String(item.id);
          const del = el("button", "council-photo-remove", "삭제"); del.type = "button"; del.dataset.photoId = String(item.id); del.dataset.action = "remove";
          controls.append(up, down, del);
          li.append(img, nameSpan, controls);
          photoList.appendChild(li);
        });
      }

      photoList.addEventListener("click", async (ev) => {
        const target = ev.target;
        if (!target || !target.dataset) return;
        // Stored photos carry server ids like "file_<hex>"; local-only rows
        // carry numeric ids. Compare as strings so both resolve.
        const id = String(target.dataset.photoId);
        const index = photos.findIndex((p) => String(p.id) === id);
        if (index < 0) return;
        if (target.dataset.move) {
          const to = index + Number(target.dataset.move);
          if (to < 0 || to >= photos.length) return;
          const [moved] = photos.splice(index, 1);
          photos.splice(to, 0, moved);
        } else if (target.dataset.action === "remove") {
          const pid = councilProject.get();
          if (photos[index].id && pid) {
            const gone = await deleteProjectFile(pid, photos[index].id);
            if (!gone) { alert("사진 삭제 실패: " + photos[index].name); return; }
          }
          photos.splice(index, 1);
        } else {
          return;
        }
         renderPhotoList();
         renderPreview();
         // Every durable composition change (reorder and removal here,
         // insertion positions on the selects) rewrites the roster file, so
         // the order and the blog insertion positions outlive the session.
         await writePhotoRoster(councilProject.get());
       });

      // #5728/#5895: with a linked PC, 사진 추가 reuses the shared 가져오기
      // dialog and the picked PC file is read through /api/pc/file into this
      // very upload pipeline. Without a linked PC the local picker stays — it
      // works on a phone too.
      const PC_PHOTO_FORMATS = "사진은 PNG·JPG·WEBP만 추가할 수 있어요: ";
      function photoBytesType(bytes) {
        const head = bytes && bytes.length >= 12 ? bytes : null;
        if (!head) return null;
        if (head[0] === 0x89 && head[1] === 0x50 && head[2] === 0x4e && head[3] === 0x47) return "image/png";
        if (head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff) return "image/jpeg";
        const riff = String.fromCharCode(head[0], head[1], head[2], head[3]);
        const form = String.fromCharCode(head[8], head[9], head[10], head[11]);
        if (riff === "RIFF" && form === "WEBP") return "image/webp";
        return null;
      }
      async function importPickedPhoto(picked) {
        if (!picked || !picked.fileId) return;
        const name = picked.name || "사진";
        let bytes;
        try {
          const res = await fetch(
            "/api/pc/file?dispatch_id=" + encodeURIComponent(picked.fileId),
            { credentials: "include", cache: "no-store" },
          );
          if (!res.ok) throw new Error("http_" + res.status);
          bytes = new Uint8Array(await (await res.blob()).arrayBuffer());
        } catch (error) {
          const matched = /^http_(\d+)$/.exec(String((error && error.message) || ""));
          const status = matched ? Number(matched[1]) : 0;
          const why = status === 0 ? GEN_OFFLINE_COPY : (GEN_ERROR_COPY[status] || "잠시 후 다시 시도해 주세요.");
          setNotice(notice, "PC에서 사진을 가져오지 못했습니다: " + name + " — " + why, "error");
          return;
        }
        const type = photoBytesType(bytes);
        if (!type) { setNotice(notice, PC_PHOTO_FORMATS + name, "error"); return; }
        if (typeof File !== "function") return;
        await addPhotoFiles([new File([bytes], name, { type: type })]);
      }
      photoAdd.addEventListener("click", async () => {
        const linked = await pcLinked();
        if (linked !== true) { photoInput.click(); return; }
        let component;
        try { component = await loadPcExchange(); } catch (_) { component = null; }
        if (!component || typeof component.open !== "function") { photoInput.click(); return; }
        component.open({ mode: "import", onSelect: (picked) => { void importPickedPhoto(picked); } });
      });
      async function addPhotoFiles(pickedFiles) {
        const files = Array.from(pickedFiles || []);
        const failed = [];
        for (const file of files) {
          if (!file || String(file.type || "").indexOf("image/") !== 0) continue;
          // A photo joins the composition only once the project-file upload
          // succeeded — the thumbnail and the stored original are the same
          // bytes, and a failed upload never looks "saved".
          const pid = await councilProject.ensure();
          if (!pid) { failed.push(file.name); continue; }
          const prepared = await preparePhoto(file);
          if (!prepared) { failed.push(file.name); continue; }
          const stored = await uploadProjectImage(pid, prepared.blob, file.name, prepared.type);
          if (!stored) { failed.push(file.name); continue; }
          photos.push({ id: stored.id, name: file.name, dataUrl: prepared.dataUrl, position: "auto" });
        }
        if (failed.length) alert("사진 저장 실패: " + failed.join(", "));
        photoInput.value = "";
        renderPhotoList();
        renderPreview();
        // An added photo is part of the durable composition as soon as its
        // upload landed — the roster records it right away.
        if (!failed.length) await writePhotoRoster(councilProject.get());
      }
      photoInput.addEventListener("change", () => { void addPhotoFiles(photoInput.files); });

      function blogParagraphs(text) {
        return String(text || "").split(new RegExp("\\n\\s*\\n")).filter((p) => p.trim());
      }

      function interleaveBlog(text) {
        const parts = blogParagraphs(text);
        if (!photos.length) return parts.map((p) => ({ type: "text", value: p }));
        const out = [];
        if (photos.some((p) => p.position === "0")) {
          photos.filter((p) => p.position === "0").forEach((p) => out.push({ type: "photo", value: p }));
        }
        parts.forEach((para, i) => {
          out.push({ type: "text", value: para });
          photos.forEach((p) => {
            if (p.position === "auto") { if (i === Math.min(photos.indexOf(p), Math.max(parts.length - 1, 0))) out.push({ type: "photo", value: p }); }
            else if (p.position === "end") { if (i === parts.length - 1) out.push({ type: "photo", value: p }); }
            else if (String(i + 1) === String(p.position)) { out.push({ type: "photo", value: p }); }
          });
        });
        return out;
      }

      function renderPreview() {
        const box = previewBox;
        if (!box || box.hidden) return;
        box.replaceChildren();
        const text = output.value || "";
        if (platform === "blog") {
          interleaveBlog(text).forEach((seg) => {
            if (seg.type === "text") { const p = el("p", "council-preview-para", seg.value); box.appendChild(p); }
            else { const im = document.createElement("img"); im.className = "council-preview-photo"; im.src = seg.value.dataUrl; im.alt = seg.value.name; box.appendChild(im); }
          });
        } else {
          if (text.trim()) { const p = el("p", "council-preview-para", text); box.appendChild(p); }
          const grid = el("div", "council-sns-media-grid" + (platform === "instagram" ? " insta" : ""));
          photos.forEach((ph) => { const im = document.createElement("img"); im.src = ph.dataUrl; im.alt = ph.name; grid.appendChild(im); });
          box.appendChild(grid);
        }
        const note = el("p", "council-photo-note", "미리보기는 초안 구성 확인용입니다. 실제 SNS 자동 게시 기능이 아닙니다.");
        box.appendChild(note);
      }

      renderPhotoList();

      const formActions = el("div", "council-form-actions");
      const submitBtn = el("button", "council-generate", "생성");
      submitBtn.type = "submit";
      submitBtn.id = "councilSnsGenerate";
      formActions.append(submitBtn);
      form.appendChild(formActions);

      const notice = noticeLine("councilSnsNotice");
      const previewBox = el("div", "council-sns-preview");
      previewBox.id = "councilSnsPreview";
      previewBox.hidden = true;
      const panel = resultPanel({
        id: "councilSnsResult", outputId: "councilSnsOutput", rows: 12,
        titleNode: title, afterOutput: previewBox, copyId: "councilSnsCopy",
        saveId: "councilSnsSave", downloadId: "councilSnsDownload",
        downloadHwpxId: "councilSnsDownloadHwpx", downloadDocxId: "councilSnsDownloadDocx",
        pcSaveId: "councilSnsPcSave",
      });
      const { result, output, copyBtn: copyB, saveBtn, dlHwpxBtn: dlHwpxB, dlDocxBtn: dlDocxB, dlBtn: dlB, pcSaveBtn } = panel;

      // 저장한 SNS 글도 다시 열 수 있다 — 축사 목록과 같은 프로젝트 파일 규칙.
      const savedList = el("div", "council-saved-list");
      savedList.id = "councilSnsSaved";
      host.replaceChildren(form, notice, result, savedList);

      async function refreshSnsList() {
        const pid = await councilProject.ensure();
        if (!pid) return;
        const files = await listProjectFiles(pid);
        const drafts = files
          .filter((f) => hasDocKind(f, "sns") || (!(f && f.doc_kind) && isSnsPostFile(f)))
          .filter(sameCountry);
        savedList.replaceChildren();
        savedList.appendChild(el("h3", null, "저장된 SNS 글"));
        if (!drafts.length) {
          savedList.appendChild(el("p", "council-empty", "저장된 SNS 글이 없습니다."));
          return;
        }
        const ul = document.createElement("ul");
        drafts.forEach((f) => {
          const li = el("li", "council-saved-item");
          const btn = el("button", "council-saved-open", f.name + " (" + (f.content_chars || 0) + "자)");
          btn.type = "button";
          btn.addEventListener("click", async () => {
            const content = await fetchProjectFile(pid, f.id);
            if (typeof content !== "string") {
              setNotice(notice, "저장된 SNS 글의 본문을 읽을 수 없습니다.", "error");
              return;
            }
            output.value = content;
            result.hidden = false;
            failed = false;
            refreshSave();
            setNotice(notice, f.name + "를 열었습니다. 같은 이름으로 저장하면 새 이름/덮어쓰기를 묻습니다.", "info");
          });
          li.appendChild(btn);
          ul.appendChild(li);
        });
        savedList.appendChild(ul);
      }

      // #5728: re-entry restores the persisted composition ONCE, at build
      // time — before any interaction with the photo list. The stored image
      // files are the originals; when the roster file exists it fixes the
      // order and the blog insertion positions, and photos it does not
      // mention still surface after it so nothing the owner stored
      // vanishes. A roster that carries a saved draft (version 2) also
      // restores the draft text and switches to the platform it was saved
      // under.
      (async () => {
        try {
          const pid = await councilProject.ensure();
          if (!pid) return;
          const files = await listProjectFiles(pid);
          const imageFiles = files.filter((f) => f.media_type === "image/png"
            || f.media_type === "image/jpeg" || f.media_type === "image/webp");
          let order = null;
          let savedDraft = null;
          const rosterFile = files.find((f) => f.name === PHOTO_ROSTER_NAME);
          if (rosterFile) {
            const detailRes = await fetch("/api/projects/" + pid + "/files/" + encodeURIComponent(rosterFile.id), { credentials: "include" });
            if (detailRes.ok) {
              const detail = await detailRes.json().catch(() => null);
              try {
                const roster = JSON.parse(String((detail && detail.file && detail.file.content) || ""));
                if (roster && Array.isArray(roster.photos)) order = roster.photos;
                // A saved draft is part of the same roster record; a v1
                // roster (photos only) leaves the draft area untouched.
                if (roster && roster.draft && typeof roster.draft.text === "string" && roster.draft.text.trim()) {
                  savedDraft = roster.draft;
                }
              } catch (_) { /* unreadable roster falls back to the stored order */ }
            }
          }
          if (savedDraft) {
            // The draft comes back with the platform it was written for;
            // photos restore after this so the preview is coherent. It also
            // rides future roster rewrites, so a later photo change never
            // silently drops the saved text.
            lastSavedDraft = savedDraft;
            result.hidden = false;
            output.value = savedDraft.text;
            previewBox.hidden = false;
            failed = false;
            refreshSave();
            if (savedDraft.platform && savedDraft.platform !== platform) {
              const targetTab = Array.from(tabDiv.querySelectorAll(".council-sns-tab")).find((t) => t.dataset.platform === savedDraft.platform);
              if (targetTab) targetTab.click();
              else { platform = savedDraft.platform; title.textContent = ({ blog: "블로그", facebook: "페이스북", instagram: "인스타그램" })[savedDraft.platform] + " 게시글"; }
            }
          }
          if (savedDraft) renderPreview();
          // Only the photos the roster names come back. A stale image file the
          // owner removed from the composition never resurrects itself just
          // because it is still stored in the project.
          if (!order || !order.length) return;
          const ordered = [];
          order.forEach((entry) => {
            const meta = imageFiles.find((f) => f.id === (entry && entry.fileId));
            if (meta) ordered.push({ meta: meta, position: entry && typeof entry.position === "string" && entry.position ? entry.position : "auto" });
          });
          for (const entry of ordered) {
            const dataUrl = await fetchOriginalDataUrl(pid, entry.meta.id);
            if (!dataUrl) continue;
            photos.push({ id: entry.meta.id, name: entry.meta.name, dataUrl: dataUrl, position: entry.position });
          }
          renderPhotoList();
          renderPreview();
        } catch (_) { /* restore is best effort; an empty composition stays honest */ }
      })();

      let busy = false;
      let failed = false;
      function refreshSave() {
        saveBtn.disabled = busy || failed || !String(output.value || "").trim();
      }

      async function runGeneration() {
        if (busy) return;
        busy = true;
        submitBtn.disabled = true;
        failed = false;
        refreshSave();
        setNotice(notice, "생성 중…", "busy");
        try {
          const answer = await apiChat(
            buildSnsPrompt(form, platform, photos, pcSection ? pcSection.read() : ""), "sns",
            (partial) => {
              output.value = partial;
              result.hidden = false;
              previewBox.hidden = false;
              renderPreview();
            },
          );
          output.value = answer;
          result.hidden = false;
          previewBox.hidden = false;
          failed = false;
          setNotice(notice, "");
          renderPreview();
        } catch (err) {
          failed = true;
          setNoticeWithRetry(notice, generationFailureText(err), runGeneration);
          if (!String(output.value || "").trim()) {
            result.hidden = true;
            previewBox.hidden = true;
          }
        } finally {
          busy = false;
          submitBtn.disabled = false;
          refreshSave();
        }
      }
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        void runGeneration();
      });
      wireCopy(copyB, output);
      dlB.addEventListener("click", () => {
        const text = String(output.value || "").trim();
        if (text) downloadText(text, "SNS_" + (title.textContent || "게시글") + "_" + todayStamp() + ".txt");
      });
      wireResultDownloads({
        hwpxBtn: dlHwpxB, docxBtn: dlDocxB, kind: "sns",
        baseName: () => "SNS_" + (title.textContent || "게시글") + "_" + todayStamp(),
        title: () => title.textContent || "게시글",
        text: () => String(output.value || "").trim(),
      });
      wirePcSave(pcSaveBtn, output, notice, () => {
        const event = form.querySelector("[name=event]");
        return "SNS_" + (fileNamePart(event ? event.value : "") || title.textContent || "게시글");
      });
      saveBtn.addEventListener("click", async () => {
        const text = output.value.trim();
        if (!text || saveBtn.disabled) return;
        const pid = await councilProject.ensure();
        if (!pid) {
          setNotice(notice, "저장할 프로젝트를 찾지 못했습니다. 잠시 후 다시 시도해 주세요.", "error");
          return;
        }
        saveBtn.disabled = true;
        saveBtn.textContent = "저장 중…";
        const outcome = await saveCouncilText({
          pid, name: (title.textContent || "SNS 게시글").trim() + ".txt", text, kind: "sns", anchor: saveBtn,
        });
        saveBtn.textContent = "저장";
        refreshSave();
        if (outcome.file) {
          saveBtn.textContent = "저장됨";
          setTimeout(() => { saveBtn.textContent = "저장"; }, 1500);
          setNotice(notice, "");
          // The saved draft rides in the roster so re-entry restores the
          // text and its platform, not only the photos.
          lastSavedDraft = { text: text, platform: platform };
          await writePhotoRoster(pid, lastSavedDraft);
          await refreshSnsList();
        } else if (outcome.failure) {
          setNotice(notice, saveFailureText(outcome.failure), "error");
        }
      });
      refreshSave();
      refreshSnsList();
      onCountryChange(refreshSnsList);
    }

    return {
      build(host) { buildForm(host); },
      buildPrompt: buildSnsPrompt,
      onOpen() { if (pcSection) pcSection.check(); },
    };
  })();

  // ── meeting module (prompts ported verbatim from util-menu.js) ───────────

  function buildMeetingPrompt(form) {
    const d = new FormData(form);
    const title = (d.get("title") || "").trim();
    const when = (d.get("when") || "").trim();
    const attendees = (d.get("attendees") || "").trim();
    const content = (d.get("content") || "").trim();
    let prompt = "다음 회의 내용을 정리해 주세요.\n\n";
    prompt += `회의명: ${title}\n`;
    if (when) prompt += `회의 일시: ${when}\n`;
    if (attendees) prompt += `참석자: ${attendees}\n`;
    prompt += `회의 내용:\n${content}\n\n`;
    prompt += "다음 항목으로 정리해 주세요:\n1. 회의 요약 (3-5문장)\n2. 주요 논의사항 (bullet)\n3. 결정사항 (bullet)\n4. 후속 업무 (담당자/일정이 원문에 있으면 포함)\n5. 미해결 사항";
    return prompt;
  }

  function buildBookPrompt(contents) {
    let prompt = "다음은 사용자가 선택한 활동 기록 본문입니다. 각 기록의 이름을 출처로 유지하세요.\n\n";
    prompt += contents.join("\n\n") + "\n\n";
    prompt += "위 기록을 바탕으로 다음을 생성해 주세요:\n";
    prompt += "1. 책/활동집 제목 후보 3개\n";
    prompt += "2. 목차 (5-8장)\n";
    prompt += "3. 각 장별 원고 초안 (200-400자)\n";
    prompt += "4. 마무리 인사\n\n";
    prompt += "목차, 월별 활동, 주요 발언, 성과 요약을 각각 포함하세요. 발언과 성과는 기록에 근거가 있을 때만 작성하세요.\n\n";
    prompt += "주의: 원본 기록에 없는 사건, 날짜, 발언을 사실처럼 추가하지 마세요. 근거가 있는 내용과 제안/해석을 구분하세요. 각 장 끝에 근거가 된 기록 파일명을 표시하세요.";
    return prompt;
  }

  const meetingModule = (() => {
    function buildForm(host) {
      const form = el("form", "council-form");
      form.id = "councilMeetingForm";
      const fields = [
        ["title", "회의명", "text", true, "예: 10월 주민 민원 회의"],
        ["when", "회의 일시", "datetime-local", false, ""],
        ["attendees", "참석자", "text", false, "예: 비서실장, 지역 담당"],
        ["content", "회의 내용", "textarea", true, "회의에서 오간 내용을 그대로 적어 주세요"],
      ];
      fields.forEach(([name, label, type, req, placeholder]) => {
        const l = el("label", null, label + " ");
        let field;
        if (type === "textarea") {
          field = document.createElement("textarea");
          field.name = name;
          field.rows = name === "content" ? 6 : 2;
        } else {
          field = document.createElement("input");
          field.name = name;
          field.type = type;
        }
        if (req) field.required = true;
        if (placeholder) field.placeholder = placeholder;
        l.appendChild(field);
        form.appendChild(l);
      });

      const formActions = el("div", "council-form-actions");
      const submitBtn = el("button", "council-generate", "요약 생성");
      submitBtn.type = "submit";
      submitBtn.id = "councilMeetingGenerate";
      formActions.append(submitBtn);
      form.appendChild(formActions);

      const notice = noticeLine("councilMeetingNotice");
      const panel = resultPanel({
        id: "councilMeetingResult", outputId: "councilMeetingOutput", rows: 12,
        title: "회의 요약", copyId: "councilMeetingCopy",
        saveId: "councilMeetingSave", downloadId: "councilMeetingDownload",
        downloadHwpxId: "councilMeetingDownloadHwpx", downloadDocxId: "councilMeetingDownloadDocx",
        pcSaveId: "councilMeetingPcSave",
      });
      const { result, output, copyBtn: copyB, saveBtn: formSaveB, dlHwpxBtn: dlHwpxB, dlDocxBtn: dlDocxB, dlBtn: dlB, pcSaveBtn } = panel;

      const archive = el("div", "council-archive");
      archive.id = "councilMeetingArchive";

      host.replaceChildren(form, notice, result, archive);

      let busy = false;
      let failed = false;
      function refreshSave() {
        formSaveB.disabled = busy || failed || !String(output.value || "").trim();
      }

      async function runGeneration() {
        if (busy) return;
        busy = true;
        submitBtn.disabled = true;
        failed = false;
        refreshSave();
        setNotice(notice, "생성 중…", "busy");
        try {
          const answer = await apiChat(buildMeetingPrompt(form), "meeting", (partial) => {
            output.value = partial;
            result.hidden = false;
          });
          output.value = answer;
          result.hidden = false;
          failed = false;
          setNotice(notice, "");
        } catch (err) {
          failed = true;
          setNoticeWithRetry(notice, generationFailureText(err), runGeneration);
          if (!String(output.value || "").trim()) result.hidden = true;
        } finally {
          busy = false;
          submitBtn.disabled = false;
          refreshSave();
        }
      }
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        void runGeneration();
      });
      wireCopy(copyB, output);
      dlB.addEventListener("click", () => {
        const text = String(output.value || "").trim();
        const titlePart = fileNamePart(form.querySelector("[name=title]")?.value) || "회의";
        if (text) downloadText(text, "회의_" + titlePart + "_" + todayStamp() + ".txt");
      });
      wireResultDownloads({
        hwpxBtn: dlHwpxB, docxBtn: dlDocxB, kind: "meeting",
        baseName: () => {
          const titlePart = fileNamePart(form.querySelector("[name=title]")?.value) || "회의";
          return "회의_" + titlePart + "_" + todayStamp();
        },
        title: () => fileNamePart(form.querySelector("[name=title]")?.value) || "회의",
        text: () => String(output.value || "").trim(),
      });
      wirePcSave(pcSaveBtn, output, notice, () => {
        const title = form.querySelector("[name=title]");
        return "회의_" + (fileNamePart(title ? title.value : "") || "회의");
      });
      formSaveB.addEventListener("click", async () => {
        const text = output.value.trim();
        if (!text || formSaveB.disabled) return;
        const pid = await councilProject.ensure();
        if (!pid) {
          setNotice(notice, "저장할 프로젝트를 찾지 못했습니다. 잠시 후 다시 시도해 주세요.", "error");
          return;
        }
        const name = fileNamePart(form.querySelector("[name=title]")?.value) || "회의";
        const when = (form.querySelector("[name=when]")?.value || "").trim();
        const storedText = when ? "회의 일시: " + when + "\n\n" + text : text;
        formSaveB.disabled = true;
        formSaveB.textContent = "저장 중…";
        const outcome = await saveCouncilText({
          pid, name: name + ".txt", text: storedText, kind: "meeting", anchor: formSaveB,
        });
        formSaveB.textContent = "저장";
        refreshSave();
        if (outcome.file) {
          formSaveB.textContent = "저장됨";
          setTimeout(() => { formSaveB.textContent = "저장"; }, 1500);
          setNotice(notice, "");
          await refreshArchive(archive);
        } else if (outcome.failure) {
          setNotice(notice, saveFailureText(outcome.failure), "error");
        }
      });
      refreshSave();

      async function refreshArchive(arc) {
        const pid = await councilProject.ensure();
        if (!pid) return;
        const files = await listProjectFiles(pid);
        // A book is not one of its own source records, and an SNS draft or the
        // photo roster never belongs here either. The stored kind decides the
        // family; documents from before kinds existed keep the name rule.
        const meetingFiles = files.filter(isMeetingFile).filter(sameCountry);
        const bookFiles = files.filter(isBookFile);

        // The book editor is built before the lists are drawn: a stored book has
        // to reopen into it even when no record exists in this project yet.
        const bookResult = el("div", "council-result");
        bookResult.id = "councilBookResult";
        bookResult.hidden = true;
        bookResult.appendChild(el("h3", null, "활동집 초안"));
        const bookOutput = document.createElement("textarea");
        bookOutput.id = "councilBookOutput";
        bookOutput.rows = 16;
        bookResult.appendChild(bookOutput);
        const bookNotice = noticeLine("councilBookNotice");
        const bookActions = el("div", "council-actions");
        const bookCopy = el("button", "council-primary", "복사");
        bookCopy.type = "button";
        bookCopy.id = "councilBookCopy";
        const bookSave = el("button", "council-save", "활동집 저장");
        bookSave.type = "button";
        bookSave.id = "councilBookSave";
        const bookHwpx = el("button", null, "한글(HWPX)");
        bookHwpx.type = "button";
        bookHwpx.id = "councilBookDownloadHwpx";
        bookHwpx.setAttribute("aria-label", "한글(HWPX) 파일로 내려받기");
        const bookDocx = el("button", null, "워드(DOCX)");
        bookDocx.type = "button";
        bookDocx.id = "councilBookDownloadDocx";
        bookDocx.setAttribute("aria-label", "워드(DOCX) 파일로 내려받기");
        const bookDl = el("button", null, "텍스트");
        bookDl.type = "button";
        bookDl.id = "councilBookDownload";
        const bookPcSave = el("button", null, PC_REF_COPY.save);
        bookPcSave.type = "button";
        bookPcSave.id = "councilBookPcSave";
        bookActions.append(bookCopy, bookSave, bookHwpx, bookDocx, bookDl, bookPcSave);
        bookResult.appendChild(bookActions);

        const bookBtn = el("button", "council-generate", "선택 기록으로 활동집 초안 생성");
        bookBtn.type = "button";
        bookBtn.id = "councilBookGenerate";

        arc.replaceChildren();
        arc.appendChild(el("h3", null, "활동 기록"));
        if (!meetingFiles.length) {
          arc.appendChild(el("p", "council-empty", "저장된 회의 기록이 없습니다."));
        } else {
          const range = el("div", "council-book-period");
          const startLabel = el("label", null, "시작일 ");
          const start = document.createElement("input");
          start.type = "date";
          start.id = "councilBookStart";
          startLabel.appendChild(start);
          const endLabel = el("label", null, "종료일 ");
          const end = document.createElement("input");
          end.type = "date";
          end.id = "councilBookEnd";
          endLabel.appendChild(end);
          const selectPeriod = el("button", null, "기간에 맞는 기록 선택");
          selectPeriod.type = "button";
          selectPeriod.id = "councilBookSelectPeriod";
          const periodStatus = el("p", null, "기간을 선택하면 회의 일시가 있는 기록을 찾습니다. 날짜가 없는 기록은 직접 확인해 선택해 주세요.");
          periodStatus.id = "councilBookPeriodStatus";
          periodStatus.setAttribute("role", "status");
          range.append(startLabel, endLabel, selectPeriod);
          // 기간 빠른 선택 — 시작/종료를 채우고 같은 선택 동작을 누른다.
          const iso = (d) => {
            const pad = (n) => String(n).padStart(2, "0");
            return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
          };
          [["이번 달", (d) => [new Date(d.getFullYear(), d.getMonth(), 1), new Date(d.getFullYear(), d.getMonth() + 1, 0)]],
           ["지난달", (d) => [new Date(d.getFullYear(), d.getMonth() - 1, 1), new Date(d.getFullYear(), d.getMonth(), 0)]],
           ["이번 분기", (d) => { const m = Math.floor(d.getMonth() / 3) * 3; return [new Date(d.getFullYear(), m, 1), new Date(d.getFullYear(), m + 3, 0)]; }],
           ["올해", (d) => [new Date(d.getFullYear(), 0, 1), new Date(d.getFullYear(), 11, 31)]]].forEach(([label, pick]) => {
            const quick = el("button", "council-book-quick", label);
            quick.type = "button";
            quick.addEventListener("click", () => {
              const [from, to] = pick(new Date());
              start.value = iso(from);
              end.value = iso(to);
              void selectPeriod.click();
            });
            range.appendChild(quick);
          });
          range.appendChild(periodStatus);
          arc.appendChild(range);
          arc.appendChild(bookBtn);
          const ul = document.createElement("ul");
          meetingFiles.forEach((f) => {
            const li = document.createElement("li");
            li.className = "council-archive-item";
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = f.id;
            cb.className = "council-book-check";
            cb.setAttribute("aria-label", f.name + " 활동집에 포함");
            /* 상자는 24px(#6075)로 두고, 그 주먹을 44×44 라벨로 감싼다. 라벨이 입력을
               감싸면 상자 밖을 눌러도 선택되므로 이름·본문 단추와 경쟁하지 않는다. */
            const check = document.createElement("label");
            check.className = "council-archive-check";
            check.appendChild(cb);
            li.appendChild(check);
            const btn = document.createElement("button");
            btn.type = "button";
            btn.textContent = f.name + " (" + (f.content_chars || 0) + "자)";
            btn.addEventListener("click", async () => {
              const content = await fetchProjectFile(pid, f.id);
              if (typeof content === "string") {
                const savedDate = content.match(/^회의 일시: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2})\n\n/);
                if (savedDate) {
                  form.querySelector("[name=when]").value = savedDate[1];
                  output.value = content.slice(savedDate[0].length);
                } else {
                  form.querySelector("[name=when]").value = "";
                  output.value = content;
                }
                result.hidden = false;
                failed = false;
                setNotice(notice, f.name + "를 열었습니다. 같은 이름으로 저장하면 새 이름/덮어쓰기를 묻습니다.", "info");
                refreshSave();
              } else {
                setNotice(notice, "저장된 회의 기록의 본문을 읽을 수 없습니다.", "error");
              }
            });
            li.appendChild(btn);
            const moveUp = el("button", "council-record-move", "↑");
            moveUp.type = "button";
            moveUp.setAttribute("aria-label", f.name + " 위로");
            const moveDown = el("button", "council-record-move", "↓");
            moveDown.type = "button";
            moveDown.setAttribute("aria-label", f.name + " 아래로");
            moveUp.addEventListener("click", () => {
              const previous = li.previousElementSibling;
              if (previous) ul.insertBefore(li, previous);
            });
            moveDown.addEventListener("click", () => {
              const next = li.nextElementSibling;
              if (next) ul.insertBefore(next, li);
            });
            li.append(moveUp, moveDown);
            ul.appendChild(li);
          });
          arc.appendChild(ul);
          selectPeriod.addEventListener("click", async () => {
            if (!start.value || !end.value || start.value > end.value) {
              periodStatus.textContent = "시작일과 종료일을 올바르게 선택해 주세요.";
              return;
            }
            selectPeriod.disabled = true;
            periodStatus.textContent = "회의 날짜를 확인하는 중입니다.";
            try {
              const selected = [];
              let undated = 0;
              for (const file of meetingFiles) {
                const content = await fetchProjectFile(pid, file.id);
                if (typeof content !== "string") throw new Error("읽기 실패");
                // Only an explicit meeting date counts; upload time and dates
                // in a filename or discussion do not establish the meeting date.
                const match = content.match(/(?:^|\n)\s*회의\s*일시\s*[:：]\s*(\d{4}-\d{2}-\d{2})/m);
                if (!match) { undated += 1; continue; }
                if (match[1] >= start.value && match[1] <= end.value) selected.push(file.id);
              }
              ul.querySelectorAll(".council-book-check").forEach((cb) => { cb.checked = selected.includes(cb.value); });
              periodStatus.textContent = selected.length + "건을 선택했습니다. 날짜를 확인할 수 없는 " + undated + "건은 직접 확인해 선택해 주세요.";
            } catch (_) {
              periodStatus.textContent = "회의 기록을 읽지 못해 기간을 적용하지 못했습니다. 다시 시도해 주세요.";
            } finally {
              selectPeriod.disabled = false;
            }
          });
        }
        arc.appendChild(bookNotice);
        arc.appendChild(bookResult);

        let bookBusy = false;
        let bookFailed = false;
        function refreshBookSave() {
          bookSave.disabled = bookBusy || bookFailed || !String(bookOutput.value || "").trim();
        }
        refreshBookSave();

        bookBtn.addEventListener("click", async () => {
          const checked = Array.from(document.querySelectorAll(".council-book-check:checked"));
          if (!checked.length) { alert("선택된 기록이 없습니다."); return; }
          if (bookBusy) return;
          bookBusy = true;
          bookBtn.disabled = true;
          let stage = "read";
          setNotice(bookNotice, "선택한 회의 기록을 불러오는 중…", "busy");
          try {
            const contents = [];
            for (const checkbox of checked) {
              const file = meetingFiles.find((item) => item.id === checkbox.value);
              if (!file) continue;
              const res = await fetch("/api/projects/" + encodeURIComponent(pid) + "/files/" + encodeURIComponent(file.id), { credentials: "include" });
              if (!res.ok) throw new Error("선택한 회의 기록을 불러오지 못했습니다: " + file.name);
              const data = await res.json();
              if (!data || !data.file || typeof data.file.content !== "string" || !data.file.content.trim()) {
                throw new Error("선택한 회의 기록의 본문이 비어 있거나 올바르지 않습니다: " + file.name);
              }
              contents.push("[기록: " + data.file.name + "]\n" + data.file.content);
            }
            setNotice(bookNotice, "활동집 초안을 만드는 중…", "busy");
            stage = "generate";
            const answer = await apiChat(buildBookPrompt(contents), "meeting", (partial) => {
              bookOutput.value = partial;
              bookResult.hidden = false;
            });
            bookOutput.value = answer;
            bookResult.hidden = false;
            bookFailed = false;
            setNotice(bookNotice, "");
          } catch (e) {
            // A record that could not be read is a concrete sentence; a
            // generation failure uses the shared Korean copy.
            bookFailed = true;
            const sentence = stage === "generate"
              ? generationFailureText(e)
              : String(e && e.message ? e.message : e);
            if (stage === "generate") setNoticeWithRetry(bookNotice, sentence, () => bookBtn.click());
            else setNotice(bookNotice, sentence, "error");
            if (!String(bookOutput.value || "").trim()) bookResult.hidden = true;
          } finally {
            bookBusy = false;
            bookBtn.disabled = false;
            refreshBookSave();
          }
        });
        wireCopy(bookCopy, bookOutput);
        wirePcSave(bookPcSave, bookOutput, bookNotice, () => {
          const firstLine = String(bookOutput.value || "").split("\n", 1)[0].trim();
          return "활동집_" + (fileNamePart(firstLine.replace(/^[0-9]+\.\s*/, "")) || "초안");
        });
        bookDl.addEventListener("click", () => {
          const text = String(bookOutput.value || "").trim();
          if (text) downloadText(text, bookFileName(text));
        });
        wireResultDownloads({
          hwpxBtn: bookHwpx, docxBtn: bookDocx, kind: "book",
          baseName: () => bookBaseName(bookOutput.value),
          title: () => fileNamePart(String(bookOutput.value || "").split("\n", 1)[0].replace(/^[0-9]+\.\s*/, "")) || "활동집",
          text: () => String(bookOutput.value || "").trim(),
        });

        // The draft is a product, not scratch: it persists through the same
        // project-file channel under the book name rule. One press must never
        // create two copies, so the button is armed only while nothing is in
        // flight and the list is refreshed from the server afterwards.
        let bookSaving = false;
        bookSave.addEventListener("click", async () => {
          const text = bookOutput.value.trim();
          if (!text || bookSaving || bookSave.disabled) return;
          bookSaving = true;
          bookSave.disabled = true;
          bookSave.textContent = "저장 중…";
          const outcome = await saveCouncilText({
            pid, name: bookFileName(text), text, kind: "book", anchor: bookSave,
          });
          bookSaving = false;
          bookSave.textContent = "활동집 저장";
          refreshBookSave();
          if (!outcome.file) {
            if (outcome.failure) setNotice(bookNotice, saveFailureText(outcome.failure), "error");
            return;
          }
          const saved = outcome.file;
          setNotice(bookNotice, "");
          // The list is refreshed from the server, which rebuilds the archive -
          // including this editor - so the draft the user just saved is written
          // back and the confirmation lands on the node that is actually on screen.
          await refreshArchive(arc);
          const current = document.getElementById("councilBookOutput");
          const currentResult = document.getElementById("councilBookResult");
          const currentSave = document.getElementById("councilBookSave") || bookSave;
          if (current && currentResult) {
            current.value = text;
            currentResult.hidden = false;
          }
          currentSave.textContent = "저장됨";
          setTimeout(() => { currentSave.textContent = "활동집 저장"; }, 1500);
          // querySelectorAll returns a NodeList, which has no .find.
          const opened = Array.from(arc.querySelectorAll(".council-book-open"))
            .find((b) => String(b.textContent).indexOf(saved.name) === 0);
          if (opened) opened.setAttribute("aria-current", "true");
        });

        if (bookFiles.length) {
          const bookSec = el("div", "council-book-list");
          bookSec.appendChild(el("h3", null, "저장된 활동집"));
          const bookUl = document.createElement("ul");
          bookFiles.forEach((f) => {
            const li = document.createElement("li");
            li.className = "council-archive-item";
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "council-book-open";
            btn.textContent = f.name + " (" + (f.content_chars || 0) + "자)";
            btn.addEventListener("click", async () => {
              const content = await fetchProjectFile(pid, f.id);
              if (typeof content !== "string") {
                alert("저장된 활동집의 본문을 읽을 수 없습니다.");
                return;
              }
              bookResult.hidden = false;
              bookOutput.value = content;
              bookFailed = false;
              setNotice(bookNotice, "");
              refreshBookSave();
              if (typeof bookOutput.focus === "function") bookOutput.focus();
            });
            li.appendChild(btn);
            bookUl.appendChild(li);
          });
          bookSec.appendChild(bookUl);
          arc.appendChild(bookSec);
        }
      }

      // The archive and the stored-book list load when the tool opens, the same
      // way the speech list does and the way util-menu.js does it: a re-entry
      // must show what is already stored before anything is saved again.
      refreshArchive(archive);
      onCountryChange(() => refreshArchive(archive));

      return { refreshArchive };
    }

    return {
      build(host) { buildForm(host); },
      buildPrompt: buildMeetingPrompt,
      buildBookPrompt,
    };
  })();

  // #6065: the stored lists are country-scoped by sameCountry(), but they were only
  // ever re-filtered when a tool rebuilt them. Switching the content country left the
  // previous country's documents on screen until a save or a reload. Each list scope
  // registers its own refresher here, so the control that changes the generation
  // language also refreshes what it claims is stored for that language.
  function onCountryChange(refresh) {
    const select = host("councilCountry");
    if (select) select.addEventListener("change", refresh);
  }

  function syncCountrySelect() {
    const select = host("councilCountry");
    if (!select) return;
    // B10: the page offers Korean only. A host that still carries an older
    // stored choice (uk/fr) must not save new documents under a language the
    // screen cannot show: the selector's own options decide what is reachable.
    const options = Array.from(select.options || select.children || []).map((o) => String(o.value));
    const stored = currentCountry();
    const country = options.length && options.indexOf(stored) < 0 ? "kr" : stored;
    if (country !== stored) {
      try { if (store()) store().setItem(COUNTRY_KEY, country); } catch (_) {}
    }
    select.value = country;
    // init()(평소 로드)과 enterSignedIn()(로그인 후) 이 모두 부른다. 리스너는 한 번만 건다.
    if (session.countryBound) return;
    session.countryBound = true;
    select.addEventListener("change", () => {
      const next = COUNTRY_INSTRUCTIONS[select.value] === undefined ? "kr" : select.value;
      try { if (window.localStorage) window.localStorage.setItem(COUNTRY_KEY, next); } catch (_) {}
      setStatus(next === "kr" ? "" : "생성 결과의 언어가 바뀝니다(저장 문서는 그대로).");
    });
  }

  // ── independent entry wiring: auth gate, then build all three tools ──────

  async function readAuthStatusOnce() {
    const res = await fetch("/api/auth/status", {
      credentials: "include",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) {
      // #6127: a 5xx is the server failing to answer, not a verdict about this
      // visitor. Chat draws the same line for the runtime's NoGilError race
      // (#5479), where every dynamic route can 500 while the account itself is
      // untouched. 401/403 IS such a verdict about the visitor, so it is returned
      // quietly and never re-asked.
      if (res.status >= 500) throw new Error("auth status unavailable");
      return { signedIn: false, methods: null, unavailable: false };
    }
    const data = await res.json().catch(() => null);
    if (!data) throw new Error("auth status unavailable");
    return {
      signedIn: !!(data && data.authenticated === true),
      methods: (data && data.methods) || null,
      unavailable: false,
    };
  }

  // #6114 as solved for Chat: a Python Worker restart can eat one status read, so
  // a request that produced NO answer is re-asked ONCE before the page says the
  // state cannot be determined. Measured on production, one re-ask takes the
  // "cannot tell" rate from 30% of loads to 10%; a definitive answer is never
  // re-asked, so a signed-out visitor pays one round trip, not two.
  async function checkSignedIn() {
    let outcome = null;
    for (let attempt = 0; attempt < 2 && !outcome; attempt += 1) {
      try {
        outcome = await readAuthStatusOnce();
      } catch (_) {
        outcome = null;
      }
    }
    // fail-closed gate, unchanged from the retired councillor screen: nothing is attached unless
    // the server itself says this cookie is authenticated, and an unanswered read
    // is not permission.
    return outcome || { signedIn: false, methods: null, unavailable: true };
  }

  // ── session and selection state (this page's UI state, never an authority) ──
  // The three cards are the entry: one chosen tool, one panel. A signed-out visit
  // logs in here (the existing same-origin session contract), then continues into
  // the tool it had picked. No new endpoint, store, token or account system.
  const TOOLS = Object.freeze(["speech", "sns", "meeting"]);
  const LABELS = Object.freeze({ speech: "축사·인사말", sns: "SNS 홍보", meeting: "회의정리·활동집" });
  const session = { signedIn: false, built: false, bound: false, selected: null, pending: null,
                     unavailable: false, themeBound: false };
  let bodies = {};

  function host(id) { return document.getElementById(id); }

  // ── 정적 자산 버전(2026-11-01 캐시 무효화) ──────────────────────────────
  // app_factory가 서빙 때 index.html에 싣는 내용 해시 지도(?v=<sha1 앞 8자)를
  // 읽어 동적 로더의 URL에도 같은 버전을 붙인다. 지도가 없으면(파일 직접 열기,
  // 시험 하네스) 버전 없는 원래 주소를 그대로 쓴다 — 서빙 계약의 변화가 없다.
  const ASSET_VERSIONS = (function () {
    try {
      const el = document.getElementById("padiem-asset-versions");
      const parsed = el ? JSON.parse(el.textContent || "{}") : {};
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch (_) { return {}; }
  })();
  function versionedAsset(url) {
    const match = /^(?:\.\/|\/)?static\/(.+)$/.exec(url);
    const digest = match && ASSET_VERSIONS[match[1]];
    return digest ? url.split("?")[0] + "?v=" + digest : url;
  }
  function setBadge(text) { const node = host("councilAuthBadge"); if (node) node.textContent = text; }
  function setStatus(text) {
    const node = host("councilAuthStatus");
    if (!node) return;
    node.textContent = text || "";
    node.hidden = !text;
  }
  function showAuthPanel(message, badge) {
    const panel = host("councilAuthPanel");
    if (panel) panel.hidden = false;
    const action = host("councilAuthAction");
    if (action) action.hidden = false;
    setBadge(badge || "로그인 필요");
    if (message) setStatus(message);
  }
  function hideAuthPanel() {
    const panel = host("councilAuthPanel");
    if (panel) panel.hidden = true;
    const action = host("councilAuthAction");
    if (action) action.hidden = true;
    setStatus("");
  }

  function store() {
    // A host may refuse storage (private mode, and the module harness runs this
    // file with no storage at all). Selection then lives in the URL only.
    try { return window.localStorage || null; } catch (_) { return null; }
  }
  function rememberedTool() {
    try {
      const value = store() && store().getItem("padiem-council-tool");
      return TOOLS.indexOf(value) >= 0 ? value : null;
    } catch (_) { return null; }
  }
  function rememberTool(tool) {
    try { if (store()) store().setItem("padiem-council-tool", tool); } catch (_) {}
  }
  function toolFromUrl() {
    const hash = (window.location && window.location.hash) || "";
    const value = hash.replace(/^#\/?/, "");
    return TOOLS.indexOf(value) >= 0 ? value : null;
  }
  function writeToolToUrl(tool) {
    const history = window.history;
    if (!tool || !history || typeof history.replaceState !== "function") return;
    try { history.replaceState(null, "", "#/" + tool); } catch (_) {}
  }

  function cardButtons() {
    return Array.from(document.querySelectorAll(".council-card-select"));
  }

  function focusToolPanel(tool) {
    const body = bodies[tool];
    const field = body ? body.querySelector("input") : null;
    if (field && typeof field.focus === "function") field.focus();
    const section = host("council-" + tool);
    if (section && typeof section.scrollIntoView === "function") {
      try { section.scrollIntoView({ block: "start" }); } catch (_) {}
    }
  }

  function applySelection(tool, moveFocus) {
    session.selected = tool;
    TOOLS.forEach((key) => {
      const body = bodies[key];
      if (body) body.hidden = key !== tool;
      const section = host("council-" + key);
      if (section && section.classList) section.classList[ key === tool ? "add" : "remove"]("active");
    });
    cardButtons().forEach((button) => {
      const active = button.dataset.tool === tool;
      button.setAttribute("aria-expanded", active ? "true" : "false");
      if (button.classList) button.classList[active ? "add" : "remove"]("active");
      const label = LABELS[button.dataset.tool] || "";
      // 시안 04의 카드 동작 문구. 열린 카드는 "닫기"로 되돌아온다.
      button.textContent = active ? "닫기" : "바로 시작하기 →";
      button.setAttribute("aria-label", label + " " + (active ? "닫기" : "바로 시작하기"));
    });
    if (tool) {
      rememberTool(tool);
      writeToolToUrl(tool);
      if (moveFocus) focusToolPanel(tool);
      // The PC check runs when this tool is actually opened, never on load.
      const opened = MODULES[tool];
      if (opened && typeof opened.onOpen === "function") opened.onOpen();
    }
    paintWorkspace(tool || null);
    return session.selected;
  }

  function openLoginHere(tool, message) {
    if (tool) session.pending = tool;
    // #6127: "로그인이 필요합니다"는 서버가 답하지 못했을 때 잘못된 지시입니다.
    // 게이트는 그대로 닫혀 있습니다.
    if (session.unavailable && !message) {
      showAuthPanel("로그인 상태 확인에 실패했습니다. 다시 시도해 주세요.", "로그인 확인 실패");
      return;
    }
    showAuthPanel(message || (!session.signedIn && session.pending
      ? "로그인이 필요합니다. 선택한 업무(" + LABELS[session.pending] + ")는 로그인 후 이 화면에서 바로 이어집니다."
      : ""));
    const form = host("councilLoginForm");
    const field = form ? form.querySelector("[name=identifier]") : null;
    if (field && typeof field.focus === "function") field.focus();
  }

  function bindCards() {
    if (session.bound) return;
    cardButtons().forEach((button) => {
      button.addEventListener("click", () => {
        const tool = button.dataset.tool;
        if (!session.signedIn) { openLoginHere(tool); return; }
        applySelection(session.selected === tool ? null : tool, true);
      });
    });
    const action = host("councilAuthAction");
    if (action) action.addEventListener("click", () => openLoginHere(session.selected));
  }

  function offerGoogle(methods) {
    const row = host("councilGoogleRow");
    if (row) row.hidden = !(methods && methods.google === true);
  }

  async function loginWithPassword(form) {
    const identifier = form.querySelector("[name=identifier]");
    const password = form.querySelector("[name=password]");
    const submit = form.querySelector(".council-login");
    setStatus("로그인 중…");
    if (submit) submit.disabled = true;
    let outcome = { ok: false, message: "로그인하지 못했습니다. 다시 시도해 주세요." };
    try {
      // The EXISTING PADIEM credential contract: same-origin JSON, host-only
      // session cookie, one non-disclosing failure projection.
      const res = await fetch("/api/auth/password/login", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          identifier: identifier ? identifier.value : "",
          password: password ? password.value : "",
        }),
      });
      const data = await res.json().catch(() => null);
      const message = data && data.error && typeof data.error.message === "string" ? data.error.message : "";
      outcome = { ok: res.ok, message: res.ok ? "" : (message || "이메일 또는 비밀번호가 올바르지 않습니다.") };
    } catch (_) {
      outcome = { ok: false, message: "로그인하지 못했습니다. 네트워크를 확인해 주세요." };
    }
    if (submit) submit.disabled = false;
    if (!outcome.ok) {
      setStatus(outcome.message);
      if (password) password.value = "";
      return false;
    }
    if (password) password.value = "";
    await enterSignedIn();
    return true;
  }

  async function enterSignedIn() {
    const auth = await checkSignedIn();
    session.signedIn = auth.signedIn;
    session.unavailable = !!auth.unavailable;
    if (!session.signedIn) { showAuthPanel("로그인 상태 확인에 실패했습니다. 다시 시도해 주세요."); return false; }
    setBadge("로그인됨");
    hideAuthPanel();
    syncCountrySelect();
    // syncCountrySelect sets the value without dispatching, so the pills follow it here.
    applyTheme(selectedCountry(), theme.style);
    buildToolPanels();
    const wanted = session.pending || toolFromUrl() || rememberedTool();
    const focusWanted = Boolean(session.pending);
    session.pending = null;
    applySelection(TOOLS.indexOf(wanted) >= 0 ? wanted : null, focusWanted);
    return true;
  }

  const MODULES = Object.freeze({ speech: speechModule, sns: snsModule, meeting: meetingModule });

  function buildToolPanels() {
    if (session.built) return;
    TOOLS.forEach((key) => {
      const hostNode = bodies[key];
      if (hostNode && MODULES[key]) MODULES[key].build(hostNode);
    });
    session.built = true;
  }

  function bindAuthForm() {
    const form = host("councilLoginForm");
    if (!form || form.dataset.councilBound === "1") return;
    form.dataset.councilBound = "1";
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      await loginWithPassword(form);
    });
  }

  function markSessionLost() {
    if (!session.signedIn) return false;
    session.signedIn = false;
    openLoginHere(session.selected, "세션이 만료되었습니다. 다시 로그인하면 이 화면에서 이어나갑니다.");
    return true;
  }

  // ── 디자인 축: 국가 4 · 스타일 5 ───────────────────────────────────────
  // The two axes come from the #5967 정본 and stay as independent as it defines them: the
  // country picks the tone ramp and the photography, the style picks where that material is
  // used. 4 x 5 is therefore 4 + 5 CSS blocks, and the browser can reach all twenty.
  //
  // Neither axis becomes a new authority over data. The country still belongs to
  // #councilCountry, so the existing change listeners keep filtering the saved lists and the
  // archive and keep writing padiem-council-country; the pills above it are a mirror. The
  // style is the only new value and it gets its own key, beside padiem-council-country and
  // padiem-council-tool rather than replacing either.
  const DESIGN_COUNTRIES = Object.freeze(["kr", "us", "uk", "fr"]);
  const DESIGN_STYLES = Object.freeze(["classic", "modern", "dark", "light", "minimal"]);
  const COUNTRY_NAMES = Object.freeze({ kr: "한국", us: "미국", uk: "영국", fr: "프랑스" });
  const STYLE_NAMES = Object.freeze({ classic: "클래식", modern: "모던", dark: "다크", light: "라이트", minimal: "미니멀" });
  const theme = { country: "kr", style: "light", open: false };

  function rememberedStyle() {
    try {
      const value = store() && store().getItem("padiem-council-style");
      return DESIGN_STYLES.indexOf(value) >= 0 ? value : "light";
    } catch (_) { return "light"; }
  }
  function rememberStyle(style) {
    try { if (store()) store().setItem("padiem-council-style", style); } catch (_) {}
  }
  function selectedCountry() {
    const node = host("councilCountry");
    const value = node && node.value;
    return DESIGN_COUNTRIES.indexOf(value) >= 0 ? value : "kr";
  }
  function markGroup(group, attr, value) {
    if (!group || typeof group.querySelectorAll !== "function") return;
    // attribute-only: the only elements inside a group carrying the axis attribute are
    // its radios, and the harness resolves one selector token, not a compound.
    Array.from(group.querySelectorAll("[" + attr + "]")).forEach((button) => {
      const on = button.getAttribute(attr) === value;
      button.setAttribute("aria-checked", on ? "true" : "false");
      if (button.tabIndex !== undefined) button.tabIndex = on ? 0 : -1;
    });
  }
  function applyTheme(country, style) {
    const root = document.documentElement;
    theme.country = DESIGN_COUNTRIES.indexOf(country) >= 0 ? country : selectedCountry();
    theme.style = DESIGN_STYLES.indexOf(style) >= 0 ? style : rememberedStyle();
    if (root && root.dataset) {
      root.dataset.country = theme.country;
      root.dataset.style = theme.style;
    }
    markGroup(host("councilCountryGroup"), "data-country", theme.country);
    markGroup(host("councilStyleGroup"), "data-style", theme.style);
    const value = host("councilThemeValue");
    if (value) value.textContent = "국가 " + COUNTRY_NAMES[theme.country] + " · 스타일 " + STYLE_NAMES[theme.style];
    rememberStyle(theme.style);
    return { country: theme.country, style: theme.style };
  }
  function chooseCountry(country) {
    const node = host("councilCountry");
    if (node && node.value !== country) {
      node.value = country;
      if (typeof node.dispatchEvent === "function" && typeof Event === "function") {
        node.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
    applyTheme(country, theme.style);
  }
  // role=radio means the arrows move the choice, not the caret.
  function bindGroup(group, attr, choose) {
    if (!group || typeof group.querySelectorAll !== "function") return;
    const buttons = Array.from(group.querySelectorAll("[" + attr + "]"));
    buttons.forEach((button, index) => {
      button.addEventListener("click", () => choose(button.getAttribute(attr)));
      button.addEventListener("keydown", (event) => {
        const key = event && event.key;
        if (key !== "ArrowRight" && key !== "ArrowLeft" && key !== "ArrowDown" && key !== "ArrowUp") return;
        if (typeof event.preventDefault === "function") event.preventDefault();
        const step = (key === "ArrowRight" || key === "ArrowDown") ? 1 : -1;
        const next = buttons[(index + step + buttons.length) % buttons.length];
        if (!next) return;
        choose(next.getAttribute(attr));
        if (typeof next.focus === "function") next.focus();
      });
    });
  }
  function setThemePanel(open) {
    const panel = host("councilThemePanel");
    const trigger = host("councilThemeTrigger");
    theme.open = !!open;
    if (panel) panel.hidden = !open;
    if (trigger) trigger.setAttribute("aria-expanded", open ? "true" : "false");
  }
  function wireTheme() {
    if (session.themeBound) return;
    session.themeBound = true;
    applyTheme(selectedCountry(), rememberedStyle());
    bindGroup(host("councilCountryGroup"), "data-country", chooseCountry);
    bindGroup(host("councilStyleGroup"), "data-style", (style) => applyTheme(theme.country, style));
    const select = host("councilCountry");
    if (select && select.addEventListener) {
      select.addEventListener("change", () => applyTheme(selectedCountry(), theme.style));
    }
    const trigger = host("councilThemeTrigger");
    if (trigger) trigger.addEventListener("click", () => setThemePanel(!theme.open));
    const box = host("councilTheme");
    if (box && box.addEventListener) {
      box.addEventListener("click", (event) => { if (event) event.stopPropagation(); });
    }
    document.addEventListener("click", () => { if (theme.open) setThemePanel(false); });
    document.addEventListener("keydown", (event) => {
      if (!event || event.key !== "Escape") return;
      // A shared PC dialog that is open owns Escape: close the dialog, never the
      // editor behind it.
      const exchange = window.PadiemPcFileExchange;
      if (exchange && typeof exchange.isOpen === "function" && exchange.isOpen()) {
        if (typeof exchange.close === "function") exchange.close();
        return;
      }
      // Escape inside a field belongs to the field (it leaves the field or
      // closes the browser's own picker). It must never dismiss the editor and
      // throw away what the writer is typing.
      const target = event.target || document.activeElement || null;
      const tag = target && target.tagName ? String(target.tagName).toUpperCase() : "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (target && target.isContentEditable)) {
        return;
      }
      // 정본의 순서: 팝오버가 먼저 닫히고, 그 다음에 작업실이 홈으로 물러난다.
      if (theme.open) { setThemePanel(false); return; }
      if (session.selected) leaveWorkspace();
    });
  }

  // ── 작업실 전환 ────────────────────────────────────────────────────────
  // The 정본 keeps the home and the editor as two screens. Production hosts each editor
  // inside its own card, so the same result is reached by state, not by moving nodes: the
  // hero and the strip step out, the bar returns to the flow, and the open card becomes the
  // paper. Nothing here touches which panel is open — applySelection still owns that.
  function paintWorkspace(tool) {
    const root = document.documentElement;
    const bar = host("councilWorkspaceBar");
    const title = host("councilWorkspaceTitle");
    if (root && root.classList) root.classList[tool ? "add" : "remove"]("council-in-workspace");
    // 도구 화면 머리(작업실 막대)가 카드의 색·사진을 이어받는 키 — 시안 04의 시네마틱 어휘.
    if (root && root.dataset) {
      if (tool) root.dataset.activeTool = tool;
      else delete root.dataset.activeTool;
    }
    if (bar) bar.hidden = !tool;
    if (title) title.textContent = tool ? (LABELS[tool] || "") : "";
    // focusToolPanel brought the open card to the top, which carried this bar off the
    // screen with it. The bar is in the flow, so the script brings the reader to it.
    if (tool && bar && typeof bar.scrollIntoView === "function") {
      try { bar.scrollIntoView({ block: "start" }); } catch (_) {}
    }
  }
  function leaveWorkspace() {
    applySelection(null, false);
    const first = cardButtons()[0];
    if (first && typeof first.focus === "function") first.focus();
    if (typeof window.scrollTo === "function") { try { window.scrollTo(0, 0); } catch (_) {} }
  }
  function wireHome() {
    const back = host("councilBack");
    if (back) back.addEventListener("click", leaveWorkspace);
    const cta = host("councilHeroCta");
    if (!cta) return;
    cta.addEventListener("click", () => {
      // The primary CTA previews the tools; authentication is requested only on tool entry.
      const heading = host("councilWorksTitle");
      if (heading && typeof heading.scrollIntoView === "function") {
        try { heading.scrollIntoView({ block: "start" }); } catch (_) {}
      }
      const first = cardButtons()[0];
      if (first && typeof first.focus === "function") first.focus();
    });
  }

  // ── 시안(04) 상단 메뉴: 실제 있는 화면으로만 연결한다 ──────────────────
  // 시안의 활용 사례·가이드·공지사항은 이 앱에 화면이 없으므로 만들지 않았다.
  function wireMenu() {
    document.querySelectorAll("[data-nav]").forEach((item) => {
      item.addEventListener("click", () => {
        const nav = item.getAttribute("data-nav");
        if (nav === "home") { leaveWorkspace(); return; }
        if (nav === "tools") {
          if (session.selected) applySelection(null, false);
          scrollToWorks();
          const first = cardButtons()[0];
          if (first && typeof first.focus === "function") first.focus();
          return;
        }
        if (TOOLS.indexOf(nav) >= 0) {
          if (!session.signedIn) { openLoginHere(nav); return; }
          applySelection(nav, true);
        }
      });
    });
  }

  // ── 시안(04) 검색 상자: 실제 있는 도구 3종 안에서만 길을 찾아준다 ────────
  // 결과를 꾸미지 않는다: 어느 도구에도 걸리지 않으면 그 사실을 알리고
  // 실제 있는 업무 도구 목록으로 안내한다.
  function bestToolFor(query) {
    const terms = String(query || "").toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return null;
    let best = null;
    let bestScore = -1;
    TOOLS.forEach((tool) => {
      const card = host("council-" + tool);
      const hay = (((card && card.textContent) || "") || (LABELS[tool] || "")).toLowerCase();
      let all = true;
      let score = 0;
      terms.forEach((term) => {
        const hits = hay.split(term).length - 1;
        if (hits <= 0) all = false;
        score += hits;
      });
      if (all && score > bestScore) { best = tool; bestScore = score; }
    });
    return best;
  }
  function showSearchStatus(message) {
    const status = host("councilSearchStatus");
    if (!status) return;
    status.textContent = message;
    status.hidden = false;
  }
  function hideSearchStatus() {
    const status = host("councilSearchStatus");
    if (!status) return;
    status.hidden = true;
    status.textContent = "";
  }
  function scrollToWorks() {
    const heading = host("councilWorksTitle");
    if (heading && typeof heading.scrollIntoView === "function") {
      try { heading.scrollIntoView({ block: "start" }); } catch (_) {}
    }
  }
  function wireSearch() {
    const form = host("councilSearchForm");
    const input = host("councilSearch");
    if (!form || !input) return;
    form.addEventListener("submit", (event) => {
      if (event && typeof event.preventDefault === "function") event.preventDefault();
      const tool = bestToolFor(input.value);
      if (tool) {
        hideSearchStatus();
        if (!session.signedIn) { openLoginHere(tool); return; }
        applySelection(tool, true);
        return;
      }
      showSearchStatus("일치하는 업무 도구가 없습니다. 아래 도구 3종에서 확인해 보세요.");
      if (session.selected) applySelection(null, false);
      scrollToWorks();
    });
  }

  async function init() {
    bodies = {
      speech: host("councilSpeechBody"),
      sns: host("councilSnsBody"),
      meeting: host("councilMeetingBody"),
    };
    bindCards();
    bindAuthForm();
    // The design axes belong to the page, not to the session: a signed-out visitor sees
    // the cinematic home and may change country and style before logging in.
    wireTheme();
    wireHome();
    wireMenu();
    wireSearch();
    // The page runs init() once at load; a second call must not stack a second
    // set of listeners, or one click would open and immediately close the panel.
    session.bound = true;
    const auth = await checkSignedIn();
    session.signedIn = auth.signedIn;
    offerGoogle(auth.methods);
    if (!session.signedIn) {
      // fail-closed: the tool builders are not attached while signed out. The
      // cards stay readable as descriptions, and choosing one opens the in-page
      // login instead of sending the visitor to Chat.
      // #6127: when the server could not answer at all, say so. The gate stays
      // closed either way; only the report to the user differs, so a runtime
      // fault is not presented as "you are not signed in".
      // Keep the first visit focused on the cinematic home and tool cards.
      // The existing login form opens only after the visitor chooses a tool.
      hideAuthPanel();
      setBadge(auth.unavailable ? "로그인 확인 실패" : "로그인 필요");
      if (auth.unavailable) setStatus("로그인 상태 확인에 실패했습니다. 다시 시도해 주세요.");
      session.unavailable = !!auth.unavailable;
      return { signedIn: false, tools: null, selected: null, unavailable: !!auth.unavailable };
    }
    setBadge("로그인됨");
    hideAuthPanel();
    syncCountrySelect();
    // syncCountrySelect sets the value without dispatching, so the pills follow it here.
    applyTheme(selectedCountry(), theme.style);
    buildToolPanels();
    const tool = toolFromUrl() || rememberedTool();
    applySelection(TOOLS.indexOf(tool) >= 0 ? tool : null, false);
    return {
      signedIn: true,
      tools: { speech: speechModule, sns: snsModule, meeting: meetingModule },
      selected: session.selected,
    };
  }

  window.PadiemCouncilApps = {
    init,
    state: () => ({
      signedIn: session.signedIn,
      built: session.built,
      bound: session.bound,
      selected: session.selected,
      pending: session.pending,
    }),
    select: (tool, moveFocus) => applySelection(tool, moveFocus),
    theme: () => ({ country: theme.country, style: theme.style, open: theme.open,
                    countries: DESIGN_COUNTRIES.slice(), styles: DESIGN_STYLES.slice() }),
    setTheme: (country, style) => applyTheme(country, style),
    workspace: () => (session.selected ? "workspace" : "home"),
    openLogin: (tool) => openLoginHere(tool),
    sessionLost: () => markSessionLost(),
    speech: speechModule,
    sns: snsModule,
    meeting: meetingModule,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => { init(); }, { once: true });
  } else {
    init();
  }
})();
