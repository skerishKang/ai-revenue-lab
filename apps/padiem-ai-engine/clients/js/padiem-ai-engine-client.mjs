const ENGINE_INTERNAL_ORIGIN = "https://padiem-ai-engine.internal";
export const ENGINE_CONTRACT_MAJOR = 1;
export const ENGINE_CONTRACT_VERSION = "1.0";
export const ENGINE_EXECUTE_PATH = "/internal/v1/execute";
export const ENGINE_STREAM_PATH = "/internal/v1/stream";
export const ENGINE_HEALTH_PATH = "/internal/v1/health";
export const ENGINE_ORCHESTRATE_PATH = "/internal/v1/orchestrate";
export const ENGINE_ORCHESTRATE_RESUME_PATH = "/internal/v1/orchestrate/resume";
export const ENGINE_ORCHESTRATE_CANCEL_PATH = "/internal/v1/orchestrate/cancel";

const ENGINE_CALLER_HEADER = "X-Padiem-Engine-Caller";
const ENGINE_CREDENTIAL_HEADER = "X-Padiem-Engine-Credential";

const REQUEST_ALLOWED = new Set([
  "agent",
  "messages",
  "session_id",
  "additional_system_context",
  "trace_id",
  "execution_context",
  "subject_id",
  "agent_plan",
  "agent_definition",
  "compiled_agent_profile",
  "tool_authorization",
  "recovery_policy",
  "max_retries",
  "require_evidence",
  "require_verification",
  "continuation_ref",
  "decision",
  "reason",
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

function requireCredential(value) {
  if (typeof value !== "string" || value.length < 32 || value.length > 512) {
    throw new PadiemAiEngineClientError(
      "invalid_client_configuration",
      "credential must contain 32 to 512 characters",
    );
  }
  return value;
}

function normalizeExecutionContext(value) {
  if (value === undefined || value === null) return undefined;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new PadiemAiEngineClientError("invalid_engine_request", "execution_context must be an object");
  }

  const allowed = new Set(["trace_id", "idempotency_key", "timeout_seconds"]);
  const unknown = Object.keys(value).filter((key) => !allowed.has(key));
  if (unknown.length > 0) {
    throw new PadiemAiEngineClientError("invalid_engine_request", "execution_context contains unsupported fields");
  }

  const context = {};
  if (value.trace_id === undefined) {
    throw new PadiemAiEngineClientError(
      "invalid_engine_request",
      "execution_context.trace_id is required",
    );
  }
  context.trace_id = requireSafeIdentifier("execution_context.trace_id", value.trace_id);

  if (value.idempotency_key !== undefined) {
    if (
      typeof value.idempotency_key !== "string" ||
      !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/.test(value.idempotency_key)
    ) {
      throw new PadiemAiEngineClientError(
        "invalid_engine_request",
        "execution_context.idempotency_key must be a bounded safe identifier",
      );
    }
    context.idempotency_key = value.idempotency_key;
  }
  if (value.timeout_seconds !== undefined) {
    if (
      typeof value.timeout_seconds !== "number" ||
      !Number.isFinite(value.timeout_seconds) ||
      value.timeout_seconds < 1 ||
      value.timeout_seconds > 60
    ) {
      throw new PadiemAiEngineClientError(
        "invalid_engine_request",
        "execution_context.timeout_seconds must be between 1 and 60",
      );
    }
    context.timeout_seconds = value.timeout_seconds;
  }
  return context;
}

function exactRunPayload(appId, run) {
  if (!run || typeof run !== "object" || Array.isArray(run)) {
    throw new PadiemAiEngineClientError("invalid_engine_request", "Engine run request must be an object");
  }
  const unknown = Object.keys(run).filter((key) => !REQUEST_ALLOWED.has(key));
  if (unknown.length > 0) {
    throw new PadiemAiEngineClientError("invalid_engine_request", "Engine run request contains unsupported fields");
  }
  if (!("agent" in run) || !("messages" in run)) {
    throw new PadiemAiEngineClientError("invalid_engine_request", "Engine run request requires agent and messages");
  }
  return {
    app_id: appId,
    agent: run.agent,
    messages: run.messages,
    ...(run.session_id === undefined ? {} : { session_id: run.session_id }),
    ...(run.additional_system_context === undefined ? {} : { additional_system_context: run.additional_system_context }),
    ...(run.trace_id === undefined ? {} : { trace_id: run.trace_id }),
    ...(run.execution_context === undefined ? {} : { execution_context: normalizeExecutionContext(run.execution_context) }),
    ...(run.subject_id === undefined ? {} : { subject_id: run.subject_id }),
    ...(run.agent_plan === undefined ? {} : { agent_plan: run.agent_plan }),
    ...(run.agent_definition === undefined ? {} : { agent_definition: run.agent_definition }),
    ...(run.compiled_agent_profile === undefined ? {} : { compiled_agent_profile: run.compiled_agent_profile }),
    ...(run.tool_authorization === undefined ? {} : { tool_authorization: run.tool_authorization }),
    ...(run.recovery_policy === undefined ? {} : { recovery_policy: run.recovery_policy }),
    ...(run.max_retries === undefined ? {} : { max_retries: run.max_retries }),
    ...(run.require_evidence === undefined ? {} : { require_evidence: run.require_evidence }),
    ...(run.require_verification === undefined ? {} : { require_verification: run.require_verification }),
    ...(run.continuation_ref === undefined ? {} : { continuation_ref: run.continuation_ref }),
    ...(run.decision === undefined ? {} : { decision: run.decision }),
    ...(run.reason === undefined ? {} : { reason: run.reason }),
  };
}

function authenticatedHeaders(callerId, credential) {
  return {
    "Content-Type": "application/json",
    [ENGINE_CALLER_HEADER]: callerId,
    [ENGINE_CREDENTIAL_HEADER]: credential,
  };
}

const CANCEL_ALLOWED = new Set(["continuation_ref", "reason"]);

function exactCancelPayload(appId, request) {
  if (!request || typeof request !== "object" || Array.isArray(request)) {
    throw new PadiemAiEngineClientError("invalid_engine_request", "Engine cancel request must be an object");
  }
  const unknown = Object.keys(request).filter((key) => !CANCEL_ALLOWED.has(key));
  if (unknown.length > 0) {
    throw new PadiemAiEngineClientError("invalid_engine_request", "Engine cancel request contains unsupported fields");
  }
  if (typeof request.continuation_ref !== "string" || !request.continuation_ref.startsWith("cont_")) {
    throw new PadiemAiEngineClientError("invalid_engine_request", "continuation_ref is required");
  }
  return {
    app_id: appId,
    continuation_ref: request.continuation_ref,
    ...(request.reason === undefined ? {} : { reason: request.reason }),
  };
}

async function parseJsonResponse(response) {
  let body;
  try { body = await response.json(); } catch {
    throw new PadiemAiEngineClientError("invalid_engine_response", "Engine returned an invalid JSON response", { status: response.status });
  }
  if (!body || typeof body !== "object") {
    throw new PadiemAiEngineClientError("invalid_engine_response", "Engine returned an invalid response object", { status: response.status });
  }
  if (body.ok === false) {
    const error = body.error && typeof body.error === "object" ? body.error : {};
    throw new PadiemAiEngineClientError(
      typeof error.code === "string" ? error.code : "engine_request_failed",
      typeof error.message === "string" ? error.message : "Padiem AI Engine request failed",
      { status: response.status, retryable: error.retryable === true, metadata: error.metadata ?? null },
    );
  }
  if (!response.ok) {
    throw new PadiemAiEngineClientError("engine_http_error", "Padiem AI Engine request failed", { status: response.status });
  }
  return body;
}

export class PadiemAiEngineClient {
  constructor({ binding, appId, callerId, credential }) {
    this.binding = requireBinding(binding);
    this.appId = requireSafeIdentifier("appId", appId);
    this.callerId = requireSafeIdentifier("callerId", callerId);
    this.credential = requireCredential(credential);
  }

  _headers() { return authenticatedHeaders(this.callerId, this.credential); }

  async execute(run) {
    const payload = exactRunPayload(this.appId, run);
    const response = await this.binding.fetch(`${ENGINE_INTERNAL_ORIGIN}${ENGINE_EXECUTE_PATH}`, {
      method: "POST", headers: this._headers(), body: JSON.stringify(payload),
    });
    const body = await parseJsonResponse(response);
    if (body.ok !== true || typeof body.answer !== "string") {
      throw new PadiemAiEngineClientError("invalid_engine_response", "Engine completed-run response is invalid", { status: response.status });
    }
    return body;
  }

  async orchestrate(request) {
    const payload = exactRunPayload(this.appId, request);
    const response = await this.binding.fetch(`${ENGINE_INTERNAL_ORIGIN}${ENGINE_ORCHESTRATE_PATH}`, {
      method: "POST", headers: this._headers(), body: JSON.stringify(payload),
    });
    const body = await parseJsonResponse(response);
    if (body.ok !== true || !body.orchestration) {
      throw new PadiemAiEngineClientError("invalid_engine_response", "Engine orchestration response is invalid", { status: response.status });
    }
    return body.orchestration;
  }

  async resumeOrchestration(request) {
    const payload = exactRunPayload(this.appId, request);
    const response = await this.binding.fetch(`${ENGINE_INTERNAL_ORIGIN}${ENGINE_ORCHESTRATE_RESUME_PATH}`, {
      method: "POST", headers: this._headers(), body: JSON.stringify(payload),
    });
    const body = await parseJsonResponse(response);
    if (body.ok !== true || !body.orchestration) {
      throw new PadiemAiEngineClientError("invalid_engine_response", "Engine orchestration resume response is invalid", { status: response.status });
    }
    return body.orchestration;
  }

  async cancelOrchestrationPause(request) {
    const payload = exactCancelPayload(this.appId, request);
    const response = await this.binding.fetch(`${ENGINE_INTERNAL_ORIGIN}${ENGINE_ORCHESTRATE_CANCEL_PATH}`, {
      method: "POST", headers: this._headers(), body: JSON.stringify(payload),
    });
    return parseJsonResponse(response);
  }

  async *stream(run) {
    const payload = exactRunPayload(this.appId, run);
    const response = await this.binding.fetch(`${ENGINE_INTERNAL_ORIGIN}${ENGINE_STREAM_PATH}`, {
      method: "POST", headers: this._headers(), body: JSON.stringify(payload),
    });
    const contentType = response.headers.get("content-type") || "";
    if (!response.ok || !contentType.toLowerCase().startsWith("application/x-ndjson")) {
      await parseJsonResponse(response);
      throw new PadiemAiEngineClientError("invalid_engine_stream", "Engine did not return the internal NDJSON stream contract", { status: response.status });
    }
    if (!response.body || typeof response.body.getReader !== "function") {
      throw new PadiemAiEngineClientError("invalid_engine_stream", "Engine response body is not streamable", { status: response.status });
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
      try { await reader.cancel(); } catch {}
      try { reader.releaseLock(); } catch {}
    }
  }

  async health() {
    const response = await this.binding.fetch(`${ENGINE_INTERNAL_ORIGIN}${ENGINE_HEALTH_PATH}`, { method: "GET" });
    return parseJsonResponse(response);
  }
}

function parseStreamLine(line, status) {
  let body;
  try { body = JSON.parse(line); } catch {
    throw new PadiemAiEngineClientError("invalid_engine_stream_event", "Engine emitted invalid NDJSON", { status });
  }
  if (body && body.ok === false) {
    const error = body.error && typeof body.error === "object" ? body.error : {};
    throw new PadiemAiEngineClientError(
      typeof error.code === "string" ? error.code : "engine_stream_failed",
      typeof error.message === "string" ? error.message : "Padiem AI Engine stream failed",
      { status, retryable: error.retryable === true, metadata: error.metadata ?? null },
    );
  }
  if (!body || body.ok !== true || !body.event || typeof body.event !== "object") {
    throw new PadiemAiEngineClientError("invalid_engine_stream_event", "Engine emitted an invalid stream event", { status });
  }
  return body.event;
}
