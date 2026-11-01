(() => {
  "use strict";

  // #6126: a picked .hwp file is judged by its own first bytes, not its name.
  // The OLE2 compound signature is the older binary Hangul format (refused
  // with the save-as-HWPX guidance), and a ZIP local header means a mislabeled
  // file that really is an HWPX package and keeps working as HWPX.
  const OLE_MAGIC = [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1];
  const ZIP_LOCAL_MAGICS = [
    [0x50, 0x4b, 0x03, 0x04],
    [0x50, 0x4b, 0x05, 0x06],
    [0x50, 0x4b, 0x07, 0x08],
  ];
  async function headerFamily(file) {
    try {
      const head = new Uint8Array(await file.slice(0, 8).arrayBuffer());
      if (ZIP_LOCAL_MAGICS.some((magic) => magic.every((byte, index) => head[index] === byte))) return "zip";
      if (OLE_MAGIC.every((byte, index) => head[index] === byte)) return "ole";
    } catch (_) {}
    return null;
  }

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

  async function read(file, hint) {
    if (!binaryEnabled()) throw new Error(attachmentCapabilities.copy(document.documentElement.lang).unsupportedFormat);
    // An explicit mediaType hint (the #6126 signature-sniffed .hwp-as-HWPX
    // case) is trusted over the name, because the bytes were already checked;
    // the name-driven path keeps the extension/canonical checks.
    const mediaType = (hint && typeof hint.mediaType === "string")
      ? hint.mediaType
      : canonicalMediaType(file);
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

  const hwpxMedia = MIME_BY_EXTENSION.get(".hwpx") || null;
  const api = Object.freeze({
    formats: Object.freeze(Array.from(MIME_BY_EXTENSION.keys())),
    headerFamily,
    hwpxMedia,
    canRead,
    read,
    pendingMeta,
  });

  window.PadiemBinaryDocuments = api;
  window.__padiemBinaryDocuments = api;
})();
