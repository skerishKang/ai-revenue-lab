(() => {
  "use strict";

  const MAX_BINARY_BYTES = 2 * 1024 * 1024;
  const MIME_BY_EXTENSION = new Map([
    [".pdf", "application/pdf"],
    [".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
    [".pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"],
    [".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
  ]);
  const ACCEPT_BINARY = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
  ].join(",");

  const fileInput = document.getElementById("attachmentFileInput");
  const form = document.getElementById("composerForm");
  const tray = document.getElementById("attachmentTray");
  const thumb = document.getElementById("attachmentThumb");
  const kind = document.getElementById("attachmentKind");
  const nameNode = document.getElementById("attachmentName");
  const sizeNode = document.getElementById("attachmentSize");
  const removeButton = document.getElementById("removeAttachment");
  const newChatButton = document.getElementById("newChatButton");
  const runtimeNote = document.getElementById("runtimeNote");
  const attachmentButton = document.getElementById("attachmentButton");
  const documentStarter = document.getElementById("documentStarterButton");
  const messageList = document.getElementById("messageList");

  if (!fileInput || !form || !tray || !kind || !nameNode || !sizeNode || !removeButton || !runtimeNote) return;

  const nativeFetch = window.fetch.bind(window);
  let pending = null;
  let pendingTruthLabel = null;

  function extensionOf(name) {
    const lower = String(name || "").toLowerCase();
    const index = lower.lastIndexOf(".");
    return index >= 0 ? lower.slice(index) : "";
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function canonicalMediaType(file) {
    const expected = MIME_BY_EXTENSION.get(extensionOf(file && file.name));
    if (!expected) return null;
    if (file.type && file.type !== expected) {
      throw new Error("문서 확장자와 파일 형식이 일치하지 않습니다.");
    }
    return expected;
  }

  function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    const chunkSize = 0x8000;
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += chunkSize) {
      binary += String.fromCharCode(...bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length)));
    }
    return btoa(binary);
  }

  async function readBinary(file, mediaType) {
    if (!file || file.size < 1) throw new Error("빈 문서는 첨부할 수 없습니다.");
    if (file.size > MAX_BINARY_BYTES) throw new Error("PDF·Office 문서는 2 MiB 이하만 첨부할 수 있습니다.");
    const buffer = await file.arrayBuffer();
    if (buffer.byteLength !== file.size || buffer.byteLength < 1 || buffer.byteLength > MAX_BINARY_BYTES) {
      throw new Error("문서 크기를 안전하게 확인하지 못했습니다.");
    }
    const base64 = arrayBufferToBase64(buffer);
    if (!base64) throw new Error("문서 데이터가 비어 있습니다.");
    return {
      type: "document",
      name: file.name || `document${extensionOf(file.name)}`,
      mediaType,
      base64,
      byteSize: buffer.byteLength,
    };
  }

  function setError(message) {
    runtimeNote.textContent = message;
    runtimeNote.dataset.state = "error";
  }

  function renderPending(value) {
    if (thumb) {
      thumb.removeAttribute("src");
      thumb.hidden = true;
    }
    kind.hidden = false;
    kind.textContent = extensionOf(value.name).replace(".", "").toUpperCase() || "DOC";
    nameNode.textContent = value.name;
    sizeNode.textContent = formatBytes(value.byteSize);
    tray.hidden = false;
    runtimeNote.textContent = "선택한 문서는 이 질문의 참고 자료로만 사용되며 파일 내용은 대화 기록에 저장되지 않습니다.";
    runtimeNote.dataset.state = "normal";
  }

  function clearPending() {
    pending = null;
  }

  function applySupportedCopy() {
    const existing = (fileInput.getAttribute("accept") || "").split(",").filter(Boolean);
    const additions = ACCEPT_BINARY.split(",");
    fileInput.setAttribute("accept", Array.from(new Set(existing.concat(additions))).join(","));
    if (attachmentButton) attachmentButton.title = "사진 또는 TXT, Markdown, CSV, JSON, PDF, DOCX, PPTX, XLSX 문서 한 개를 첨부합니다";
    const small = documentStarter && documentStarter.querySelector("small");
    if (small) small.textContent = "TXT·Markdown·CSV·JSON·PDF·DOCX·PPTX·XLSX";
    runtimeNote.textContent = "사진과 TXT·Markdown·CSV·JSON·PDF·DOCX·PPTX·XLSX 문서 한 개를 첨부할 수 있습니다.";
    runtimeNote.dataset.state = "normal";
  }

  function isChatStreamRequest(input) {
    const raw = input instanceof Request ? input.url : String(input || "");
    try {
      const url = new URL(raw, window.location.href);
      return url.origin === window.location.origin && url.pathname === "/api/chat/stream";
    } catch (_) {
      return false;
    }
  }

  function completedChatUrl(input) {
    const raw = input instanceof Request ? input.url : String(input || "");
    const url = new URL(raw, window.location.href);
    url.pathname = "/api/chat";
    return url.toString();
  }

  function jsonError(message, status = 502) {
    return new Response(JSON.stringify({ error: { code: "binary_document_bridge_error", message } }), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  function truthLabel(data) {
    const runtimeLabel = data.runtime === "mock" ? "모의 응답 · 실제 모델 호출 없음" : "AI 응답";
    const skillTitle = data.skill && data.skill.id !== "auto" && typeof data.skill.title === "string" ? data.skill.title : "";
    return skillTitle ? `${runtimeLabel} · ${skillTitle}` : runtimeLabel;
  }

  function toSseResponse(data) {
    const done = { done: true };
    ["conversation_id", "project_id", "project", "project_files_used"].forEach((key) => {
      if (data[key] !== undefined) done[key] = data[key];
    });
    const frames = [
      `event: delta\ndata: ${JSON.stringify({ delta: data.answer })}\n\n`,
      `event: done\ndata: ${JSON.stringify(done)}\n\n`,
    ];
    return new Response(frames.join(""), {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-store",
      },
    });
  }

  if (messageList) {
    const truthObserver = new MutationObserver(() => {
      if (!pendingTruthLabel) return;
      const assistants = messageList.querySelectorAll(".assistant-message");
      const assistant = assistants[assistants.length - 1];
      if (!assistant || assistant.querySelector(".typing") || !assistant.querySelector(".assistant-content p")) return;
      const label = assistant.querySelector("[data-runtime-label]");
      if (!label) return;
      label.textContent = pendingTruthLabel;
      pendingTruthLabel = null;
    });
    truthObserver.observe(messageList, { childList: true, subtree: true });
  }

  window.fetch = async function padiemDocumentAwareFetch(input, init) {
    if (!pending || !isChatStreamRequest(input) || !init || typeof init.body !== "string") {
      return nativeFetch(input, init);
    }

    let payload;
    try {
      payload = JSON.parse(init.body);
    } catch (_) {
      return nativeFetch(input, init);
    }
    if (!payload || typeof payload !== "object" || payload.attachments !== undefined) {
      return nativeFetch(input, init);
    }

    const snapshot = pending;
    payload.attachments = [{
      type: "document",
      name: snapshot.name,
      media_type: snapshot.mediaType,
      base64: snapshot.base64,
    }];
    const headers = new Headers(init.headers || {});
    headers.set("Content-Type", "application/json");
    headers.set("Accept", "application/json");

    const response = await nativeFetch(completedChatUrl(input), { ...init, headers, body: JSON.stringify(payload) });
    if (!response.ok) return response;

    const data = await response.json().catch(() => null);
    if (!data || typeof data.answer !== "string" || !data.answer) {
      return jsonError("AI 응답 형식을 확인하지 못했습니다.");
    }
    pendingTruthLabel = truthLabel(data);
    if (pending === snapshot) clearPending();
    return toSseResponse(data);
  };

  fileInput.addEventListener("change", async (event) => {
    const [file] = fileInput.files || [];
    if (!file) return;

    let mediaType;
    try {
      mediaType = canonicalMediaType(file);
    } catch (error) {
      event.stopImmediatePropagation();
      clearPending();
      fileInput.value = "";
      setError(error instanceof Error ? error.message : "문서 형식을 확인하지 못했습니다.");
      return;
    }
    if (!mediaType) {
      clearPending();
      return;
    }

    event.stopImmediatePropagation();
    try {
      // Clear any app.js-owned image/text attachment before taking ownership of this binary one.
      removeButton.click();
      const next = await readBinary(file, mediaType);
      pending = next;
      renderPending(next);
    } catch (error) {
      clearPending();
      fileInput.value = "";
      setError(error instanceof Error ? error.message : "문서를 읽지 못했습니다.");
    }
  }, true);

  form.addEventListener("submit", () => {
    if (!pending || !messageList) return;
    const snapshot = { name: pending.name, byteSize: pending.byteSize };
    queueMicrotask(() => {
      const bubbles = messageList.querySelectorAll(".user-message .message-bubble");
      const bubble = bubbles[bubbles.length - 1];
      if (!bubble || bubble.querySelector(".message-attachment-meta")) return;
      const meta = document.createElement("span");
      meta.className = "message-attachment-meta";
      meta.textContent = `문서 · ${snapshot.name} · ${formatBytes(snapshot.byteSize)}`;
      bubble.appendChild(meta);
    });
  }, true);

  removeButton.addEventListener("click", clearPending, true);
  if (newChatButton) newChatButton.addEventListener("click", clearPending, true);
  window.addEventListener("DOMContentLoaded", applySupportedCopy, { once: true });

  window.__padiemBinaryDocuments = Object.freeze({
    formats: Object.freeze(Array.from(MIME_BY_EXTENSION.keys())),
    maxBytes: MAX_BINARY_BYTES,
    pendingMeta: () => pending ? { name: pending.name, mediaType: pending.mediaType, byteSize: pending.byteSize } : null,
  });
})();
