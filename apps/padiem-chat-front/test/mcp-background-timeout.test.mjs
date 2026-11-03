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
    const timer = setTimeout(() => resolve(new Response('{"ok":true}', { status: 200 })), ms);
    request.signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve(new Response("upstream_timeout", { status: 504 }));
    }, { once: true });
  });
}

const mcpRequest = () => new Request("https://chat.example.test/api/mcp", {
  method: "POST", body: "{}", headers: { "content-type": "application/json" },
});

test("MCP uses 180 seconds without changing OAuth, orchestration, or answer ceilings", async () => {
  const source = readFileSync(join(HERE, "..", "worker.mjs"), "utf8");
  assert.match(source, /const DEFAULT_MCP_TIMEOUT_MS = 180000;/);
  assert.match(source, /numeric\(env\.MCP_TIMEOUT_MS, DEFAULT_MCP_TIMEOUT_MS\)/);
  assert.match(source, /const DEFAULT_API_READ_TIMEOUT_MS = 30000;/);
  assert.match(source, /const DEFAULT_ORCHESTRATION_TIMEOUT_MS = 60000;/);

  const handle = createFront({ fetchImpl: (request) => delayed(request, 120) });
  const response = await handle(mcpRequest(), {
    FRONT_ORIGIN: "https://host.example", FALLBACK_MODE: "static",
    UPSTREAM_TIMEOUT_MS: "30", API_READ_TIMEOUT_MS: "35",
    ORCHESTRATION_TIMEOUT_MS: "40",
  });
  assert.equal(response.status, 200);
});

test("MCP_TIMEOUT_MS is configurable and remains scoped to /api/mcp", async () => {
  const handle = createFront({ fetchImpl: (request) => delayed(request, 120) });
  const response = await handle(mcpRequest(), {
    FRONT_ORIGIN: "https://host.example", FALLBACK_MODE: "static",
    UPSTREAM_TIMEOUT_MS: "8000", MCP_TIMEOUT_MS: "40",
  });
  assert.equal(response.status, 504);
});
