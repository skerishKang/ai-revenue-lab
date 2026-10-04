/**
 * CLAW4 #3083 — narrow typed IPC contract.
 *
 * Rules enforced here (issue #3083 "Security"):
 *
 *   NO_GENERIC_INVOKE_COMMAND_ARGS=YES
 *   NO_ARBITRARY_CHANNEL_PASSTHROUGH=YES
 *   ALLOWLIST_ONLY=YES
 *   RENDERER_CREDENTIAL_AUTHORITY=NO
 *
 * Every channel is a literal constant with a fixed request/response pair.
 * There is deliberately no `invoke(command, args)` entry point and no
 * `on(channel, cb)` passthrough that accepts an arbitrary channel name.
 */

export const IPC_CHANNELS = [
  'padiem:shell:get-status',
  'padiem:shell:runner-start',
  'padiem:shell:runner-stop',
  'padiem:shell:runner-health',
  'padiem:shell:pairing-deeplink-submit',
  'padiem:shell:get-bounded-log',
  'padiem:shell:workspace-choose-root',
  'padiem:shell:workspace-list',
  'padiem:shell:workspace-clear-root',
  'padiem:shell:conversation-list',
  'padiem:shell:conversation-read',
  'padiem:shell:run-list',
  'padiem:shell:run-read',
] as const;

export type IpcChannel = (typeof IPC_CHANNELS)[number];

export const IPC_ALLOWLIST: ReadonlySet<string> = Object.freeze(
  new Set<string>(IPC_CHANNELS),
) as ReadonlySet<string>;

export const IPC_SECURITY = Object.freeze({
  CONTEXT_ISOLATION: true,
  NODE_INTEGRATION: false,
  SANDBOX: true,
  NO_GENERIC_INVOKE_COMMAND_ARGS: true,
  NO_ARBITRARY_CHANNEL_PASSTHROUGH: true,
  NO_RAW_SHELL_TERMINAL: true,
  RENDERER_CREDENTIAL_AUTHORITY: false,
  ALLOWLIST_SIZE: IPC_CHANNELS.length,
} as const);

/** Explicitly denied capabilities — asserted by negative tests. */
export const DENIED_IPC_CHANNELS = Object.freeze([
  'padiem:shell:invoke',
  'padiem:shell:exec',
  'padiem:shell:run-command',
  'padiem:shell:read-file',
  'padiem:shell:write-file',
  'padiem:shell:spawn',
  'padiem:shell:shell',
  'padiem:shell:set-pairing-credential',
  'padiem:shell:mint-session',
  'padiem:shell:broker-transport',
  'padiem:shell:approve',
  '*',
  'padiem:shell:*',
]);

export function isAllowedIpcChannel(candidate: unknown): candidate is IpcChannel {
  return typeof candidate === 'string' && IPC_ALLOWLIST.has(candidate);
}

export class IpcContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'IpcContractError';
  }
}

export function assertAllowedIpcChannel(candidate: unknown): IpcChannel {
  if (!isAllowedIpcChannel(candidate)) {
    throw new IpcContractError(
      `ipc channel not in static allowlist: ${String(candidate)}`,
    );
  }
  return candidate;
}

export type RunnerLifecycleState = 'STOPPED' | 'STARTING' | 'RUNNING' | 'STOPPING' | 'CRASHED';

export interface ShellStatus {
  readonly deviceState: import('./device-lifecycle.js').DeviceLifecycleState;
  readonly deviceStateRevision: number;
  readonly runnerState: RunnerLifecycleState;
  readonly runnerPid: number | null;
  readonly pairingSeamAccepted: boolean;
  readonly authoritativeTruthOwner: '#3080';
  readonly rendererMayDeclareOnline: false;
}

export interface RunnerStartRequest {
  readonly requestedBy: 'renderer-shell';
}

export interface RunnerStartResponse {
  readonly ok: boolean;
  readonly state: RunnerLifecycleState;
  readonly pid: number | null;
  readonly reason: string;
}

export interface RunnerStopRequest {
  readonly requestedBy: 'renderer-shell';
}

export interface RunnerStopResponse {
  readonly ok: boolean;
  readonly state: RunnerLifecycleState;
  readonly pid: number | null;
  readonly reason: string;
}

export interface RunnerHealthResponse {
  readonly state: RunnerLifecycleState;
  readonly pid: number | null;
  readonly alive: boolean;
  readonly checkedAtMs: number;
  readonly lastExitCode: number | null;
  readonly lastExitSignal: string | null;
}

export interface PairingDeepLinkRequest {
  readonly deepLink: string;
}

export interface PairingDeepLinkResponse {
  readonly accepted: boolean;
  readonly kind: 'pair' | 'unknown';
  readonly correlationRef: string | null;
  readonly reason: string;
  readonly pairingAuthorityOwnedBy: '#3080';
  readonly credentialStored: false;
  readonly sessionMinted: false;
  /**
   * #3095. Whether a bounded pairing code crossed the seam to the trusted
   * runner boundary. This is a boolean *fact*, never the value itself: the
   * renderer must never see the pairing code, so the response surface gains no
   * secret field.
   */
  readonly pairingCodeTransferred: boolean;
  readonly pairingCodePersisted: false;
  readonly pairingCodeRendererDiagnostic: false;
}

