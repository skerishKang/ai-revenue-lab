(() => {
  "use strict";
  const AUTO_BYTES = 10_000_000;
  const TYPES = Object.freeze({txt: "text/plain", md: "text/markdown", csv: "text/csv", pdf: "application/pdf"});
  const extension = (file) => String(file?.name || "").split(".").pop().toLowerCase();
  function shouldUse(file) {
    const needsPdfParser = extension(file) === "pdf" && window.PadiemAttachmentCapabilities?.binarySupported === false
      && window.PadiemAttachmentCapabilities?.fileLaneSupported === true;
    return Number.isSafeInteger(file?.size) && file.size > 0 && (file.size >= AUTO_BYTES || needsPdfParser)
      && Object.hasOwn(TYPES, extension(file));
  }
  async function available() {
    try {
      const response = await fetch("/api/files/capabilities", {credentials: "same-origin", cache: "no-store"});
      return response.ok && (await response.json()).ready === true;
    } catch (_) { return false; }
  }
  function pending(file) {
    return {type: "document", name: file.name, mediaType: TYPES[extension(file)], byteSize: file.size,
      file, fileLane: true};
  }
  async function upload(file, signal) {
    const ticketResponse = await fetch("/api/files/ticket", {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify({size_bytes: file.size}), signal});
    const ticket = await ticketResponse.json().catch(() => null);
    if (!ticketResponse.ok || !ticket?.ok) throw new Error(ticket?.error?.message || "파일 업로드를 준비하지 못했습니다.");
    const target = new URL(ticket.upload_url);
    if (target.protocol !== "https:" || target.username || target.password || target.search || target.hash
        || target.pathname !== "/files") throw new Error("파일 서버 주소를 확인하지 못했습니다.");
    target.searchParams.set("filename", file.name);
    const response = await fetch(target.href, {method: "POST", credentials: "include", headers: ticket.headers,
      body: file, signal}); // Native File body; never FileReader, arrayBuffer or base64.
    const data = await response.json().catch(() => null);
    if (!response.ok || !data?.ok || !/^file_[a-f0-9]{32}$/.test(data.file_id || "") || data.size_bytes !== file.size) {
      throw new Error("파일 서버에 첨부를 저장하지 못했습니다. 다시 시도해 주세요.");
    }
    return {fileId: data.file_id};
  }
  // Refresh the picker only after the current product authentication changed.
  // A missing/unconfigured lane cannot advertise a PDF parser it does not have.
  window.addEventListener?.("padiem:auth-state", () => {
    void available().then((ready) => {
      window.PadiemAttachmentCapabilities?.setFileLaneSupport?.(ready);
      window.dispatchEvent(new CustomEvent("padiem:file-lane-capability"));
    });
  });
  window.PadiemFileLane = Object.freeze({AUTO_BYTES, shouldUse, available, pending, upload});
})();
