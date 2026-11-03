const AUTH_ORIGIN = "https://auth.padiem.net";
export const STORYMEMORY_AUTH_CLIENT_ID = "b61-storymemory";
export const STORYMEMORY_AUTH_CALLBACK_URI = "https://storymemory-padiem.pages.dev/auth/callback";

const ACCESS_COOKIE = "__Host-storymemory-access";
const REFRESH_COOKIE = "storymemory_refresh";
const STATE_COOKIE = "__Host-storymemory-auth-state";
const MARKER_COOKIE = "__Host-storymemory-shared";
const CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer";
const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });

function b64url(bytes) {
  let binary = "";
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function un64(value) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value)) throw new Error("invalid_encoding");
  return Uint8Array.from(atob(value.replaceAll("-", "+").replaceAll("_", "/").padEnd(Math.ceil(value.length / 4) * 4, "=")), (x) => x.charCodeAt(0));
}

function json64(value) { return b64url(encoder.encode(JSON.stringify(value))); }

function parseJson64(value) {
  return JSON.parse(decoder.decode(un64(value)));
}

function randomOpaque() { return b64url(crypto.getRandomValues(new Uint8Array(32))); }

function cookies(request) {
  const result = Object.create(null);
  for (const part of (request.headers.get("cookie") || "").split(";")) {
    const at = part.indexOf("=");
    if (at < 1) continue;
    result[part.slice(0, at).trim()] = part.slice(at + 1).trim();
  }
  return result;
}

function json(body, status = 200, headers = {}) {
  const responseHeaders = headers instanceof Headers ? headers : new Headers({
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    ...headers
  });
  if (!responseHeaders.has("content-type")) responseHeaders.set("content-type", "application/json; charset=utf-8");
  if (!responseHeaders.has("cache-control")) responseHeaders.set("cache-control", "no-store");
  if (!responseHeaders.has("x-content-type-options")) responseHeaders.set("x-content-type-options", "nosniff");
  return new Response(JSON.stringify(body), {
    status,
    headers: responseHeaders
  });
}

function isConfigured(env) {
  if (env?.STORYMEMORY_SHARED_AUTH_ENABLED !== "true" ||
      typeof env.STORYMEMORY_AUTH_CLIENT_KID !== "string" || !/^[A-Za-z0-9._-]{1,128}$/.test(env.STORYMEMORY_AUTH_CLIENT_KID)) return false;
  try {
    const jwk = JSON.parse(env.STORYMEMORY_AUTH_CLIENT_PRIVATE_JWK || "");
    const stateKey = un64(env.STORYMEMORY_AUTH_STATE_KEY || "");
    return jwk?.kty === "EC" && jwk?.crv === "P-256" && (!jwk.kid || jwk.kid === env.STORYMEMORY_AUTH_CLIENT_KID) &&
      [jwk.x, jwk.y, jwk.d].every((value) => typeof value === "string" && un64(value).byteLength === 32) && stateKey.byteLength === 32;
  } catch {
    return false;
  }
}

async function importedStateKey(env) {
  const raw = un64(env.STORYMEMORY_AUTH_STATE_KEY || "");
  if (raw.byteLength !== 32) throw new Error("state_key_unavailable");
  return crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
}

async function sealState(env, state) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const cipher = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await importedStateKey(env), encoder.encode(JSON.stringify(state)));
  return b64url(iv) + "." + b64url(new Uint8Array(cipher));
}

async function unsealState(env, token) {
  const parts = String(token || "").split(".");
  if (parts.length !== 2) throw new Error("invalid_state");
  const clear = await crypto.subtle.decrypt({ name: "AES-GCM", iv: un64(parts[0]) }, await importedStateKey(env), un64(parts[1]));
  return JSON.parse(decoder.decode(clear));
}

