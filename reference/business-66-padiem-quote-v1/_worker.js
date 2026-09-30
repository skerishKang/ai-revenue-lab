const B14_IMAGE_EXTRACTION_URL =
  "https://ai-revenue-korean-ai-platform.charliekant.workers.dev/api/b66/v1/quote/extract-image";
const INTAKE_PATH = "/api/v1/quote/intake";
const MAX_REQUEST_BYTES = 6 * 1024 * 1024;
const MAX_RESPONSE_BYTES = 1024 * 1024;

function jsonError(code, status) {
  return new Response(JSON.stringify({ ok: false, error: { code } }), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    }
  });
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

  let upstream;
  try {
    upstream = await fetch(B14_IMAGE_EXTRACTION_URL, {
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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === INTAKE_PATH) {
      return handleIntake(request);
    }
    return env.ASSETS.fetch(request);
  }
};
