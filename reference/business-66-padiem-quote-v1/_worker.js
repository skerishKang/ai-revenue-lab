const B14_IMAGE_EXTRACTION_URL =
  "https://ai-revenue-korean-ai-platform.charliekant.workers.dev/api/b66/v1/quote/extract-image";
const B14_DOCUMENT_EXTRACTION_URL =
  "https://ai-revenue-korean-ai-platform.charliekant.workers.dev/api/b66/v1/quote/extract-document";
const PADIEM_CHAT_ORIGIN = "https://chat.padiem.net";
const INTAKE_PATH = "/api/v1/quote/intake";
const PADIEM_PREFIX = "/api/padiem";
const MAX_REQUEST_BYTES = 6 * 1024 * 1024;
const MAX_RESPONSE_BYTES = 1024 * 1024;
const MAX_PADIEM_BODY_BYTES = 32 * 1024;
const IMAGE_MEDIA = new Set(["image/jpeg", "image/png", "image/webp"]);
const SAVED_SKILL_ROW = /^b66skill_[0-9a-f]{32}$/;

function jsonError(code, status) {
  return new Response(JSON.stringify({ ok: false, error: { code } }), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    }
  });
}

function upstreamForBody(body) {
  let payload;
  try {
    payload = JSON.parse(new TextDecoder().decode(body));
  } catch (_) {
    return null;
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  return IMAGE_MEDIA.has(payload.media_type)
    ? B14_IMAGE_EXTRACTION_URL
    : B14_DOCUMENT_EXTRACTION_URL;
}

async function handleIntake(request) {
  if (request.method !== "POST") return jsonError("method_not_allowed", 405);
  const type = (request.headers.get("content-type") || "").split(";", 1)[0].trim().toLowerCase();
  if (type !== "application/json") return jsonError("invalid_content_type", 415);

  const length = Number(request.headers.get("content-length") || "0");
  if (Number.isFinite(length) && length > MAX_REQUEST_BYTES) {
    return jsonError("request_too_large", 413);
  }

  const body = await request.arrayBuffer();
  if (!body.byteLength || body.byteLength > MAX_REQUEST_BYTES) {
    return jsonError("request_too_large", 413);
  }

  const upstreamUrl = upstreamForBody(body);
  if (!upstreamUrl) return jsonError("invalid_request", 422);

  let upstream;
  try {
    upstream = await fetch(upstreamUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json"
      },
      body
    });
  } catch (_) {
    return jsonError("analysis_service_unavailable", 502);
  }

  const responseBody = await upstream.arrayBuffer();
  if (responseBody.byteLength > MAX_RESPONSE_BYTES) {
    return jsonError("analysis_response_too_large", 502);
  }

  return new Response(responseBody, {
    status: upstream.status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    }
  });
}

function padiemTarget(url, method) {
  const path = url.pathname;
  const exact = new Map([
    ["/api/padiem/auth/status", ["GET", "/api/auth/status"]],
    ["/api/padiem/auth/password/login", ["POST", "/api/auth/password/login"]],
    ["/api/padiem/auth/password/register", ["POST", "/api/auth/password/register"]],
    ["/api/padiem/auth/google/start", ["GET", "/api/auth/google/start"]],
    ["/api/padiem/auth/google/callback", ["GET", "/api/auth/google/callback"]],
    ["/api/padiem/auth/logout", ["POST", "/api/auth/logout"]],
    ["/api/padiem/b66/quote/interpret", ["POST", "/api/b66/quote/interpret"]]
  ]);
  if (exact.has(path)) {
    const [allowedMethod, upstreamPath] = exact.get(path);
    return method === allowedMethod ? upstreamPath : null;
  }

  if (path === "/api/padiem/b66/saved-skills" && method === "GET") {
    const raw = url.searchParams.get("limit");
    if (raw === null) return "/api/b66/saved-skills";
    if (!/^\d{1,2}$/.test(raw)) return null;
    const limit = Number(raw);
    if (!Number.isInteger(limit) || limit < 1 || limit > 20) return null;
    return "/api/b66/saved-skills?limit=" + String(limit);
  }

  const prefix = "/api/padiem/b66/saved-skills/";
  if (path.startsWith(prefix) && method === "GET") {
    const id = path.slice(prefix.length);
    if (!SAVED_SKILL_ROW.test(id)) return null;
    return "/api/b66/saved-skills/" + id;
  }
  return null;
}

function relaySetCookies(source, target) {
  const getSetCookie = source && typeof source.getSetCookie === "function"
    ? source.getSetCookie.bind(source)
    : null;
  const values = getSetCookie ? getSetCookie() : [];
  if (Array.isArray(values) && values.length) {
    values.forEach((value) => target.append("Set-Cookie", value));
    return;
  }
  const one = source ? source.get("set-cookie") : null;
  if (one) target.append("Set-Cookie", one);
}

async function handlePadiemBridge(request, url, env) {
  const upstreamPath = padiemTarget(url, request.method);
  if (!upstreamPath) return jsonError("padiem_route_not_allowed", 404);

  const headers = new Headers({ "Accept": "application/json" });
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("Cookie", cookie);
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);

  let body;
  if (request.method !== "GET" && request.method !== "HEAD") {
    const length = Number(request.headers.get("content-length") || "0");
    if (Number.isFinite(length) && length > MAX_PADIEM_BODY_BYTES) {
      return jsonError("request_too_large", 413);
    }
    body = await request.arrayBuffer();
    if (body.byteLength > MAX_PADIEM_BODY_BYTES) {
      return jsonError("request_too_large", 413);
    }
  }

  const target = new URL(upstreamPath, PADIEM_CHAT_ORIGIN);
  const init = {
    method: request.method,
    headers,
    body,
    redirect: "manual"
  };

  let upstream;
  try {
    const binding = env && env.PADIEM_CHAT_SERVICE;
    if (binding && typeof binding.fetch === "function") {
      upstream = await binding.fetch(new Request(target, init));
    } else {
      upstream = await fetch(target, init);
    }
  } catch (_) {
    return jsonError("padiem_service_unavailable", 502);
  }

  const responseHeaders = new Headers({
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache"
  });
  const upstreamType = upstream.headers.get("content-type");
  if (upstreamType) responseHeaders.set("Content-Type", upstreamType);
  relaySetCookies(upstream.headers, responseHeaders);
  const location = upstream.headers.get("location");
  if (location && upstream.status >= 300 && upstream.status < 400) {
    responseHeaders.set("Location", location);
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === INTAKE_PATH) {
      return handleIntake(request);
    }
    if (url.pathname === PADIEM_PREFIX || url.pathname.startsWith(PADIEM_PREFIX + "/")) {
      return handlePadiemBridge(request, url, env);
    }
    return env.ASSETS.fetch(request);
  }
};