async function makeClientAssertion(env, now) {
  const privateJwk = JSON.parse(env.STORYMEMORY_AUTH_CLIENT_PRIVATE_JWK || "{}");
  const key = await crypto.subtle.importKey("jwk", privateJwk, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
  const input = json64({ alg: "ES256", typ: "JWT", kid: env.STORYMEMORY_AUTH_CLIENT_KID }) + "." + json64({
    iss: STORYMEMORY_AUTH_CLIENT_ID,
    sub: STORYMEMORY_AUTH_CLIENT_ID,
    aud: AUTH_ORIGIN + "/token",
    iat: now,
    exp: now + 120,
    jti: randomOpaque()
  });
  const signature = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, encoder.encode(input));
  if (signature.byteLength !== 64) throw new Error("invalid_client_signature");
  return input + "." + b64url(new Uint8Array(signature));
}

class AuthEndpointError extends Error {
  constructor(status, code) { super("auth_endpoint_failed"); this.status = status; this.code = code; }
}

async function authPost(path, params, env, fetcher, now) {
  const body = new URLSearchParams({
    client_id: STORYMEMORY_AUTH_CLIENT_ID,
    client_assertion_type: CLIENT_ASSERTION_TYPE,
    client_assertion: await makeClientAssertion(env, now),
    ...params
  });
  const response = await fetcher(AUTH_ORIGIN + path, {
    method: "POST",
    redirect: "manual",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body
  });
  let result = null;
  try { result = await response.json(); } catch { /* response body is not logged or forwarded */ }
  if (!response.ok) throw new AuthEndpointError(response.status, result?.error || "request_failed");
  if (!result || typeof result !== "object" || Array.isArray(result)) throw new Error("invalid_auth_response");
  return result;
}

function cookieHeaders(tokens, accessMaxAge = 900) {
  const headers = new Headers({ "cache-control": "no-store", "referrer-policy": "no-referrer" });
  const secureHttpOnly = "Secure; HttpOnly; SameSite=Lax";
  headers.append("set-cookie", ACCESS_COOKIE + "=" + (tokens?.access_token || "") + "; Path=/; Max-Age=" + (tokens ? accessMaxAge : 0) + "; " + secureHttpOnly);
  headers.append("set-cookie", REFRESH_COOKIE + "=" + (tokens?.refresh_token || "") + "; Path=/auth; Max-Age=" + (tokens ? 2592000 : 0) + "; " + secureHttpOnly);
  headers.append("set-cookie", MARKER_COOKIE + "=" + (tokens ? "1" : "") + "; Path=/; Max-Age=" + (tokens ? 2592000 : 0) + "; Secure; SameSite=Lax");
  headers.append("set-cookie", STATE_COOKIE + "=; Path=/; Max-Age=0; " + secureHttpOnly);
  return headers;
}

function clearCookies(extra = {}) {
  const headers = new Headers({ "cache-control": "no-store", "referrer-policy": "no-referrer", ...extra });
  const secureHttpOnly = "Secure; HttpOnly; SameSite=Lax";
  headers.append("set-cookie", ACCESS_COOKIE + "=; Path=/; Max-Age=0; " + secureHttpOnly);
  headers.append("set-cookie", REFRESH_COOKIE + "=; Path=/auth; Max-Age=0; " + secureHttpOnly);
  headers.append("set-cookie", MARKER_COOKIE + "=; Path=/; Max-Age=0; Secure; SameSite=Lax");
  headers.append("set-cookie", STATE_COOKIE + "=; Path=/; Max-Age=0; " + secureHttpOnly);
  return headers;
}

function clearStateCookie(extra = {}) {
  const headers = new Headers({ "cache-control": "no-store", "referrer-policy": "no-referrer", ...extra });
  headers.append("set-cookie", STATE_COOKIE + "=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax");
  return headers;
}

function loginStateCookie(value) {
  return STATE_COOKIE + "=" + value + "; Path=/; Max-Age=600; Secure; HttpOnly; SameSite=Lax";
}

function validNext(value) {
  return typeof value === "string" && /^\/(?!\/)[A-Za-z0-9_./-]*$/.test(value) && !value.split("/").includes("..") ? value : "/";
}

function parseToken(token) {
  const parts = String(token || "").split(".");
  if (parts.length !== 3) throw new Error("invalid_access_token");
  const header = parseJson64(parts[0]);
  const payload = parseJson64(parts[1]);
  if (!header || typeof header !== "object" || header.alg !== "ES256" || header.typ !== "JWT" || typeof header.kid !== "string") throw new Error("invalid_access_token");
  return { header, payload, input: parts[0] + "." + parts[1], signature: un64(parts[2]) };
}

