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
 *   read (GET/HEAD/OPTIONS)  com2 health failure/connection refusal → FALLBACK_MODE:
 *                              service → env.CHAT_WORKER.fetch(request)
 *                              static  → 503 maintenance page
 *   write                    com2 health failure/connection refusal →
 *                              COM2_CANONICAL != "writes": same fallback rules
 *                              COM2_CANONICAL  == "writes": 503 maintenance,
 *                              NEVER the Python Worker (data must not split).
 *
 * Redirects are forwarded with redirect:"manual" so a Google/OAuth 302 reaches
 * the browser instead of being followed inside the Worker.
 */

import { newRequestId, signedRequestHeaders } from "./edge-proof.mjs";
import { errorPageHtml, wantsHtml } from "./error-copy.mjs";

const READ_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const DEFAULT_HEALTH_TTL_MS = 10000;
const DEFAULT_TIMEOUT_MS = 8000;
// A tool call can wait while a common Claw background command is running. The
// MCP response ceiling is separate from the PC process lifetime.
const DEFAULT_MCP_TIMEOUT_MS = 180000;
// #6735: the orchestration answer is one buffered JSON document, so its deadline
// covers the whole model pipeline. The generic 8s write window is far too short
// for it; 60s is the CTO's fixed ceiling, and a configured ORCHESTRATION_TIMEOUT_MS
// still takes precedence.
const DEFAULT_ORCHESTRATION_TIMEOUT_MS = 60000;
// #6460: every path whose answer is produced by a model call behind COM2 needs the
// same first-byte deadline as /api/orchestration — what is slow is the answer, not
// the write (guest /api/chat/stream measured 504 at 9.9s against the 8s window while
// the same answer completes in ~10-11s). Ordinary writes — saves, settings, files,
// account, connectors — deliberately stay on the 8s window.
const ANSWER_GENERATION_PATHS = new Set([
  "/api/orchestration",
  "/api/orchestration/resume",
  "/api/chat",
  "/api/chat/stream",
  "/api/claw/general",
  "/api/claw/manual-intake/execute",
  "/api/claw/manual-intake/preview",
  "/api/b66/ai/chat",
]);
const DEFAULT_API_READ_TIMEOUT_MS = 30000;
// Resumable chunked uploads (tus, /api/projects/*/files/tus) hold the request
// open while a ≤90MB chunk drains to COM2 — a healthy upload must not die on
// the plain write deadline. PATCH/POST on those paths get their own allowance
// (TUS_UPLOAD_TIMEOUT_MS); the HEAD offset check keeps the API read deadline.
const DEFAULT_TUS_TIMEOUT_MS = 180000;
// The common-login callback is a redirect, but COM2 only answers it after an OAuth
// exchange, a JWKS verification and an identity RPC. Under the plain read deadline
// the browser saw upstream_timeout while the host was still finishing the login, so
// this one path gets its own allowance; every other /auth/* keeps the short one.
const DEFAULT_AUTH_CALLBACK_TIMEOUT_MS = 30000;
// The login write (/api/auth/*) waits on the same host work as the callback: an
// OAuth exchange, a JWKS-verified token and the canonical identity RPC. Measured
// on the host: 52 events over 3 days where resolve_or_create_product_link alone
// ran past the 5s window and the front answered a cookie-less 504 while the
// session was created right after it. #6957 lightened that RPC; until its effect
// is measured, the login write keeps its own window so the cookie the host
// already made reaches the browser. Every other write keeps the generic window.
const DEFAULT_AUTH_WRITE_TIMEOUT_MS = 30000;
// #7293: a voice STT write waits on the STT Worker's own bounded upstream
// budget (the token mint and the file transcription each allow the upstream
// 8s/25s inside apps/padiem-voice-stt/voice_stt_contract.py), and the mint
// rides the host→Chat-Worker RPC on top (measured on the host: 5.7s, 7.1s and
// 7.6s total on 2026-11-08/09 — the 7.6s one was a 200 the front still cut at
// the generic 8s window, and the browser lost the same race). Like the login
// write, these two writes get their own allowance; every other write keeps
// the generic window.
const DEFAULT_VOICE_STT_WRITE_TIMEOUT_MS = 30000;
const TIMED_OUT = Symbol("timed_out");
const CONNECTION_REFUSED = Symbol("connection_refused");
const TRANSPORT_FAILED = Symbol("transport_failed");
const SIGNING_FAILED = Symbol("signing_failed");
// 답변 시간 예산: one request id crosses the front door in both directions. Chat's
// telemetry accepts a bounded client-supplied id and echoes it as X-Request-Id,
// so the same value on a front-generated timeout ties the two logs together.
const REQUEST_ID_RE = /^[A-Za-z0-9._:-]{8,64}$/;

