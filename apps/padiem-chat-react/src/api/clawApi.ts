import { chatTransport } from "../lib/chat-transport";
import {
  clawOrchestrationUi,
  clawRecoveryTruth,
  clawRunEventProjection,
  setSelectedDeviceId,
  type RecoveryTruth,
  type RunEventProjection,
} from "../lib/claw-runtime";
import type { OutboundMessage } from "./types";

/**
 * #5298 — the real Claw execution client.
 *
 * The generic Claw submit runs on the canonical P01 Engine lane. There is
 * deliberately no fallback to the standalone Chat lane: an unavailable P01 lane
 * surfaces as a bounded error instead of silently changing products.
 *
 * The request contract, the P01 event projection, the observed-run recovery
 * truth and the approval intents all come from the operational modules.
 */

export interface ClawCapabilities {
  live_events_available?: boolean;
  [key: string]: unknown;
}

export interface ClawDevice {
  device_id: string;
  name?: string;
  platform?: string;
  online?: boolean;
  state?: string;
  revoked?: boolean;
  expired?: boolean;
  [key: string]: unknown;
}

export interface ClawDeviceDirectory {
  devices?: ClawDevice[];
  saved_target_id?: string | null;
  status_code?: string;
  available?: boolean;
  read_completed?: boolean;
  [key: string]: unknown;
}

export interface ClawRequest {
  messages: OutboundMessage[];
  tier?: string;
  skill?: string;
  modelId?: string | null;
  signal: AbortSignal;
}

export interface ClawStreamHandlers {
  /** A validated P01 event, projected to its canonical kind and label. */
  onRuntimeLabel: (label: string) => void;
  onDelta: (text: string) => void;
  onDone: (result: { answer: string; conversationId: string | null }) => void;
  /** The observed-run state, used for the bounded failure copy. */
  onRecovery: (recovery: RecoveryTruth) => void;
}

export async function fetchClawCapabilities(signal?: AbortSignal): Promise<ClawCapabilities> {
  const response = await fetch("/api/claw/general/capabilities", {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw new Error("Claw 실행 준비 상태를 확인하지 못했습니다.");
  }
  return (await response.json()) as ClawCapabilities;
}

export async function fetchClawDeviceDirectory(
  signal?: AbortSignal,
): Promise<ClawDeviceDirectory> {
  const response = await fetch("/api/claw/local-access/devices", {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw new Error("연결된 컴퓨터를 확인하지 못했습니다.");
  }
  return (await response.json()) as ClawDeviceDirectory;
}

/** Chooses the execution target. The server re-verifies it against the authority. */
export async function selectClawDevice(deviceId: string): Promise<void> {
  const response = await fetch("/api/claw/local-access/devices/select", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ device_id: deviceId }),
  });
  if (!response.ok) {
    throw new Error("작업 대상 컴퓨터를 저장하지 못했습니다.");
  }
  setSelectedDeviceId(deviceId);
}

/**
 * Streams one Claw execution.
 *
 * Only a validated canonical P01 envelope can change the runtime label. A
 * legacy delta/done stream keeps its existing response status, and a verified
 * P01 failure, cancellation or approval pause can never be revived by a later
 * delta.
 */
export async function streamClawGeneral(
  request: ClawRequest,
  handlers: ClawStreamHandlers,
): Promise<void> {
  const payload: Record<string, unknown> = {
    messages: request.messages,
  };
  if (request.tier) payload.tier = request.tier;
  if (request.skill) payload.skill = request.skill;
  if (request.modelId) payload.model_id = request.modelId;

  const projection: RunEventProjection = clawRunEventProjection.create();
  const recovery: RecoveryTruth = clawRecoveryTruth.create();
  handlers.onRecovery(recovery);

  const response = await chatTransport.requestClawGeneral(payload, request.signal);

  let answer = "";
  let conversationId: string | null = null;
  let done = false;

  await chatTransport.readSseEvents(response, async (frame) => {
    if (frame.event === "p01_event") {
      let envelope: unknown;
      try {
        envelope = JSON.parse(frame.data);
      } catch {
        return false;
      }
      const delivery =
        envelope && typeof envelope === "object"
          ? (envelope as { delivery?: string }).delivery
          : undefined;
      if (delivery !== "live" && delivery !== "post_execution") return false;
      const projected = projection.consume(envelope);
      if (!projected.accepted || !projected.kind) return false;
      recovery.observe(projected.kind);
      if (delivery === "post_execution") {
        // The Engine returned a completed run, not a live event.
        return false;
      }
      const label = clawRunEventProjection.label(projected.kind);
      if (label) handlers.onRuntimeLabel(label);
      return false;
    }

    if (!["delta", "done", "error"].includes(frame.event)) return false;
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(frame.data) as Record<string, unknown>;
    } catch {
      throw new Error("스트리밍 응답 형식이 올바르지 않습니다.");
    }

    if (frame.event === "delta") {
      // Never append new content after a verified failure, cancellation or
      // approval pause.
      if (!recovery.completionAllowed()) return false;
      if (typeof data.delta !== "string") {
        throw new Error("스트리밍 응답 형식이 올바르지 않습니다.");
      }
      if (!data.delta) return false;
      answer += data.delta;
      handlers.onDelta(data.delta);
      return false;
    }

    if (frame.event === "error") {
      const error = new Error(
        typeof data.message === "string"
          ? data.message
          : "AI 작업을 처리하지 못했습니다. 다시 시도해 주세요.",
      ) as Error & { code?: string };
      if (typeof data.code === "string") error.code = data.code;
      throw error;
    }

    if (typeof data.conversation_id === "string") conversationId = data.conversation_id;
    done = true;
    handlers.onDone({ answer, conversationId });
    return true;
  });

  if (!done) {
    throw new Error("AI 작업을 처리하지 못했습니다. 다시 시도해 주세요.");
  }
}

/** The bounded copy for a failed, cancelled or unverified Claw run. */
export function clawFailureCopy(state: string): string {
  return clawRecoveryTruth.copy(state);
}

/** The approval intents the operational transport resumes and cancels with. */
export const clawApproval = {
  approve(orchestration: unknown) {
    return clawOrchestrationUi?.approvalIntent(orchestration, "approved") ?? null;
  },
  deny(orchestration: unknown) {
    return clawOrchestrationUi?.approvalIntent(orchestration, "denied") ?? null;
  },
  cancel(orchestration: unknown) {
    return clawOrchestrationUi?.cancelIntent(orchestration) ?? null;
  },
  viewModel(orchestration: unknown) {
    return clawOrchestrationUi?.viewModel(orchestration) ?? null;
  },
};