function validAccessClaims(payload, now) {
  return payload && typeof payload === "object" &&
    payload.iss === AUTH_ORIGIN && payload.aud === STORYMEMORY_AUTH_CLIENT_ID && payload.token_use === "access" &&
    /^sub_[A-Za-z0-9_-]{1,128}$/.test(payload.sub || "") && payload.account_id === payload.sub &&
    /^sub_[A-Za-z0-9_-]{1,128}$/.test(payload.account_id || "") &&
    /^[A-Za-z0-9_-]{20,128}$/.test(payload.sid || "") && Number.isSafeInteger(payload.iat) &&
    Number.isSafeInteger(payload.exp) && payload.iat <= now + 30 && payload.exp > now && payload.exp > payload.iat &&
    payload.exp - payload.iat <= 900;
}

export function createStoryMemorySharedAuth({ fetcher = fetch, now = () => Math.floor(Date.now() / 1000) } = {}) {
  let jwksCache = null;
  let jwksExpires = 0;

  async function verifyAccess(token, current) {
    const parsed = parseToken(token);
    if (!validAccessClaims(parsed.payload, current) || parsed.signature.byteLength !== 64) throw new Error("invalid_access_token");
    if (!jwksCache || jwksExpires <= current) {
      const response = await fetcher(AUTH_ORIGIN + "/.well-known/jwks.json", { method: "GET", redirect: "manual", headers: { accept: "application/json" } });
      if (!response.ok) throw new Error("jwks_unavailable");
      const document = await response.json();
      if (!Array.isArray(document?.keys)) throw new Error("invalid_jwks");
      jwksCache = document.keys;
      jwksExpires = current + 300;
    }
    const jwk = jwksCache.find((item) => item?.kid === parsed.header.kid && item.kty === "EC" && item.crv === "P-256" && (!item.use || item.use === "sig") && (!item.alg || item.alg === "ES256"));
    if (!jwk) throw new Error("unknown_signing_key");
    const key = await crypto.subtle.importKey("jwk", jwk, { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
    const valid = await crypto.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, key, parsed.signature, encoder.encode(parsed.input));
    if (!valid) throw new Error("invalid_access_signature");
    return true;
  }

  async function refreshTokens(refreshToken, env, current) {
    return authPost("/token", { grant_type: "refresh_token", refresh_token: refreshToken }, env, fetcher, current);
  }

  async function sessionResponse(request, env, jar, current) {
    const configured = isConfigured(env);
    if (!configured) return json({ configured: false, authenticated: false, syncEnabled: false });
    const access = jar[ACCESS_COOKIE];
    if (access) {
      try {
        await verifyAccess(access, current);
        return json({ configured: true, authenticated: true, syncEnabled: false });
      } catch { /* refresh below; details are intentionally not exposed */ }
    }
    if (!jar[REFRESH_COOKIE]) return json({ configured: true, authenticated: false, syncEnabled: false });
    try {
      const tokens = await refreshTokens(jar[REFRESH_COOKIE], env, current);
      if (typeof tokens.access_token !== "string" || typeof tokens.refresh_token !== "string") throw new Error("invalid_auth_response");
      await verifyAccess(tokens.access_token, current);
      const headers = cookieHeaders(tokens);
      return json({ configured: true, authenticated: true, syncEnabled: false }, 200, headers);
    } catch (error) {
      if (error instanceof AuthEndpointError && error.status === 400 && error.code === "invalid_grant") {
        return json({ configured: true, authenticated: false, syncEnabled: false }, 200, clearCookies());
      }
      return json({ configured: true, authenticated: false, syncEnabled: false, available: false }, 503);
    }
  }

  return async function handleStoryMemorySharedAuth(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/auth/")) return null;
    const jar = cookies(request);
    const current = now();
    const configured = isConfigured(env);

    if (url.pathname === "/auth/status") {
      if (request.method !== "GET") return json({ error: "method_not_allowed" }, 405);
      return sessionResponse(request, env, jar, current);
    }

    if (url.pathname === "/auth/login") {
      if (request.method !== "GET") return json({ error: "method_not_allowed" }, 405);
      if (!configured) return json({ error: "not_configured" }, 503);
      try {
        const state = randomOpaque();
        const verifier = randomOpaque();
        const challenge = b64url(await crypto.subtle.digest("SHA-256", encoder.encode(verifier)));
        const next = validNext(url.searchParams.get("next") || "/");
        const sealed = await sealState(env, { state, verifier, next, callback: STORYMEMORY_AUTH_CALLBACK_URI, exp: current + 600 });
        const target = new URL(AUTH_ORIGIN + "/login");
        for (const [key, value] of Object.entries({ client_id: STORYMEMORY_AUTH_CLIENT_ID, redirect_uri: STORYMEMORY_AUTH_CALLBACK_URI, state, code_challenge: challenge, code_challenge_method: "S256" })) target.searchParams.set(key, value);
        return new Response(null, { status: 302, headers: { location: target.href, "cache-control": "no-store", "referrer-policy": "no-referrer", "set-cookie": loginStateCookie(sealed) } });
      } catch {
        return json({ error: "auth_unavailable" }, 503);
      }
    }

    if (url.pathname === "/auth/callback") {
      if (request.method !== "GET") return json({ error: "method_not_allowed" }, 405);
      if (!configured) return json({ error: "not_configured" }, 503, clearStateCookie());
      try {
        const state = await unsealState(env, jar[STATE_COOKIE]);
        const code = url.searchParams.get("code");
        if (state.callback !== STORYMEMORY_AUTH_CALLBACK_URI || state.exp <= current || state.state !== url.searchParams.get("state") ||
            !/^[A-Za-z0-9_-]{20,128}\.[A-Za-z0-9_-]{20,128}$/.test(code || "") || !state.verifier || validNext(state.next) !== state.next) throw new Error("invalid_state");
        const tokens = await authPost("/token", { grant_type: "authorization_code", code, redirect_uri: STORYMEMORY_AUTH_CALLBACK_URI, code_verifier: state.verifier }, env, fetcher, current);
        if (typeof tokens.access_token !== "string" || typeof tokens.refresh_token !== "string") throw new Error("invalid_auth_response");
        await verifyAccess(tokens.access_token, current);
        const headers = cookieHeaders(tokens);
        headers.set("location", new URL(state.next, url.origin).href);
        return new Response(null, { status: 302, headers });
      } catch {
        const headers = clearStateCookie();
        headers.set("location", new URL("/?shared_login=failed", url.origin).href);
        return new Response(null, { status: 302, headers });
      }
    }

    if (url.pathname === "/auth/refresh" || url.pathname === "/auth/logout") {
      if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
      if (request.headers.get("origin") !== url.origin) return json({ error: "invalid_origin" }, 403);
      if (!configured) return json({ error: "not_configured" }, 503);
      if (url.pathname === "/auth/refresh") {
        if (!jar[REFRESH_COOKIE]) return json({ error: "not_authenticated" }, 401, clearCookies());
        try {
          const tokens = await refreshTokens(jar[REFRESH_COOKIE], env, current);
          if (typeof tokens.access_token !== "string" || typeof tokens.refresh_token !== "string") throw new Error("invalid_auth_response");
          await verifyAccess(tokens.access_token, current);
          return new Response(null, { status: 204, headers: cookieHeaders(tokens) });
        } catch (error) {
          if (error instanceof AuthEndpointError && error.status === 400 && error.code === "invalid_grant") return json({ error: "not_authenticated" }, 401, clearCookies());
          return json({ error: "auth_unavailable" }, 503);
        }
      }
      if (!jar[REFRESH_COOKIE]) return new Response(null, { status: 204, headers: clearCookies() });
      try {
        await authPost("/logout", { refresh_token: jar[REFRESH_COOKIE] }, env, fetcher, current);
        return new Response(null, { status: 204, headers: clearCookies() });
      } catch (error) {
        if (error instanceof AuthEndpointError && error.status === 400 && error.code === "invalid_grant") return new Response(null, { status: 204, headers: clearCookies() });
        return json({ error: "auth_unavailable" }, 503);
      }
    }

    return json({ error: "not_found" }, 404);
  };
}
