"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const drive = require("../static/meeting-drive-upload.js");
const goodSession = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=sessionexampleABC";
function started(blob) {
  return { ok: true, byte_size: blob.size, mime_type: blob.type, session_uri: goodSession };
}
function jsonResponse(payload, status = 200, extra = {}) {
  return { ok: status < 400, status, headers: { get: (key) => extra[key] ?? null },
    json: async () => payload };
}
test("authorized 1-chunk flow keeps content off PADIEM, receives actual Drive file ID", async () => {
  const blob = new Blob(["hello"], { type: "text/plain" });
  const requests = [];
  const fetch = async (url, options) => {
    requests.push({ url, options });
    if (url === drive.SESSION_PATH) return jsonResponse(started(blob));
    return jsonResponse({ id: "1B2C3D4E5F6G7H8I", name: "fromDrive.txt" }, 200);
  };
  const result = await drive.upload(blob, { fetch });
  assert.equal(result.fileId, "1B2C3D4E5F6G7H8I");
  assert.equal(requests.length, 2);
  assert.equal(requests[0].url, drive.SESSION_PATH);
  assert.deepEqual(JSON.parse(requests[0].options.body), { mime_type: "text/plain", byte_size: 5 });
  assert.equal(requests[1].url, goodSession);
  assert.equal(requests[1].options.method, "PUT");
  assert.equal(requests[1].options.headers["Content-Range"], "bytes 0-4/5");
  assert.equal(requests[1].options.body.size, 5);
  assert.equal(requests[0].options.body.includes("hello"), false);
  assert.equal(JSON.stringify(requests.map(x => x.options.headers || {})).includes("Bearer"), false);
});
test("real resumable chunk status 308 advances by verified Range", async () => {
  const blob = new Blob([new Uint8Array(4 * 1024 * 1024 + 19)], { type: "audio/webm" });
  const puts = [];
  const fetch = async (url, options) => {
    if (url === drive.SESSION_PATH) return jsonResponse(started(blob));
    puts.push(options);
    return puts.length === 1
      ? jsonResponse({}, 308, { Range: "bytes=0-4194303" })
      : jsonResponse({ id: "1a2b3c4d5e6f7g8h" }, 201);
  };
  const result = await drive.upload(blob, { fetch });
  assert.equal(result.fileId, "1a2b3c4d5e6f7g8h");
  assert.equal(puts.length, 2);
  assert.equal(puts[0].headers["Content-Range"], "bytes 0-4194303/4194323");
  assert.equal(puts[1].headers["Content-Range"], "bytes 4194304-4194322/4194323");
});
test("unsupported or missing canonical permission fails closed without provider bytes", async () => {
  const blob = new Blob(["file"], { type: "text/plain" });
  let called = 0;
  const fetch = async () => { called++; return jsonResponse({ error: { code: "no_drive_write" } }, 503); };
  await assert.rejects(drive.upload(blob, { fetch }), error => error.code === "drive_write_unavailable");
  assert.equal(called, 1);
  assert.equal(drive.isSessionUri("https://evil.example/upload/drive/v3/files?uploadType=resumable&upload_id=x"), false);
  assert.equal(drive.isSessionUri("https://www.googleapis.com.evil.example/upload/drive/v3/files?uploadType=resumable&upload_id=x"), false);
  await assert.rejects(drive.upload(new Blob(["hi"], { type: "application/json" }), { fetch }),
    error => error.code === "invalid_upload_file");
  assert.equal(called, 1);
});
test("invalid resumable session or fake Google completion never reports success", async () => {
  const blob = new Blob(["hello"], { type: "text/plain" });
  const invalid = async () => jsonResponse({ ...started(blob), session_uri: "https://evil.example/path" });
  await assert.rejects(drive.upload(blob, { fetch: invalid }), error => error.code === "invalid_upload_session");
  const fake = async (url) => url === drive.SESSION_PATH
    ? jsonResponse(started(blob)) : jsonResponse({ ok: true });
  await assert.rejects(drive.upload(blob, { fetch: fake }), error => error.code === "invalid_drive_receipt");
});
