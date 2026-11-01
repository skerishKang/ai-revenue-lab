(() => {
  "use strict";
  const AUTO_BYTES = 10_000_000;
  const TYPES = Object.freeze({
    txt: "text/plain", md: "text/markdown", csv: "text/csv", pdf: "application/pdf",
    docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
  });
  const BINARY = new Set(["pdf", "docx", "pptx", "xlsx"]);
  const extension = (file) => String(file?.name || "").split(".").pop().toLowerCase();
  function shouldUse(file) {
    const kind = extension(file);
    const needsBinaryLane = BINARY.has(kind) &&
      (window.PadiemAttachmentCapabilities?.fileLaneSupported === true ||
       window.PadiemAttachmentCapabilities?.binarySupported === true);
    return Number.isSafeInteger(file?.size) && file.size > 0 &&
      (file.size >= AUTO_BYTES || needsBinaryLane) && Object.hasOwn(TYPES, kind);
  }
  async function available() {
    try {
      const response = await fetch("/api/files/capabilities", {credentials: "same-origin", cache: "no-store"});
      return response.ok && (await response.json()).ready === true;
    } catch (_) { return false; }
  }
  function isBinary(file) { return BINARY.has(extension(file)); }
  function pending(file) {
    return {type: "document", name: file.name, mediaType: TYPES[extension(file)], byteSize: file.size,
      file, fileLane: true};
  }
  function uploadError(data, fallback) {
    const code = data?.error?.code;
    const messages = {
      unauthorized: "로그인한 뒤 다시 첨부해 주세요.",
      invalid_request: "첨부할 파일을 확인한 뒤 다시 시도해 주세요.",
      request_too_large: "파일이 너무 큽니다. 더 작은 파일을 선택해 주세요.",
    };
    const error = new Error(Object.hasOwn(messages, code) ? messages[code] : fallback);
    if (typeof code === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(code)) error.code = code;
    return error;
  }
  async function upload(file, signal) {
    const ticketResponse = await fetch("/api/files/ticket", {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify({size_bytes: file.size}), signal});
    const ticket = await ticketResponse.json().catch(() => null);
    if (!ticketResponse.ok || !ticket?.ok) throw uploadError(ticket, "파일 업로드를 준비하지 못했습니다. 다시 시도해 주세요.");
    const target = new URL(ticket.upload_url);
    if (target.protocol !== "https:" || target.username || target.password || target.search || target.hash
        || target.pathname !== "/files") throw new Error("파일 서버 주소를 확인하지 못했습니다.");
    target.searchParams.set("filename", file.name);
    const response = await fetch(target.href, {method: "POST", credentials: "include", headers: ticket.headers,
      body: file, signal}); // Native File body; never FileReader, arrayBuffer or base64.
    const data = await response.json().catch(() => null);
    if (!response.ok || !data?.ok || !/^file_[a-f0-9]{32}$/.test(data.file_id || "") || data.size_bytes !== file.size) {
      throw uploadError(data, "파일 서버에 첨부를 저장하지 못했습니다. 다시 시도해 주세요.");
    }
    return {fileId: data.file_id};
  }
  // Refresh the picker only after the current product authentication changed.
  // A missing/unconfigured lane cannot advertise a binary parser it does not have.
  window.addEventListener?.("padiem:auth-state", () => {
    void available().then((ready) => {
      window.PadiemAttachmentCapabilities?.setFileLaneSupport?.(ready);
      window.dispatchEvent(new CustomEvent("padiem:file-lane-capability"));
    });
  });
  window.PadiemFileLane = Object.freeze({AUTO_BYTES, shouldUse, isBinary, available, pending, upload});
})();
