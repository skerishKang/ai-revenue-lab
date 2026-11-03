import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { createFront as realCreateFront } from "../worker.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
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

const orchestrationRequest = () => new Request("https://chat.example.test/api/orchestration", {
  method: "POST", body: "{}", headers: { "content-type": "application/json" },
});

test("the orchestration default is the 60s ceiling, not the generic 8s write window", async () => {
  const source = readFileSync(join(HERE, "..", "worker.mjs"), "utf8");
  assert.match(source, /const DEFAULT_TIMEOUT_MS = 8000;/);
  assert.match(source, /const DEFAULT_ORCHESTRATION_TIMEOUT_MS = 60000;/);
  assert.match(source, /numeric\(env\.ORCHESTRATION_TIMEOUT_MS, DEFAULT_ORCHESTRATION_TIMEOUT_MS\)/);

  // The generic window is still 8s; this path must not answer 504 under it.
  const handle = createFront({ fetchImpl: (request) => delayed(request, 120) });
  const response = await handle(orchestrationRequest(), {
    FRONT_ORIGIN: "https://host.example", FALLBACK_MODE: "static",
    UPSTREAM_TIMEOUT_MS: "8000",
  });
  assert.equal(response.status, 200);
});

test("a configured ORCHESTRATION_TIMEOUT_MS still wins over the default", async () => {
  const handle = createFront({ fetchImpl: (request) => delayed(request, 120) });
  const response = await handle(orchestrationRequest(), {
    FRONT_ORIGIN: "https://host.example", FALLBACK_MODE: "static",
    ORCHESTRATION_TIMEOUT_MS: "40",
  });
  assert.equal(response.status, 504);
});
