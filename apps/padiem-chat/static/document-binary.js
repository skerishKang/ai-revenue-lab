(() => {
  "use strict";

  const MAX_BINARY_BYTES = 2 * 1024 * 1024;
  const MIME_BY_EXTENSION = new Map([
    [".pdf", "application/pdf"],
    [".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
    [".pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"],
    [".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
  ]);

  function extensionOf(name) {
    const lower = String(name || "").toLowerCase();
    const index = lower.lastIndexOf(".");
    return index >= 0 ? lower.slice(index) : "";
  }

  function expectedMediaType(file) {
    return MIME_BY_EXTENSION.get(extensionOf(file && file.name)) || null;
  }

  function canRead(file) {
    return expectedMediaType(file) !== null;
  }

  function canonicalMediaType(file) {
    const expected = expectedMediaType(file);
    if (!expected) return null;
    if (file && file.type && file.type !== expected) {
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

  async function read(file) {
    const mediaType = canonicalMediaType(file);
    if (!mediaType) throw new Error("지원하지 않는 바이너리 문서 형식입니다.");
    if (!file || file.size < 1) throw new Error("빈 문서는 첨부할 수 없습니다.");
    if (file.size > MAX_BINARY_BYTES) throw new Error("PDF·Office 문서는 2 MiB 이하만 첨부할 수 있습니다.");

    const buffer = await file.arrayBuffer();
    if (buffer.byteLength !== file.size || buffer.byteLength < 1 || buffer.byteLength > MAX_BINARY_BYTES) {
      throw new Error("문서 크기를 안전하게 확인하지 못했습니다.");
    }
    const base64 = arrayBufferToBase64(buffer);
    if (!base64) throw new Error("문서 데이터가 비어 있습니다.");

    return Object.freeze({
      type: "document",
      name: file.name || `document${extensionOf(file.name)}`,
      mediaType,
      base64,
      byteSize: buffer.byteLength,
    });
  }

  function pendingMeta() {
    const input = document.getElementById("attachmentFileInput");
    const file = input && input.files ? input.files[0] : null;
    if (!file || !canRead(file)) return null;
    let mediaType;
    try {
      mediaType = canonicalMediaType(file);
    } catch (_) {
      return null;
    }
    return Object.freeze({
      name: file.name || "document",
      mediaType,
      byteSize: file.size,
    });
  }

  const api = Object.freeze({
    formats: Object.freeze(Array.from(MIME_BY_EXTENSION.keys())),
    maxBytes: MAX_BINARY_BYTES,
    canRead,
    read,
    pendingMeta,
  });

  window.PadiemBinaryDocuments = api;
  window.__padiemBinaryDocuments = api;
})();
