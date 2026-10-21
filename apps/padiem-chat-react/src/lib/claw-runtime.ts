/**
 * #5298 — typed access to the operational Claw runtime modules.
 *
 * These modules are the product's own Claw truth: the canonical P01 event
 * projection, the observed-run recovery state and the orchestration approval
 * model. The clone consumes them instead of re-implementing the rules, so a
 * clone run and a product run cannot disagree about what a P01 event means.
 */

import "../../../../apps/padiem-chat/static/claw-run-event-projection.js";
import "../../../../apps/padiem-chat/static/claw-recovery-truth.js";
import "../../../../apps/padiem-chat/static/message-lifecycle.js";

export interface RunEventProjection {
  consume(event: unknown): {
    accepted: boolean;
    reason?: string;
    kind?: string;
    sequence?: number;
    terminal?: boolean;
    labelAvailable?: boolean;
  };
  snapshot(): {
    runId: string | null;
    traceId: string | null;
    appId: string | null;
    sequence: number;
    terminal: boolean;
  };
}

export interface RecoveryTruth {
  observe(kind: string): boolean;
  state(): string;
  seen(): boolean;
  completionAllowed(): boolean;
}

export interface ApprovalModel {
  approval?: {
    continuationRef: string;
    pauseId: string;
    summary?: unknown;
  } | null;
  terminal?: string | null;
  events?: { kind: string }[];
  [key: string]: unknown;
}

export interface ApprovalIntent {
  continuationRef: string;
  pauseId: string;
  outcome: "approved" | "denied";
  requiresTrustedDecision: boolean;
}

export interface CancelIntent {
  continuationRef: string;
}

export interface OrchestrationUi {
  kinds: Record<string, string>;
  viewModel(orchestration: unknown): ApprovalModel;
  approvalIntent(orchestration: unknown, outcome: "approved" | "denied"): ApprovalIntent | null;
  cancelIntent(orchestration: unknown): CancelIntent | null;
}

const runtime = globalThis as typeof globalThis & {
  PadiemClawRunEventProjection?: {
    create(): RunEventProjection;
    label(kind: string, lang?: string): string | null;
  };
  PadiemClawRecoveryTruth?: {
    create(): RecoveryTruth;
    copy(state: string, lang?: string): string;
  };
  PadiemChatOrchestrationUI?: OrchestrationUi;
  padiemSelectedDeviceId?: string | null;
  padiemClawSelectedDeviceId?: string | null;
};

if (!runtime.PadiemClawRunEventProjection || !runtime.PadiemClawRecoveryTruth) {
  throw new Error(
    "The operational Claw runtime modules did not publish their globals",
  );
}

export const clawRunEventProjection = runtime.PadiemClawRunEventProjection;
export const clawRecoveryTruth = runtime.PadiemClawRecoveryTruth;
export const clawOrchestrationUi: OrchestrationUi | undefined =
  runtime.PadiemChatOrchestrationUI;

/**
 * The shared execution-target hint.
 *
 * The operational transport reads this global when it builds the request, so
 * setting it here is the same choice the product makes.
 */
export function setSelectedDeviceId(deviceId: string | null): void {
  runtime.padiemSelectedDeviceId = deviceId;
  runtime.padiemClawSelectedDeviceId = deviceId;
}
