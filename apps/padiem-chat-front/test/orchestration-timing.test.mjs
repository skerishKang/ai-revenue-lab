import test from 'node:test';
import assert from 'node:assert/strict';
import { createFront as realCreateFront } from "../worker.mjs";

const createFront = (options = {}) => realCreateFront({
  sign: async (request) => new Headers(request.headers),
  ...options,
});

function delayed(request, ms) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(new Response('{"ok":true}', {
      status: 200, headers: { "content-type": "application/json" },
    })), ms);
    request.signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve(new Response("upstream_timeout", { status: 504 }));
    }, { once: true });
  });
}

test("the orchestration window is its own deadline, not the generic write one", async () => {
  // 60ms dedicated window vs the 8000ms generic write window: a 140ms upstream
  // answers 504 only when the dedicated branch actually applies.
  const logs = [];
  const original = console.log;
  console.log = (...args) => logs.push(args.join(" "));
  try {
    const handle = createFront({
      fetchImpl: (request) => delayed(request, 140),
    });
    const response = await handle(
      new Request("https://chat.example.test/api/orchestration", {
        method: "POST", body: "{}",
        headers: { "content-type": "application/json" },
      }),
      {
        FRONT_ORIGIN: "https://host.example", FALLBACK_MODE: "service",
        ORCHESTRATION_TIMEOUT_MS: "60",
      },
    );
    assert.equal(response.status, 504);
    // The timing line prints when the upstream body has fully streamed.
    await response.text();
    await new Promise((resolve) => setTimeout(resolve, 20));
  } finally {
    console.log = original;
  }
  const line = logs.find((entry) => entry.includes("orchestration_timing"));
  assert.ok(line, "one orchestration_timing line expected: " + logs.join(" | "));
  assert.match(line, /path=\/api\/orchestration/);
  assert.match(line, /status=504/);
  const ttfb = Number(line.match(/ttfb_ms=(\d+)/)[1]);
  assert.ok(ttfb < 200, "the dedicated window fired, not the 8s one: " + line);
});

test("a clear orchestration answer logs status ttfb and total, nothing else", async () => {
  const logs = [];
  const original = console.log;
  console.log = (...args) => logs.push(args.join(" "));
  try {
    const handle = createFront({
      fetchImpl: (request) => delayed(request, 140),
    });
    const response = await handle(
      new Request("https://chat.example.test/api/orchestration", {
        method: "POST", body: '{"tier":"max"}',
        headers: { "content-type": "application/json", cookie: "__Host-padiem-shared-access=probe" },
      }),
      {
        FRONT_ORIGIN: "https://host.example", FALLBACK_MODE: "service",
        ORCHESTRATION_TIMEOUT_MS: "30000",
      },
    );
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("x-padiem-orchestration-ttfb-ms"), String(
      Number(response.headers.get("x-padiem-orchestration-ttfb-ms"))));
    await response.text();
    await new Promise((resolve) => setTimeout(resolve, 20));
  } finally {
    console.log = original;
  }
  const line = logs.find((entry) => entry.includes("orchestration_timing"));
  assert.ok(line, "one orchestration_timing line expected: " + logs.join(" | "));
  assert.match(line, /status=200/);
  assert.match(line, /ttfb_ms=\d+/);
  assert.match(line, /total_ms=\d+/);
  assert.ok(!line.includes("__Host"), "no cookie values in the timing line");
  assert.ok(!line.includes("tier=max"), "no tier copy in the timing line");
  assert.ok(!line.includes('{"ok"'), "no response body in the timing line");
});
