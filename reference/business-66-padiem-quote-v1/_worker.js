const PADIEM_CHAT_ORIGIN = "https://chat.padiem.net";
const INTAKE_PATH = "/api/v1/quote/intake";
const PADIEM_PREFIX = "/api/padiem";
const MAX_PADIEM_BODY_BYTES = 32 * 1024;
const SAVED_SKILL_ROW = /^b66skill_[0-9a-f]{32}$/;
const B66_ASSET_ROW = /^b66asset_[0-9a-f]{32}$/;

function jsonError(code, status) {
  return new Response(JSON.stringify({ ok: false, error: { code } }), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    }
  });
}

/* Policy A (P0 CGI pilot): standalone intake provider forwarding 은 fail-closed 로 비활성화한다.
   이 경로는 익명 호출자가 cost-bearing provider/model 호출을 유발할 수 있는 extraction relay 였으므로,
   요청 모양(메서드/크기/본문)을 판별하기 전에 어떤 호출도 하지 않고 bounded disabled 응답으로 닫는다.
   provider 내부 정보(B14 URL 등)는 응답에 노출하지 않는다. */
function handleIntake() {
  return jsonError("intake_disabled", 410);
}

function padiemTarget(url, method) {
  const path = url.pathname;
  const exact = new Map([
    ["/api/padiem/auth/status", ["GET", "/api/auth/status"]],
    ["/api/padiem/auth/password/login", ["POST", "/api/auth/password/login"]],
    ["/api/padiem/auth/password/register", ["POST", "/api/auth/password/register"]],
    ["/api/padiem/auth/google/start", ["GET", "/auth/google/start"]],
    ["/api/padiem/auth/google/callback", ["GET", "/auth/google/callback"]],
    ["/api/padiem/auth/logout", ["POST", "/api/auth/logout"]],
    ["/api/padiem/b66/company-profile", ["GET", "/api/b66/company-profile"]],
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

  const assetPrefix = "/api/padiem/b66/assets/";
  if (path.startsWith(assetPrefix) && method === "GET") {
    const id = path.slice(assetPrefix.length);
    if (!B66_ASSET_ROW.test(id)) return null;
    return "/api/b66/assets/" + id;
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
  headers.set("X-B66-Origin", url.origin);
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
  for (const name of [
    "X-B66-Rejection-Reason",
    "X-B66-Rejection-Path",
    "X-B66-Rejection-Type"
  ]) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
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