export interface BoundedLogRequest {
  readonly maxLines?: number;
}

export interface BoundedLogResponse {
  readonly lines: readonly string[];
  readonly truncated: boolean;
  readonly redactionApplied: true;
}

export interface WorkspaceRootResponse {
  readonly selected: boolean;
  readonly rootName: string | null;
  readonly rootPath: string | null;
  readonly reason: 'current' | 'selected' | 'cancelled' | 'invalid_selection' | 'cleared';
}

export type WorkspaceEntryKind = 'directory' | 'file' | 'link';

export interface WorkspaceEntry {
  readonly name: string;
  readonly relativePath: string;
  readonly kind: WorkspaceEntryKind;
  /**
   * #3436 project browser: bounded basic metadata, projected per entry by the
   * main process from the same validated directory. Null when the entry is
   * not a regular file or the stat could not be taken — the listing stays
   * usable and truthful either way. Read-only surface: no content bytes ever
   * cross this contract.
   */
  readonly sizeBytes: number | null;
  readonly modifiedAt: string | null;
}

export interface WorkspaceListRequest {
  readonly relativePath?: string;
}

export interface WorkspaceListResponse {
  readonly ok: boolean;
  readonly root: WorkspaceRootResponse;
  readonly directory: string;
  readonly entries: readonly WorkspaceEntry[];
  readonly truncated: boolean;
  readonly maxEntries: number;
  readonly errorCode:
    | null
    | 'root_not_selected'
    | 'invalid_relative_path'
    | 'path_outside_root'
    | 'depth_exceeded'
    | 'workspace_unavailable';
}

/**
 * #3436 B2b — canonical conversation projection (read-only).
 *
 * Every value here came from the canonical Padiem conversation authority in
 * the current call. The Desktop mints no conversation id, keeps no conversation
 * store, and adds no message history: `SECOND_CONVERSATION_AUTHORITY = 0`.
 */
export interface CanonicalConversationListItem {
  readonly id: string;
  readonly title: string;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface CanonicalConversationListResponse {
  readonly ok: boolean;
  readonly configured: boolean;
  readonly conversations: readonly CanonicalConversationListItem[];
  readonly errorCode: null | 'canonical_conversation_unavailable' | 'invalid_conversation_payload';
}

export interface CanonicalConversationMessage {
  readonly role: 'user' | 'assistant';
  readonly content: string;
}

export interface CanonicalConversationDetail {
  readonly id: string;
  readonly title: string;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly messages: readonly CanonicalConversationMessage[];
}

export interface CanonicalConversationReadRequest {
  readonly conversationId: string;
}

export interface CanonicalConversationReadResponse {
  readonly ok: boolean;
  readonly conversation: CanonicalConversationDetail | null;
  readonly errorCode: null | 'canonical_conversation_unavailable' | 'invalid_conversation_id' | 'conversation_not_found' | 'invalid_conversation_payload';
}

/**
 * #3436 B3a — canonical run projection (read-only).
 *
 * The canonical types live in `../run/canonical-run.js` next to the authority
 * boundary that validates them; the IPC surface re-exports them unchanged so a
 * projection can never be reshaped on its way to the renderer.
 */
import type {
  CanonicalRunListResponse,
  CanonicalRunReadRequest,
  CanonicalRunReadResponse,
} from '../run/canonical-run.js';

export type {
  CanonicalRunArtifactRef,
  CanonicalRunListItem,
  CanonicalRunListResponse,
  CanonicalRunReadRequest,
  CanonicalRunReadResponse,
  CanonicalRunStatus,
} from '../run/canonical-run.js';

/** Maps a channel to its request/response types — the whole surface, closed. */
export interface IpcSurface {
  'padiem:shell:get-status': { request: undefined; response: ShellStatus };
  'padiem:shell:runner-start': { request: RunnerStartRequest; response: RunnerStartResponse };
  'padiem:shell:runner-stop': { request: RunnerStopRequest; response: RunnerStopResponse };
  'padiem:shell:runner-health': { request: undefined; response: RunnerHealthResponse };
  'padiem:shell:pairing-deeplink-submit': {
    request: PairingDeepLinkRequest;
    response: PairingDeepLinkResponse;
  };
  'padiem:shell:get-bounded-log': { request: BoundedLogRequest; response: BoundedLogResponse };
  'padiem:shell:workspace-choose-root': { request: undefined; response: WorkspaceRootResponse };
  'padiem:shell:workspace-list': { request: WorkspaceListRequest; response: WorkspaceListResponse };
  'padiem:shell:workspace-clear-root': { request: undefined; response: WorkspaceRootResponse };
  'padiem:shell:conversation-list': {
    request: undefined;
    response: CanonicalConversationListResponse;
  };
  'padiem:shell:conversation-read': {
    request: CanonicalConversationReadRequest;
    response: CanonicalConversationReadResponse;
  };
  'padiem:shell:run-list': {
    request: undefined;
    response: CanonicalRunListResponse;
  };
  'padiem:shell:run-read': {
    request: CanonicalRunReadRequest;
    response: CanonicalRunReadResponse;
  };
}

export type IpcRequestOf<C extends IpcChannel> = IpcSurface[C]['request'];
export type IpcResponseOf<C extends IpcChannel> = IpcSurface[C]['response'];
