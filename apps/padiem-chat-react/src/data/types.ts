/**
 * #5298 — shared first-screen types.
 *
 * These mirror the operational Chat / Claw contract closely enough that a
 * later PR can swap the fixture source for the real API without reshaping the
 * component tree.
 */

export type ProductMode = "chat" | "claw";

export type ShellState =
  | "home"
  | "chat"
  | "claw"
  | "connectors"
  | "automation"
  | "meeting";

export type MessageState = "streaming" | "complete" | "error";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** ISO timestamp. `null` for a restored turn that never had one. */
  completedAt: string | null;
  state: MessageState;
  errorMessage: string | null;
  /** The prompt that produced this answer. Kept so a failed turn can retry. */
  sourcePrompt: string | null;
  /** The canonical P01 runtime label, when the server reported one. */
  runtimeLabel?: string | null;
  /** How many times this turn has been attempted. The first attempt is 1. */
  attempt: number;
  /** Set when the turn came from the local fixture source, not a live API. */
  fixture: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  product: ProductMode;
  updatedAt: string;
  messages: ChatMessage[];
}

/**
 * Model choices are described by their execution contract, not by provider or
 * model identity. The public repository must not publish model-to-tier
 * assignments; the authoritative registry stays in the controlled source.
 */
export interface ModelChoice {
  id: string;
  label: string;
  description: string;
}

export type ConnectorId = "pc" | "drive" | "github" | "web";

export type ConnectorState = "unknown" | "check" | "connected" | "disconnected";

export interface ConnectorCard {
  id: ConnectorId;
  label: string;
  description: string;
  state: ConnectorState;
}

export interface PendingAttachment {
  id: string;
  name: string;
  sizeLabel: string;
  kind: "image" | "document";
}
