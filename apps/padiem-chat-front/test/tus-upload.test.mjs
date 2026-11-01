// 1GB 통일 1단계 — 앞단 워커의 tus 조각 업로드 통과 계약.
//
// The front is a pure proxy, so the contract here is narrow and strict:
//   1. PATCH (append) and POST (creation) on /api/projects/*/files/tus* keep
//      their Upload-* headers and their body stream untouched.
//   2. Those writes ride their own deadline (TUS_UPLOAD_TIMEOUT_MS, default
//      120s) instead of the plain 8s write timeout — a healthy ≤90MB chunk
//      must not die on the front while COM2 is still draining it.
import test from "node:test";
import assert from "node:assert/strict";

import { createFront as realCreateFront } from "../worker.mjs";

const createFront = (options = {}) => realCreateFront({
  ...options,
  sign: async (request) => new Headers(request.headers),
});

const ORIGIN = "https://chat-com2.padiem.net";

function baseEnv(overrides = {}) {
  return {
    FRONT_ORIGIN: ORIGIN,
    FALLBACK_MODE: "static",
    COM2_CANONICAL: "off",
    HEALTH_TTL_MS: "10000",
    UPSTREAM_TIMEOUT_MS: "8000",
    ...overrides,
  };
}

function recordingFetch(respond) {
  const calls = [];
  const impl = async (input) => {
    calls.push(input);
    return respond(input, calls.length);
  };
  impl.calls = calls;
  return impl;
}

// A real upstream fetch rejects when the front's deadline aborts it. The
// timeout tests need that behavior; the passthrough tests do not.
function slowUpstreamFetch(delayMs, respond) {
  const calls = [];
  const impl = (input) => {
    calls.push(input);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => resolve(respond()), delayMs);
      input.signal?.addEventListener("abort", () => {
        clearTimeout(timer);
        reject(new Error("The operation was aborted"));
      });
    });
  };
  impl.calls = calls;
  return impl;
}

function tusPatchRequest(body, uploadId = "up_1") {
  return new Request(`https://chat.padiem.net/api/projects/proj_1/files/tus/${uploadId}`, {
    method: "PATCH",
    headers: {
      cookie: "padiem_session=abc",
      "content-type": "application/offset+octet-stream",
      "upload-offset": "94371840",
      "tus-resumable": "1.0.0",
    },
    body,
    duplex: "half",
  });
}

test("tus PATCH keeps Upload-* headers and passes the chunk body through untouched", async () => {
  const upstream = new Response(null, { status: 204, headers: { "upload-offset": "188743680" } });
  const fetchImpl = recordingFetch(() => upstream);
  const handle = createFront({ fetchImpl });

  const response = await handle(tusPatchRequest("CHUNK-BYTES-90MB"), baseEnv());

  assert.equal(response, upstream); // the exact upstream object, untouched
  const forwarded = fetchImpl.calls[0];
  assert.equal(forwarded.url, `${ORIGIN}/api/projects/proj_1/files/tus/up_1`);
  assert.equal(forwarded.method, "PATCH");
  assert.equal(forwarded.headers.get("upload-offset"), "94371840");
  assert.equal(forwarded.headers.get("content-type"), "application/offset+octet-stream");
  assert.equal(forwarded.headers.get("tus-resumable"), "1.0.0");
  assert.equal(forwarded.headers.get("cookie"), "padiem_session=abc");
  assert.equal(await forwarded.text(), "CHUNK-BYTES-90MB"); // the front never read or rewrote the body
});

test("tus POST creation keeps Upload-Length and Upload-Metadata", async () => {
  const upstream = new Response(JSON.stringify({ upload_id: "up_9" }), {
    status: 201,
    headers: { "location": "/api/projects/proj_1/files/tus/up_9", "tus-resumable": "1.0.0" },
  });
  const fetchImpl = recordingFetch(() => upstream);
  const handle = createFront({ fetchImpl });

  const request = new Request("https://chat.padiem.net/api/projects/proj_1/files/tus", {
    method: "POST",
    headers: {
      cookie: "padiem_session=abc",
      "upload-length": "1073741824",
      "upload-metadata": "filename Ym9nb3NlLnBkZg==,filetype YXBwbGljYXRpb24vcGRm",
      "tus-resumable": "1.0.0",
    },
  });
  const response = await handle(request, baseEnv());

  assert.equal(response, upstream);
  const forwarded = fetchImpl.calls[0];
  assert.equal(forwarded.method, "POST");
  assert.equal(forwarded.headers.get("upload-length"), "1073741824");
  assert.equal(forwarded.headers.get("upload-metadata"), "filename Ym9nb3NlLnBkZg==,filetype YXBwbGljYXRpb24vcGRm");
});

test("a healthy tus chunk outlives the plain write timeout", async () => {
  // 10ms upstream allowance with a 30ms chunk drain: the plain write timeout
  // would answer 504 — the tus allowance (default 120s) must let it finish.
  const fetchImpl = slowUpstreamFetch(30, () => new Response(null, { status: 204, headers: { "upload-offset": "100" } }));
  const handle = createFront({ fetchImpl });

  const response = await handle(tusPatchRequest("slow-chunk"), baseEnv({ UPSTREAM_TIMEOUT_MS: "10" }));
  assert.equal(response.status, 204);
});

test("TUS_UPLOAD_TIMEOUT_MS overrides the default when configured", async () => {
  const fetchImpl = slowUpstreamFetch(30, () => new Response(null, { status: 204, headers: { "upload-offset": "100" } }));
  const handle = createFront({ fetchImpl });

  const response = await handle(tusPatchRequest("slow-chunk"), baseEnv({ TUS_UPLOAD_TIMEOUT_MS: "10" }));
  assert.equal(response.status, 504);
  assert.equal((await response.json()).error.code, "upstream_timeout");
});

test("a non-tus write keeps the plain write timeout", async () => {
  const fetchImpl = slowUpstreamFetch(30, () => new Response("{}", { status: 201 }));
  const handle = createFront({ fetchImpl });

  const response = await handle(new Request("https://chat.padiem.net/api/projects/proj_1/files", {
    method: "POST",
    headers: { cookie: "padiem_session=abc", "content-type": "application/json" },
    body: JSON.stringify({ name: "n", media_type: "text/plain", text: "t" }),
  }), baseEnv({ UPSTREAM_TIMEOUT_MS: "10" }));
  assert.equal(response.status, 504);
});
