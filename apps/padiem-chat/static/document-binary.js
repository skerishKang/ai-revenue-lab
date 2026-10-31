(() => {
  "use strict";

  const attachmentCapabilities = window.PadiemAttachmentCapabilities;
  const MIME_BY_EXTENSION = new Map();
  attachmentCapabilities.binaryDocuments.forEach((format) => {
    const mediaType = format.mediaTypes[0];
    format.extensions.forEach((extension) => MIME_BY_EXTENSION.set(extension, mediaType));
  });

  function extensionOf(name) {
    const lower = String(name || "").toLowerCase();
    const index = lower.lastIndexOf(".");
    return index >= 0 ? lower.slice(index) : "";
  }

  function expectedMediaType(file) {
    return MIME_BY_EXTENSION.get(extensionOf(file && file.name)) || null;
  }

  function binaryEnabled() {
    return attachmentCapabilities.binarySupported !== false;
  }

  function canRead(file) {
    return binaryEnabled() && expectedMediaType(file) !== null;
  }

  function canonicalMediaType(file) {
    const expected = expectedMediaType(file);
    if (!expected) return null;
    if (file && file.type && file.type !== expected) {
      throw new Error("문서 확장자와 파일 형식이 일치하지 않습니다.");
    }
    return expected;
  }

  async function read(file) {
    if (!binaryEnabled()) throw new Error(attachmentCapabilities.copy(document.documentElement.lang).unsupportedFormat);
    const mediaType = canonicalMediaType(file);
    if (!mediaType) throw new Error(attachmentCapabilities.copy(document.documentElement.lang).unsupportedFormat);
    if (!file || file.size < 1) throw new Error("빈 문서는 첨부할 수 없습니다.");

    return Object.freeze({
      type: "document",
      name: file.name || `document${extensionOf(file.name)}`,
      mediaType,
      file,
      byteSize: file.size,
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
    canRead,
    read,
    pendingMeta,
  });

  window.PadiemBinaryDocuments = api;
  window.__padiemBinaryDocuments = api;
})();
