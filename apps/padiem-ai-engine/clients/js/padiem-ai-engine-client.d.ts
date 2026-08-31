export const ENGINE_CONTRACT_MAJOR: 1;
export const ENGINE_CONTRACT_VERSION: "1.0";
export const ENGINE_EXECUTE_PATH: "/internal/v1/execute";
export const ENGINE_STREAM_PATH: "/internal/v1/stream";
export const ENGINE_HEALTH_PATH: "/internal/v1/health";
export const ENGINE_ORCHESTRATE_PATH: "/internal/v1/orchestrate";
export const ENGINE_ORCHESTRATE_RESUME_PATH: "/internal/v1/orchestrate/resume";
export const ENGINE_ORCHESTRATE_CANCEL_PATH: "/internal/v1/orchestrate/cancel";

export interface EngineBinding {
  fetch(input: string | URL | Request, init?: RequestInit): Promise<Response>;
}

export interface EngineExecutionContext {
  trace_id: string;
  idempotency_key?: string;
  timeout_seconds?: number;
}

export interface EngineAgentRequest {
  id: string;
  title: string;
  description: string;
  system_instruction: string;
  task_type: string;
  optimize_for: string;
  max_tokens: number;
  required_capabilities?: string[];
  model_policy?: Record<string, unknown>;
}

export interface EngineMessage {
  role: "user" | "assistant";
  content: string;
}

export interface EnginePlanStep {
  step_id: string;
  objective: string;
  tool_id?: string | null;
  depends_on?: string[];
}

export interface EngineAgentPlan {
  agent_id: string;
  steps: EnginePlanStep[];
}

export interface EngineRunRequest {
  agent: EngineAgentRequest;
  messages: EngineMessage[];
  session_id?: string | null;
  additional_system_context?: string | null;
  trace_id?: string | null;
  execution_context?: EngineExecutionContext;
  subject_id?: string | null;
  agent_plan?: EngineAgentPlan;
  agent_definition?: Record<string, unknown>;
  compiled_agent_profile?: Record<string, unknown>;
  tool_authorization?: Record<string, unknown>;
  recovery_policy?: Record<string, unknown>;
  max_retries?: number;
  require_evidence?: boolean;
  require_verification?: boolean;
  pause?: Record<string, unknown>;
  decision?: Record<string, unknown>;
  reason?: string;
}

export interface EngineCompletedResult {
  ok: true;
  answer: string;
  route: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface EngineOrchestrationResult {
  execution: Record<string, unknown>;
  context: Record<string, unknown>;
  app_id: string;
  subject_id?: string | null;
  plan?: Record<string, unknown> | null;
  activated_skill?: Record<string, unknown> | null;
  resolved_tool_ids: string[];
  evidence: Record<string, unknown>;
  events: Record<string, unknown>[];
  approval_pause?: Record<string, unknown> | null;
  continuation_state?: Record<string, unknown> | null;
  state_machine?: Record<string, unknown> | null;
}

export interface EngineStreamEvent {
  delta_content?: string | null;
  answer?: string | null;
  finish_reason?: string | null;
  route?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  done?: boolean;
}

export interface EngineHealthResult {
  status: string;
  service: string;
  core_available: boolean;
  b14_service_bound: boolean;
  completed_run: boolean;
  streaming_run: boolean;
  orchestration_run?: boolean;
  [key: string]: unknown;
}

export class PadiemAiEngineClientError extends Error {
  readonly code: string;
  readonly status: number | null;
  readonly retryable: boolean;
  readonly metadata: unknown;
}

export interface PadiemAiEngineClientOptions {
  binding: EngineBinding;
  appId: string;
  callerId: string;
  credential: string;
}

export class PadiemAiEngineClient {
  constructor(options: PadiemAiEngineClientOptions);
  execute(run: EngineRunRequest): Promise<EngineCompletedResult>;
  orchestrate(request: EngineRunRequest): Promise<EngineOrchestrationResult>;
  resumeOrchestration(request: EngineRunRequest): Promise<EngineOrchestrationResult>;
  cancelOrchestrationPause(request: Record<string, unknown>): Promise<Record<string, unknown>>;
  stream(run: EngineRunRequest): AsyncGenerator<EngineStreamEvent, void, unknown>;
  health(): Promise<EngineHealthResult>;
}
