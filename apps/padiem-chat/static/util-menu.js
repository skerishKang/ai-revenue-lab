(() => {
  "use strict";

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  // One place for generation-failure copy. The server's own Korean message
  // wins; a bare "HTTP nnn" never reaches the screen — statuses the server
  // did not name resolve here, once, for every util tool.
  const GEN_ERROR_COPY = {
    401: "로그인이 필요합니다. 다시 로그인해 주세요.",
    403: "이 계정에서는 할 수 없는 요청입니다. 로그인 상태를 확인해 주세요.",
    429: "요청이 잠시 많습니다. 조금 뒤에 다시 시도해 주세요.",
    500: "만드는 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.",
    502: "서버 연결이 잠시 끊겼습니다. 잠시 후 다시 시도해 주세요.",
    503: "서버가 잠시 과부하 상태입니다. 잠시 후 다시 시도해 주세요.",
    504: "서버 응답이 늦어집니다. 잠시 후 다시 시도해 주세요."
  };
  const GEN_ERROR_FALLBACK = "생성에 실패했습니다. 잠시 후 다시 시도해 주세요.";
  const GEN_OFFLINE_COPY = "인터넷 연결을 확인해 주세요.";
  const GEN_RETRY_LABEL = "다시 시도";

  // #5608: activity books persist under their own name rule so the meeting
  // record list and the book list stay two separate data flows over the same
  // project-file store. #5731 reads the same rule for the rows stored before a
  // kind was recorded, and every list needs it — hence the one place here.
  const BOOK_PREFIX = "활동집 - ";

  function generationFailureText(error) {
    const message = error && typeof error.message === "string" ? error.message.trim() : "";
    return "생성 실패: " + (message || GEN_ERROR_FALLBACK);
  }

  // The failure line stays prefixed with 생성 실패: the session-restore code
  // treats drafts that do not start with it as real content.
  function showGenerationFailure(output, retry, error) {
    output.value = generationFailureText(error);
    if (retry) retry.hidden = false;
  }

  function retryButton(id, run) {
    const button = el("button", "util-retry", GEN_RETRY_LABEL);
    button.type = "button";
    button.id = id;
    button.hidden = true;
    button.addEventListener("click", () => {
      button.hidden = true;
      run();
    });
    return button;
  }

  async function apiChat(prompt, util) {
    // Same rule as app.js selectedProductTier(), lines 3039-3040.
    const selected = window.PadiemTierSelection?.get?.();
    const tier = ["free", "plus", "pro", "max", "admin"].includes(selected) ? selected : "free";
    const payload = { messages: [{ role: "user", content: prompt }], tier };
    if (util) payload.util = util;
    let res;
    try {
      res = await fetch("/api/chat", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (_) {
      throw new Error(GEN_OFFLINE_COPY);
    }
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      const message = data?.error?.message;
      throw new Error(typeof message === "string" && message.trim()
        ? message
        : (GEN_ERROR_COPY[res.status] || GEN_ERROR_FALLBACK));
    }
    const data = await res.json();
    return (data && data.answer) ? data.answer : (data && data.message ? data.message : JSON.stringify(data));
  }

  async function getProjects() {
    const res = await fetch("/api/projects", { credentials: "include" });
    if (!res.ok) return [];
    const data = await res.json();
    return (data && data.projects) ? data.projects : [];
  }

  async function ensureProject() {
    const projects = await getProjects();
    if (projects.length) return projects[0].id;
    const res = await fetch("/api/projects", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "유틸 작업" }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data && data.project ? data.project.id : null;
  }

  // #5783: a save that did not store anything says so inside the tab — one
  // aria-live="polite" status line per tab, never a browser modal. One honest
  // sentence per status: permission (403/404), size (413, and the 422 the
  // store answers for an over-limit text body), session (401), and for what
  // can genuinely change by pressing again a 다시 시도 that re-runs the SAME
  // save. No sentence promises a save that has not happened.
  const SAVE_PERMISSION_TEXT = "이 글을 저장할 권한이 없어요";
  const SAVE_SIZE_TEXT = "파일이 너무 커서 저장하지 못했어요";
  const SAVE_LOGIN_TEXT = "로그인이 필요합니다. 다시 로그인해 주세요.";
  const SAVE_RETRY_TEXT = "잠시 저장하지 못했어요";

  function saveFailureText(failure) {
    const status = failure ? failure.status : undefined;
    if (failure && failure.size) return SAVE_SIZE_TEXT;
    if (status === 403 || status === 404) return SAVE_PERMISSION_TEXT;
    if (status === 413) return SAVE_SIZE_TEXT;
    if (status === 401) return SAVE_LOGIN_TEXT;
    return SAVE_RETRY_TEXT;
  }

  function saveFailureRetries(failure) {
    const status = failure ? failure.status : undefined;
    if (failure && failure.size) return false;
    // 다시 시도 answers what pressing again can change. Permission, session
    // and size do not change by pressing — 413 and the store's 422 limit are
    // the same too-big piece either way.
    return !(status === 401 || status === 403 || status === 404 || status === 413);
  }

  function saveStatusLine(id) {
    const line = el("p", "util-save-status");
    line.id = id;
    line.hidden = true;
    line.setAttribute("aria-live", "polite");
    return line;
  }

  function showSaveStatus(line, failure, run) {
    line.replaceChildren();
    line.textContent = saveFailureText(failure);
    if (saveFailureRetries(failure) && typeof run === "function") {
      line.textContent += " · ";
      const retry = el("button", "util-retry", GEN_RETRY_LABEL);
      retry.type = "button";
      retry.addEventListener("click", () => {
        hideSaveStatus(line);
        run();
      });
      line.appendChild(retry);
    }
    line.hidden = false;
  }

  function hideSaveStatus(line) {
    line.hidden = true;
    line.textContent = "";
  }

  // The read paths may reuse ensureProject, but a save must say why nothing
  // was stored, so this variant keeps the HTTP status of whichever step
  // failed instead of collapsing it to null.
  async function ensureProjectForSave() {
    let res;
    try {
      res = await fetch("/api/projects", { credentials: "include" });
    } catch (_error) {
      return { status: 0 };
    }
    if (!res.ok) return { status: res.status };
    const data = await res.json().catch(() => null);
    const projects = data && data.projects ? data.projects : [];
    if (projects.length) return { pid: projects[0].id };
    let create;
    try {
      create = await fetch("/api/projects", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "유틸 작업" }),
      });
    } catch (_error) {
      return { status: 0 };
    }
    if (!create.ok) return { status: create.status };
    const created = await create.json().catch(() => null);
    return created && created.project ? { pid: created.project.id } : { status: 0 };
  }

  // #5731: a stored writing carries the kind its screen saved it as
  // (speech/sns/meeting/book), so a list asks for its own kind instead of
  // reading every .txt in the project. A name already used by the same kind
  // comes back as 409 with the existing file — the caller asks the owner
  // rather than quietly stacking a second row.
  async function saveProjectFile(pid, name, text, mediaType, docKind) {
    const payload = { name: name, media_type: mediaType || "text/plain", text: text };
    if (docKind) payload.doc_kind = docKind;
    let res;
    try {
      res = await fetch("/api/projects/" + pid + "/files", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        // The server refuses a file whose media type contradicts its
        // extension; callers that store .json payloads must say so.
        body: JSON.stringify(payload),
      });
    } catch (_error) {
      // The request never reached an answer — the screen says 잠시 + 다시 시도.
      return { failure: { status: 0 } };
    }
    if (res.status === 409) {
      const body = await res.json().catch(() => null);
      const existing = body && body.error && body.error.existing;
      return existing && existing.id ? { conflict: existing } : { failure: { status: res.status } };
    }
    if (!res.ok) {
      // The request body bound answers 413; an over-limit text body is the
      // store's 422 project_file_limit. Both say the same thing to the person
      // typing: the piece is too big, and pressing again cannot shrink it.
      const body = await res.json().catch(() => null);
      const size = res.status === 422 && !!(body && body.error && body.error.code === "project_file_limit");
      return { failure: { status: res.status, size: size } };
    }
    const data = await res.json();
    return data && data.file ? { file: data.file } : { failure: { status: res.status } };
  }

  // #5731: overwriting keeps the displaced body on the server, so the same
  // name can be reused without losing what was written before.
  async function overwriteProjectFile(pid, fileId, text, docKind) {
    const payload = { text: text };
    if (docKind) payload.doc_kind = docKind;
    let res;
    try {
      res = await fetch(
        "/api/projects/" + encodeURIComponent(pid) + "/files/" + encodeURIComponent(fileId),
        {
          method: "PUT",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
    } catch (_error) {
      return { failure: { status: 0 } };
    }
    if (!res.ok) return { failure: { status: res.status } };
    const data = await res.json().catch(() => null);
    return data && data.file ? { file: data.file, previous: data.previous || null } : { failure: { status: res.status } };
  }

  // `행사.txt` -> `행사 (2).txt`, first free number. The default the owner is
  // offered is a NEW file, never a silent overwrite.
  function nextFreeName(name, taken) {
    const used = new Set((taken || []).map((item) => String(item || "")));
    if (!used.has(name)) return name;
    const stem = name.replace(/\.[^.]+$/, "");
    const ext = (name.match(/\.[^.]+$/) || [""])[0];
    let n = 2;
    while (used.has(stem + " (" + n + ")" + ext)) n += 1;
    return stem + " (" + n + ")" + ext;
  }

  // One question, two buttons, and the safe answer is the default: a save that
  // collides asks instead of guessing. `overwrite` is offered as the second
  // choice with the version behaviour stated in its label.
  function askSaveChoice(anchor, name, suggested) {
    return new Promise((resolve) => {
      const box = el("div", "util-save-choice");
      box.setAttribute("role", "group");
      box.setAttribute("aria-label", "같은 이름의 글이 이미 있습니다");
      const text = el("p", "util-save-choice-text",
        "같은 이름의 글이 이미 있습니다: " + name);
      const asNew = el("button", "util-save-as-new", "새 이름으로 저장 (" + suggested + ")");
      asNew.type = "button";
      const overwrite = el("button", "util-save-overwrite", "덮어쓰기 (이전 내용은 버전으로 남김)");
      overwrite.type = "button";
      const done = (choice) => {
        if (box.parentNode) box.parentNode.removeChild(box);
        resolve(choice);
      };
      asNew.addEventListener("click", () => done("new"));
      overwrite.addEventListener("click", () => done("overwrite"));
      box.append(text, asNew, overwrite);
      const host = anchor && anchor.parentNode ? anchor.parentNode : anchor;
      if (host && typeof host.appendChild === "function") host.appendChild(box);
      else resolve(null);
    });
  }

  /**
   * The one save path for a util writing: POST with its kind, and on a name
   * collision ask the owner (new name is the default) before writing again.
   * Returns what happened, so the tab can say it: { file } when stored,
   * { failure: { status, size? } } when a request failed, { none: true } when
   * nothing was saved and nothing failed — the owner has not chosen yet.
   */
  async function saveUtilText(options) {
    const pid = options.pid;
    if (!pid) return { none: true };
    const first = await saveProjectFile(pid, options.name, options.text, "text/plain", options.kind);
    if (first.failure) return first;
    if (!first.conflict) return { file: first.file };
    const files = await listProjectFiles(pid);
    const suggested = nextFreeName(options.name, files.map((f) => f.name));
    const choice = await askSaveChoice(options.anchor, options.name, suggested);
    if (choice === "overwrite") {
      const replaced = await overwriteProjectFile(pid, first.conflict.id, options.text, options.kind);
      return replaced.failure ? replaced : { file: replaced.file };
    }
    if (choice === "new") {
      const second = await saveProjectFile(pid, suggested, options.text, "text/plain", options.kind);
      return second.failure ? second : { file: second.file };
    }
    return { none: true };
  }

  // #6199: re-opening a stored piece reads its body from the existing detail
  // route. It keeps the HTTP status (and the empty-body case apart) so the
  // screen can say what actually failed instead of a generic sentence.
  async function readStoredBody(pid, fileId) {
    let res;
    try {
      res = await fetch(
        "/api/projects/" + encodeURIComponent(pid) + "/files/" + encodeURIComponent(fileId),
        { credentials: "include" },
      );
    } catch (_error) {
      return { ok: false, status: 0, text: "" };
    }
    if (!res.ok) return { ok: false, status: res.status, text: "" };
    const data = await res.json().catch(() => null);
    const file = data && data.file ? data.file : null;
    const text = file ? (typeof file.content === "string" ? file.content : file.text) : null;
    if (typeof text !== "string") return { ok: false, status: res.status, text: "" };
    if (!text.trim()) return { ok: false, status: res.status, text: "", empty: true };
    return { ok: true, status: res.status, text: text };
  }

  // Korean picks 을 or 를 from the last syllable. The two labels below end in
  // 사 (vowel) and 글 (consonant), so one small helper keeps every sentence
  // grammatical instead of a fixed particle that reads wrong in one tool.
  function withObjectParticle(word) {
    const last = word.charCodeAt(word.length - 1);
    const endsInConsonant = last >= 0xac00 && last <= 0xd7a3 && (last - 0xac00) % 28 !== 0;
    return word + (endsInConsonant ? "을" : "를");
  }

  // One sentence per real failure: another account's piece answers 404 and the
  // copy says so instead of pretending the row vanished.
  function storedOpenFailureText(label, result) {
    if (result && result.empty) return label + "의 본문이 비어 있습니다.";
    if (!result || !result.status) return withObjectParticle(label) + " 열지 못했습니다. 인터넷 연결을 확인해 주세요.";
    if (result.status === 404) return withObjectParticle(label) + " 찾을 수 없습니다. 다른 계정의 글이거나 삭제된 글입니다.";
    if (result.status === 401) return "로그인이 필요합니다. 다시 로그인해 주세요.";
    return withObjectParticle(label) + " 열지 못했습니다 (HTTP " + result.status + ").";
  }

  // #6199: the edit banner names the stored piece the save will collide with,
  // so [새 이름으로 저장] / [덮어쓰기] is never a surprise.
  function editingStateText(target) {
    return "고쳐 쓰는 중: " + target.name
      + " · 저장하면 같은 이름은 새 이름 또는 덮어쓰기(이전 내용은 버전으로 남김) 중에서 묻습니다.";
  }

  // #5728: photos persist through the SAME project-file channel as text
  // drafts — binary original upload, owner/project scoped, no new limits.
  // The failure keeps its HTTP status so the screen can say what happened
  // (GEN_ERROR_COPY) instead of a bare "failed".
  async function uploadProjectImage(pid, blob, name, type) {
    let res;
    try {
      res = await fetch("/api/projects/" + pid + "/files", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/octet-stream",
          "X-Padiem-Filename": encodeURIComponent(name),
          "X-Padiem-Media-Type": type,
        },
        body: blob,
      });
    } catch (_error) {
      // A dead network is not an HTTP status; it gets the offline sentence.
      return { ok: false, file: null, status: 0 };
    }
    if (!res.ok) return { ok: false, file: null, status: res.status };
    const data = await res.json().catch(() => null);
    const file = data && data.file ? data.file : null;
    return file
      ? { ok: true, file: file, status: res.status }
      : { ok: false, file: null, status: res.status };
  }

  // #5728: the browser does the shrinking (static/photo-resize.js explains the
  // Worker CPU/memory reason). Loaded on first photo, so a page that never adds
  // a photo touches no extra script.
  let photoResizeLoading = null;
  function loadPhotoResize() {
    if (window.PadiemPhotoResize) return Promise.resolve(window.PadiemPhotoResize);
    if (photoResizeLoading) return photoResizeLoading;
    photoResizeLoading = new Promise((resolve, reject) => {
      const head = document.head || document.body;
      const script = document.createElement("script");
      script.src = "./photo-resize.js";
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

  async function listProjectFiles(pid) {
    const res = await fetch("/api/projects/" + pid + "/files", { credentials: "include" });
    if (!res.ok) return [];
    const data = await res.json();
    return (data && data.files) ? data.files : [];
  }

  // ── #5895: "내 PC에서 예전 글 가져오기" / "내 PC에 저장" ─────────────────
  // The authoring tools share one browser part. It is loaded on first use (#5895:
  // nothing joins the page or the Worker's cold init until a menu needs it), and the
  // only endpoints it adds are the PC file-exchange routes that already exist.
  const PC_REF_COPY = {
    pick: "내 PC에서 예전 글 가져오기",
    again: "내 PC에서 더 가져오기",
    remove: "빼기",
    preview: "가져온 글",
    unavailable: "PC 파일 창을 열지 못했습니다. 잠시 후 다시 시도해 주세요.",
    unreadable: "이 파일은 참고 글로 읽지 못했어요. 글자가 들어 있는 문서를 골라 주세요.",
    hwpEncrypted: "암호가 걸린 한글 파일은 읽을 수 없어요.",
    hwpDistributable: "배포용으로 저장된 한글 파일은 읽을 수 없어요.",
    laneDown: "파일 읽기 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    noPc: "PC를 연결하면 예전 글을 가져올 수 있습니다.",
    connect: "이 PC 연결",
    save: "내 PC에 저장",
    saveUnavailable: "PC에 저장할 창을 열지 못했습니다. 잠시 후 다시 시도해 주세요.",
    saved: "내 PC에 저장했습니다.",
  };

  let pcExchangeLoading = null;

  function loadPcExchange() {
    if (window.PadiemPcFileExchange) return Promise.resolve(window.PadiemPcFileExchange);
    if (pcExchangeLoading) return pcExchangeLoading;
    pcExchangeLoading = new Promise((resolve, reject) => {
      const head = document.head || document.body;
      if (head && !document.querySelector('link[href="./pc-file-exchange.css"]')) {
        const css = document.createElement("link");
        css.rel = "stylesheet";
        css.href = "./pc-file-exchange.css";
        head.appendChild(css);
      }
      const script = document.createElement("script");
      script.src = "./pc-file-exchange.js";
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

  // The existing Connectors surface owns the computer card: no second pairing screen.
  function openPcConnect() {
    const opener = document.getElementById("connectorsNavButton");
    if (!opener) return;
    opener.click();
    const card = document.getElementById("connectorComputerCard");
    if (!card) return;
    if (!card.hasAttribute("tabindex")) card.setAttribute("tabindex", "-1");
    if (typeof card.focus === "function") card.focus({ preventScroll: true });
    if (typeof card.scrollIntoView === "function") card.scrollIntoView({ block: "nearest" });
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
        // #5895: the refusals the lane and the Worker answer by code, said out
        // loud — a sealed or distributed 한글 file is not a broken picker.
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
  // preview, and — when no PC is linked — the one-line notice instead.
  function createPcReferenceSection() {
    const box = el("div", "util-pc-ref");
    const pick = el("button", "util-pc-ref-pick", PC_REF_COPY.pick);
    pick.type = "button";
    const note = el("p", "util-pc-ref-note", "");
    note.hidden = true;
    const status = el("p", "util-pc-ref-status", "");
    status.hidden = true;
    const list = el("ul", "util-pc-ref-list");
    list.hidden = true;
    box.append(pick, note, list, status);
    const files = [];

    function say(text) {
      status.textContent = text || "";
      status.hidden = !text;
    }

    function render() {
      list.replaceChildren();
      files.forEach((file, index) => {
        const item = el("li", "util-pc-ref-item");
        const head = el("div", "util-pc-ref-head");
        head.append(el("strong", "util-pc-ref-name", file.name));
        head.append(el("span", "util-pc-ref-chars", file.text.length.toLocaleString("ko-KR") + "자"));
        const drop = el("button", "util-pc-ref-remove", PC_REF_COPY.remove);
        drop.type = "button";
        drop.addEventListener("click", () => {
          files.splice(index, 1);
          render();
        });
        head.append(drop);
        const preview = el("pre", "util-pc-ref-preview", file.text);
        item.append(head, preview);
        list.append(item);
      });
      list.hidden = files.length === 0;
      pick.textContent = files.length ? PC_REF_COPY.again : PC_REF_COPY.pick;
    }

    async function addPicked(picked) {
      say("");
      const entry = await pcReferenceEntry(picked);
      if (entry && typeof entry.error === "string") {
        say(entry.error);
        return;
      }
      if (!entry) {
        say(PC_REF_COPY.unreadable);
        return;
      }
      files.push(entry);
      render();
    }

    pick.addEventListener("click", async () => {
      say("");
      let component;
      try {
        component = await loadPcExchange();
      } catch (_) {
        component = null;
      }
      if (!component || typeof component.open !== "function") {
        say(PC_REF_COPY.unavailable);
        return;
      }
      component.open({ onSelect: (picked) => { void addPicked(picked); } });
    });

    // The check runs when the screen is first shown, not when the module loads:
    // a page that never opens this tool asks the PC directory nothing at all.
    let checked = false;
    function check() {
      if (checked) return;
      checked = true;
      void pcLinked().then((linked) => {
        if (linked !== false) return;
        pick.hidden = true;
        note.textContent = PC_REF_COPY.noPc + " ";
        const connect = el("button", "util-pc-ref-connect", PC_REF_COPY.connect);
        connect.type = "button";
        connect.addEventListener("click", openPcConnect);
        note.appendChild(connect);
        note.hidden = false;
      });
    }

    return {
      box,
      files,
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
    const title = String(base || "").trim().replace(/[\/:*?"<>|]+/g, " ").trim() || "글";
    const now = new Date();
    const pad = (value) => String(value).padStart(2, "0");
    const day = now.getFullYear() + "-" + pad(now.getMonth() + 1) + "-" + pad(now.getDate());
    return title + "_" + day + ".txt";
  }

  async function saveTextToPc(text, baseName) {
    const content = String(text || "").trim();
    if (!content) return;
    let component;
    try {
      component = await loadPcExchange();
    } catch (_) {
      component = null;
    }
    if (!component || typeof component.open !== "function") {
      alert(PC_REF_COPY.saveUnavailable);
      return;
    }
    component.open({
      mode: "save",
      content,
      fileName: pcSaveFileName(baseName),
      onSave: () => {},
    });
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

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  ready(() => {
    const utilNav = document.getElementById("utilNavButton");
    const utilView = document.getElementById("utilView");
    if (!utilNav || !utilView) return;

    const speechForm = document.getElementById("utilSpeechForm");
    const speechResult = document.getElementById("utilSpeechResult");
    const speechOutput = document.getElementById("utilSpeechOutput");
    const copyBtn = document.getElementById("utilSpeechCopy");
    const downloadBtn = document.getElementById("utilSpeechDownload");
    // #5727: the save action lives in the form area next to 초안 생성 (index.html
    // markup) and stays disabled until a draft exists — it never claims a save
    // that did not happen.
    const saveBtn = document.getElementById("utilSpeechSave");
    const speechPc = createPcReferenceSection();
    const speechPcMount = document.getElementById("utilSpeechPcRef");
    if (speechPcMount) speechPcMount.appendChild(speechPc.box);
    // #5895 beta UX: a failed draft comes back with its own 다시 시도 instead of
    // leaving the owner to find the form button again.
    const speechActions = document.querySelector("#utilSpeechResult .util-actions");
    const speechRetry = retryButton("utilSpeechRetry", () => { if (speechForm) generateSpeech(speechForm); });
    if (speechActions) speechActions.appendChild(speechRetry);
    const utilTitleEl = document.getElementById("utilTitle");
    const utilKickerEl = document.getElementById("utilKicker");
    const utilTaglineEl = document.getElementById("utilTagline");
    const tabs = document.querySelectorAll(".util-tab");
    const panels = {
      speech: document.getElementById("utilSpeechPanel"),
      sns: document.getElementById("utilSnsPanel"),
      meeting: document.getElementById("utilMeetingPanel"),
      pdfmd: document.getElementById("utilPdfmdPanel"),
    };

    let lastPayload = null;
    let currentPid = null;
    // #5895: the SNS panel is built on first open, so its PC section is handed back
    // to the tab handler that knows when the panel is actually on screen.
    let snsPcRef = null;
    // #6199: the stored speech currently in the draft editor, if any. It keeps
    // the name the save offers to the existing 409 check and the kind it keeps.
    let speechEditing = null;

    // #5608 follow-up: the sidebar Util entry expands into its four tools. The
    // submenu rows and the (hidden) in-page tabs drive the same switch, so the
    // panels, lazy builders and saved state keep their single owner here.
    const utilSubmenu = document.getElementById("utilSubmenu");
    const utilSubmenuItems = utilSubmenu
      ? Array.from(utilSubmenu.querySelectorAll(".util-submenu-item"))
      : [];

    // #5608: the util page is its own shell state. The sibling views are gated
    // by CSS (util-menu.css), so entering the state is enough and navigating to
    // any other view restores them -- no per-view cleanup needed here.
    function showUtil() {
      const shell = document.querySelector(".app-shell");
      if (shell) shell.dataset.state = "util";
      utilView.hidden = false;
      utilNav.setAttribute("aria-current", "page");
    }

    function setUtilSubmenuOpen(open) {
      if (!utilSubmenu) return;
      utilSubmenu.hidden = !open;
      utilNav.setAttribute("aria-expanded", open ? "true" : "false");
      const chevron = utilNav.querySelector(".side-chevron");
      if (chevron) chevron.textContent = open ? "⌄" : "›";
    }

    function markActiveUtilSubmenuItem(key) {
      if (!utilSubmenu) return;
      utilSubmenuItems.forEach((item) => {
        const active = key != null && item.dataset.util === key;
        item.classList.toggle("active", active);
        item.setAttribute("aria-current", active ? "true" : "false");
      });
    }

    function closeMobileSidebar() {
      const shell = document.querySelector(".app-shell");
      if (!shell || !shell.classList.contains("sidebar-open")) return;
      shell.classList.remove("sidebar-open");
      const menu = document.getElementById("mobileMenu");
      if (menu) menu.setAttribute("aria-expanded", "false");
      const scrim = document.getElementById("sidebarScrim");
      if (scrim) scrim.hidden = true;
    }

    utilNav.addEventListener("click", () => {
      showUtil();
      if (utilSubmenu) setUtilSubmenuOpen(utilSubmenu.hidden);
    });
    utilSubmenuItems.forEach((item) => {
      item.addEventListener("click", () => {
        showUtil();
        setUtilSubmenuOpen(true);
        markActiveUtilSubmenuItem(item.dataset.util);
        const tab = Array.prototype.find.call(
          tabs, (t) => t.dataset.util === item.dataset.util
        );
        if (tab) activateUtilTab(tab);
        closeMobileSidebar();
      });
    });
    markActiveUtilSubmenuItem("speech");
    // Leaving the util view (any other nav) must not leave a stale highlight
    // on a submenu row. app.js owns aria-current on the parent, so watching
    // that one attribute covers every navigation path.
    if (utilSubmenu && typeof MutationObserver === "function") {
      new MutationObserver(() => {
        if (utilNav.getAttribute("aria-current") === "false") {
          markActiveUtilSubmenuItem(null);
        }
      }).observe(utilNav, { attributes: true, attributeFilter: ["aria-current"] });
    }
    function activateUtilTab(tab) {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const key = tab.dataset.util;
      Object.keys(panels).forEach((k) => { if (panels[k]) panels[k].hidden = k !== key; });
      // #5727: the page title names the actual tool, the shared standalone
      // header hierarchy (kicker → task title → tagline) stays untouched.
      if (utilTitleEl && tab.textContent.trim()) utilTitleEl.textContent = tab.textContent.trim();
      // #5799: the kicker and tagline follow the active tool the same way.
      // Only the speech template carries its own values so far; the other
      // tools keep the shared defaults until their own pass.
      if (utilKickerEl) utilKickerEl.textContent = tab.dataset.kicker || "Padiem Util";
      if (utilTaglineEl) utilTaglineEl.textContent = tab.dataset.tagline || "AI 홍보·기록 비서";
      if (key === "speech") speechPc.check();
      if (key === "sns") {
        if (!panels.sns.dataset.loaded) buildSns();
        snsPcRef.check();
      }
      if (key === "meeting" && !panels.meeting.dataset.loaded) buildMeeting();
      // #5731: re-entering the speech tool must show the past speeches the
      // account already stored — the list can't only exist after a save.
      if (key === "speech" && !panels.speech.dataset.speechListLoaded) {
        panels.speech.dataset.speechListLoaded = "1";
        refreshSpeechList();
      }
      if (key === "pdfmd" && !panels.pdfmd.dataset.loaded) {
        panels.pdfmd.dataset.loaded = "1";
        if (typeof window.initPdfMdUtility === "function") window.initPdfMdUtility(panels.pdfmd);
      }
    }
    tabs.forEach((tab) => {
      tab.addEventListener("click", () => activateUtilTab(tab));
    });

    // Speech
    function buildPrompt(form) {
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
      const references = speechPc.read();
      if (references) prompt += `\n아래는 사용자의 PC에서 가져온 예전 글입니다. 문체와 어휘, 글의 구성을 참고하되 그대로 옮기지 마세요:\n---\n${references}\n---\n`;
      prompt += "\n축사 초안을 작성해 주세요. 행사 성격에 맞는 공식 축사 형식으로 작성하고, 인사말과 마무리 인사를 포함해 주세요.";
      return prompt;
    }

    async function generateSpeech(form) {
      const prompt = buildPrompt(form);
      lastPayload = prompt;
      // A fresh generation is no longer an edit of the stored piece, so the
      // save must not offer that old name back.
      setSpeechEditing(null);
      speechResult.hidden = false;
      speechOutput.value = "생성 중...";
      try {
        speechOutput.value = await apiChat(prompt, "speech");
      } catch (e) {
        showGenerationFailure(speechOutput, speechRetry, e);
      }
      // #5727: saving is a form-area action; the click handler's empty guard
      // keeps an unused save from claiming anything.
    }
    if (speechForm) {
      speechForm.addEventListener("submit", (e) => { e.preventDefault(); generateSpeech(speechForm); });
    }
    if (copyBtn) copyBtn.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(speechOutput.value); copyBtn.textContent = "복사됨"; setTimeout(() => { copyBtn.textContent = "복사"; }, 1500); } catch (_) {}
    });
    if (downloadBtn) downloadBtn.addEventListener("click", () => { downloadText(speechOutput.value, "speech.txt"); });
    const speechPcSave = document.getElementById("utilSpeechPcSave");
    if (speechPcSave) speechPcSave.addEventListener("click", () => {
      const eventName = String(document.querySelector("#utilSpeechForm [name=event]")?.value || "축사").trim();
      void saveTextToPc(speechOutput.value, eventName || "축사");
    });

    // #5783: the speech tab's save status lives in the form, above the two
    // buttons — the same place the 409 ask appears.
    const speechSaveState = saveStatusLine("utilSpeechSaveState");
    if (saveBtn && saveBtn.parentNode && saveBtn.parentNode.parentNode) {
      saveBtn.parentNode.parentNode.insertBefore(speechSaveState, saveBtn.parentNode);
    }

    async function runSpeechSave() {
      const text = speechOutput.value.trim();
      if (!text) return;
      hideSaveStatus(speechSaveState);
      if (!currentPid) {
        const ensured = await ensureProjectForSave();
        if (!ensured.pid) { showSaveStatus(speechSaveState, { status: ensured.status }, runSpeechSave); return; }
        currentPid = ensured.pid;
      }
      // #6199: an edited stored speech saves under its OWN name and kind, so
      // the existing 409 (새 이름으로 저장 / 덮어쓰기) runs instead of a second
      // row appearing under the form's event name.
      const editing = speechEditing;
      const eventName = (document.querySelector("#utilSpeechForm [name=event]")?.value || "축사").trim();
      const name = editing ? editing.name : (eventName || "축사") + ".txt";
      // #5731: the kind is what makes this row a 축사 for every later list.
      const kind = editing && editing.kind ? editing.kind : "speech";
      const outcome = await saveUtilText({ pid: currentPid, name: name, text: text, kind: kind, anchor: saveBtn });
      if (outcome.file) {
        saveBtn.textContent = "저장됨";
        setTimeout(() => { saveBtn.textContent = "저장"; }, 1500);
        setSpeechEditing(null);
        hideSaveStatus(speechSaveState);
        await refreshSpeechList();
      } else if (outcome.failure) {
        showSaveStatus(speechSaveState, outcome.failure, runSpeechSave);
      }
      // outcome.none: the 409 ask is on screen and owns the next move.
    }
    if (saveBtn) saveBtn.addEventListener("click", () => runSpeechSave());

    // #6199: the line above the draft says an edit of a stored piece is open,
    // not a fresh generation.
    const speechEditState = el("p", "util-edit-state");
    speechEditState.id = "utilSpeechEditState";
    speechEditState.hidden = true;
    if (speechOutput && speechOutput.parentNode) {
      speechOutput.parentNode.insertBefore(speechEditState, speechOutput);
    }

    function setSpeechEditing(target) {
      speechEditing = target;
      speechEditState.hidden = !target;
      speechEditState.textContent = target ? editingStateText(target) : "";
    }

    // #6199: [고쳐 쓰기] puts a stored speech back into the SAME draft editor —
    // no second editor, no second store — so the owner can change it and save.
    async function openSpeechForEdit(file) {
      if (!currentPid) currentPid = await ensureProject();
      if (!currentPid) { alert("프로젝트를 찾을 수 없습니다."); return; }
      const stored = await readStoredBody(currentPid, file.id);
      if (!stored.ok) { alert(storedOpenFailureText("저장된 축사", stored)); return; }
      setSpeechEditing({ id: file.id, name: file.name, kind: file.doc_kind || "speech" });
      speechResult.hidden = false;
      speechOutput.value = stored.text;
      speechOutput.focus();
    }

    const savedList = document.createElement("div");
    savedList.id = "utilSpeechSaved";
    savedList.className = "util-saved-list";
    if (speechResult) speechResult.appendChild(savedList);

    async function refreshSpeechList() {
      if (!currentPid) currentPid = await ensureProject();
      if (!currentPid) return;
      const files = await listProjectFiles(currentPid);
      // #5731: only this tool's own writing, plus the rows stored before the
      // kind was recorded — those are grouped as 기타, never hidden. A version
      // row is history of a current file and is not a separate item here.
      const current = files.filter((f) => !f.doc_version_of);
      const speechFiles = current.filter((f) => f.doc_kind === "speech");
      const legacyFiles = current.filter((f) => !f.doc_kind && (f.name || "").endsWith(".txt")
        && !(f.name || "").startsWith(BOOK_PREFIX));
      savedList.replaceChildren();
      if (!speechFiles.length && !legacyFiles.length) {
        const p = el("p", "util-empty", "저장된 축사가 없습니다.");
        savedList.appendChild(p);
        return;
      }
      const group = (title, list) => {
        if (title) savedList.appendChild(el("h4", "util-saved-group", title));
        const ul = document.createElement("ul");
        list.forEach((f) => { ul.appendChild(speechItem(f)); });
        savedList.appendChild(ul);
      };
      if (speechFiles.length) group(null, speechFiles);
      if (legacyFiles.length) group("기타 (종류가 표시되지 않은 예전 글)", legacyFiles);

      function speechItem(f) {
        const li = document.createElement("li");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "util-edit-stored";
        btn.dataset.fileId = f.id;
        // #6199: the row leads with the action — a past speech reopens in the
        // editable draft instead of only being displayed.
        btn.textContent = "고쳐 쓰기: " + f.name + " (" + (f.content_chars || 0) + "자)";
        btn.addEventListener("click", async () => { await openSpeechForEdit(f); });
        li.appendChild(btn);
        // #5731: a stored speech can be picked as the style reference — the
        // same owner/project file the list already reads fills the style
        // sample textarea, so the next generation carries it as the sample.
        const useAsRef = document.createElement("button");
        useAsRef.type = "button";
        useAsRef.className = "util-speech-use-ref";
        useAsRef.dataset.fileId = f.id;
        useAsRef.textContent = "참고로 선택";
        useAsRef.addEventListener("click", async () => {
          const styleField = document.querySelector('#utilSpeechForm [name=style]');
          if (!styleField) { alert("참고 원고 필드를 찾을 수 없습니다."); return; }
          const res = await fetch("/api/projects/" + encodeURIComponent(currentPid) + "/files/" + encodeURIComponent(f.id), { credentials: "include" });
          if (!res.ok) { alert("참고 원고를 불러오지 못했습니다."); return; }
          const data = await res.json().catch(() => null);
          const content = data && data.file && (data.file.content || data.file.text);
          if (typeof content !== "string" || !content.trim()) { alert("참고 원고의 본문을 읽을 수 없습니다."); return; }
          styleField.value = content;
        });
        li.appendChild(useAsRef);
        return li;
      }
    }

    // SNS builder
    function buildSns() {
      const panel = panels.sns;
      if (!panel || panel.dataset.loaded) return;
      const form = el("form", "util-form");
      form.id = "utilSnsForm";
      // 참고 글: the PC reference leads the form in its own titled section —
      // the speech tool's fieldset language — instead of floating between the
      // two-lane grid's field cells.
      const refSection = el("fieldset", "util-fieldset");
      refSection.id = "utilSnsRef";
      refSection.appendChild(el("legend", null, "참고 글"));
      const snsPc = createPcReferenceSection();
      snsPcRef = snsPc;
      refSection.appendChild(snsPc.box);
      form.appendChild(refSection);
      // fields
      const fields = [
        ["event", "행사명", "text", true],
        ["whenwhere", "날짜·장소", "text", false],
        ["content", "주요 내용", "textarea", true],
        ["memo", "메모", "textarea", false],
        ["audience", "대상 독자", "text", false],
      ];
      fields.forEach(([name, label, type, req]) => {
        const l = el("label", null, label + " ");
        if (type === "textarea") {
          const ta = document.createElement("textarea");
          ta.name = name; ta.rows = (name === "content" ? 3 : 2);
          if (req) ta.required = true;
          l.appendChild(ta);
        } else {
          const inp = document.createElement("input");
          inp.name = name; inp.type = "text";
          if (req) inp.required = true;
          l.appendChild(inp);
        }
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

      const tabDiv = el("div", "util-sns-tabs");
      const tabNames = { blog: "블로그", facebook: "페이스북", instagram: "인스타그램" };
      let platform = "blog";
      Object.keys(tabNames).forEach((key) => {
        const b = el("button", "util-sns-tab" + (key === "blog" ? " active" : ""), tabNames[key]);
        b.type = "button";
        b.dataset.platform = key;
        b.addEventListener("click", () => {
          tabDiv.querySelectorAll(".util-sns-tab").forEach((x) => x.classList.remove("active"));
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
      // between chosen paragraphs; facebook/instagram treat them as separate
      // post media. Photos survive platform switches, stay in this session
      // (no upload claim), and no automatic publishing is implied.
      const photos = [];
      const photoBox = el("div", "util-photos");
      photoBox.id = "utilSnsPhotoBox";
      const photoHead = el("div", "util-photos-head");
      const photoTitle = el("span", "util-photos-title", "사진");
      const photoAdd = el("button", "util-photo-add", "사진 추가");
      photoAdd.type = "button"; photoAdd.id = "utilSnsPhotoAdd";
      const photoInput = document.createElement("input");
      photoInput.type = "file"; photoInput.accept = "image/*";
      photoInput.multiple = true; photoInput.hidden = true; photoInput.id = "utilSnsPhotoInput";
      const photoCount = el("span", "util-photos-count", "0장");
      photoCount.id = "utilSnsPhotoCount";
      photoHead.append(photoTitle, photoAdd, photoInput, photoCount);
      const photoList = el("ul", "util-photo-list");
      photoList.id = "utilSnsPhotoList";
      const photoNote = el("p", "util-photo-note");
      photoNote.id = "utilSnsPhotoNote";
      // #5728: a failed photo upload is said out loud in Korean, and the same
      // photos can be retried without picking them again.
      const photoStatus = el("p", "util-photo-status");
      photoStatus.id = "utilSnsPhotoStatus";
      photoStatus.setAttribute("role", "status");
      photoStatus.setAttribute("aria-live", "polite");
      photoStatus.hidden = true;
      const photoRetry = el("button", "util-photo-retry", GEN_RETRY_LABEL);
      photoRetry.type = "button";
      photoRetry.id = "utilSnsPhotoRetry";
      photoRetry.hidden = true;
      photoBox.append(photoHead, photoList, photoNote, photoStatus, photoRetry);
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

      // #5728: shrink big photos BEFORE the upload. The Worker cannot decode a
      // multi-megabyte image inside the free plan's per-request CPU budget, so
      // the browser does the resizing (static/photo-resize.js carries the full
      // reason). A resize that fails leaves the original bytes alone — the
      // upload still happens.
      async function preparePhoto(file) {
        const original = await readImageDataUrl(file);
        if (!original) return null;
        let dataUrl = original;
        let type = file.type || "image/jpeg";
        // Only a real browser can decode and re-encode an image; a DOM without
        // Image (the Node harness) keeps the original bytes and never waits.
        const canDecode = typeof window === "object" && typeof window.Image === "function";
        if (canDecode) {
          try {
            const shrink = await loadPhotoResize();
            const out = await shrink.resizeDataUrl(original, shrink.MAX_EDGE, type);
            if (out && out.resized && typeof out.dataUrl === "string") {
              dataUrl = out.dataUrl;
              const mime = (dataUrl.match(/^data:([^;,]+)/) || [])[1];
              if (mime) type = mime;
            }
          } catch (_error) { /* the original bytes are still uploaded */ }
        }
        const blob = dataUrlToBlob(dataUrl) || file;
        return { blob: blob, dataUrl: dataUrl, type: type };
      }

      // #5728: the roster is one small JSON file that carries the whole
      // persisted composition — the photo order, the blog insertion
      // positions, the saved draft text and the platform it was written
      // for. The photo originals themselves are already stored (each add
      // uploaded them). Rewrites replace the previous roster in place, so a
      // stale roster can never resurrect a photo the owner deleted.
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
          // #5728: the saved draft rides with the roster so re-entry
          // restores the text too; the last explicit 저장 wins.
          if (carriedDraft && carriedDraft.text) {
            roster.draft = { text: carriedDraft.text, platform: carriedDraft.platform || platform };
          }
          const existing = await listProjectFiles(pid);
          const previous = existing.find((f) => f.name === PHOTO_ROSTER_NAME);
          if (previous) await deleteProjectFile(pid, previous.id);
          await saveProjectFile(pid, PHOTO_ROSTER_NAME, JSON.stringify(roster), "application/json");
        }).catch(() => { /* the composition keeps working; the roster stays last-known */ });
        return rosterWriteChain;
      }

      function renderPhotoList() {
        photoCount.textContent = photos.length + "장";
        photoNote.textContent = photoNoteText();
        photoList.replaceChildren();
        photos.forEach((item, index) => {
          const li = el("li", "util-photo-item");
          const img = document.createElement("img");
          img.className = "util-photo-thumb"; img.src = item.dataUrl; img.alt = item.name;
          const nameSpan = el("span", "util-photo-name", item.name);
          const controls = el("div", "util-photo-controls");
          if (platform === "blog") {
            const posLabel = el("label", "util-photo-pos", "삽입 위치 ");
            const sel = document.createElement("select");
            sel.className = "util-photo-pos-select";
            sel.dataset.photoId = String(item.id);
            const opts = [["auto", "자동"], ["0", "맨 앞"], ["end", "문단 끝"]];
            opts.forEach(([v, t]) => { const o = document.createElement("option"); o.value = v; o.textContent = t; sel.appendChild(o); });
            sel.value = item.position;
            sel.addEventListener("change", () => { item.position = sel.value; renderPreview(); writePhotoRoster(currentPid); });
            posLabel.appendChild(sel);
            controls.appendChild(posLabel);
          }
          const up = el("button", "util-photo-move", "↑"); up.type = "button"; up.dataset.move = "-1"; up.dataset.photoId = String(item.id);
          const down = el("button", "util-photo-move", "↓"); down.type = "button"; down.dataset.move = "1"; down.dataset.photoId = String(item.id);
          const del = el("button", "util-photo-remove", "삭제"); del.type = "button"; del.dataset.photoId = String(item.id); del.dataset.action = "remove";
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
          if (photos[index].id && currentPid) {
            const gone = await deleteProjectFile(currentPid, photos[index].id);
            if (!gone) { alert("사진 삭제 실패: " + photos[index].name); return; }
          }
          photos.splice(index, 1);
        } else {
          return;
        }
        renderPhotoList();
        renderPreview();
        // #5728: every durable composition change (reorder and removal here,
        // insertion positions on the selects) rewrites the roster file, so
        // the order and the blog insertion positions outlive the session.
        writePhotoRoster(currentPid);
      });

      // #5728: with a linked PC, 사진 추가 reuses the shared 가져오기 dialog —
      // the same component the reference-text import uses — and the picked PC
      // file is read through /api/pc/file into this very upload pipeline.
      // Without an explicitly linked PC, including a pairing store that
      // cannot answer (503), the local file picker stays: it works on a phone
      // too, and the dialog would only open a dead end.
      // A PC file arrives with no browser filter behind it: the 가져오기 dialog
      // lists every file in the folder, so the extension proves nothing. The
      // media type comes from the bytes, and the same three formats the store
      // accepts (app/project_files.py IMAGE_PROJECT_FILE_MEDIA) are the three
      // that pass. Anything else is refused here, before an upload the server
      // could only answer with a 422 — a retry that can never succeed is worse
      // than one sentence naming the formats that work.
      const PC_PHOTO_FORMATS = "사진은 PNG·JPG·WEBP만 추가할 수 있어요: ";

      function photoBytesType(bytes) {
        const head = new Uint8Array(bytes.slice(0, 12));
        if (head[0] === 0x89 && head[1] === 0x50 && head[2] === 0x4e && head[3] === 0x47) return "image/png";
        if (head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff) return "image/jpeg";
        const riff = String.fromCharCode(head[0], head[1], head[2], head[3]);
        const form = String.fromCharCode(head[8], head[9], head[10], head[11]);
        if (riff === "RIFF" && form === "WEBP") return "image/webp";
        return null;
      }

      // Nothing was added to the composition, so [다시 시도] has nothing to
      // offer: the owner opens the dialog again and the sentence says why.
      function showPhotoImportRefusal(sentence) {
        failedPhotos = [];
        photoRetry.hidden = true;
        photoStatus.textContent = sentence;
        photoStatus.hidden = false;
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
          const blob = await res.blob();
          bytes = await blob.arrayBuffer();
        } catch (error) {
          // A dead network is not an HTTP status: it keeps the offline
          // sentence the rest of this menu already uses.
          const matched = /^http_(\d+)$/.exec(String((error && error.message) || ""));
          const status = matched ? Number(matched[1]) : 0;
          const why = status === 0
            ? GEN_OFFLINE_COPY
            : (GEN_ERROR_COPY[status] || "잠시 후 다시 시도해 주세요.");
          showPhotoImportRefusal("PC에서 사진을 가져오지 못했어요: " + name + " — " + why);
          return;
        }
        const type = photoBytesType(bytes);
        if (!type) { showPhotoImportRefusal(PC_PHOTO_FORMATS + name); return; }
        // The bytes keep their real type, so preparePhoto decodes and shrinks
        // the same way a locally picked photo does, and an upload failure
        // still reaches the shared [다시 시도] row through addPhotoFiles.
        await addPhotoFiles([new File([bytes], name, { type: type })]);
      }

      photoAdd.addEventListener("click", async () => {
        let linked = null;
        try { linked = await pcLinked(); } catch (_error) { linked = null; }
        if (linked !== true) { photoInput.click(); return; }
        let component;
        try { component = await loadPcExchange(); } catch (_error) { component = null; }
        if (!component || typeof component.open !== "function") { photoInput.click(); return; }
        component.open({
          mode: "import",
          onSelect: (picked) => { void importPickedPhoto(picked); },
        });
      });
      // #5728: what failed stays available for [다시 시도]; the sentence is the
      // same Korean copy the generation path already uses for that status.
      let failedPhotos = [];
      function showPhotoFailure(failures) {
        failedPhotos = failures;
        if (!failures.length) {
          photoStatus.hidden = true;
          photoStatus.textContent = "";
          photoRetry.hidden = true;
          return;
        }
        const status = failures[0].status;
        const sentence = status === 0
          ? GEN_OFFLINE_COPY
          : (GEN_ERROR_COPY[status] || "사진을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.");
        photoStatus.textContent = "사진 저장 실패: " + failures.map((f) => f.name).join(", ")
          + " — " + sentence;
        photoStatus.hidden = false;
        photoRetry.hidden = false;
      }

      async function addPhotoFiles(files) {
        const failures = [];
        for (const file of files) {
          if (!file || String(file.type || "").indexOf("image/") !== 0) continue;
          // #5728: a photo joins the composition only once the project-file
          // upload succeeded — the thumbnail and the stored original are the
          // same bytes, and a failed upload never looks "saved".
          if (!currentPid) currentPid = await ensureProject();
          if (!currentPid) { failures.push({ file: file, name: file.name, status: 0 }); continue; }
          const prepared = await preparePhoto(file);
          if (!prepared) { failures.push({ file: file, name: file.name, status: 0 }); continue; }
          const stored = await uploadProjectImage(
            currentPid, prepared.blob, file.name, prepared.type,
          );
          if (!stored.ok) { failures.push({ file: file, name: file.name, status: stored.status }); continue; }
          photos.push({
            id: stored.file.id,
            name: file.name,
            dataUrl: prepared.dataUrl,
            position: "auto",
          });
        }
        showPhotoFailure(failures);
        renderPhotoList();
        renderPreview();
        // An added photo is part of the durable composition as soon as its
        // upload landed — the roster records it right away.
        if (!failures.length) writePhotoRoster(currentPid);
      }

      photoInput.addEventListener("change", async () => {
        const files = Array.from(photoInput.files || []);
        photoInput.value = "";
        await addPhotoFiles(files);
      });

      photoRetry.addEventListener("click", () => {
        const retry = failedPhotos.map((f) => f.file);
        showPhotoFailure([]);
        if (retry.length) void addPhotoFiles(retry);
      });

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
        const box = document.getElementById("utilSnsPreview");
        if (!box || box.hidden) return;
        box.replaceChildren();
        const text = output.value || "";
        if (platform === "blog") {
          interleaveBlog(text).forEach((seg) => {
            if (seg.type === "text") { const p = el("p", "util-preview-para", seg.value); box.appendChild(p); }
            else { const im = document.createElement("img"); im.className = "util-preview-photo"; im.src = seg.value.dataUrl; im.alt = seg.value.name; box.appendChild(im); }
          });
        } else {
          if (text.trim()) { const p = el("p", "util-preview-para", text); box.appendChild(p); }
          const grid = el("div", "util-sns-media-grid" + (platform === "instagram" ? " insta" : ""));
          photos.forEach((ph) => { const im = document.createElement("img"); im.src = ph.dataUrl; im.alt = ph.name; grid.appendChild(im); });
          box.appendChild(grid);
        }
        const note = el("p", "util-photo-note", "미리보기는 초안 구성 확인용입니다. 실제 SNS 자동 게시 기능이 아닙니다.");
        box.appendChild(note);
      }

      renderPhotoList();

      // #5727: the form owns 생성+저장; the result area keeps 복사+다운로드 only.
      const formActions = el("div", "util-form-actions");
      const submitBtn = el("button", "util-generate", "생성");
      submitBtn.type = "submit";
      const formSaveB = el("button", "util-save", "저장");
      formSaveB.type = "button"; formSaveB.id = "utilSnsSave";
      formActions.append(submitBtn, formSaveB);
      // #5783: the save status lives in the form, above the two buttons — the
      // same place the 409 ask appears.
      const snsSaveState = saveStatusLine("utilSnsSaveState");
      // The actions row has to be in the form before it can be a reference
      // node — insertBefore with a node that is not a child yet throws.
      form.appendChild(formActions);
      form.insertBefore(snsSaveState, formActions);

      const result = el("div", "util-result");
      result.id = "utilSnsResult";
      result.hidden = true;
      const h3 = el("h3", null, "블로그 게시글");
      h3.id = "utilSnsTitle";
      const output = document.createElement("textarea");
      output.id = "utilSnsOutput";
      output.rows = 12;
      const previewBox = el("div", "util-sns-preview");
      previewBox.id = "utilSnsPreview";
      previewBox.hidden = true;
      // #6199: the stored SNS piece currently in the editor, if any, plus the
      // line that states the save will ask about its name.
      let snsEditing = null;
      const snsEditState = el("p", "util-edit-state");
      snsEditState.id = "utilSnsEditState";
      snsEditState.hidden = true;
      function setSnsEditing(target) {
        snsEditing = target;
        snsEditState.hidden = !target;
        snsEditState.textContent = target ? editingStateText(target) : "";
      }
      // #6199: [고쳐 쓰기] loads the stored body into the SAME editable draft
      // the generation writes to. The platform tabs keep whatever the owner has
      // selected — the stored file does not carry a platform, and guessing one
      // would be a fake.
      async function openSnsForEdit(file) {
        if (!currentPid) currentPid = await ensureProject();
        if (!currentPid) { alert("프로젝트를 찾을 수 없습니다."); return; }
        const stored = await readStoredBody(currentPid, file.id);
        if (!stored.ok) { alert(storedOpenFailureText("저장한 글", stored)); return; }
        setSnsEditing({ id: file.id, name: file.name, kind: file.doc_kind || "sns" });
        result.hidden = false;
        output.value = stored.text;
        if (previewBox) previewBox.hidden = false;
        renderPreview();
        output.focus();
      }
      const actions = el("div", "util-actions");
      const copyB = el("button", null, "복사"); copyB.type = "button"; copyB.id = "utilSnsCopy";
      const dlB = el("button", null, "TXT 다운로드"); dlB.type = "button"; dlB.id = "utilSnsDownload";
      const pcSaveB = el("button", "util-save", PC_REF_COPY.save);
      pcSaveB.type = "button"; pcSaveB.id = "utilSnsPcSave";
      const snsRetry = retryButton("utilSnsRetry", () => { void gen(); });
      actions.append(copyB, dlB, pcSaveB, snsRetry);
      // #5731: SNS had no list at all, so its stored pieces only came back as
      // the roster's last draft. This list reads the rows this screen saved
      // (kind = sns) and leaves the other tools' writings out.
      const snsSaved = document.createElement("div");
      snsSaved.id = "utilSnsSaved";
      snsSaved.className = "util-saved-list";
      result.append(h3, snsEditState, output, previewBox, actions, snsSaved);

      async function refreshSnsList() {
        if (!currentPid) currentPid = await ensureProject();
        if (!currentPid) return;
        const files = await listProjectFiles(currentPid);
        const own = files.filter((f) => !f.doc_version_of && f.doc_kind === "sns");
        snsSaved.replaceChildren();
        if (!own.length) return;
        snsSaved.appendChild(el("h4", "util-saved-group", "저장한 글"));
        const ul = document.createElement("ul");
        own.forEach((f) => {
          const li = document.createElement("li");
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "util-edit-stored";
          btn.dataset.fileId = f.id;
          btn.textContent = "고쳐 쓰기: " + f.name + " (" + (f.content_chars || 0) + "자)";
          btn.addEventListener("click", async () => { await openSnsForEdit(f); });
          li.appendChild(btn);
          ul.appendChild(li);
        });
        snsSaved.appendChild(ul);
      }
      void refreshSnsList();

      panel.replaceChildren(form, result);
      const title = h3;

      // #5728: re-entry restores the persisted composition ONCE, at build
      // time — before any interaction with the photo list. The stored image
      // files are the originals; when the roster file exists it fixes the
      // order and the blog insertion positions, and photos it does not
      // mention still surface after it so nothing the owner stored vanishes.
      // A roster that carries a saved draft (version 2) also restores the
      // draft text and switches to the platform it was saved under.
      (async () => {
        try {
          if (!currentPid) currentPid = await ensureProject();
          if (!currentPid) return;
          const files = await listProjectFiles(currentPid);
          const imageFiles = files.filter((f) => f.media_type === "image/png"
            || f.media_type === "image/jpeg" || f.media_type === "image/webp");
          let order = null;
          let savedDraft = null;
          const rosterFile = files.find((f) => f.name === PHOTO_ROSTER_NAME);
          if (rosterFile) {
            const detailRes = await fetch("/api/projects/" + currentPid + "/files/" + encodeURIComponent(rosterFile.id), { credentials: "include" });
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
            if (previewBox) { previewBox.hidden = false; }
            if (savedDraft.platform && savedDraft.platform !== platform) {
              const targetTab = Array.from(tabDiv.querySelectorAll(".util-sns-tab")).find((t) => t.dataset.platform === savedDraft.platform);
              if (targetTab) targetTab.click();
              else { platform = savedDraft.platform; title.textContent = ({ blog: "블로그", facebook: "페이스북", instagram: "인스타그램" })[savedDraft.platform] + " 게시글"; }
            }
          }
          if (photos.length || !imageFiles.length) {
            if (savedDraft) renderPreview();
            return;
          }
          const ordered = [];
          if (order && order.length) {
            order.forEach((entry) => {
              const meta = imageFiles.find((f) => f.id === (entry && entry.fileId));
              if (meta) ordered.push({ meta: meta, position: entry && typeof entry.position === "string" && entry.position ? entry.position : "auto" });
            });
            imageFiles.forEach((meta) => {
              if (!ordered.some((o) => o.meta.id === meta.id)) ordered.push({ meta: meta, position: "auto" });
            });
          } else {
            imageFiles.forEach((meta) => ordered.push({ meta: meta, position: "auto" }));
          }
          for (const entry of ordered) {
            const dataUrl = await fetchOriginalDataUrl(currentPid, entry.meta.id);
            if (!dataUrl) continue;
            photos.push({ id: entry.meta.id, name: entry.meta.name, dataUrl: dataUrl, position: entry.position });
          }
          renderPhotoList();
          renderPreview();
        } catch (_) { /* restore is best effort; an empty composition stays honest */ }
      })();

      async function gen() {
        const d = new FormData(form);
        const event = (d.get("event") || "").trim();
        const whenwhere = (d.get("whenwhere") || "").trim();
        const content = (d.get("content") || "").trim();
        const photo = (d.get("photo") || "").trim();
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
        if (photos.length) {
          const names = photos.map((ph) => ph.name).join(", ");
          prompt += `첨부 사진: ${photos.length}장 (${names})\n`;
          prompt += platform === "blog"
            ? "사진은 본문 문단 사이에 삽입됩니다. 각 사진이 어느 내용과 이어지는지 참고해서 문단을 구성해 주세요.\n"
            : "사진은 본문과 구분된 게시물 미디어로 첨부됩니다. 본문에 이미지 위치 설명은 넣지 마세요.\n";
        }
        if (memo) prompt += `메모: ${memo}\n`;
        if (audience) prompt += `대상 독자: ${audience}\n`;
        prompt += `문체: ${toneMap[tone]}\n`;
        const references = snsPc.read();
        if (references) {
          prompt += `아래는 사용자의 PC에서 가져온 예전 글입니다. 문체와 어휘, 글의 구성을 참고하되 그대로 옮기지 마세요:\n---\n${references}\n---\n`;
        }
        prompt += "\n제목, 본문, 해시태그를 구분하여 작성해 주세요.";
        // A fresh generation is no longer an edit of the stored piece.
        setSnsEditing(null);
        result.hidden = false;
        output.value = "생성 중...";
        try { output.value = await apiChat(prompt, "sns"); }
        catch (e) { showGenerationFailure(output, snsRetry, e); }
        if (previewBox) { previewBox.hidden = false; renderPreview(); }
      }
      form.addEventListener("submit", (e) => { e.preventDefault(); gen(); });
      copyB.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(output.value); copyB.textContent = "복사됨"; setTimeout(() => { copyB.textContent = "복사"; }, 1500); } catch (_) {}
      });
      dlB.addEventListener("click", () => { downloadText(output.value, "sns-" + platform + ".txt"); });
      pcSaveB.addEventListener("click", () => {
        const eventName = String(document.querySelector("#utilSnsForm [name=event]")?.value || "SNS").trim();
        void saveTextToPc(output.value, eventName || "SNS");
      });
      async function runSnsSave() {
        const text = output.value.trim();
        if (!text) return;
        hideSaveStatus(snsSaveState);
        if (!currentPid) {
          const ensured = await ensureProjectForSave();
          if (!ensured.pid) { showSaveStatus(snsSaveState, { status: ensured.status }, runSnsSave); return; }
          currentPid = ensured.pid;
        }
        const name = (h3.textContent || "sns").trim() + ".txt";
        // #6199: an edited stored SNS piece saves under its own name and kind,
        // so the existing 409 asks 새 이름/덮어쓰기 instead of stacking a row.
        const editing = snsEditing;
        const saveName = editing ? editing.name : name;
        const kind = editing && editing.kind ? editing.kind : "sns";
        const outcome = await saveUtilText({ pid: currentPid, name: saveName, text: text, kind: kind, anchor: formSaveB });
        if (outcome.file) {
          formSaveB.textContent = "저장됨";
          setTimeout(() => { formSaveB.textContent = "저장"; }, 1500);
          // #5728: the saved draft rides in the roster so re-entry restores
          // the text and its platform, not only the photos.
          lastSavedDraft = { text: text, platform: platform };
          writePhotoRoster(currentPid, lastSavedDraft);
          setSnsEditing(null);
          hideSaveStatus(snsSaveState);
          void refreshSnsList();
        } else if (outcome.failure) {
          showSaveStatus(snsSaveState, outcome.failure, runSnsSave);
        }
        // outcome.none: the 409 ask is on screen and owns the next move.
      }
      formSaveB.addEventListener("click", () => runSnsSave());
      // Set only once the form is on screen: a build that throws has to be
      // retryable on the next entry instead of leaving the panel on its
      // placeholder for the rest of the session.
      panel.dataset.loaded = "1";

    }

    // Meeting builder
    function buildMeeting() {
      const panel = panels.meeting;
      if (!panel || panel.dataset.loaded) return;
      const form = el("form", "util-form");
      form.id = "utilMeetingForm";
      const fields = [
        ["title", "회의명", "text", true],
        ["when", "회의 일시", "datetime-local", false],
        ["attendees", "참석자", "text", false],
        ["content", "회의 내용", "textarea", true],
      ];
      fields.forEach(([name, label, type, req]) => {
        const l = el("label", null, label + " ");
        if (type === "textarea") {
          const ta = document.createElement("textarea");
          ta.name = name; ta.rows = (name === "content" ? 6 : 2);
          if (req) ta.required = true;
          l.appendChild(ta);
        } else {
          const inp = document.createElement("input");
          inp.name = name; inp.type = type;
          if (req) inp.required = true;
          l.appendChild(inp);
        }
        form.appendChild(l);
      });
      // #5727: the form owns 생성+저장; the result area keeps 복사+다운로드 only.
      const formActions = el("div", "util-form-actions");
      const submitBtn = el("button", "util-generate", "요약 생성");
      submitBtn.type = "submit";
      const formSaveB = el("button", "util-save", "저장");
      formSaveB.type = "button"; formSaveB.id = "utilMeetingSave";
      formActions.append(submitBtn, formSaveB);
      // #5783: the save status lives in the form, above the two buttons — the
      // same place the 409 ask appears.
      const meetingSaveState = saveStatusLine("utilMeetingSaveState");
      // Same order constraint as the SNS builder: append first, then insert
      // the status line above the action row.
      form.appendChild(formActions);
      form.insertBefore(meetingSaveState, formActions);

      const result = el("div", "util-result");
      result.id = "utilMeetingResult";
      result.hidden = true;
      const h3 = el("h3", null, "회의 요약");
      const output = document.createElement("textarea");
      output.id = "utilMeetingOutput";
      output.rows = 12;
      // #6199: the stored record currently in the editor, if any, plus the
      // line that states the save will ask about its name — the same component
      // and wording the speech and SNS tabs use.
      let meetingEditing = null;
      const meetingEditState = el("p", "util-edit-state");
      meetingEditState.id = "utilMeetingEditState";
      meetingEditState.hidden = true;
      function setMeetingEditing(target) {
        meetingEditing = target;
        meetingEditState.hidden = !target;
        meetingEditState.textContent = target ? editingStateText(target) : "";
      }
      const actions = el("div", "util-actions");
      const copyB = el("button", null, "복사"); copyB.type = "button"; copyB.id = "utilMeetingCopy";
      const dlB = el("button", null, "TXT 다운로드"); dlB.type = "button"; dlB.id = "utilMeetingDownload";
      const meetingRetry = retryButton("utilMeetingRetry", () => { void gen(); });
      actions.append(copyB, dlB, meetingRetry);
      result.append(h3, meetingEditState, output, actions);

      const archive = el("div", "util-archive");
      archive.id = "utilMeetingArchive";
      const archiveH = el("h3", null, "활동 기록");
      const archiveEmpty = el("p", "util-empty", "저장된 회의 기록이 없습니다.");
      archive.append(archiveH, archiveEmpty);

      panel.replaceChildren(form, result, archive);

      async function gen() {
        const d = new FormData(form);
        const title = (d.get("title") || "").trim();
        const when = (d.get("when") || "").trim();
        const attendees = (d.get("attendees") || "").trim();
        const content = (d.get("content") || "").trim();
        // A fresh generation is no longer an edit of the stored record.
        setMeetingEditing(null);
        let prompt = "다음 회의 내용을 정리해 주세요.\n\n";
        prompt += `회의명: ${title}\n`;
        if (when) prompt += `회의 일시: ${when}\n`;
        if (attendees) prompt += `참석자: ${attendees}\n`;
        prompt += `회의 내용:\n${content}\n\n`;
        prompt += "다음 항목으로 정리해 주세요:\n1. 회의 요약 (3-5문장)\n2. 주요 논의사항 (bullet)\n3. 결정사항 (bullet)\n4. 후속 업무 (담당자/일정이 원문에 있으면 포함)\n5. 미해결 사항";
        result.hidden = false;
        output.value = "생성 중...";
        try { output.value = await apiChat(prompt, "meeting"); }
        catch (e) { showGenerationFailure(output, meetingRetry, e); }
      }
      form.addEventListener("submit", (e) => { e.preventDefault(); gen(); });
      copyB.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(output.value); copyB.textContent = "복사됨"; setTimeout(() => { copyB.textContent = "복사"; }, 1500); } catch (_) {}
      });
      async function runMeetingSave() {
        const text = output.value.trim();
        if (!text) return;
        hideSaveStatus(meetingSaveState);
        if (!currentPid) {
          const ensured = await ensureProjectForSave();
          if (!ensured.pid) { showSaveStatus(meetingSaveState, { status: ensured.status }, runMeetingSave); return; }
          currentPid = ensured.pid;
        }
        // #6199: an edited stored record saves under its own name and kind, so
        // the existing 409 asks 새 이름/덮어쓰기 instead of stacking a row.
        const editing = meetingEditing;
        const name = editing ? editing.name : (form.querySelector("[name=title]")?.value || "회의").trim() + ".txt";
        const kind = editing && editing.kind ? editing.kind : "meeting";
        const outcome = await saveUtilText({ pid: currentPid, name: name, text: text, kind: kind, anchor: formSaveB });
        if (outcome.file) {
          formSaveB.textContent = "저장됨";
          setTimeout(() => { formSaveB.textContent = "저장"; }, 1500);
          setMeetingEditing(null);
          hideSaveStatus(meetingSaveState);
          await refreshArchive(archive);
        } else if (outcome.failure) {
          showSaveStatus(meetingSaveState, outcome.failure, runMeetingSave);
        }
        // outcome.none: the 409 ask is on screen and owns the next move.
      }
      formSaveB.addEventListener("click", () => runMeetingSave());
      dlB.addEventListener("click", () => { downloadText(output.value, "meeting.txt"); });

      // #6199: [고쳐 쓰기] puts a stored record back into the SAME draft
      // editor — no second editor, no second store — so the owner can change
      // it and save. Same component and wording as the speech and SNS tabs.
      async function openMeetingForEdit(file) {
        if (!currentPid) currentPid = await ensureProject();
        if (!currentPid) { alert("프로젝트를 찾을 수 없습니다."); return; }
        const stored = await readStoredBody(currentPid, file.id);
        if (!stored.ok) { alert(storedOpenFailureText("저장된 회의 기록", stored)); return; }
        setMeetingEditing({ id: file.id, name: file.name, kind: file.doc_kind || "meeting" });
        result.hidden = false;
        output.value = stored.text;
        output.focus();
      }

      async function refreshArchive(arc) {
        if (!currentPid) currentPid = await ensureProject();
        if (!currentPid) return;
        const files = await listProjectFiles(currentPid);
        // #5731: this list reads this tool's own records (kind = meeting) and
        // the rows saved before the kind existed (기타). Another tool's writing
        // no longer appears here, and a version row is not a record.
        const current = files.filter((f) => !f.doc_version_of);
        const meetingFiles = current.filter((f) => (f.doc_kind === "meeting")
          || (!f.doc_kind && (f.name || "").endsWith(".txt")
              && !(f.name || "").startsWith(BOOK_PREFIX)));
        // #5608: activity books surface in their own section, never as raw
        // records — by kind now, with the name rule kept for older rows.
        const bookFiles = current.filter((f) => (f.doc_kind === "book")
          || (!f.doc_kind && (f.name || "").startsWith(BOOK_PREFIX)));
        arc.replaceChildren();
        const h = el("h3", null, "활동 기록");
        arc.appendChild(h);
        if (!meetingFiles.length && !bookFiles.length) {
          const p = el("p", "util-empty", "저장된 회의 기록이 없습니다.");
          arc.appendChild(p);
          return;
        }
        const bookBtn = el("button", "util-generate", "선택 기록으로 책/활동집 초안 생성");
        bookBtn.type = "button";
        bookBtn.id = "utilBookGenerate";
        bookBtn.style.marginBottom = "8px";
        if (meetingFiles.length) {
          arc.appendChild(bookBtn);
        } else {
          // #5731: a project that only holds stored books still opens them —
          // the book section below is not behind a meeting record any more.
          arc.appendChild(el("p", "util-empty", "저장된 회의 기록이 없습니다."));
        }

        // #5608: the record order here is the book order. The up/down moves
        // re-arrange this list itself, so what the user sees is exactly the
        // sequence the book builder reads.
        let order = meetingFiles.slice();
        const ul = document.createElement("ul");
        function renderRows() {
          ul.replaceChildren();
          order.forEach((f, index) => {
            const li = document.createElement("li");
            li.style.display = "flex";
            li.style.alignItems = "center";
            li.style.gap = "8px";
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = f.id;
            cb.className = "util-book-check";
            cb.setAttribute("aria-label", f.name + " 책/활동집에 포함");
            li.appendChild(cb);
            const btn = document.createElement("button");
            btn.type = "button";
            // #6199: the row leads with the action — a stored record reopens
            // in the editable draft instead of only being displayed.
            btn.className = "util-edit-stored";
            btn.dataset.fileId = f.id;
            btn.textContent = "고쳐 쓰기: " + f.name + " (" + (f.content_chars || 0) + "자)";
            btn.style.flex = "1";
            btn.addEventListener("click", async () => { await openMeetingForEdit(f); });
            li.appendChild(btn);
            const up = document.createElement("button");
            up.type = "button";
            up.className = "util-record-move";
            up.dataset.move = "-1";
            up.dataset.fileName = f.name;
            up.textContent = "↑";
            up.disabled = index === 0;
            up.addEventListener("click", () => {
              const to = index - 1;
              if (to < 0) return;
              const [moved] = order.splice(index, 1);
              order.splice(to, 0, moved);
              renderRows();
            });
            const down = document.createElement("button");
            down.type = "button";
            down.className = "util-record-move";
            down.dataset.move = "1";
            down.dataset.fileName = f.name;
            down.textContent = "↓";
            down.disabled = index === order.length - 1;
            down.addEventListener("click", () => {
              const to = index + 1;
              if (to >= order.length) return;
              const [moved] = order.splice(index, 1);
              order.splice(to, 0, moved);
              renderRows();
            });
            li.appendChild(up);
            li.appendChild(down);
            ul.appendChild(li);
          });
        }
        renderRows();
        arc.appendChild(ul);

        const bookResult = el("div", "util-result");
        bookResult.id = "utilBookResult";
        bookResult.hidden = true;
        const bookH = el("h3", null, "책/활동집 초안");
        const bookOutput = document.createElement("textarea");
        bookOutput.id = "utilBookOutput";
        bookOutput.rows = 16;
        // #5727: result actions are copy/download only; regenerating the
        // book draft is re-pressing the generate button in the selection area.
        const bookRetry = retryButton("utilBookRetry", () => bookBtn.click());
        const bookActions = el("div", "util-actions");
        const bookCopy = el("button", null, "복사"); bookCopy.type = "button";
        const bookDl = el("button", null, "TXT 다운로드"); bookDl.type = "button";
        // #5608: the book draft is a product, not scratch — it persists
        // through the same project-file channel under its own name rule, so
        // re-entering the tool restores and re-edits it.
        const bookSave = el("button", "util-save", "활동집 저장"); bookSave.type = "button"; bookSave.id = "utilBookSave";
        bookActions.append(bookCopy, bookDl, bookSave, bookRetry);
        // #5783: the book's save status sits between the draft and the actions,
        // rebuilt with this section on every refresh.
        const bookSaveState = saveStatusLine("utilBookSaveState");
        bookResult.append(bookH, bookOutput, bookSaveState, bookActions);
        arc.appendChild(bookResult);

        bookBtn.addEventListener("click", async () => {
          const checked = Array.from(document.querySelectorAll(".util-book-check:checked"));
          if (!checked.length) { alert("선택된 기록이 없습니다."); return; }
          // #5608: the book reads the records in the order the list shows —
          // the same sequence the up/down moves arrange. Only the checked
          // records enter the prompt: nothing unselected can bleed in.
          const checkedIds = new Set(checked.map((cb) => cb.value));
          const ordered = order.filter((f) => checkedIds.has(f.id));
          bookResult.hidden = false;
          bookOutput.value = "선택한 회의 기록을 불러오는 중...";
          try {
            const contents = [];
            for (const file of ordered) {
              const res = await fetch("/api/projects/" + encodeURIComponent(currentPid) + "/files/" + encodeURIComponent(file.id), { credentials: "include" });
              if (!res.ok) throw new Error("선택한 회의 기록을 불러오지 못했습니다: " + file.name);
              const data = await res.json();
              if (!data || !data.file || typeof data.file.content !== "string" || !data.file.content.trim()) {
                throw new Error("선택한 회의 기록의 본문이 비어 있거나 올바르지 않습니다: " + file.name);
              }
              contents.push("[기록: " + data.file.name + "]\n" + data.file.content);
            }
            let prompt = "다음은 사용자가 선택한 활동 기록 본문입니다. 각 기록의 이름을 출처로 유지하세요.\n\n";
            prompt += contents.join("\n\n") + "\n\n";
            prompt += "위 기록을 바탕으로 다음을 생성해 주세요:\n";
            prompt += "1. 책/활동집 제목 후보 3개\n";
            prompt += "2. 목차 (5-8장)\n";
            prompt += "3. 각 장별 원고 초안 (200-400자)\n";
            prompt += "4. 마무리 인사\n\n";
            prompt += "주의: 원본 기록에 없는 사건, 날짜, 발언을 사실처럼 추가하지 마세요. 근거가 있는 내용과 제안/해석을 구분하세요. 각 장 끝에 근거가 된 기록 파일명을 표시하세요.";
            bookOutput.value = "생성 중...";
            bookOutput.value = await apiChat(prompt, "meeting");
          } catch (e) {
            showGenerationFailure(bookOutput, bookRetry, e);
          }
        });

        bookCopy.addEventListener("click", async () => {
          try { await navigator.clipboard.writeText(bookOutput.value); bookCopy.textContent = "복사됨"; setTimeout(() => { bookCopy.textContent = "복사"; }, 1500); } catch (_) {}
        });
        bookDl.addEventListener("click", () => { downloadText(bookOutput.value, "book-draft.txt"); });

        // #5608: saving the book uses its own name rule so books never mix
        // with meeting records in the list — the book section reads only
        // names starting with BOOK_PREFIX. The title comes from the draft's
        // first line (what the user edited); fallback keeps a safe name.
        async function runBookSave() {
          const text = bookOutput.value.trim();
          if (!text) return;
          hideSaveStatus(bookSaveState);
          if (!currentPid) {
            const ensured = await ensureProjectForSave();
            if (!ensured.pid) { showSaveStatus(bookSaveState, { status: ensured.status }, runBookSave); return; }
            currentPid = ensured.pid;
          }
          const firstLine = text.split("\n", 1)[0].replace(/^[0-9]+\.\s*/, "").trim();
          const safe = firstLine.replace(/[\\/:*?"<>|]/g, "").replace(/\.*$/, "").slice(0, 40).trim();
          const name = BOOK_PREFIX + (safe || "제목 미정") + ".txt";
          const outcome = await saveUtilText({ pid: currentPid, name: name, text: text, kind: "book", anchor: bookSave });
          if (outcome.file) {
            bookSave.textContent = "저장됨";
            setTimeout(() => { bookSave.textContent = "활동집 저장"; }, 1500);
            hideSaveStatus(bookSaveState);
            await refreshArchive(arc);
          } else if (outcome.failure) {
            showSaveStatus(bookSaveState, outcome.failure, runBookSave);
          }
          // outcome.none: the 409 ask is on screen and owns the next move.
        }
        bookSave.addEventListener("click", () => runBookSave());

        // Stored books reopen into the editor for editing and re-saving.
        if (bookFiles.length) {
          const bookSec = el("div", null);
          const bookSecH = el("h3", null, "저장된 활동집");
          bookSec.appendChild(bookSecH);
          const bookUl = document.createElement("ul");
          bookFiles.forEach((f) => {
            const li = document.createElement("li");
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "util-book-open";
            btn.textContent = f.name + " (" + (f.content_chars || 0) + "자)";
            btn.addEventListener("click", async () => {
              const res = await fetch("/api/projects/" + encodeURIComponent(currentPid) + "/files/" + encodeURIComponent(f.id), { credentials: "include" });
              if (res.ok) {
                const data = await res.json();
                const content = data && data.file && (data.file.content || data.file.text);
                if (typeof content === "string") {
                  bookOutput.value = content;
                  bookResult.hidden = false;
                } else {
                  alert("저장된 활동집의 본문을 읽을 수 없습니다.");
                }
              } else {
                alert("저장된 활동집을 열지 못했습니다.");
              }
            });
            li.appendChild(btn);
            bookUl.appendChild(li);
          });
          bookSec.appendChild(bookUl);
          arc.appendChild(bookSec);
        }
      }
      refreshArchive(archive);
      panel.dataset.loaded = "1";
    }
  });
})();
