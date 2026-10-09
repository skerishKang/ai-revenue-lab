// #3932: authenticated, same-origin inline PDF preview for an actual Claw
// result artifact. The existing server route is the only file/tenant authority.
// No guessed URLs, XLSX render, local storage, global file cache or retries.
(() => {
  "use strict";
  const VALID_ID = /^doc_[A-Za-z0-9]{32}$/;
  const PDF_TYPE = "application/pdf";
  const MAX_PDF = 10 * 1024 * 1024;
  const controllers = new Set();

  function copy(lang, key) {
    const en = String(lang || "").toLowerCase().startsWith("en");
    const variants = {
      action: ["PDF 미리보기", "Preview PDF"],
      heading: ["PDF 미리보기", "PDF preview"],
      close: ["닫기", "Close"],
      error: ["PDF 미리보기를 열 수 없습니다. 권한과 파일 상태를 확인하세요.", "PDF preview is unavailable. Check access and the file state."],
    };
    return (variants[key] || variants.error)[en ? 1 : 0];
  }
  function validArtifact(value) {
    return value && typeof value === "object" &&
      VALID_ID.test(value.document_id || "") &&
      value.media_type === PDF_TYPE &&
      typeof value.filename === "string" && /\.pdf$/i.test(value.filename) &&
      Number.isInteger(value.byte_length) &&
      value.byte_length > 0 && value.byte_length <= MAX_PDF;
  }
  function isPdf(bytes) {
    if (!(bytes instanceof Uint8Array) || bytes.length < 16 || bytes.length > MAX_PDF) return false;
    if (bytes[0] !== 37 || bytes[1] !== 80 || bytes[2] !== 68 ||
        bytes[3] !== 70 || bytes[4] !== 45) return false;
    const tail = bytes.subarray(Math.max(0, bytes.length - 1024));
    const eof = [37, 37, 69, 79, 70];
    for (let i = 0; i <= tail.length - eof.length; i += 1) {
      if (eof.every((x, j) => tail[i + j] === x)) return true;
    }
    return false;
  }

  function create({ mount, doc = document, fetcher = fetch, onError = () => {},
                    makeUrl = (blob) => URL.createObjectURL(blob),
                    revokeUrl = (url) => URL.revokeObjectURL(url) } = {}) {
    if (!mount || typeof mount.appendChild !== "function") return null;
    let current = null;
    let button = null;
    let dialog = null;
    let currentUrl = null;
    let abort = null;
    let generation = 0;

    function closeViewer() {
      const closing = dialog;
      dialog = null;
      if (closing) {
        if (closing.open) closing.close();
        closing.remove();
      }
      if (currentUrl) { revokeUrl(currentUrl); currentUrl = null; }
      if (current && button && !button.disabled) button.focus?.();
    }
    function clear() {
      generation += 1;
      if (abort) { abort.abort(); abort = null; }
      closeViewer();
      if (button) { button.remove(); button = null; }
      current = null;
    }
    async function show() {
      if (!current || !button || button.disabled) return false;
      const epoch = generation;
      const artifact = current;
      button.disabled = true;
      const controller = new AbortController();
      abort = controller;
      let blobUrl = null;
      try {
        const path = "/api/claw/manual-intake/artifact/" +
          encodeURIComponent(artifact.document_id) + "/preview";
        const response = await fetcher(path, {
          method: "GET", cache: "no-store", credentials: "same-origin",
          headers: { Accept: PDF_TYPE }, signal: controller.signal,
        });
        if (epoch !== generation) return false;
        if (!response || response.status !== 200 ||
            !response.headers || String(response.headers.get("content-type") || "").split(";")[0].trim().toLowerCase() !== PDF_TYPE) {
          throw new Error("PREVIEW_UNAVAILABLE");
        }
        const payload = new Uint8Array(await response.arrayBuffer());
        if (epoch !== generation) return false;
        if (!isPdf(payload)) throw new Error("PREVIEW_UNAVAILABLE");
        blobUrl = makeUrl(new Blob([payload], { type: PDF_TYPE }));
        if (epoch !== generation) { revokeUrl(blobUrl); return false; }
        const modal = doc.createElement("dialog");
        modal.className = "claw-pdf-preview-modal";
        modal.setAttribute("aria-label", copy(doc.documentElement.lang, "heading"));
        const head = doc.createElement("div");
        head.className = "claw-pdf-preview-head";
        const title = doc.createElement("strong");
        title.textContent = artifact.filename;
        const closeButton = doc.createElement("button");
        closeButton.type = "button";
        closeButton.textContent = copy(doc.documentElement.lang, "close");
        closeButton.addEventListener("click", () => modal.close());
        const frame = doc.createElement("iframe");
        frame.title = copy(doc.documentElement.lang, "heading");
        frame.setAttribute("referrerpolicy", "no-referrer");
        frame.src = blobUrl;
        head.append(title, closeButton);
        modal.append(head, frame);
        doc.body.appendChild(modal);
        dialog = modal;
        currentUrl = blobUrl;
        blobUrl = null;
        modal.addEventListener("close", closeViewer, { once: true });
        if (typeof modal.showModal !== "function") throw new Error("PREVIEW_UNSUPPORTED");
        modal.showModal();
        closeButton.focus?.();
        return true;
      } catch (_) {
        if (epoch === generation) onError(copy(doc.documentElement.lang, "error"));
        return false;
      } finally {
        if (blobUrl) revokeUrl(blobUrl);
        if (abort === controller) abort = null;
        if (epoch === generation && button) button.disabled = false;
        if (epoch === generation && dialog && !dialog.open) closeViewer();
      }
    }
    function set(artifact) {
      clear();
      if (!validArtifact(artifact)) return false;
      current = Object.freeze({
        document_id: artifact.document_id,
        filename: artifact.filename,
      });
      button = doc.createElement("button");
      button.type = "button";
      button.className = "claw-pdf-preview-action";
      button.textContent = copy(doc.documentElement.lang, "action");
      button.addEventListener("click", () => { void show(); });
      mount.appendChild(button);
      return true;
    }
    const instance = Object.freeze({ set, clear, show });
    controllers.add(instance);
    return instance;
  }
  function revokeAll() {
    for (const controller of controllers) controller.clear();
  }
  window.PadiemClawPdfPreview = Object.freeze({ create, validArtifact, isPdf, revokeAll });
})();
