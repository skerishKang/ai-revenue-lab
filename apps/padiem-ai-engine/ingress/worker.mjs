const EXECUTE_PATH = "/internal/v1/execute";
const MAX_REQUEST_BODY_BYTES = 128 * 1024;
const MAX_CALLER_CHARS = 128;
const MAX_CREDENTIAL_CHARS = 512;
const MAX_RESPONSE_BYTES = 1024 * 1024;

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

function boundedHeader(headers, name, maxChars) {
  const value = headers.get(name);
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  if (!normalized || normalized.length > maxChars) return null;
  return normalized;
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

  const caller = boundedHeader(request.headers, "x-padiem-engine-caller", MAX_CALLER_CHARS);
  const credential = boundedHeader(
    request.headers,
    "x-padiem-engine-credential",
    MAX_CREDENTIAL_CHARS,
  );
  if (!caller || !credential) {
    return jsonError(401, "service_authentication_failed", "Service authentication failed.");
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

  const forwardHeaders = new Headers({
    "content-type": "application/json",
    "x-padiem-engine-caller": caller,
    "x-padiem-engine-credential": credential,
  });

  let upstream;
  try {
    upstream = await env.ENGINE.fetch(
      new Request("https://padiem-ai-engine/internal/v1/execute", {
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
