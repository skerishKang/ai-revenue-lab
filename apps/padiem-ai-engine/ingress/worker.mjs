const EXECUTE_PATH = "/internal/v1/execute";
const MAX_REQUEST_BODY_BYTES = 128 * 1024;
const MAX_INGRESS_CREDENTIAL_CHARS = 512;
const MAX_RESPONSE_BYTES = 1024 * 1024;
// Hard ceiling on Engine attempts per ingress request: the initial attempt
// plus, during the dual-credential migration window only, exactly one
// CURRENT-credential retry. Never raised, never looped.
export const MAX_ENGINE_ATTEMPTS = 2;

// Ingress-owned canonical Engine service identity. These values live ONLY in
// the ingress deployment secrets. They are minted here and never accepted from
// the caller. First-party callers never receive the canonical Engine secret,
// eliminating operational coupling across accounts.
const CALLER_ID_ENV = "PADIEM_ENGINE_CALLER_ID";
const CALLER_SECRET_ENV = "PADIEM_ENGINE_CALLER_SECRET";
// Optional migration-window credential for zero-downtime rotation of the
// opaque CURRENT secret. When configured, the FIRST Engine attempt presents
// NEXT; CURRENT is presented at most once, and only as a retry on the exact
// bounded Engine authentication-failure signal. Plaintext of NEXT is never
// retained past the rotation and the CURRENT plaintext is never recoverable
// from NEXT.
const CALLER_SECRET_NEXT_ENV = "PADIEM_ENGINE_CALLER_SECRET_NEXT";
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

// Exactly one bounded Engine attempt with a SELECTED caller credential. The
// already-buffered request body Uint8Array is replayed unchanged; it is never
// re-read from the incoming request. Returns { status, body } on success, or
// a prepared fail-closed error Response on fetch failure or oversized body.
async function engineAttempt(engineBinding, callerId, credential, body) {
  let response;
  try {
    response = await engineBinding.fetch(
      new Request(ENGINE_EXECUTE_URL, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          [ENGINE_CALLER_HEADER]: callerId,
          [ENGINE_CREDENTIAL_HEADER]: credential,
        },
        body,
      }),
    );
  } catch {
    return { error: jsonError(503, "engine_unavailable", "Padiem AI Engine is unavailable.") };
  }

  const buffered = new Uint8Array(await response.arrayBuffer());
  if (buffered.byteLength > MAX_RESPONSE_BYTES) {
    return { error: jsonError(502, "engine_response_too_large", "Padiem AI Engine response exceeded the safety limit.") };
  }

  return { status: response.status, body: buffered };
}

// Safe fallback detector for the migration seam ONLY. Consumes/parses the
// first (NEXT) response body exactly once and returns true ONLY for the
// precise non-executing Engine authentication-failure signal:
// status 401 + bounded + JSON + error.code === service_authentication_failed.
// Anything else (403/413/429/5xx, timeout, malformed/non-JSON/oversized
// body, other error codes, or anything that could represent actual
// Core/B14 execution) must NOT trigger a retry.
function shouldRetryWithCurrent(status, bodyBytes) {
  if (status !== 401) return false;
  let payload;
  try {
    payload = JSON.parse(new TextDecoder().decode(bodyBytes));
  } catch {
    return false;
  }
  return payload?.error?.code === "service_authentication_failed";
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

  // Dual-credential migration seam. When NEXT is absent (normal operation),
  // behavior is semantically identical to pre-migration: exactly one Engine
  // attempt with CURRENT. When NEXT is present, it is attempted first and
  // CURRENT is used at most once, only on the exact auth-failure signal —
  // for a hard maximum of MAX_ENGINE_ATTEMPTS (2) calls. The caller
  // identity is ingress-owned in every attempt; caller-supplied Engine
  // headers remain ignored.
  const engineCallerSecretNext = readSecret(env, CALLER_SECRET_NEXT_ENV);
  const primaryCredential = engineCallerSecretNext ?? engineCallerSecret;

  const first = await engineAttempt(env.ENGINE, engineCallerId, primaryCredential, body);
  if (first.error) return first.error;

  let result = first;
  if (engineCallerSecretNext && shouldRetryWithCurrent(first.status, first.body)) {
    const retry = await engineAttempt(env.ENGINE, engineCallerId, engineCallerSecret, body);
    if (retry.error) return retry.error;
    result = retry;
  }

  // Project only bounded safe response headers. Never reflect caller or Engine
  // internal headers across the account boundary.
  return new Response(result.body, {
    status: result.status,
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
