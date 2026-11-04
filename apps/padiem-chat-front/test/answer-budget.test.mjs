/**
 * 답변 시간 예산: the front door labels every answer request with one request id and
 * tells Chat how much of the 60s answer window is left. A front-generated
 * timeout keeps the same id and the Korean copy, so a user never loses the turn
 * to an edge page without a correlation id.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { createFront as realCreateFront } from "../worker.mjs";

const createFront = (options = {}) => realCreateFront({
  sign: async (request) => new Headers(request.headers),
  ...options,
});

function post(path, headers = {}) {
  return new Request("https://chat.padiem.net" + path, {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify({ messages: [{ role: "user", content: "ping" }] }),
  });
}

const ENV = {
  FRONT_ORIGIN: "https://host.example",
  FALLBACK_MODE: "static",
  ORCHESTRATION_TIMEOUT_MS: "45000",
};

function captureFetch(response = new Response('{"ok":true}', {
  status: 200, headers: { "content-type": "application/json" },
})) {
  const calls = [];
  return {
    calls,
    fetchImpl: async (request) => { calls.push(request); return response; },
  };
}

test("an answer request carries one request id and its remaining budget", async () => {
  const { calls, fetchImpl } = captureFetch();
  const handle = createFront({ fetchImpl });
  const response = await handle(post("/api/orchestration"), ENV);
  assert.equal(response.status, 200);
  const id = response.headers.get("x-request-id");
  assert.match(id, /^[A-Za-z0-9._:-]{8,64}$/);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].headers.get("x-request-id"), id);
  assert.equal(calls[0].headers.get("x-padiem-answer-budget-ms"), "45000");
  await response.text();
});

test("a client request id is preserved end to end", async () => {
  const { calls, fetchImpl } = captureFetch();
  const handle = createFront({ fetchImpl });
  const response = await handle(
    post("/api/orchestration", { "x-request-id": "client_req_12345" }), ENV,
  );
  assert.equal(calls[0].headers.get("x-request-id"), "client_req_12345");
  assert.equal(response.headers.get("x-request-id"), "client_req_12345");
  await response.text();
});

test("an upstream request id is passed through unchanged", async () => {
  const { fetchImpl } = captureFetch(new Response('{"ok":true}', {
    status: 200,
    headers: { "content-type": "application/json", "x-request-id": "server_req_67890" },
  }));
  const handle = createFront({ fetchImpl });
  const response = await handle(post("/api/orchestration"), ENV);
  assert.equal(response.headers.get("x-request-id"), "server_req_67890");
  await response.text();
});

test("a front-generated timeout keeps the id and the Korean JSON copy", async () => {
  const handle = createFront({
    fetchImpl: (request) => new Promise((resolve, reject) => {
      request.signal.addEventListener("abort", () => {
        reject(new DOMException("aborted", "AbortError"));
      }, { once: true });
    }),
  });
  const response = await handle(post("/api/orchestration"), {
    ...ENV, ORCHESTRATION_TIMEOUT_MS: "30",
  });
  assert.equal(response.status, 504);
  const id = response.headers.get("x-request-id");
  assert.match(id, /^[A-Za-z0-9._:-]{8,64}$/);
  const body = await response.text();
  assert.match(body, /upstream_timeout/);
  assert.match(body, /요청을 처리하지 못했습니다/);
});

test("an ordinary write carries the id but not the answer budget", async () => {
  const { calls, fetchImpl } = captureFetch();
  const handle = createFront({ fetchImpl });
  const response = await handle(
    new Request("https://chat.padiem.net/api/projects", { method: "POST", body: "{}" }),
    ENV,
  );
  assert.equal(response.status, 200);
  assert.equal(calls[0].headers.get("x-padiem-answer-budget-ms"), null);
  assert.ok(calls[0].headers.get("x-request-id"));
  await response.text();
});
