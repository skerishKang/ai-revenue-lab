/* #4647: Browser-to-Google-Drive resumable upload with an authorized,
 * server-initiated session URI. Never accepts a browser OAuth bearer token.
 * A Google upload session URI is a capability; never log or persist it.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module && module.exports) module.exports = api;
  if (root) root.PadiemMeetingDriveUpload = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const SESSION_PATH = "/api/claw/meeting/drive-upload-session";
  const GOOGLE_ORIGIN = "https://www.googleapis.com";
  const MAX_TOTAL = 180 * 1024 * 1024;
  const CHUNK_BYTES = 4 * 1024 * 1024;
  const ALLOWED_TYPES = new Set(["audio/webm", "audio/mp4", "audio/ogg", "text/plain"]);
  class UploadError extends Error {
    constructor(code) { super(code); this.name = "MeetingDriveUploadError"; this.code = code; }
  }
  function isSessionUri(value) {
    if (typeof value !== "string" || value.length > 4096) return false;
    try {
      const url = new URL(value);
      return url.origin === GOOGLE_ORIGIN
        && url.pathname === "/upload/drive/v3/files"
        && url.searchParams.get("uploadType") === "resumable"
        && Boolean(url.searchParams.get("upload_id"))
        && !url.hash && !url.username && !url.password;
    } catch (_) { return false; }
  }
  function checkedBlob(blob) {
    if (!blob || typeof blob.slice !== "function" || !Number.isSafeInteger(blob.size)
      || blob.size < 1 || blob.size > MAX_TOTAL || !ALLOWED_TYPES.has(blob.type)) {
      throw new UploadError("invalid_upload_file");
    }
    if (blob.type === "text/plain" && blob.size > 10 * 1024 * 1024) throw new UploadError("invalid_upload_file");
    return blob;
  }
  async function safeJson(response) {
    try { return await response.json(); } catch (_) { throw new UploadError("invalid_upload_response"); }
  }
  async function begin(blob, fetcher) {
    checkedBlob(blob);
    const response = await fetcher(SESSION_PATH, {
      method: "POST", credentials: "same-origin", cache: "no-store", redirect: "error",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ mime_type: blob.type, byte_size: blob.size }),
    });
    if (response.status === 401) throw new UploadError("login_required");
    if (response.status === 503) throw new UploadError("drive_write_unavailable");
    if (!response.ok) throw new UploadError("upload_session_rejected");
    const receipt = await safeJson(response);
    if (receipt?.ok !== true || receipt?.byte_size !== blob.size || receipt?.mime_type !== blob.type
      || !isSessionUri(receipt?.session_uri)) throw new UploadError("invalid_upload_session");
    return receipt.session_uri;
  }
  function nextOffset(range, current, end, total) {
    if (typeof range !== "string") throw new UploadError("invalid_upload_range");
    const match = /^bytes=0-(\d+)$/.exec(range);
    if (!match) throw new UploadError("invalid_upload_range");
    const next = Number(match[1]) + 1;
    if (!Number.isSafeInteger(next) || next < current || next > total) throw new UploadError("invalid_upload_range");
    return next;
  }
  async function upload(blob, options = {}) {
    checkedBlob(blob);
    const fetcher = options.fetch || fetch;
    const report = typeof options.onProgress === "function" ? options.onProgress : () => {};
    const url = await begin(blob, fetcher);
    let offset = 0;
    let requests = 0;
    const maxRequests = Math.ceil(blob.size / CHUNK_BYTES) + 8;
    while (offset < blob.size && requests < maxRequests) {
      if (options.signal?.aborted) throw new UploadError("upload_cancelled");
      const end = Math.min(blob.size, offset + CHUNK_BYTES);
      let response;
      try {
        response = await fetcher(url, {
          method: "PUT", mode: "cors", redirect: "error", signal: options.signal,
          headers: { "Content-Range": "bytes " + offset + "-" + (end - 1) + "/" + blob.size },
          body: blob.slice(offset, end, blob.type),
        });
      } catch (_) {
        // Network failure: do not falsely report completion or automatically
        // replay an ambiguous chunk. The original local Blob remains available.
        throw new UploadError("drive_upload_network_failed");
      }
      requests += 1;
      if (response.status === 308) {
        offset = nextOffset(response.headers?.get("Range"), offset, end, blob.size);
        report({ sent: offset, total: blob.size });
        continue;
      }
      if (!response.ok) throw new UploadError("drive_upload_failed");
      const metadata = await safeJson(response);
      if (!metadata || typeof metadata.id !== "string"
        || !/^[A-Za-z0-9_-]{8,128}$/.test(metadata.id)) {
        throw new UploadError("invalid_drive_receipt");
      }
      report({ sent: blob.size, total: blob.size });
      return Object.freeze({ fileId: metadata.id, name: metadata.name || "" });
    }
    throw new UploadError("incomplete_drive_upload");
  }
  return Object.freeze({ SESSION_PATH, isSessionUri, begin, upload, UploadError });
});
