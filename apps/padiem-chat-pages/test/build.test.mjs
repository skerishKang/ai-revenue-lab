import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

import { buildDist } from "../build.mjs";

const ORIGIN = "https://chat-com2.padiem.net";

function baseEnv(overrides = {}) {
  return {
    FRONT_ORIGIN: ORIGIN,
    FALLBACK_MODE: "static",
    COM2_CANONICAL: "writes",
    HEALTH_TTL_MS: "10000",
    UPSTREAM_TIMEOUT_MS: "8000",
    PADIEM_COM2_EDGE_SECRET: "synthetic-only-secret-0123456789abcdef",
    ...overrides,
  };
}

// The front door signs every request with request.cf.tlsVersion and forwards
// through the global fetch; a plain object stands in for the edge request.
function edgeRequest(url, { method = "GET", headers = {}, tlsVersion = "TLSv1.3" } = {}) {
  return { url, method, headers: new Headers(headers), cf: { tlsVersion } };
}

async function assembled() {
  const out = await mkdtemp(path.join(tmpdir(), "padiem-chat-pages-"));
  await buildDist({ outDir: out });
  return out;
}

test("dist carries the shared static assets and the one front proxy", async () => {
  const out = await assembled();
  const entries = await readdir(out);
  assert.ok(entries.includes("index.html"), "index.html is served by Pages");
  assert.ok(entries.includes("_worker.js"), "advanced-mode entry exists");
  assert.ok(entries.includes("_worker"), "front modules are inside dist");
  for (const name of ["worker.mjs", "edge-proof.mjs", "error-copy.mjs"]) {
    assert.ok((await readdir(path.join(out, "_worker"))).includes(name), `${name} copied`);
  }
  const entry = await readFile(path.join(out, "_worker.js"), "utf8");
  assert.match(entry, /export \{ default \} from "\.\/_worker\/worker\.mjs"/);
});

test("the generated entry proxies the same paths to the same tunnel origin", async () => {
  const out = await assembled();
  const { default: worker } = await import(pathToFileURL(path.join(out, "_worker.js")).href);
  const upstream = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (input) => {
    upstream.push(String(input.url));
    return new Response("ok", { status: 200, headers: { "content-type": "text/plain" } });
  };
  try {
    const response = await worker.fetch(
      edgeRequest("https://padiem-chat.pages.dev/health"),
      baseEnv(),
    );
    assert.equal(response.status, 200);
    assert.deepEqual(upstream, [`${ORIGIN}/health`]);
  } finally {
    globalThis.fetch = original;
  }
});

test("the generated entry serves the shell from the Pages asset store", async () => {
  const out = await assembled();
  const { default: worker } = await import(pathToFileURL(path.join(out, "_worker.js")).href);
  const assetCalls = [];
  const env = baseEnv({
    ASSETS: {
      fetch: async (request) => {
        assetCalls.push(new URL(request.url).pathname);
        return new Response("<!doctype html><title>chat</title>", {
          status: 200,
          headers: { "content-type": "text/html; charset=utf-8" },
        });
      },
    },
  });
  const response = await worker.fetch(edgeRequest("https://padiem-chat.pages.dev/"), env);
  assert.equal(response.status, 200);
  assert.deepEqual(assetCalls, ["/"]);
  assert.match(await response.text(), /<title>chat<\/title>/);
});

