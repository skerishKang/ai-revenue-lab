/**
 * #6460: an answer must not die on the generic 8s write window.
 *
 * worker.mjs gives every path whose answer is produced by a model call behind COM2
 * the dedicated first-byte window (ORCHESTRATION_TIMEOUT_MS, default 60s) — including
 * /api/chat/stream, which a logged-out browser uses and which measured 504 at 9.9s
 * against the 8s window on 2026-11-03 while the same answer completes in ~10-11s.
 * Ordinary writes (saves, settings, files) keep the 8s window, and an answer is never
 * re-dispatched to a second upstream.
 *
 * Nothing here waits seconds: the deadline is lowered instead.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { createFront as realCreateFront } from "../worker.mjs";

const createFront = (options = {}) => realCreateFront({
  sign: async (request) => new Headers(request.headers),
  ...options,
});

const ANSWER_PATHS = [
  "/api/orchestration",
  "/api/orchestration/resume",
  "/api/chat",
  "/api/chat/stream",
  "/api/claw/general",
  "/api/claw/manual-intake/execute",
  "/api/claw/manual-intake/preview",
  "/api/b66/ai/chat",
];

function delayedHeader(request, ms, body = '{"ok":true}') {
  // A real fetch rejects when its signal aborts; forward() turns that into TIMED_OUT.
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => resolve(new Response(body, {
      status: 200, headers: { "content-type": "application/json" },
    })), ms);
    request.signal.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("aborted", "AbortError"));
    }, { once: true });
  });
}

function trickle(chunks, gapMs) {
  const encoder = new TextEncoder();
  let index = 0;
  return new ReadableStream({
    async pull(controller) {
      if (index >= chunks.length) { controller.close(); return; }
      await new Promise((resolve) => setTimeout(resolve, gapMs));
      controller.enqueue(encoder.encode(chunks[index]));
      index += 1;
    },
  });
}

async function drain(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let text = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return text;
    text += decoder.decode(value, { stream: true });
  }
}

function post(path) {
  return new Request("https://chat.padiem.net" + path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ messages: [{ role: "user", content: "ping" }] }),
  });
}

const GENERIC_WINDOW = { FRONT_ORIGIN: "https://host.example", FALLBACK_MODE: "static", UPSTREAM_TIMEOUT_MS: "60" };

for (const path of ANSWER_PATHS) {
  test(`answer path keeps the dedicated window, not the 8s write window: ${path}`, async () => {
    // The generic write window is 60ms here and the upstream answers in 140ms: only a
    // path that ignores the generic window can still answer 200.
    const handle = createFront({ fetchImpl: (request) => delayedHeader(request, 140) });
    const response = await handle(post(path), GENERIC_WINDOW);
    assert.equal(response.status, 200, `${path} must not fall into the generic write deadline`);
    assert.equal(response.headers.get("x-padiem-orchestration-ttfb-ms") !== null, true,
      `${path} should carry the answer timing header`);
    await response.text();
  });
}

test("the dedicated window itself still bites: ORCHESTRATION_TIMEOUT_MS wins", async () => {
  for (const path of ["/api/chat/stream", "/api/claw/general"]) {
    const handle = createFront({ fetchImpl: (request) => delayedHeader(request, 140) });
    const response = await handle(post(path), {
      ...GENERIC_WINDOW, UPSTREAM_TIMEOUT_MS: "60000", ORCHESTRATION_TIMEOUT_MS: "60",
    });
    assert.equal(response.status, 504, `${path} must honour the configured answer window`);
    const body = await response.text();
    assert.match(body, /upstream_timeout/, path);
  }
});

test("ordinary writes keep the short write window", async () => {
  for (const path of ["/api/conversations", "/api/projects", "/api/account/pc-delegations"]) {
    const handle = createFront({ fetchImpl: (request) => delayedHeader(request, 140) });
    const response = await handle(
      new Request("https://chat.padiem.net" + path, { method: "POST", headers: { "content-type": "application/json" }, body: "{}" }),
      GENERIC_WINDOW,
    );
    assert.equal(response.status, 504, `${path} is a write and must stay on the generic window`);
    await response.text();
  }
});

test("an answer that starts streaming is never cut, whatever the window says", async () => {
  const handle = createFront({
    fetchImpl: async () => new Response(trickle(["a", "b", "c", "d", "e", "f"], 40), {
      status: 200, headers: { "content-type": "text/event-stream" },
    }),
  });
  const response = await handle(post("/api/chat/stream"), {
    ...GENERIC_WINDOW, ORCHESTRATION_TIMEOUT_MS: "30",
  });
  assert.equal(response.status, 200);
  assert.equal(await drain(response), "abcdef");
});

test("a refused connection never re-dispatches an answer", async () => {
  let fallbackCalls = 0;
  const chatWorker = {
    async fetch() { fallbackCalls += 1; return new Response("python-answer", { status: 200 }); },
  };
  const refused = async () => { const e = new Error("connect ECONNREFUSED"); e.code = "ECONNREFUSED"; throw e; };
  const handle = createFront({ fetchImpl: refused });

  const response = await handle(post("/api/chat/stream"), {
    FRONT_ORIGIN: "https://host.example", FALLBACK_MODE: "service", COM2_CANONICAL: "off",
    CHAT_WORKER: chatWorker,
  });
  assert.equal(response.status, 503);
  assert.match(await response.text(), /upstream_refused/);
  assert.equal(fallbackCalls, 0, "an answer must not be sent to a second upstream");

  // The guard is scoped to answers: an ordinary write still uses the configured fallback.
  const write = await handle(
    new Request("https://chat.padiem.net/api/conversations", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" }),
    { FRONT_ORIGIN: "https://host.example", FALLBACK_MODE: "service", COM2_CANONICAL: "off", CHAT_WORKER: chatWorker },
  );
  assert.equal(write.status, 200);
  assert.equal(await write.text(), "python-answer");
  assert.equal(fallbackCalls, 1);
});

test("the timing line names the answer path, not a hard-coded one", async () => {
  const logs = [];
  const original = console.log;
  console.log = (...args) => logs.push(args.join(" "));
  let response;
  try {
    const handle = createFront({
      fetchImpl: async () => new Response(trickle(["x", "y"], 20), {
        status: 200, headers: { "content-type": "application/x-ndjson" },
      }),
    });
    response = await handle(post("/api/claw/general"), GENERIC_WINDOW);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(await drain(response), "xy");
    await new Promise((resolve) => setTimeout(resolve, 40));
  } finally {
    console.log = original;
  }
  const lines = logs.filter((entry) => entry.includes("orchestration_timing"));
  assert.equal(lines.length, 1, "one timing line per answer: " + logs.join(" | "));
  assert.match(lines[0], /path=\/api\/claw\/general/);
  assert.match(lines[0], /status=200/);
  // The line is exactly four facts: path, status, ttfb, total. No body, no prompt,
  // no cookie, no identity.
  assert.deepEqual(
    Object.keys(Object.fromEntries(lines[0].replace("orchestration_timing ", "").split(" ").map((pair) => pair.split("=")))),
    ["path", "status", "ttfb_ms", "total_ms"],
    lines[0],
  );
  assert.doesNotMatch(lines[0], /ping|messages|cookie|authorization/i, "never the body or a credential: " + lines[0]);
});
