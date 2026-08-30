const ENGINE_INTERNAL_ORIGIN = "https://padiem-ai-engine.internal";
export const ENGINE_CONTRACT_MAJOR = 1;
export const ENGINE_CONTRACT_VERSION = "1.0";
export const ENGINE_EXECUTE_PATH = "/internal/v1/execute";
export const ENGINE_STREAM_PATH = "/internal/v1/stream";
export const ENGINE_HEALTH_PATH = "/internal/v1/health";

const ENGINE_CALLER_HEADER = "X-Padiem-Engine-Caller";
const ENGINE_CREDENTIAL_HEADER = "X-Padiem-Engine-Credential";

const REQUEST_ALLOWED = new Set([
  "agent",
  "messages",
  "session_id",
  "additional_system_context",
  "trace_id",
]);

export class PadiemAiEngineClientError extends Error {
  constructor(code, message, { status = null, retryable = false, metadata = null } = {}) {
    super(message);
    this.name = "PadiemAiEngineClientError";
    this.code = code;
    this.status = status;
    this.retryable = Boolean(retryable);
    this.metadata = metadata;
  }
}

function requireSafeIdentifier(name, value) {
  if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value)) {
    throw new PadiemAiEngineClientError(
      "invalid_client_configuration",
      `${name} must be a bounded safe identifier`,
    );
  }
  return value;
}

function requireBinding(binding) {
  if (!binding || typeof binding.fetch !== "function") {
    throw new PadiemAiEngineClientError(
      "invalid_engine_binding",
      "Engine Service Binding must expose fetch()",
    );
  }
  return binding;
}

function exactRunPayload(appId, run) {
  if (!run || typeof run !== "object" || Array.isArray(run)) {
    throw new PadiemAiEngineClientError(
      "invalid_engine_request",
      "Engine run request must be an object",
    );
  }
  const unknown = Object.keys(run).filter((key) => !REQUEST_ALLOWED.has(key));
  if (unknown.length > 0) {
    throw new PadiemAiEngineClientError(
      "invalid_engine_request",
      "Engine run request contains unsupported fields",
    );
  }
  if (!("agent" in run) || !("messages" in run)) {
    throw new PadiemAiEngineClientError(
      "invalid_engine_request",
      "Engine run request requires agent and messages",
    );
  }
  return {
    app_id: appId,
    agent: run.agent,
    messages: run.messages,
    ...(run.session_id === undefined ? {} : { session_id: run.session_id }),
    ...(run.additional_system_context === undefined
      ? {}
      : { additional_system_context: run.additional_system_context }),
    ...(run.trace_id === undefined ? {} : { trace_id: run.trace_id }),
  };
}

function authenticatedHeaders(callerId, credential) {
  const headers = { "Content-Type": "application/json" };
  if (callerId !== undefined || credential !== undefined) {
    if (typeof callerId !== "string" || callerId.length === 0) {
      throw new PadiemAiEngineClientError(
        "invalid_client_configuration",
        "callerId is required when caller credentials are configured",
      );
    }
    if (typeof credential !== "string" || credential.length === 0) {
      throw new PadiemAiEngineClientError(
        "invalid_client_configuration",
        "credential is required when caller credentials are configured",
      );
    }
    headers[ENGINE_CALLER_HEADER] = callerId;
    headers[ENGINE_CREDENTIAL_HEADER] = credential;
  }
  return headers;
}

async function parseJsonResponse(response) {
  let body;
  try {
    body = await response.json();
  } catch {
    throw new PadiemAiEngineClientError(
      "invalid_engine_response",
      "Engine returned an invalid JSON response",
      { status: response.status },
    );
  }
  if (!body || typeof body !== "object") {
    throw new PadiemAiEngineClientError(
      "invalid_engine_response",
      "Engine returned an invalid response object",
      { status: response.status },
    );
  }
  if (body.ok === false) {
    const error = body.error && typeof body.error === "object" ? body.error : {};
    throw new PadiemAiEngineClientError(
      typeof error.code === "string" ? error.code : "engine_request_failed",
      typeof error.message === "string" ? error.message : "Padiem AI Engine request failed",
      {
        status: response.status,
        retryable: error.retryable === true,
        metadata: error.metadata ?? null,
      },
    );
  }
  if (!response.ok) {
    throw new PadiemAiEngineClientError(
      "engine_http_error",
      "Padiem AI Engine request failed",
      { status: response.status },
    );
  }
  return body;
}

