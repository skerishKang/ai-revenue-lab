const PADIEM_CHAT_ORIGIN = "https://chat.padiem.net";
const INTAKE_PATH = "/api/v1/quote/intake";
const PADIEM_PREFIX = "/api/padiem";
const MAX_PADIEM_BODY_BYTES = 32 * 1024;
const SAVED_SKILL_ROW = /^b66skill_[0-9a-f]{32}$/;
const B66_ASSET_ROW = /^b66asset_[0-9a-f]{32}$/;
const B66_QUOTE_ROW = /^b66quote_[0-9a-f]{32}$/;
const MAX_QUOTE_HISTORY_LIMIT = 50;
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const SESSION_COOKIE_NAME = "padiem_session";

function carriesSessionCookie(cookieHeader) {
  return String(cookieHeader || "").split(";").some((part) => {
    const eq = part.indexOf("=");
    const name = (eq === -1 ? part : part.slice(0, eq)).trim();
    return name === SESSION_COOKIE_NAME;
  });
}

function bridgeMutationOriginAllowed(request, url) {
  if (!MUTATING_METHODS.has(request.method)) return true;
  if (!carriesSessionCookie(request.headers.get("cookie"))) return true;
  return request.headers.get("origin") === url.origin;
}

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
    ["/api/padiem/b66/quote/interpret", ["POST", "/api/b66/quote/interpret"]],
    ["/api/padiem/b66/quote/models", ["GET", "/api/b66/quote/models"]],
    ["/api/padiem/b66/quote/preview-base", ["GET", "/api/b66/quote/preview-base"]],
    ["/api/padiem/b66/quote/pdf", ["POST", "/api/b66/quote/pdf"]]
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

  /* #3405 Slice B: canonical quote-history 프록시. 서버가 세션에서 owner/
     workspace 를 도출하므로 브리지는 경로/limit/기록 id 형태만 경계한다. */
  if (path === "/api/padiem/b66/quotes" && (method === "GET" || method === "POST")) {
    if (method === "POST") return "/api/b66/quotes";
    const raw = url.searchParams.get("limit");
    if (raw === null) return "/api/b66/quotes";
    if (!/^\d{1,2}$/.test(raw)) return null;
    const limit = Number(raw);
    if (!Number.isInteger(limit) || limit < 1 || limit > MAX_QUOTE_HISTORY_LIMIT) return null;
    return "/api/b66/quotes?limit=" + String(limit);
  }

  const quotePrefix = "/api/padiem/b66/quotes/";
  if (path.startsWith(quotePrefix) && (method === "GET" || method === "DELETE")) {
    const id = path.slice(quotePrefix.length);
    if (!B66_QUOTE_ROW.test(id)) return null;
    return "/api/b66/quotes/" + id;
  }
  return null;
}

/* ── #3871 B66 브라우저 Drive 설정 전달 경로 ──
   Pages 프로젝트 환경변수(B66 전용)에서 **공개 브라우저 값만** 읽어 정확한 경로로 제공한다.
   - 값이 없거나 형식이 틀리면 빈 문자열을 내보낸다(fail-closed). 기능은 비활성으로 남는다.
   - 자격증명·토큰·서버 시크릿은 어떤 경우에도 내보내지 않고, 오류 응답에도 값을 담지 않는다.
   - 기존 정적 자산 경로(env.ASSETS.fetch)와 PADIEM 프록시는 그대로 둔다. */
const DRIVE_CONFIG_PATH = "/drive-config.js";
const DRIVE_CONFIG_ENV = {
  clientId: "B66_DRIVE_CLIENT_ID",
  pickerAppId: "B66_DRIVE_PICKER_APP_ID",
  pickerDeveloperKey: "B66_DRIVE_PICKER_DEVELOPER_KEY"
};
/* 승인된 공개 값의 형식만 통과시킨다. 그 외 문자는 애초에 통과할 수 없다. */
const BROWSER_CLIENT_ID_PATTERN = /^[0-9A-Za-z._-]{6,200}\.apps\.googleusercontent\.com$/;
const BROWSER_PICKER_APP_ID_PATTERN = /^[0-9]{1,20}$/;
const BROWSER_PICKER_KEY_PATTERN = /^[0-9A-Za-z_.-]{16,128}$/;
const DRIVE_CONFIG_MAX_CHARS = 512;

