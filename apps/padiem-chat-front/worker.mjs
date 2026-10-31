/**
 * padiem-chat-front — the #5573 stage-4 front door for chat.padiem.net.
 *
 * Pure proxy: the request body, response body, streaming (SSE) and WebSocket
 * upgrade all pass through untouched. No body reads, no JSON/HTML rewriting, no
 * crypto — the 10 ms free-plan CPU budget is spent on URL/header assembly and
 * one fetch. A response is returned as the exact object fetch produced, which
 * is what keeps Set-Cookie (multiple) and 101 upgrades intact.
 *
 * Fallback (stage 4, request-scoped with a SHORT health cache):
 *   read (GET/HEAD/OPTIONS)  com2 unreachable/5xx/timeout → FALLBACK_MODE:
 *                              service → env.CHAT_WORKER.fetch(request)
 *                              static  → 503 maintenance page
 *   write                    com2 unreachable/5xx/timeout →
 *                              COM2_CANONICAL != "writes": same fallback rules
 *                              COM2_CANONICAL  == "writes": 503 maintenance,
 *                              NEVER the Python Worker (data must not split).
 *
 * Redirects are forwarded with redirect:"manual" so a Google/OAuth 302 reaches
 * the browser instead of being followed inside the Worker.
 */

import { signedRequestHeaders } from "./edge-proof.mjs";

const READ_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const DEFAULT_HEALTH_TTL_MS = 10000;
const DEFAULT_TIMEOUT_MS = 8000;

export const MAINTENANCE_HTML = `<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>잠시 점검 중</title>
<style>body{font-family:system-ui,sans-serif;margin:0;display:grid;place-items:center;min-height:100vh;background:#0f1115;color:#e8eaf0}main{text-align:center;padding:24px}h1{font-size:1.25rem;font-weight:600}p{color:#9aa3b2}</style>
</head><body><main><h1>잠시 점검 중입니다</h1><p>곧 다시 이용할 수 있습니다. 잠시 후 새로고침해 주세요.</p></main></body></html>`;

function maintenanceResponse(reason) {
  return new Response(MAINTENANCE_HTML, {
    status: 503,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "retry-after": "120",
      "x-padiem-front": reason,
    },
  });
}

function numeric(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function originEnv(env) {
  const raw = String(env.FRONT_ORIGIN || "").trim();
  if (!raw) throw new Error("FRONT_ORIGIN is required");
  const origin = new URL(raw);
  if (origin.protocol !== "https:") throw new Error("FRONT_ORIGIN must be https");
  return origin;
}

export function createFront({ fetchImpl = (...args) => fetch(...args), now = () => Date.now(), sign = signedRequestHeaders } = {}) {
  // origin -> timestamp of the last upstream failure (short, request-scoped use)
  const unhealthySince = new Map();

  function healthy(origin, ttlMs) {
    const since = unhealthySince.get(origin);
    if (since === undefined) return true;
    return now() - since > ttlMs;
  }

  function markFailure(origin) {
    unhealthySince.set(origin, now());
  }

  async function forward(request, target, env, timeoutMs) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const headers = await sign(request, env.PADIEM_COM2_EDGE_SECRET);
      headers.delete("host");
      headers.set("x-forwarded-host", new URL(request.url).host);
      headers.set("x-forwarded-proto", "https");
      const ip = request.headers.get("cf-connecting-ip");
      if (ip) {
        const prior = request.headers.get("x-forwarded-for");
        headers.set("x-forwarded-for", prior ? `${prior}, ${ip}` : ip);
        headers.set("x-real-ip", ip);
      }
      const init = { method: request.method, headers, redirect: "manual", signal: controller.signal };
      if (request.method !== "GET" && request.method !== "HEAD") {
        init.body = request.body;
        init.duplex = "half";
      }
      const response = await fetchImpl(new Request(target.toString(), init));
      // Headers are in: the stream may outlive any deadline (SSE); never abort it.
      clearTimeout(timer);
      return response;
    } catch {
      clearTimeout(timer);
      return null;
    }
  }

  async function fallback(request, env, isWrite) {
    const mode = String(env.FALLBACK_MODE || "static").trim().toLowerCase();
    if (mode === "service" && env.CHAT_WORKER && typeof env.CHAT_WORKER.fetch === "function") {
      try {
        const response = await env.CHAT_WORKER.fetch(request);
        if (response) return response;
      } catch {
        // The fallback itself failing falls through to the honest static answer.
      }
    }
    return maintenanceResponse(isWrite ? "write_refused" : "read_fallback_static");
  }

  return async function handle(request, env) {
    const url = new URL(request.url);
    const staticPath = request.method === "GET" || request.method === "HEAD";
    if (staticPath && env.ASSETS && (url.pathname === "/" || /^\/[^/]+\.(?:js|css|png|jpg|jpeg|svg|ico|webp|woff2?)$/i.test(url.pathname) || url.pathname.startsWith("/static/"))) {
      const asset = await env.ASSETS.fetch(request);
      if (asset.status !== 404) return asset;
    }
    const origin = originEnv(env);
    const target = new URL(url.pathname + url.search, origin);
    const isWrite = !READ_METHODS.has(request.method);
    const canonicalWrites = String(env.COM2_CANONICAL || "off").trim().toLowerCase() === "writes";
    const timeoutMs = numeric(env.UPSTREAM_TIMEOUT_MS, DEFAULT_TIMEOUT_MS);

    if (isWrite) {
      const response = await forward(request, target, env, timeoutMs);
      if (response && response.status < 500) return response;
      markFailure(origin.toString());
      if (canonicalWrites) return maintenanceResponse("write_com2_canonical_refused");
      return fallback(request, env, true);
    }

    const healthTtlMs = numeric(env.HEALTH_TTL_MS, DEFAULT_HEALTH_TTL_MS);
    if (healthy(origin.toString(), healthTtlMs)) {
      const response = await forward(request, target, env, timeoutMs);
      if (response && response.status < 500) return response;
      markFailure(origin.toString());
    }
    return fallback(request, env, false);
  };
}

const handler = createFront();

export default {
  fetch(request, env) {
    return handler(request, env);
  },
};