test("dist/index.html stamps every local asset reference with ?v=<version>", async () => {
  const previous = process.env.PADIEM_ASSET_VERSION;
  process.env.PADIEM_ASSET_VERSION = "ab12cd34";
  let out;
  try {
    out = await assembled();
  } finally {
    if (previous === undefined) delete process.env.PADIEM_ASSET_VERSION;
    else process.env.PADIEM_ASSET_VERSION = previous;
  }
  const html = await readFile(path.join(out, "index.html"), "utf8");
  const refs = [...html.matchAll(
    /(<(?:script|link)\b[^>]*?\b(?:src|href)=)(["'])([^"']+?)\2/gi,
  )].map((match) => match[3]);
  const local = refs.filter((value) =>
    !/^(?:[a-z][a-z0-9+.-]*:|\/\/|#)/i.test(value));
  assert.ok(local.length > 50, `expected ~90 local references, got ${local.length}`);
  for (const value of local) {
    assert.ok(value.endsWith("?v=ab12cd34"), value);
  }
  // External references are untouched.
  for (const value of refs) {
    if (!local.includes(value)) assert.ok(!value.includes("?v="), value);
  }
  // JS/CSS literals that load static files carry the same version; API-only
  // files stay byte-identical to the repository source.
  const a11y = await readFile(path.join(out, "a11y.js"), "utf8");
  assert.ok(a11y.includes(`"./interaction-polish.js?v=ab12cd34"`), a11y.slice(180, 220));
  const cinematic = await readFile(path.join(out, "padiem-cinematic-chat.css"), "utf8");
  assert.match(cinematic, /@import url\('\.\/padiem-foundation\.css\?v=ab12cd34'\)/);
  const transport = await readFile(path.join(out, "chat-transport.js"), "utf8");
  const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
  const repoTransport = await readFile(
    path.join(repoRoot, "apps", "padiem-chat", "static", "chat-transport.js"), "utf8");
  assert.equal(transport, repoTransport);
});

test("a write is never retried on a second upstream and answers the maintenance page", async () => {
  const out = await assembled();
  const { default: worker } = await import(pathToFileURL(path.join(out, "_worker.js")).href);
  const original = globalThis.fetch;
  globalThis.fetch = async () => {
    throw new TypeError("connect ECONNREFUSED");
  };
  try {
    const response = await worker.fetch(
      edgeRequest("https://padiem-chat.pages.dev/api/projects", { method: "POST" }),
      baseEnv(),
    );
    assert.equal(response.status, 503);
    assert.equal(response.headers.get("x-padiem-front"), "write_com2_canonical_refused");
  } finally {
    globalThis.fetch = original;
  }
});

test("#6924 operational probes only target registered chat health routes", async () => {
  const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
  const server = await readFile(
    path.join(repoRoot, "apps", "padiem-chat", "app", "app_factory.py"),
    "utf8",
  );
  assert.match(server, /Route\("\/health",/, "Chat must keep GET /health registered");
  assert.doesNotMatch(server, /Route\("\/api\/health"/, "Chat must not register /api/health");

  const forbidden = ["/api/" + "health", "/api/" + "models"];
  const roots = ["."];
  const codeExt = new Set([".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".yml", ".yaml"]);
  // This test intentionally requests a removed route in-process to pin its
  // absence; it never sends the path over the network.
  const intentionalAbsence = new Set([
    "apps/padiem-chat/tests/test_owner_model_preview_contract.py",
  ]);
  const offenders = [];
  async function walk(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      if (
        ["node_modules", "dist", ".git", ".venv", "venv", "vendor", "build", "coverage", "__pycache__"].includes(
          entry.name,
        )
      ) {
        continue;
      }
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        await walk(full);
        continue;
      }
      if (!codeExt.has(path.extname(entry.name))) continue;
      if (path.resolve(full) === fileURLToPath(import.meta.url)) continue;
      const rel = path.relative(repoRoot, full).split(path.sep).join("/");
      if (intentionalAbsence.has(rel)) continue;
      const text = await readFile(full, "utf8");
      for (const needle of forbidden) {
        if (text.includes(needle)) offenders.push(`${rel}: ${needle}`);
      }
    }
  }
  for (const root of roots) await walk(path.join(repoRoot, root));
  assert.deepEqual(offenders, [], "probes must use /health (Chat) or /api/pilot/... (B14)");
});

test("the generated _routes.json serves the shell and pretty urls from the static layer", async () => {
  const out = await assembled();
  const routes = JSON.parse(await readFile(path.join(out, "_routes.json"), "utf8"));
  // Pages advanced mode runs the function for every INCLUDED request: the
  // shell and root-level pages must be EXCLUDED so the static layer serves
  // the stamped dist/index.html and the default .html omission instead of
  // proxying to COM2 (#7130-era mirror; 5th deploy root).
  assert.deepEqual(routes.include, ["/*"]);
  for (const staticPath of ["/", "/index.html", "/privacy", "/terms"]) {
    assert.ok(routes.exclude.includes(staticPath), `${staticPath} excluded`);
  }
  assert.equal(new Set(routes.exclude).size, routes.exclude.length,
    "no duplicate exclude rules");
  assert.ok(!routes.exclude.includes("/index"));
  // A bare "/" has no wildcard, so console/SPA subpaths stay on the proxy.
  assert.ok(!routes.exclude.includes("/c/*"));
  assert.ok(!routes.exclude.includes("/claw"));
  // The include/exclude rules stay far below the 100-rule ceiling.
  assert.ok(routes.include.length + routes.exclude.length < 100);
  const redirectsGone = await readFile(path.join(out, "_redirects"), "utf8").then(
    () => true,
    () => false,
  );
  assert.equal(redirectsGone, false, "_redirects is not applied in advanced mode and must not ship");
});