function readEnvString(env, name) {
  if (!env) return "";
  let value;
  try {
    value = env[name];
  } catch (_) {
    return "";
  }
  if (typeof value !== "string") return "";
  const text = value.trim();
  if (!text || text.length > DRIVE_CONFIG_MAX_CHARS) return "";
  return text;
}

function approvedBrowserValue(env, name, pattern) {
  const value = readEnvString(env, name);
  if (!value || !pattern.test(value)) return "";
  return value;
}

/* <script> 안에서 탈출할 수 없도록 JSON 직렬화 후 위험 문자를 이스케이프한다. */
function jsStringLiteral(value) {
  return JSON.stringify(String(value))
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

function driveConfigBody(env) {
  const clientId = approvedBrowserValue(env, DRIVE_CONFIG_ENV.clientId, BROWSER_CLIENT_ID_PATTERN);
  const pickerAppId = approvedBrowserValue(env, DRIVE_CONFIG_ENV.pickerAppId, BROWSER_PICKER_APP_ID_PATTERN);
  const pickerDeveloperKey = approvedBrowserValue(env, DRIVE_CONFIG_ENV.pickerDeveloperKey, BROWSER_PICKER_KEY_PATTERN);
  return [
    "/* B66 Drive 런타임 설정 (Pages 환경변수에서 생성). 값이 없거나 형식이 틀리면 빈 문자열이다. */",
    "window.B66_DRIVE_CLIENT_ID = " + jsStringLiteral(clientId) + ";",
    "window.B66_DRIVE_PICKER_APP_ID = " + jsStringLiteral(pickerAppId) + ";",
    "window.B66_DRIVE_PICKER_DEVELOPER_KEY = " + jsStringLiteral(pickerDeveloperKey) + ";",
    ""
  ].join("\n");
}

function handleDriveConfig(request, env) {
  const headers = new Headers({
    "Content-Type": "application/javascript; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff"
  });
  if (request.method === "GET") return new Response(driveConfigBody(env), { status: 200, headers });
  if (request.method === "HEAD") return new Response(null, { status: 200, headers });
  return new Response(null, {
    status: 405,
    headers: {
      "Allow": "GET, HEAD",
      "Content-Type": "application/javascript; charset=utf-8",
      "Cache-Control": "no-store"
    }
  });
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
  if (!bridgeMutationOriginAllowed(request, url)) {
    return jsonError("padiem_origin_rejected", 403);
  }

  const headers = new Headers({
    "Accept": upstreamPath === "/api/b66/quote/pdf"
      ? "application/pdf,application/json"
      : (upstreamPath === "/api/b66/quote/preview-base" ? "image/png,application/json" : "application/json")
  });
  headers.set("X-B66-Origin", url.origin);
  if (MUTATING_METHODS.has(request.method)) headers.set("Origin", PADIEM_CHAT_ORIGIN);
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
  if (upstreamPath === "/api/b66/quote/preview-base") target.search = url.search;
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
  if (upstreamPath === "/api/b66/quote/pdf") {
    const disposition = upstream.headers.get("content-disposition");
    if (disposition) responseHeaders.set("Content-Disposition", disposition);
  }
  for (const name of [
    "X-B66-Rejection-Reason",
    "X-B66-Rejection-Path",
    "X-B66-Rejection-Type",
    "X-B66-Upstream-Class",
    "X-B66-Model-Selection-Status",
    "Retry-After",
    "X-B66-Interpret-Failure-Stage",
    "X-B66-Interpret-Exception-Family",
    "X-B66-Result-Origin"
  ]) {
    const value = upstream.headers.get(name);
    if (name === "X-B66-Result-Origin" &&
        !["registered_model_completion", "deterministic_fallback"].includes(value)) continue;
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
    if (url.pathname === DRIVE_CONFIG_PATH) {
      return handleDriveConfig(request, env);
    }
    return env.ASSETS.fetch(request);
  }
};
