/**
 * B54 Preview Wire Pilot Caller Worker (#2786 Stage 11-C M3-3.5).
 *
 * Exposes an authenticated dispatch endpoint for the GitHub Actions runner,
 * invoking the private `padiem-ai-engine-preview` worker over Cloudflare
 * Service Binding (`PREVIEW_ENGINE`).
 *
 * Invariant guarantees:
 * - NO production worker access: bound strictly to padiem-ai-engine-preview.
 * - NO D1 access: 0 database bindings declared.
 * - NO external provider calls: target preview lane is provider-free (raises if called).
 * - NO user data: strictly transmits the fixed synthetic agent task payload.
 */

export const PREVIEW_PILOT_APP_ID = "engine-a5-agent-synthetic";
export const PREVIEW_PILOT_AGENT_ID = "agent:engine:a5-probe@1";
export const PREVIEW_PILOT_TOOL_ID = "a5-agent-probe.tool";

export const SYNTHETIC_TASK_PAYLOAD = Object.freeze({
  app_id: PREVIEW_PILOT_APP_ID,
  agent_id: PREVIEW_PILOT_AGENT_ID,
  messages: [{ role: "user", content: "synthetic" }],
  agent_plan: {
    agent_id: PREVIEW_PILOT_AGENT_ID,
    steps: [
      {
        step_id: "read",
        objective: "Run synthetic read",
        tool_id: PREVIEW_PILOT_TOOL_ID,
      },
    ],
  },
  tool_arguments: {
    read: { query: "synthetic" },
  },
});

export const PREVIEW_PILOT_PATH = "/run-pilot";
export const AUTH_CHECK_PATH = "/auth-check";
export const ENGINE_SKILL_RUN_URL = "https://padiem-ai-engine-preview.internal/internal/v1/agent-skill/run";
export const MAX_PREVIEW_ENGINE_RESPONSE_BYTES = 256 * 1024;

const CALLER_ID_HEADER = "x-padiem-engine-caller";
const CALLER_CREDENTIAL_HEADER = "x-padiem-engine-credential";

function jsonResponse(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

function constantTimeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const len = Math.max(a.length, b.length);
  let diff = a.length ^ b.length;
  for (let i = 0; i < len; i++) {
    const ca = i < a.length ? a.charCodeAt(i) : 0;
    const cb = i < b.length ? b.charCodeAt(i) : 0;
    diff |= ca ^ cb;
  }
  return diff === 0;
}

async function cancelReader(reader) {
  try {
    await reader.cancel();
  } catch {
    // Best-effort cleanup after a fail-closed verdict.
  }
}

function releaseReader(reader) {
  try {
    reader.releaseLock();
  } catch {
    // Best-effort cleanup after the body has been consumed or cancelled.
  }
}

async function readBoundedEngineObject(response) {
  const body = response?.body;
  if (!body || typeof body.getReader !== "function") {
    return {
      error: jsonResponse(502, {
        ok: false,
        error: {
          code: "invalid_engine_response",
          message: "Preview engine returned an invalid response.",
        },
      }),
    };
  }

  const reader = body.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      const chunk = value instanceof Uint8Array ? value : new Uint8Array(value ?? []);
      if (total + chunk.byteLength > MAX_PREVIEW_ENGINE_RESPONSE_BYTES) {
        await cancelReader(reader);
        return {
          error: jsonResponse(502, {
            ok: false,
            error: {
              code: "engine_response_too_large",
              message: "Preview engine response exceeded the safety limit.",
            },
          }),
        };
      }
      total += chunk.byteLength;
      chunks.push(chunk);
    }
  } catch {
    await cancelReader(reader);
    return {
      error: jsonResponse(502, {
        ok: false,
        error: {
          code: "invalid_engine_response",
          message: "Preview engine response could not be read.",
        },
      }),
    };
  } finally {
    releaseReader(reader);
  }

  const raw = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    raw.set(chunk, offset);
    offset += chunk.byteLength;
  }

  let parsed;
  try {
    parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
  } catch {
    return {
      error: jsonResponse(502, {
        ok: false,
        error: {
          code: "invalid_engine_response",
          message: "Preview engine returned an invalid response.",
        },
      }),
    };
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return {
      error: jsonResponse(502, {
        ok: false,
        error: {
          code: "invalid_engine_response",
          message: "Preview engine returned an invalid response.",
        },
      }),
    };
  }
  return { value: parsed };
}

