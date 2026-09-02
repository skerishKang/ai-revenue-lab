const EXECUTE_PATH = "/internal/v1/execute";
const MAX_REQUEST_BODY_BYTES = 128 * 1024;
const MAX_INGRESS_CREDENTIAL_CHARS = 512;
const MAX_RESPONSE_BYTES = 1024 * 1024;

// Ingress-owned canonical Engine service identity. These values live ONLY in
// the ingress deployment secrets. They are minted here and never accepted from
// the caller. First-party callers never receive the canonical Engine secret,
// eliminating operational coupling across accounts.
const CALLER_ID_ENV = "PADIEM_ENGINE_CALLER_ID";
const CALLER_SECRET_ENV = "PADIEM_ENGINE_CALLER_SECRET";
// Separate cross-account client credential. The only credential a caller may
// supply. Compared in constant time against the ingress secret.
const INGRESS_CLIENT_SECRET_ENV = "PADIEM_INGRESS_CLIENT_SECRET";

const INGRESS_CREDENTIAL_HEADER = "x-padiem-ingress-credential";
const ENGINE_CALLER_HEADER = "x-padiem-engine-caller";
const ENGINE_CREDENTIAL_HEADER = "x-padiem-engine-credential";

// Fixed canonical Engine destination. Never derived from caller input.
const ENGINE_EXECUTE_URL = "https://padiem-ai-engine/internal/v1/execute";

function jsonError(status, code, message) {
  return new Response(
    JSON.stringify({
      ok: false,
      error: { code, message, retryable: false },
    }),
    {
      status,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
        "x-content-type-options": "nosniff",
      },
    },
  );
}

function boundedText(value, maxChars) {
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  if (!normalized || normalized.length > maxChars) return null;
  return normalized;
}

function readSecret(env, name) {
  if (!env || typeof env !== "object") return null;
  const value = env[name];
  if (typeof value !== "string") return null;
  return value.length ? value : null;
}

// Constant-time string comparison: always iterates the full length with no
// early exit, so timing is independent of the secret value.
function secretsEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const len = Math.max(a.length, b.length);
  let result = 0;
  for (let i = 0; i < len; i++) {
    const ca = i < a.length ? a.charCodeAt(i) : 0;
    const cb = i < b.length ? b.charCodeAt(i) : 0;
    result |= ca ^ cb;
  }
  return result === 0;
}

export async function handleIngress(request, env) {
  const url = new URL(request.url);

  if (url.pathname !== EXECUTE_PATH) {
    return jsonError(404, "not_found", "Ingress route not found.");
  }
  if (request.method !== "POST") {
    return jsonError(405, "method_not_allowed", "Method not allowed.");
  }

  // This ingress is for first-party server-to-server calls only. Browsers send
  // an Origin header on cross-origin requests; reject before any Engine call.
  if (request.headers.has("origin")) {
    return jsonError(403, "browser_request_rejected", "Browser-origin requests are not accepted.");
  }

  const contentType = (request.headers.get("content-type") || "")
    .split(";", 1)[0]
    .trim()
    .toLowerCase();
  if (contentType !== "application/json") {
    return jsonError(415, "unsupported_media_type", "Content-Type must be application/json.");
  }

  // The ONLY caller credential accepted is the ingress client credential.
  // Any caller-supplied Engine credential header (x-padiem-engine-caller /
  // x-padiem-engine-credential) is deliberately ignored and never forwarded.
  const ingressCredential = boundedText(
    request.headers.get(INGRESS_CREDENTIAL_HEADER),
    MAX_INGRESS_CREDENTIAL_CHARS,
  );

  // Ingress-owned canonical Engine identity. Loaded from deployment secrets
  // only. Never sourced from the caller.
  const ingressClientSecret = readSecret(env, INGRESS_CLIENT_SECRET_ENV);
  const engineCallerId = readSecret(env, CALLER_ID_ENV);
  const engineCallerSecret = readSecret(env, CALLER_SECRET_ENV);

  if (!ingressClientSecret || !engineCallerId || !engineCallerSecret) {
    return jsonError(503, "service_identity_misconfigured", "Ingress service identity is misconfigured.");
  }

  if (!ingressCredential || !secretsEqual(ingressCredential, ingressClientSecret)) {
    return jsonError(401, "service_authentication_failed", "Ingress authentication failed.");
  }

  const declaredLength = request.headers.get("content-length");
  if (declaredLength !== null) {
    const parsed = Number(declaredLength);
    if (!Number.isFinite(parsed) || parsed < 0) {
      return jsonError(400, "invalid_request", "Request body length is invalid.");
    }
    if (parsed > MAX_REQUEST_BODY_BYTES) {
      return jsonError(413, "request_too_large", "Request body exceeds the ingress safety limit.");
    }
  }

  const body = new Uint8Array(await request.arrayBuffer());
  if (body.byteLength > MAX_REQUEST_BODY_BYTES) {
    return jsonError(413, "request_too_large", "Request body exceeds the ingress safety limit.");
  }

  if (!env?.ENGINE || typeof env.ENGINE.fetch !== "function") {
    return jsonError(503, "engine_unavailable", "Padiem AI Engine is unavailable.");
  }

  // Mint canonical Engine headers from ingress env secrets ONLY. Caller-
  // supplied Engine headers are excluded from forwardHeaders.
  const forwardHeaders = new Headers({
    "content-type": "application/json",
    [ENGINE_CALLER_HEADER]: engineCallerId,
    [ENGINE_CREDENTIAL_HEADER]: engineCallerSecret,
  });

  let upstream;
  try {
    upstream = await env.ENGINE.fetch(
      new Request(ENGINE_EXECUTE_URL, {
        method: "POST",
        headers: forwardHeaders,
        body,
      }),
    );
  } catch {
    return jsonError(503, "engine_unavailable", "Padiem AI Engine is unavailable.");
  }

  const upstreamBody = new Uint8Array(await upstream.arrayBuffer());
  if (upstreamBody.byteLength > MAX_RESPONSE_BYTES) {
    return jsonError(502, "engine_response_too_large", "Padiem AI Engine response exceeded the safety limit.");
  }

  // Project only bounded safe response headers. Never reflect caller or Engine
  // internal headers across the account boundary.
  return new Response(upstreamBody, {
    status: upstream.status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

export default {
  fetch: handleIngress,
};
