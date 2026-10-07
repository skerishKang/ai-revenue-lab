/* Dedicated browser PDF extraction Worker for B67 #3329.
 *
 * The two PDF.js modules are test/build-time copied from the exact pinned
 * pdfjs-dist package. They are local assets. No user PDF URL is ever handed to
 * PDF.js; only transferred bytes are parsed.
 */
import * as pdfjsLib from "./vendor/pdf.mjs";
import { WorkerMessageHandler } from "./vendor/pdf.worker.mjs";

const PINNED_PDFJS_VERSION = "6.3.289";
const B67_BROWSER_EXTRACTION_CONTRACT_VERSION = "b67-browser-pdf-extraction.v1";
if (pdfjsLib.version !== PINNED_PDFJS_VERSION) {
  throw new Error("Pinned PDF.js version mismatch");
}

/* Force PDF.js to use its loopback/fake-worker transport inside this already
 * isolated dedicated Worker rather than spawning a second Worker. */
globalThis.pdfjsWorker = { WorkerMessageHandler };

function safeFailure(code, extra = {}) {
  return { ok: false, code, ...extra };
}

function normalizePageText(textContent) {
  const parts = [];
  for (const item of textContent.items || []) {
    if (!item || typeof item.str !== "string") continue;
    if (item.str) parts.push(item.str);
    if (item.hasEOL) parts.push("\n");
  }
  return parts
    .join(" ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

function sha256Hex(buffer) {
  if (!globalThis.crypto || !globalThis.crypto.subtle) {
    throw new Error("Web Crypto unavailable");
  }
  return globalThis.crypto.subtle.digest("SHA-256", buffer).then((digest) => {
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  });
}

function mapPdfError(error) {
  const name = error && typeof error.name === "string" ? error.name : "";
  if (name === "PasswordException") return "pdf_password_required";
  if (
    name === "InvalidPDFException" ||
    name === "MissingPDFException" ||
    name === "UnexpectedResponseException"
  ) {
    return "pdf_parse_failed";
  }
  return "pdf_parse_failed";
}

async function parsePdf(buffer, limits) {
  if (!(buffer instanceof ArrayBuffer)) return safeFailure("pdf_invalid_buffer");
  if (!limits || typeof limits !== "object") return safeFailure("pdf_invalid_limits");
  if (buffer.byteLength < 5) return safeFailure("pdf_too_small");
  if (buffer.byteLength > limits.maxBytes) return safeFailure("pdf_too_large");

  let loadingTask = null;
  let document = null;
  try {
    const sourceSha256 = await sha256Hex(buffer);
    loadingTask = pdfjsLib.getDocument({
      data: new Uint8Array(buffer),
      disableAutoFetch: true,
      disableRange: true,
      disableStream: true,
      useWorkerFetch: false,
      useWasm: false,
      isEvalSupported: false,
      stopAtErrors: true,
      disableFontFace: true
    });
    document = await loadingTask.promise;

    if (!Number.isInteger(document.numPages) || document.numPages < 1) {
      return safeFailure("pdf_page_count_invalid");
    }
    if (document.numPages > limits.maxPages) {
      return safeFailure("pdf_page_limit");
    }

    const pages = [];
    const ocrCandidatePages = [];
    let totalTextChars = 0;

    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
      const page = await document.getPage(pageNumber);
      const content = await page.getTextContent({
        includeMarkedContent: false,
        disableNormalization: false
      });
      const text = normalizePageText(content);
      if (text.length > limits.maxPageChars) {
        return safeFailure("pdf_page_text_limit");
      }
      totalTextChars += text.length;
      if (totalTextChars > limits.maxTotalChars) {
        return safeFailure("pdf_total_text_limit");
      }
      const nativeText = text.length > 0;
      if (!nativeText) ocrCandidatePages.push(pageNumber);
      pages.push({
        page_number: pageNumber,
        text,
        text_chars: text.length,
        native_text: nativeText
      });
      if (typeof page.cleanup === "function") page.cleanup();
    }

    const nativePages = pages.length - ocrCandidatePages.length;
    const nativeTextState = nativePages === 0
      ? "none"
      : (ocrCandidatePages.length === 0 ? "all" : "mixed");

    const projection = {
      contract_version: B67_BROWSER_EXTRACTION_CONTRACT_VERSION,
      parser: "pdfjs-dist",
      parser_version: PINNED_PDFJS_VERSION,
      source_sha256: sourceSha256,
      page_count: pages.length,
      pages,
      total_text_chars: totalTextChars,
      native_text_state: nativeTextState,
      ocr_candidate_pages: ocrCandidatePages
    };

    if (nativePages === 0) {
      return safeFailure("pdf_no_native_text", projection);
    }
    return { ok: true, ...projection };
  } catch (error) {
    return safeFailure(mapPdfError(error));
  } finally {
    try {
      if (document && typeof document.destroy === "function") await document.destroy();
      else if (loadingTask && typeof loadingTask.destroy === "function") await loadingTask.destroy();
    } catch (_) {
      /* Cleanup failure must never turn parser output into source authority. */
    }
  }
}

self.addEventListener("message", async (event) => {
  const data = event && event.data;
  if (!data || data.type !== "parse") return;
  const result = await parsePdf(data.buffer, data.limits);
  self.postMessage({ type: "result", result });
});

self.postMessage({
  type: "ready",
  parser: "pdfjs-dist",
  parser_version: PINNED_PDFJS_VERSION
});
