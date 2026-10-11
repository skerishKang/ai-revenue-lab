/**
 * CLAW4 #3083 — renderer-facing type re-exports.
 *
 * The renderer re-uses the exact contract types the main process enforces, so
 * a projection can never be reshaped on its way to the UI.
 */

export type {
  BoundedLogResponse,
  CanonicalConversationDetail,
  CanonicalConversationListItem,
  CanonicalConversationListResponse,
  CanonicalConversationMessage,
  CanonicalConversationReadResponse,
  CanonicalRunArtifactRef,
  CanonicalRunListItem,
  CanonicalRunListResponse,
  CanonicalRunReadResponse,
  CanonicalRunStatus,
  PairingDeepLinkResponse,
  RunnerHealthResponse,
  RunnerStartResponse,
  RunnerStopResponse,
  ShellStatus,
  WorkspaceEntry,
  WorkspaceEntryKind,
  WorkspaceListResponse,
  WorkspaceRootResponse,
  WorkspaceSearchResponse,
} from '../contract/ipc.js';

export type { DeviceLifecycleState } from '../contract/device-lifecycle.js';