export class PadiemAiEngineClient {
  constructor({ binding, appId, callerId, credential }) {
    this.binding = requireBinding(binding);
    this.appId = requireSafeIdentifier("appId", appId);
    this.callerId = callerId === undefined ? undefined : requireSafeIdentifier("callerId", callerId);
    this.credential = credential;
  }

  _headers() {
    return authenticatedHeaders(this.callerId, this.credential);
  }

  async execute(run) {
    const payload = exactRunPayload(this.appId, run);
    const response = await this.binding.fetch(
      `${ENGINE_INTERNAL_ORIGIN}${ENGINE_EXECUTE_PATH}`,
      {
        method: "POST",
        headers: this._headers(),
        body: JSON.stringify(payload),
      },
    );
    const body = await parseJsonResponse(response);
    if (body.ok !== true || typeof body.answer !== "string") {
      throw new PadiemAiEngineClientError(
        "invalid_engine_response",
        "Engine completed-run response is invalid",
        { status: response.status },
      );
    }
    return body;
  }

  async *stream(run) {
    const payload = exactRunPayload(this.appId, run);
    const response = await this.binding.fetch(
      `${ENGINE_INTERNAL_ORIGIN}${ENGINE_STREAM_PATH}`,
      {
        method: "POST",
        headers: this._headers(),
        body: JSON.stringify(payload),
      },
    );

    const contentType = response.headers.get("content-type") || "";
    if (!response.ok || !contentType.toLowerCase().startsWith("application/x-ndjson")) {
      await parseJsonResponse(response);
      throw new PadiemAiEngineClientError(
        "invalid_engine_stream",
        "Engine did not return the internal NDJSON stream contract",
        { status: response.status },
      );
    }
    if (!response.body || typeof response.body.getReader !== "function") {
      throw new PadiemAiEngineClientError(
        "invalid_engine_stream",
        "Engine response body is not streamable",
        { status: response.status },
      );
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let newline;
        while ((newline = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, newline).trim();
          buffer = buffer.slice(newline + 1);
          if (!line) continue;
          yield parseStreamLine(line, response.status);
        }
      }
      buffer += decoder.decode();
      const tail = buffer.trim();
      if (tail) yield parseStreamLine(tail, response.status);
    } finally {
      try {
        await reader.cancel();
      } catch {
        // Best-effort downstream cancellation cleanup.
      }
      try {
        reader.releaseLock();
      } catch {
        // Ignore already-released readers.
      }
    }
  }

  async health() {
    const response = await this.binding.fetch(
      `${ENGINE_INTERNAL_ORIGIN}${ENGINE_HEALTH_PATH}`,
      { method: "GET" },
    );
    return parseJsonResponse(response);
  }
}

function parseStreamLine(line, status) {
  let body;
  try {
    body = JSON.parse(line);
  } catch {
    throw new PadiemAiEngineClientError(
      "invalid_engine_stream_event",
      "Engine emitted invalid NDJSON",
      { status },
    );
  }
  if (body && body.ok === false) {
    const error = body.error && typeof body.error === "object" ? body.error : {};
    throw new PadiemAiEngineClientError(
      typeof error.code === "string" ? error.code : "engine_stream_failed",
      typeof error.message === "string" ? error.message : "Padiem AI Engine stream failed",
      {
        status,
        retryable: error.retryable === true,
        metadata: error.metadata ?? null,
      },
    );
  }
  if (!body || body.ok !== true || !body.event || typeof body.event !== "object") {
    throw new PadiemAiEngineClientError(
      "invalid_engine_stream_event",
      "Engine emitted an invalid stream event",
      { status },
    );
  }
  return body.event;
}