export async function handleCaller(request, env) {
  const url = new URL(request.url);

  // Health check endpoint
  if (url.pathname === "/health" && request.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "padiem-ai-engine-preview-caller",
      status: "ready",
    });
  }

  // Auth readiness check endpoint for secret propagation verification
  if (url.pathname === AUTH_CHECK_PATH && (request.method === "GET" || request.method === "POST")) {
    const authHeader = request.headers.get("authorization") || "";
    const token = authHeader.startsWith("Bearer ") ? authHeader.slice(7).trim() : "";
    const runnerSecret = env?.PILOT_RUNNER_SECRET;
    const engineCredential = env?.PREVIEW_ENGINE_CREDENTIAL;

    if (!runnerSecret || !token || !constantTimeEqual(token, runnerSecret)) {
      return jsonResponse(401, {
        ok: false,
        error: { code: "unauthorized", message: "Invalid or missing runner bearer token." },
      });
    }

    if (!engineCredential) {
      return jsonResponse(503, {
        ok: false,
        error: {
          code: "caller_credential_unavailable",
          message: "PREVIEW_ENGINE_CREDENTIAL secret is not available.",
        },
      });
    }

    return jsonResponse(200, {
      ok: true,
      service: "padiem-ai-engine-preview-caller",
      status: "authenticated",
    });
  }

  if (url.pathname !== PREVIEW_PILOT_PATH || request.method !== "POST") {
    return jsonResponse(404, {
      ok: false,
      error: { code: "not_found", message: "Route not found." },
    });
  }

  // Runner authentication
  const authHeader = request.headers.get("authorization") || "";
  const token = authHeader.startsWith("Bearer ") ? authHeader.slice(7).trim() : "";
  const runnerSecret = env?.PILOT_RUNNER_SECRET;

  if (!runnerSecret || !token || !constantTimeEqual(token, runnerSecret)) {
    return jsonResponse(401, {
      ok: false,
      error: { code: "unauthorized", message: "Invalid or missing runner bearer token." },
    });
  }

  // Service binding guard
  const previewEngine = env?.PREVIEW_ENGINE;
  if (!previewEngine || typeof previewEngine.fetch !== "function") {
    return jsonResponse(503, {
      ok: false,
      error: {
        code: "service_binding_unavailable",
        message: "PREVIEW_ENGINE service binding is unavailable.",
      },
    });
  }

  // Ephemeral caller authority guard
  const credential = env?.PREVIEW_ENGINE_CREDENTIAL;
  if (!credential || typeof credential !== "string") {
    return jsonResponse(503, {
      ok: false,
      error: {
        code: "caller_credential_unavailable",
        message: "PREVIEW_ENGINE_CREDENTIAL is not configured.",
      },
    });
  }

  const callerId = env?.PREVIEW_ENGINE_CALLER_ID || "preview-pilot-caller";

  // Single invocation to preview engine using the fixed synthetic payload ONLY
  let engineResponse;
  try {
    engineResponse = await previewEngine.fetch(
      new Request(ENGINE_SKILL_RUN_URL, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          [CALLER_ID_HEADER]: callerId,
          [CALLER_CREDENTIAL_HEADER]: credential,
        },
        body: JSON.stringify(SYNTHETIC_TASK_PAYLOAD),
      })
    );
  } catch (_err) {
    return jsonResponse(502, {
      ok: false,
      error: {
        code: "engine_connection_failed",
        message: "Failed to connect to preview engine over service binding.",
      },
    });
  }

  const status = engineResponse.status;
  const bounded = await readBoundedEngineObject(engineResponse);
  if (bounded.error) return bounded.error;
  const parsed = bounded.value;

  return jsonResponse(status, {
    ok: engineResponse.ok,
    status_code: status,
    caller_service: "padiem-ai-engine-preview-caller",
    target_service: "padiem-ai-engine-preview",
    target_route: "/internal/v1/agent-skill/run",
    synthetic_app_id: PREVIEW_PILOT_APP_ID,
    engine_response: parsed,
  });
}

export default {
  fetch: handleCaller,
};
