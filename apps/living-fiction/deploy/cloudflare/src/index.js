/**
 * Living Fiction thin proxy (Cloudflare Workers Free plan).
 *
 * Forwards every request to the fixed upstream origin configured in
 * `env.UPSTREAM_ORIGIN` (the Modal app URL). The destination is fixed by
 * configuration — the client cannot influence it — so this is never an open
 * proxy. No secret or upstream URL ever appears in an error body.
 *
 * Behaviour:
 *  - method, body, query string, and headers are preserved;
 *  - Host is set to the upstream host; X-Forwarded-Host / X-Forwarded-Proto
 *    carry the original request's host and scheme;
 *  - the browser Origin header passes through unchanged so the application can
 *    verify it against LF_ALLOWED_ORIGINS (the public worker hostname);
 *  - CORS preflight is answered only for same-host origins (pages served by
 *    this worker); arbitrary cross-origin access is never allowed;
 *  - Set-Cookie headers pass through untouched (cookies are scoped to the
 *    worker hostname because the app sets no Domain attribute);
 *  - redirect Location headers carrying the upstream host are rewritten back
 *    to the user-facing hostname (as a relative reference);
 *  - responses are never cached (Cache-Control: no-store, cache: "no-store");
 *  - a bounded timeout yields a generic 504; upstream failures yield a generic
 *    502. Neither body reveals the upstream URL.
 *
 * Cloudflare Access protection for /admin/* is configured out of band in the
 * Cloudflare dashboard (Zero Trust > Access) — see README.md. This worker does
 * not block any path, so the reader /access flow is never interfered with.
 */

const REQUEST_TIMEOUT_MS = 30000;

function upstreamOrigin(env) {
  const raw = (env.UPSTREAM_ORIGIN || "").trim().replace(/\/+$/, "");
  if (!raw) {
    return null;
  }
  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== "https:") {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
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
  if (originUrl.host !== incoming.host) {
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
    headers.set("Host", upstream.host);
    headers.set("X-Forwarded-Host", incoming.host);
    headers.set("X-Forwarded-Proto", incoming.protocol.replace(":", ""));

    let response;
    try {
      response = await fetch(target, {
        method: request.method,
        headers,
        body: request.body,
        redirect: "manual",
        cache: "no-store",
        cf: { cacheEverything: false },
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
    } catch (err) {
      if (err && err.name === "TimeoutError") {
        return plainResponse(504, "upstream timeout");
      }
      return plainResponse(502, "upstream unavailable");
    }

    const outHeaders = new Headers(response.headers);
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
