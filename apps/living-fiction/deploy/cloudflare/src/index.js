/**
 * Living Fiction thin proxy (Cloudflare Workers Free plan).
 *
 * Forwards every request to the fixed upstream origin configured in
 * `env.UPSTREAM_ORIGIN` (the Modal app URL). The destination is fixed by
 * configuration — the client cannot influence it — so this is never an open
 * proxy. No secret or upstream URL ever appears in an error body.
 *
 * Proxy authentication:
 *  - The worker and the app share a single CSPRNG secret. On the worker it is
 *    `env.UPSTREAM_PROXY_SECRET`; on the app it is `LF_PROXY_SHARED_SECRET`.
 *    The value is never hardcoded here — it is injected as a Worker secret.
 *  - The worker STRIPS any client-supplied `X-LF-Proxy-Auth`,
 *    `X-Forwarded-Host`, and `X-Forwarded-Proto` headers, then re-sets the
 *    forwarded headers from the original request and sets `X-LF-Proxy-Auth` to
 *    the shared secret. A client can therefore never spoof the proxy identity.
 *  - The app trusts `X-Forwarded-Host` / `X-Forwarded-Proto` ONLY when
 *    `X-LF-Proxy-Auth` verifies (constant-time). A direct Modal caller that
 *    forges forwarded headers — but cannot present the secret — is not trusted.
 *  - A missing or weak `UPSTREAM_PROXY_SECRET` fails closed (generic 500); the
 *    worker never forwards without authenticating itself to the upstream.
 *
 * Behaviour:
 *  - method, body, query string, and headers are preserved;
 *  - Host is set to the upstream host; X-Forwarded-Host / X-Forwarded-Proto
 *    carry the original request's host and scheme;
 *  - the browser Origin header passes through unchanged so the application can
 *    verify it against LF_ALLOWED_ORIGINS (the public worker hostname);
 *  - CORS preflight is answered only when the request Origin is the SAME full
 *    origin as this worker (scheme + host + port), never on a host-only match;
 *  - every Set-Cookie header is preserved (multiple cookies are not collapsed);
 *  - redirect Location headers carrying the upstream host are rewritten back to
 *    the user-facing hostname (absolute or relative);
 *  - responses are never cached (Cache-Control: no-store on the response and
 *    cf.cacheEverything=false on the upstream request);
 *  - a bounded timeout yields a generic 504; upstream failures yield a generic
 *    502. Neither body reveals the upstream URL or any secret.
 *
 * Cloudflare Access protection for /admin/* is configured out of band in the
 * Cloudflare dashboard (Zero Trust > Access) — see README.md. This worker does
 * not block any path, so the reader /access flow is never interfered with.
 */

const REQUEST_TIMEOUT_MS = 30000;
const PROXY_AUTH_HEADER = "X-LF-Proxy-Auth";
const MIN_PROXY_SECRET_LEN = 32;

function proxySecret(env) {
  const secret = env.UPSTREAM_PROXY_SECRET || "";
  // Missing or weak secret -> fail closed. The worker never forwards without a
  // strong shared secret to authenticate itself to the upstream.
  if (secret.trim().length < MIN_PROXY_SECRET_LEN) {
    return null;
  }
  return secret;
}

function upstreamOrigin(env) {
  const raw = (env.UPSTREAM_ORIGIN || "").trim().replace(/\/+$/, "");
  if (!raw) {
    return null;
  }
  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    return null;
  }
  // HTTPS origins only.
  if (parsed.protocol !== "https:") {
    return null;
  }
  // Reject any origin carrying credentials, a path, a query, or a fragment —
  // the upstream must be a bare scheme://host[:port].
  if (parsed.username || parsed.password) {
    return null;
  }
  if (parsed.pathname && parsed.pathname !== "/") {
    return null;
  }
  if (parsed.search || parsed.hash) {
    return null;
  }
  return parsed;
}

function plainResponse(status, text) {
  return new Response(text, {
    status,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

function sameOriginPreflight(request, incoming) {
  const origin = request.headers.get("Origin");
  if (!origin) {
    return null;
  }
  let originUrl;
  try {
    originUrl = new URL(origin);
  } catch {
    return null;
  }
  // Full origin comparison (scheme + host + port), not host-only: an http
  // origin must not satisfy an https worker origin, and a different port must
  // not match. `.origin` canonicalizes scheme/host case and default ports.
  const selfOrigin = new URL(`${incoming.protocol}//${incoming.host}`).origin;
  if (originUrl.origin !== selfOrigin) {
    return null;
  }
  return new Response(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers":
        request.headers.get("Access-Control-Request-Headers") || "",
      "Access-Control-Allow-Credentials": "true",
      "Access-Control-Max-Age": "600",
      "Cache-Control": "no-store",
      Vary: "Origin",
    },
  });
}

export default {
  async fetch(request, env) {
    const secret = proxySecret(env);
    if (!secret) {
      return plainResponse(500, "proxy misconfigured");
    }

    const upstream = upstreamOrigin(env);
    if (!upstream) {
      return plainResponse(500, "proxy misconfigured");
    }

    const incoming = new URL(request.url);

    if (request.method === "OPTIONS") {
      const preflight = sameOriginPreflight(request, incoming);
      if (preflight) {
        return preflight;
      }
    }

    const target = new URL(
      incoming.pathname + incoming.search,
      upstream.origin,
    );

    const headers = new Headers(request.headers);
    // Strip any client-supplied proxy / forwarded headers so they cannot be
    // spoofed, then re-establish them from the trusted proxy.
    headers.delete(PROXY_AUTH_HEADER);
    headers.delete("X-Forwarded-Host");
    headers.delete("X-Forwarded-Proto");
    headers.set("Host", upstream.host);
    headers.set("X-Forwarded-Host", incoming.host);
    headers.set("X-Forwarded-Proto", incoming.protocol.replace(":", ""));
    headers.set(PROXY_AUTH_HEADER, secret);

    let response;
    try {
      response = await fetch(target, {
        method: request.method,
        headers,
        body: request.body,
        redirect: "manual",
        // workerd does not implement the standard `cache` field; cache control
        // is expressed via the `cf` object here and the response Cache-Control
        // header set below.
        cf: { cacheEverything: false },
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
    } catch (err) {
      if (err && err.name === "TimeoutError") {
        return plainResponse(504, "upstream timeout");
      }
      return plainResponse(502, "upstream unavailable");
    }

    // Rebuild response headers, preserving EVERY Set-Cookie (multiple cookies
    // must not be collapsed into one comma-joined header).
    const outHeaders = new Headers();
    for (const [key, value] of response.headers.entries()) {
      if (key.toLowerCase() === "set-cookie") {
        continue;
      }
      outHeaders.append(key, value);
    }
    const setCookies =
      typeof response.headers.getSetCookie === "function"
        ? response.headers.getSetCookie()
        : [];
    for (const cookie of setCookies) {
      outHeaders.append("Set-Cookie", cookie);
    }

    const location = outHeaders.get("Location");
    if (location) {
      try {
        const locUrl = new URL(location, target);
        if (locUrl.host === upstream.host) {
          outHeaders.set("Location", locUrl.pathname + locUrl.search);
        }
      } catch {
        // Leave an unparseable Location untouched.
      }
    }
    outHeaders.set("Cache-Control", "no-store");

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: outHeaders,
    });
  },
};