function requestIdFor(request) {
  const incoming = request.headers.get("x-request-id");
  if (incoming && REQUEST_ID_RE.test(incoming)) return incoming;
  return newRequestId();
}

export const MAINTENANCE_HTML = `<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>잠시 점검 중</title>
<style>body{font-family:system-ui,sans-serif;margin:0;display:grid;place-items:center;min-height:100vh;background:#0f1115;color:#e8eaf0}main{text-align:center;padding:24px}h1{font-size:1.25rem;font-weight:600}p{color:#9aa3b2}</style>
</head><body><main><h1>잠시 점검 중입니다</h1><p>곧 다시 이용할 수 있습니다. 잠시 후 새로고침해 주세요.</p></main></body></html>`;

function maintenanceResponse(reason, requestId) {
  return new Response(MAINTENANCE_HTML, {
    status: 503,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "retry-after": "120",
      "x-padiem-front": reason,
      ...(requestId ? { "x-request-id": requestId } : {}),
    },
  });
}

function numeric(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function connectionRefused(error) {
  const cause = error?.cause;
  return error?.code === "ECONNREFUSED" || cause?.code === "ECONNREFUSED" ||
    /\b(?:ECONNREFUSED|connect(?:ion)? (?:failed|refused))\b/i.test(String(error?.message || ""));
}

function requestFailure(request, status, code, requestId) {
  // A browser that navigated here must not be shown the JSON body it cannot
  // read as a page; a machine call keeps the JSON it parses.
  if (wantsHtml(request)) {
    return new Response(errorPageHtml(code, new URL(request.url).pathname), {
      status,
      headers: {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "no-store, max-age=0",
        "retry-after": "30",
        "x-padiem-front": code,
        ...(requestId ? { "x-request-id": requestId } : {}),
      },
    });
  }
  return new Response(JSON.stringify({ error: { code, message: "요청을 처리하지 못했습니다. 다시 시도해 주세요." } }), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...(requestId ? { "x-request-id": requestId } : {}),
    },
  });
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

  function withOrchestrationTotal(response, started, status, path = "/api/orchestration") {
    // The total covers exactly the upstream answer: the log line prints when
    // the upstream body has fully streamed through. The bytes pass through
    // untouched — lengths only, never the body, never cookies, never identity.
    const ttfb = Math.round(now() - started);
    const { readable, writable } = new TransformStream();
    response.body.pipeTo(writable).then(() => {
      console.log(`orchestration_timing path=${path} status=${status} ttfb_ms=${ttfb} total_ms=${Math.round(now() - started)}`);
    }).catch(() => {
      console.log(`orchestration_timing path=${path} status=${status} ttfb_ms=${ttfb} total_ms=stream_aborted`);
    });
    return new Response(readable, {
      status: response.status, statusText: response.statusText, headers: response.headers,
    });
  }

  async function forward(request, target, env, timeoutMs, { requestId = null, answerBudgetMs = null } = {}) {
    let headers;
    try {
      headers = await sign(request, env.PADIEM_COM2_EDGE_SECRET);
    } catch {
      // A local signing/configuration error is not evidence that COM2 is down.
      return SIGNING_FAILED;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      headers.delete("host");
      headers.set("x-forwarded-host", new URL(request.url).host);
      headers.set("x-forwarded-proto", "https");
      if (requestId) headers.set("x-request-id", requestId);
      if (answerBudgetMs) headers.set("x-padiem-answer-budget-ms", String(answerBudgetMs));
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
    } catch (error) {
      clearTimeout(timer);
      if (controller.signal.aborted) return TIMED_OUT;
      return connectionRefused(error) ? CONNECTION_REFUSED : TRANSPORT_FAILED;
    }
  }

  async function fallback(request, env, isWrite, requestId = null) {
    const mode = String(env.FALLBACK_MODE || "static").trim().toLowerCase();
    if (mode === "service" && env.CHAT_WORKER && typeof env.CHAT_WORKER.fetch === "function") {
      try {
        const response = await env.CHAT_WORKER.fetch(request);
        if (response) return response;
      } catch {
        // The fallback itself failing falls through to the honest static answer.
      }
    }
    return maintenanceResponse(isWrite ? "write_refused" : "read_fallback_static", requestId);
  }

  // Static answers carry a short fresh window plus background revalidation.
  // The static URLs are not content-versioned, so a long immutable lifetime
  // would pin a stale UI after a deploy; 300s keeps a session's repeat
  // navigations off the network (the ~150-request first-load spike) while
  // (no stale-while-revalidate: static URLs carry no version yet, so an old script must not outlive a deploy by more than the 5-minute window) refreshes
  // it in the background. HTML is never cached: it must pick up a new deploy.
  const STATIC_CACHE_CONTROL = "private, max-age=300";
  function withStaticCache(response) {
    const type = response.headers.get("content-type") || "";
    if (!response.ok) return response;
    const headers = new Headers(response.headers);
    if (type.includes("text/html")) {
      // Say no-cache explicitly: the assets default (max-age=0, must-revalidate)
      // is close, but a few mobile browsers round it down to heuristic caching,
      // and index.html is the file that pins which asset version a tab runs.
      // no-cache keeps storing + ETag revalidation, it just removes the guess.
      headers.set("cache-control", "no-cache");
    } else {
      headers.set("cache-control", STATIC_CACHE_CONTROL);
    }
    return new Response(response.body, {
      status: response.status, statusText: response.statusText, headers,
    });
  }

  return async function handle(request, env) {
    const url = new URL(request.url);
    const requestId = requestIdFor(request);
    // MCP OAuth endpoints and metadata are dynamic, no-store responses. Keep
    // them out of the static asset/cache branch and give them the API-read
    // budget (DB + redirect work) instead of the generic proxy deadline.
    const oauthRequest = url.pathname.startsWith("/oauth/") ||
      url.pathname.startsWith("/.well-known/oauth-");
    const staticPath = (request.method === "GET" || request.method === "HEAD") && !oauthRequest;
    if (staticPath && env.ASSETS && (url.pathname === "/" || /^\/[^/]+\.(?:js|css|png|jpg|jpeg|svg|ico|webp|woff2?)$/i.test(url.pathname) || url.pathname.startsWith("/static/"))) {
      const asset = await env.ASSETS.fetch(request);
      if (asset.status !== 404) return withStaticCache(asset);
    }
    const origin = originEnv(env);
    const target = new URL(url.pathname + url.search, origin);
    const isWrite = !READ_METHODS.has(request.method);
    const canonicalWrites = String(env.COM2_CANONICAL || "off").trim().toLowerCase() === "writes";
    // App AI needs time for a completed model response; records stay on COM2.
    const appsAI = request.method === "POST" && url.pathname === "/api/apps/ai";
    const bookAIRecords = url.pathname === "/api/bookai/records";
    const authCallback = READ_METHODS.has(request.method) && url.pathname === "/auth/shared/callback";
    const authWrite = !READ_METHODS.has(request.method) && url.pathname.startsWith("/api/auth/");
    const voiceSttWrite = !READ_METHODS.has(request.method) &&
      (url.pathname === "/api/voice/live-token" || url.pathname === "/api/voice/transcribe");
    const tusWrite = (request.method === "PATCH" || request.method === "POST") &&
      /^\/api\/projects\/[^/]+\/files\/tus(?:\/|$)/.test(url.pathname);
    const upstreamTimeout = numeric(env.UPSTREAM_TIMEOUT_MS, DEFAULT_TIMEOUT_MS);
    const healthProbe = url.pathname === "/health" && (request.method === "GET" || request.method === "HEAD");
    const streaming = /text\/event-stream/i.test(request.headers.get("accept") || "") ||
      (request.headers.get("upgrade") || "").toLowerCase() === "websocket";
    const apiRead = !isWrite && url.pathname.startsWith("/api/") && !streaming;
    // #6460 4-2 / #6735: the orchestration answer is one buffered JSON document,
    // so this deadline is the WHOLE request — the model pipeline behind it can
    // legitimately run past the generic write window (measured 504 at ~13.5s and
    // 11.2s worst case on 2026-11-03). The default is the CTO's 60s ceiling; a
    // configured ORCHESTRATION_TIMEOUT_MS still wins.
    const answerRequest = request.method === "POST" && ANSWER_GENERATION_PATHS.has(url.pathname);
    const mcpRequest = request.method === "POST" && url.pathname === "/api/mcp";
    const timeoutMs = oauthRequest
      ? numeric(env.API_READ_TIMEOUT_MS, DEFAULT_API_READ_TIMEOUT_MS)
      : answerRequest
      ? numeric(env.ORCHESTRATION_TIMEOUT_MS, DEFAULT_ORCHESTRATION_TIMEOUT_MS)
      : mcpRequest
      ? numeric(env.MCP_TIMEOUT_MS, DEFAULT_MCP_TIMEOUT_MS)
      : appsAI
      ? numeric(env.APPS_AI_TIMEOUT_MS, 65000)
      : apiRead ? numeric(env.API_READ_TIMEOUT_MS, DEFAULT_API_READ_TIMEOUT_MS)
      : authCallback ? numeric(env.AUTH_CALLBACK_TIMEOUT_MS, DEFAULT_AUTH_CALLBACK_TIMEOUT_MS)
      : tusWrite ? numeric(env.TUS_UPLOAD_TIMEOUT_MS, DEFAULT_TUS_TIMEOUT_MS)
      : authWrite ? numeric(env.AUTH_WRITE_TIMEOUT_MS, DEFAULT_AUTH_WRITE_TIMEOUT_MS)
      : voiceSttWrite ? numeric(env.VOICE_STT_WRITE_TIMEOUT_MS, DEFAULT_VOICE_STT_WRITE_TIMEOUT_MS)
        : upstreamTimeout;
    // 답변 시간 예산: Chat derives the remaining Engine budget from this value. Only an
    // answer request carries it; ordinary writes keep their existing wire shape.
    const answerBudgetMs = answerRequest ? timeoutMs : null;

    if (isWrite) {
      const started = now();
      const response = await forward(request, target, env, timeoutMs, { requestId, answerBudgetMs });
      if (answerRequest) {
        // One line per answer request: path, status, time to first byte, total time.
        // Never the body, never cookies, never identity.
        if (response instanceof Response) {
          const ttfb = Math.round(now() - started);
          const headers = new Headers(response.headers);
          headers.set("x-padiem-orchestration-ttfb-ms", String(ttfb));
          // 답변 시간 예산: an edge-generated error page carries no request id; keep the
          // one the front sent upstream so the browser can report the turn.
          if (!headers.has("x-request-id")) headers.set("x-request-id", requestId);
          // #6742: an NDJSON answer streams through untouched. The deadline above
          // covered the first byte only — it was cleared when the headers arrived.
          if ((response.headers.get("content-type") || "").toLowerCase().includes("application/x-ndjson")) {
            headers.set("cache-control", "no-store");
          }
          const timed = new Response(response.body, {
            status: response.status, statusText: response.statusText, headers,
          });
          return withOrchestrationTotal(timed, started, response.status, url.pathname);
        }
        console.log(`orchestration_timing path=${url.pathname} status=upstream_${response.description ?? String(response)} ttfb_ms=${Math.round(now() - started)} total_ms=${Math.round(now() - started)}`);
      }
      if (response === SIGNING_FAILED) return maintenanceResponse("write_refused", requestId);
      if (response === TIMED_OUT) return requestFailure(request, 504, "upstream_timeout", requestId);
      if (response === TRANSPORT_FAILED) return requestFailure(request, 502, "upstream_transport_failed", requestId);
      if (response !== CONNECTION_REFUSED) return response;
      markFailure(origin.toString());
      // An answer is never handed to a second upstream: a refused connection could
      // have arrived after the model already started, and re-sending would run the
      // same question twice. Report it instead; the client decides.
      if (answerRequest) return requestFailure(request, 503, "upstream_refused", requestId);
      if (canonicalWrites || appsAI || bookAIRecords) return maintenanceResponse("write_com2_canonical_refused", requestId);
      return fallback(request, env, true, requestId);
    }

    const healthTtlMs = numeric(env.HEALTH_TTL_MS, DEFAULT_HEALTH_TTL_MS);
    if (healthy(origin.toString(), healthTtlMs)) {
      const response = await forward(request, target, env, timeoutMs, { requestId });
      if (response === SIGNING_FAILED) return maintenanceResponse("read_fallback_static", requestId);
      if (healthProbe) {
        if (response !== TIMED_OUT && response !== CONNECTION_REFUSED &&
            response !== TRANSPORT_FAILED && response.status >= 200 && response.status < 300) return response;
        markFailure(origin.toString());
      } else {
        if (response === TIMED_OUT) return requestFailure(request, 504, "upstream_timeout", requestId);
        if (response === TRANSPORT_FAILED) return requestFailure(request, 502, "upstream_transport_failed", requestId);
        if (response !== CONNECTION_REFUSED) return response;
        markFailure(origin.toString());
      }
    }
    if (bookAIRecords) return maintenanceResponse("bookai_records_com2_unavailable", requestId);
    return fallback(request, env, false, requestId);
  };
}

const handler = createFront();

export default {
  fetch(request, env) {
    return handler(request, env);
  },
};
