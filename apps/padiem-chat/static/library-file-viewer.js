(() => {
  "use strict";

  // #7782 — the Library row opens its stored content read-only, and the row's
  // project action lands on that project's file list instead of the settings
  // dialog. This module is the ONE seam for both: library.js still never
  // fetches file bytes itself, it only hands a row over here.
  //
  // Scope contract (do not widen):
  //   - Reads only the canonical owner-scoped routes this service already
  //     publishes: `GET /api/projects/{pid}/files` (list) and
  //     `GET /api/projects/{pid}/files/{fid}` (content). Downloads reuse
  //     `GET /api/projects/{pid}/files/{fid}/original` for the kinds the
  //     server serves there. No second store, no new route, no indexing.
  //   - Read-only: nothing here edits, overwrites or deletes. The project
  //     settings dialog keeps every edit guard; this viewer grants none.
  //   - Every read is same-origin, no-store, and owner-scoped by the session
  //     cookie; a foreign or stale id gets the server's own refusal and an
  //     honest sentence — never fabricated content.
  //   - Formats: stored text documents (plain/Markdown/CSV/JSON/HTML) and
  //     util-generated documents show their stored text as text. Images show
  //     the stored original. Extracted PDF/DOCX/HWPX show the extracted text
  //     and offer the original for download. Anything else says so instead of
  //     pretending to render. Stored text is shown as text — no Markdown or
  //     HTML rendering, so nothing stored can become markup here.
  //   - Dialogs are created in this module, so index.html gains no markup and
  //     app.js gains no logic.

  const TEXT_MEDIA = new Set([
    "text/plain", "text/markdown", "text/csv", "application/json", "text/html",
  ]);
  const IMAGE_MEDIA = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);
  const EXTRACTED_MEDIA = new Set(["extracted/pdf", "extracted/docx", "extracted/hwpx"]);

  const TYPE_LABELS = {
    "application/pdf": "PDF",
    "text/plain": "텍스트",
    "text/markdown": "Markdown",
    "text/csv": "CSV",
    "text/html": "HTML",
    "application/json": "JSON",
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/gif": "GIF",
    "image/webp": "WebP",
  };
  const EXTRACTED_LABELS = {
    "extracted/pdf": "PDF",
    "extracted/docx": "Word",
    "extracted/hwpx": "한글 문서",
  };

  function copy(ko, en) {
    return document.documentElement.lang.toLowerCase().startsWith("en") ? en : ko;
  }

  const TEXT = {
    viewTitle: () => copy("저장한 글 보기", "Saved document"),
    close: () => copy("닫기", "Close"),
    copyButton: () => copy("복사", "Copy"),
    copied: () => copy("복사했습니다.", "Copied."),
    copyFailed: () => copy("복사하지 못했습니다. 직접 선택해 주세요.", "Could not copy. Please select it yourself."),
    downloadButton: () => copy("내려받기", "Download"),
    downloadOriginal: (kind) => copy(`원본 (${kind}) 내려받기`, `Download original (${kind})`),
    listTitle: (name) => copy(`프로젝트 ${name} — 파일`, `Project ${name} — files`),
    listLoading: () => copy("불러오는 중…", "Loading…"),
    listEmpty: () => copy("이 프로젝트에는 저장된 파일이 없습니다.", "No stored files in this project."),
    listFailed: () => copy("파일 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.", "Could not load the file list. Please try again shortly."),
    fileLoading: () => copy("불러오는 중…", "Loading…"),
    fileFailed: () => copy("지금 이 파일을 열 수 없습니다. 잠시 후 다시 시도해 주세요.", "This file cannot be opened right now. Please try again shortly."),
    fileGone: () => copy("파일을 찾을 수 없습니다. 목록을 새로 불러 주세요.", "The file could not be found. Please reload the list."),
    fileLogin: () => copy("파일을 열려면 로그인하세요.", "Sign in to open the file."),
    unsupported: () => copy("이 형식은 화면에서 볼 수 없습니다.", "This format cannot be shown here."),
    openFailed: () => copy("지금 열 수 없습니다. 잠시 후 다시 시도해 주세요.", "Cannot open right now. Please try again shortly."),
    chars: (n) => copy(`${n.toLocaleString()}자`, `${n.toLocaleString()} characters`),
    bytesNote: () => copy(
      "원본은 서버에 저장된 그대로 내려받아집니다.",
      "The original downloads exactly as stored on the server.",
    ),
  };

  function typeLabel(mediaType) {
    const raw = String(mediaType || "");
    if (Object.prototype.hasOwnProperty.call(EXTRACTED_LABELS, raw)) return EXTRACTED_LABELS[raw];
    if (Object.prototype.hasOwnProperty.call(TYPE_LABELS, raw)) return TYPE_LABELS[raw];
    if (IMAGE_MEDIA.has(raw)) return raw.replace("image/", "").toUpperCase();
    return raw;
  }

  function metaLine(file) {
    const type = typeLabel(file.media_type);
    const chars = Number(file.content_chars) || 0;
    if (!type) return TEXT.chars(chars);
    return copy(`${type} · ${TEXT.chars(chars)}`, `${type} · ${TEXT.chars(chars)}`);
  }

  function fileUrl(file) {
    return `/api/projects/${encodeURIComponent(file.project_id)}/files/${encodeURIComponent(file.id)}`;
  }

  function originalUrl(file) {
    return `${fileUrl(file)}/original`;
  }

  function normalizedFile(row, projectName) {
    return {
      id: String(row.id || ""),
      project_id: String(row.project_id || ""),
      name: typeof row.name === "string" ? row.name : "",
      media_type: typeof row.media_type === "string" ? row.media_type : "",
      content_chars: Number(row.content_chars) || 0,
      project_name: typeof row.project_name === "string" && row.project_name
        ? row.project_name
        : (projectName || ""),
      doc_kind: typeof row.doc_kind === "string" ? row.doc_kind : "",
    };
  }

  let fileDialog = null;
  let listDialog = null;
  let lastFocused = null;

  function buildDialog(className) {
    const dialog = document.createElement("dialog");
    dialog.className = className;
    dialog.setAttribute("aria-modal", "true");
    const head = document.createElement("div");
    head.className = "library-dialog-head";
    const heading = document.createElement("div");
    heading.className = "library-dialog-heading";
    const title = document.createElement("p");
    title.className = "library-dialog-title";
    const meta = document.createElement("p");
    meta.className = "library-dialog-meta";
    heading.appendChild(title);
    heading.appendChild(meta);
    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "library-dialog-close";
    closeButton.textContent = "✕";
    closeButton.setAttribute("aria-label", TEXT.close());
    head.appendChild(heading);
    head.appendChild(closeButton);
    const note = document.createElement("p");
    note.className = "library-dialog-note";
    note.hidden = true;
    const body = document.createElement("div");
    body.className = "library-dialog-body";
    const actions = document.createElement("div");
    actions.className = "library-dialog-actions";
    dialog.appendChild(head);
    dialog.appendChild(note);
    dialog.appendChild(body);
    dialog.appendChild(actions);
    closeButton.addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => {
      if (lastFocused && typeof lastFocused.focus === "function") lastFocused.focus();
      lastFocused = null;
    });
    document.body.appendChild(dialog);
    return { dialog, title, meta, note, body, actions };
  }

  function setNote(pane, text) {
    pane.note.textContent = text || "";
    pane.note.hidden = !text;
  }

  function clearActions(pane) {
    pane.actions.replaceChildren();
  }

  function actionButton(pane, label, run) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "library-dialog-button";
    button.textContent = label;
    button.addEventListener("click", run);
    pane.actions.appendChild(button);
    return button;
  }

  function show(pane) {
    lastFocused = document.activeElement;
    if (typeof pane.dialog.showModal === "function") pane.dialog.showModal();
    else pane.dialog.setAttribute("open", "");
  }

  function openFile(file) {
    if (!fileDialog) fileDialog = buildDialog("library-file-dialog");
    const pane = fileDialog;
    pane.title.textContent = file.name || TEXT.viewTitle();
    pane.meta.textContent = [file.project_name ? copy(`프로젝트 ${file.project_name}`, `Project ${file.project_name}`) : "", metaLine(file)]
      .filter(Boolean).join(" · ");
    pane.body.replaceChildren();
    clearActions(pane);
    setNote(pane, TEXT.fileLoading());
    show(pane);

    fetch(fileUrl(file), {
      headers: { "Accept": "application/json" },
      credentials: "same-origin",
      cache: "no-store",
    }).then((response) => {
      if (response.status === 401) throw { kind: "login" };
      if (response.status === 404) throw { kind: "gone" };
      return response.json().catch(() => null).then((data) => {
        if (!response.ok || !data || !data.file) throw { kind: "failed" };
        return data.file;
      });
    }).then((record) => {
      if (!pane.dialog.open) return;
      renderFile(pane, file, record);
    }).catch((reason) => {
      if (!pane.dialog.open) return;
      pane.body.replaceChildren();
      clearActions(pane);
      const kind = reason && typeof reason === "object" ? reason.kind : "failed";
      setNote(pane, kind === "login" ? TEXT.fileLogin()
        : kind === "gone" ? TEXT.fileGone()
        : TEXT.fileFailed());
    });
  }

  function renderFile(pane, file, record) {
    setNote(pane, "");
    const mediaType = String(record.media_type || file.media_type || "");
    const content = typeof record.content === "string" ? record.content : "";
    const shown = {
      id: String(record.id || file.id),
      project_id: String(record.project_id || file.project_id),
      name: typeof record.name === "string" && record.name ? record.name : file.name,
      media_type: mediaType,
      content_chars: Number(record.content_chars) || content.length,
    };

    if (IMAGE_MEDIA.has(mediaType)) {
      const image = document.createElement("img");
      image.className = "library-viewer-image";
      image.alt = shown.name;
      image.src = originalUrl(shown);
      pane.body.appendChild(image);
      const anchor = document.createElement("a");
      anchor.className = "library-dialog-button";
      anchor.href = originalUrl(shown);
      anchor.setAttribute("download", shown.name || "image");
      anchor.textContent = TEXT.downloadButton();
      pane.actions.appendChild(anchor);
      return;
    }

    if (EXTRACTED_MEDIA.has(mediaType)) {
      if (content) {
        const pre = document.createElement("div");
        pre.className = "library-viewer-text";
        pre.textContent = content;
        pane.body.appendChild(pre);
        actionButton(pane, TEXT.copyButton(), () => copyText(pane, content));
      } else {
        setNote(pane, TEXT.unsupported());
      }
      const kind = typeLabel(mediaType);
      const anchor = document.createElement("a");
      anchor.className = "library-dialog-button";
      anchor.href = originalUrl(shown);
      anchor.setAttribute("download", shown.name || "document");
      anchor.textContent = TEXT.downloadOriginal(kind);
      pane.actions.appendChild(anchor);
      const hint = document.createElement("p");
      hint.className = "library-dialog-hint";
      hint.textContent = TEXT.bytesNote();
      pane.actions.appendChild(hint);
      return;
    }

    if (TEXT_MEDIA.has(mediaType) && content) {
      const pre = document.createElement("div");
      pre.className = "library-viewer-text";
      pre.textContent = content;
      pane.body.appendChild(pre);
      actionButton(pane, TEXT.copyButton(), () => copyText(pane, content));
      actionButton(pane, TEXT.downloadButton(), () => downloadText(shown, content));
      return;
    }

    setNote(pane, TEXT.unsupported());
  }

  function copyText(pane, content) {
    const api = window.PadiemAnswerCopy;
    const finish = (done) => setNote(pane, done ? TEXT.copied() : TEXT.copyFailed());
    if (api && typeof api.copyText === "function") {
      Promise.resolve(api.copyText(content)).then(finish, () => finish(false));
      return;
    }
    finish(false);
  }

  function downloadText(file, content) {
    const blob = new Blob([content], { type: `${file.media_type || "text/plain"};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.setAttribute("download", file.name || "document.txt");
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function openProjectFiles(projectId, projectName) {
    if (!listDialog) listDialog = buildDialog("library-files-dialog");
    const pane = listDialog;
    const label = projectName || copy("프로젝트", "Project");
    pane.title.textContent = TEXT.listTitle(label);
    pane.meta.textContent = "";
    pane.body.replaceChildren();
    clearActions(pane);
    setNote(pane, TEXT.listLoading());
    show(pane);

    fetch(`/api/projects/${encodeURIComponent(projectId)}/files`, {
      headers: { "Accept": "application/json" },
      credentials: "same-origin",
      cache: "no-store",
    }).then(async (response) => {
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !Array.isArray(data.files)) throw new Error("unavailable");
      return data.files;
    }).then((files) => {
      if (!pane.dialog.open) return;
      setNote(pane, "");
      pane.body.replaceChildren();
      if (!files.length) {
        setNote(pane, TEXT.listEmpty());
        return;
      }
      const list = document.createElement("div");
      list.className = "library-file-list";
      list.setAttribute("role", "list");
      for (const row of files) {
        if (!row || typeof row.id !== "string") continue;
        const file = normalizedFile(row, projectName);
        const item = document.createElement("button");
        item.type = "button";
        item.className = "library-item";
        item.setAttribute("role", "listitem");
        const text = document.createElement("span");
        text.className = "library-item-text";
        const title = document.createElement("span");
        title.className = "library-item-title";
        title.textContent = file.name;
        const meta = document.createElement("span");
        meta.className = "library-item-meta";
        meta.textContent = metaLine(file);
        text.appendChild(title);
        text.appendChild(meta);
        item.appendChild(text);
        item.addEventListener("click", () => openFile(file));
        list.appendChild(item);
      }
      pane.body.appendChild(list);
    }).catch(() => {
      if (!pane.dialog.open) return;
      pane.body.replaceChildren();
      clearActions(pane);
      setNote(pane, TEXT.listFailed());
    });
  }

  window.PadiemChatLibraryFiles = Object.freeze({
    openFile,
    openProjectFiles,
    isFileOpen: () => Boolean(fileDialog && fileDialog.dialog.open),
    isProjectOpen: () => Boolean(listDialog && listDialog.dialog.open),
  });
})();
