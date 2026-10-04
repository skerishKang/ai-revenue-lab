/**
 * #3436 B3a — Desktop-side consumer of the canonical Padiem Claw run
 * authority (apps/padiem-chat HistoryStore `claw_run_history`, exposed as
 * `GET /api/claw/runs`).
 *
 * Authority boundary:
 *
 *   SECOND_TASK_AUTHORITY=0 / SECOND_RUN_AUTHORITY=0
 *                                          Desktop mints no task or run id and
 *                                          stores no run state. Every run on
 *                                          this surface came from the canonical
 *                                          server in the current call; nothing
 *                                          is persisted.
 *   DESKTOP_RUN_ID_MINTING=0               The id grammar accepted here is the
 *                                          server's own bounded run-id grammar
 *                                          (`claw_local_task_result_routes._RUN_ID`).
 *                                          It is validated so a malformed or
 *                                          caller-shaped id fails closed before
 *                                          any request leaves the process, never
 *                                          so the Desktop can create one.
 *   DESKTOP_TASK_DATABASE=0
 *   DESKTOP_RUN_DATABASE=0                 No localStorage, no file, no cache.
 *   LOCAL_RUN_FALLBACK=0                   An unconfigured or failing port is the
 *                                          honest fail-closed answer — the same
 *                                          presentation as "canonical run
 *                                          unavailable", never a temporary or
 *                                          locally invented run.
 *   RUN_CONVERSATION_REBIND=0              The run→conversation linkage is the
 *                                          server's own (`history` #2829:
 *                                          immutable once set). This surface
 *                                          only projects it; no caller input can
 *                                          attach a run to a different
 *                                          conversation.
 *   RUN_WORKSPACE_REBIND=0                 The canonical `workspace_id` is
 *                                          projected verbatim when the payload
 *                                          carries it. The Desktop's selected
 *                                          local folder is never treated as a
 *                                          canonical Padiem workspace.
 *   RUN_MUTATION=0                         Read-only. No run create, no task
 *                                          create, no cancel, no retry, no
 *                                          approval decision, no P01 resume, no
 *                                          artifact download or mutation. Those
 *                                          stay with the canonical Claw/P01
 *                                          authorities.
 *   LIVE_ACTIVITY_SOURCE=NOT_YET_AVAILABLE There is no canonical live run-event
 *                                          authority in the repository yet. What
 *                                          this surface shows is a bounded,
 *                                          point-in-time projection of the
 *                                          canonical run history — it is never
 *                                          presented as a live stream.
 *
 * The transport is injected: the main process supplies an authenticated
 * canonical fetch port when the Desktop holds a canonical session credential,
 * and an UnconfiguredCanonicalRunPort otherwise. The response payload mirrors
 * `history._run_history_public` — the exact projection Web Claw reads — so the
 * two surfaces show the same canonical run state.
 */

import { CANONICAL_CONVERSATION_ID_PATTERN } from '../conversation/canonical-conversation.js';

/**
 * Mirrors `claw_local_task_result_routes._RUN_ID`, the server's own bounded
 * run-id grammar at its `/api/claw/runs/{run_id}` boundary.
 */
export const CANONICAL_RUN_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,511}$/;

/**
 * Mirrors `workspace_storage._SAFE_ID_RE`, the grammar `HistoryStore` enforces
 * for a canonical workspace linkage.
 */
export const CANONICAL_WORKSPACE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

/** Mirrors `kagent.contracts.ClawRunStatus` — the closed status vocabulary. */
export const CANONICAL_RUN_STATUSES = Object.freeze([
  'queued',
  'preparing',
  'running',
  'waiting_approval',
  'completed',
  'failed',
  'cancelled',
] as const);

export type CanonicalRunStatus = (typeof CANONICAL_RUN_STATUSES)[number];

/** Mirrors `history.MAX_CLAW_RUNS` behaviour for a bounded list. */
export const MAX_CANONICAL_RUNS = 30;

/** Mirrors `history.MAX_RUN_RESULT_SUMMARY_CHARS`. */
export const MAX_RUN_RESULT_SUMMARY_CHARS = 200;

const MAX_TITLE_LENGTH = 300;
const MAX_CHANNEL_LENGTH = 64;
const MAX_ACTION_LENGTH = 64;
const MAX_TIMESTAMP_LENGTH = 64;
const MAX_ARTIFACT_DOCUMENT_ID_LENGTH = 128;
const MAX_ARTIFACT_FILENAME_LENGTH = 256;
const MAX_ARTIFACT_MEDIA_TYPE_LENGTH = 128;

/**
 * Honest provenance marker: this projection is point-in-time canonical run
 * state, not a live event stream. There is no live run-event authority to
 * consume yet, and none is invented here.
 */
export const LIVE_ACTIVITY_SOURCE = 'not_yet_available' as const;

export interface CanonicalRunArtifactRef {
  readonly documentId: string;
  readonly filename: string;
  readonly mediaType: string;
}

export interface CanonicalRunListItem {
  readonly runId: string;
  readonly status: CanonicalRunStatus;
  readonly channel: string;
  readonly action: string;
  readonly title: string;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly resultSummary: string | null;
  readonly artifact: CanonicalRunArtifactRef | null;
  /** The server-linked canonical conversation, verbatim from the run row. */
  readonly conversationId: string | null;
  /** The server-linked canonical workspace, verbatim from the run row. */
  readonly workspaceId: string | null;
}

export interface CanonicalRunListResponse {
  readonly ok: boolean;
  readonly configured: boolean;
  readonly runs: readonly CanonicalRunListItem[];
  readonly liveActivitySource: typeof LIVE_ACTIVITY_SOURCE;
  readonly errorCode: null | 'canonical_run_unavailable' | 'invalid_run_payload';
}

export interface CanonicalRunReadRequest {
  readonly runId: string;
}

export interface CanonicalRunReadResponse {
  readonly ok: boolean;
  readonly run: CanonicalRunListItem | null;
  readonly errorCode: null | 'canonical_run_unavailable' | 'invalid_run_id' | 'run_not_found' | 'invalid_run_payload';
}

export interface CanonicalRunPort {
  readonly configured: boolean;
  listRuns(): Promise<unknown>;
}

/**
 * Fail-closed default: no canonical credential is available to the Desktop yet.
 *
 * Reading the canonical run list needs the signed-in Padiem session credential,
 * which the Desktop does not hold in this slice (that channel is B2c's work).
 * Until it is established, every call reports the run surface as unavailable
 * instead of inventing a local run history.
 */
export class UnconfiguredCanonicalRunPort implements CanonicalRunPort {
  readonly configured = false;

  async listRuns(): Promise<unknown> {
    throw new Error('canonical run port is not configured');
  }
}

export type RunListErrorCode =
  | 'canonical_run_unavailable'
  | 'invalid_run_payload';

export type RunReadErrorCode =
  | 'canonical_run_unavailable'
  | 'invalid_run_id'
  | 'run_not_found'
  | 'invalid_run_payload';

export class CanonicalRunController {
  readonly #port: CanonicalRunPort;

  constructor(port: CanonicalRunPort = new UnconfiguredCanonicalRunPort()) {
    this.#port = port;
  }

  get configured(): boolean {
    return this.#port.configured;
  }

  async listRuns(): Promise<CanonicalRunListResponse> {
    if (!this.#port.configured) {
      return Object.freeze({
        ok: false,
        configured: false,
        runs: Object.freeze([]),
        liveActivitySource: LIVE_ACTIVITY_SOURCE,
        errorCode: 'canonical_run_unavailable' as const,
      });
    }
    let payload: unknown;
    try {
      payload = await this.#port.listRuns();
    } catch {
      return Object.freeze({
        ok: false,
        configured: true,
        runs: Object.freeze([]),
        liveActivitySource: LIVE_ACTIVITY_SOURCE,
        errorCode: 'canonical_run_unavailable' as const,
      });
    }
    const runs = parseRunList(payload);
    if (runs === null) {
      return Object.freeze({
        ok: false,
        configured: true,
        runs: Object.freeze([]),
        liveActivitySource: LIVE_ACTIVITY_SOURCE,
        errorCode: 'invalid_run_payload' as const,
      });
    }
    return Object.freeze({
      ok: true,
      configured: true,
      runs: Object.freeze(runs),
      liveActivitySource: LIVE_ACTIVITY_SOURCE,
      errorCode: null,
    });
  }

  /**
   * Reads one canonical run out of a fresh canonical run-list call.
   *
   * The caller supplies only a run id in the server's own grammar — never a
   * conversation, never a workspace, never a status. The linkage fields on the
   * returned projection are the server's own, so a caller-shaped request cannot
   * re-bind a run to a different conversation or workspace.
   */
  async readRun(request: unknown): Promise<CanonicalRunReadResponse> {
    const runId = extractRunId(request);
    if (runId === null) {
      return Object.freeze({
        ok: false,
        run: null,
        errorCode: 'invalid_run_id' as const,
      });
    }
    if (!this.#port.configured) {
      return Object.freeze({
        ok: false,
        run: null,
        errorCode: 'canonical_run_unavailable' as const,
      });
    }
    let payload: unknown;
    try {
      payload = await this.#port.listRuns();
    } catch {
      return Object.freeze({
        ok: false,
        run: null,
        errorCode: 'canonical_run_unavailable' as const,
      });
    }
    const runs = parseRunList(payload);
    if (runs === null) {
      return Object.freeze({
        ok: false,
        run: null,
        errorCode: 'invalid_run_payload' as const,
      });
    }
    const run = runs.find((item) => item.runId === runId) ?? null;
    if (run === null) {
      return Object.freeze({
        ok: false,
        run: null,
        errorCode: 'run_not_found' as const,
      });
    }
    return Object.freeze({
      ok: true,
      run: Object.freeze(run),
      errorCode: null,
    });
  }
}

/**
 * Accepts only a plain request whose shape matches the closed contract:
 * `{ runId }`. Extra fields are ignored, never forwarded, so a renderer-shaped
 * caller cannot widen the request.
 */
function extractRunId(request: unknown): string | null {
  if (request === undefined || request === null) return null;
  if (typeof request !== 'object' || Array.isArray(request)) return null;
  const value = (request as { runId?: unknown }).runId;
  if (typeof value !== 'string' || !CANONICAL_RUN_ID_PATTERN.test(value)) {
    return null;
  }
  return value;
}

function parseRunList(payload: unknown): readonly CanonicalRunListItem[] | null {
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) return null;
  const raw = (payload as { runs?: unknown }).runs;
  if (!Array.isArray(raw)) return null;
  const rows: CanonicalRunListItem[] = [];
  for (const item of raw.slice(0, MAX_CANONICAL_RUNS)) {
    const parsed = parseRunListItem(item);
    if (parsed === null) return null;
    rows.push(parsed);
  }
  return rows;
}

function parseRunListItem(payload: unknown): CanonicalRunListItem | null {
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) return null;
  const source = payload as Record<string, unknown>;
  const runId =
    typeof source.run_id === 'string' && CANONICAL_RUN_ID_PATTERN.test(source.run_id)
      ? source.run_id
      : null;
  if (runId === null) return null;
  const status = parseRunStatus(source.status);
  if (status === null) return null;
  const resultSummary = parseResultSummary(source.result_summary);
  if (resultSummary === 'invalid') return null;
  const artifact = parseArtifact(source.artifact);
  if (artifact === 'invalid') return null;
  const conversationId = parseConversationLinkage(source.session);
  if (conversationId === 'invalid') return null;
  const workspaceId = parseWorkspaceLinkage(source.workspace_id);
  if (workspaceId === 'invalid') return null;
  return Object.freeze({
    runId,
    status,
    channel: boundedText(source.channel, MAX_CHANNEL_LENGTH) ?? '',
    action: boundedText(source.action, MAX_ACTION_LENGTH) ?? '',
    title: boundedText(source.title, MAX_TITLE_LENGTH) ?? '',
    createdAt: boundedText(source.created_at ?? source.createdAt, MAX_TIMESTAMP_LENGTH) ?? '',
    updatedAt: boundedText(source.updated_at ?? source.updatedAt, MAX_TIMESTAMP_LENGTH) ?? '',
    resultSummary: resultSummary === 'absent' ? null : resultSummary,
    artifact: artifact === 'absent' ? null : artifact,
    conversationId: conversationId === 'absent' ? null : conversationId,
    workspaceId: workspaceId === 'absent' ? null : workspaceId,
  });
}

function parseRunStatus(value: unknown): CanonicalRunStatus | null {
  if (typeof value !== 'string') return null;
  return (CANONICAL_RUN_STATUSES as readonly string[]).includes(value)
    ? (value as CanonicalRunStatus)
    : null;
}

/** String values are bounded exactly like the server bounds them; anything
 *  else that is not a present-or-absent null fails closed. */
function parseResultSummary(
  value: unknown,
): 'invalid' | 'absent' | string {
  if (value === undefined || value === null) return 'absent';
  if (typeof value !== 'string') return 'invalid';
  return value.slice(0, MAX_RUN_RESULT_SUMMARY_CHARS);
}

/**
 * The closed artifact input shape: the server's own snake keys
 * (`history._run_history_public` emits `document_id` / `filename` /
 * `media_type`), with the camelCase spelling accepted as the projection's
 * internal representation. ANY other key — a private ref, a path, an
 * unexpected extra — makes the whole payload invalid, and carrying both
 * spellings of one field is an ambiguity, not a coincidence, so it is invalid
 * too. A widened canonical artifact is never silently cleaned.
 */
const ARTIFACT_FIELD_BY_KEY: Readonly<Record<string, 'documentId' | 'filename' | 'mediaType'>> =
  Object.freeze({
    document_id: 'documentId',
    documentId: 'documentId',
    filename: 'filename',
    media_type: 'mediaType',
    mediaType: 'mediaType',
  });

function parseArtifact(
  value: unknown,
): 'invalid' | 'absent' | CanonicalRunArtifactRef {
  if (value === undefined || value === null) return 'absent';
  if (typeof value !== 'object' || Array.isArray(value)) return 'invalid';
  const source = value as Record<string, unknown>;
  const seen = new Map<'documentId' | 'filename' | 'mediaType', unknown>();
  for (const key of Object.keys(source)) {
    const field = ARTIFACT_FIELD_BY_KEY[key];
    if (field === undefined) return 'invalid';
    if (seen.has(field)) return 'invalid';
    seen.set(field, source[key]);
  }
  const documentId = boundedText(seen.get('documentId'), MAX_ARTIFACT_DOCUMENT_ID_LENGTH);
  if (documentId === null || documentId.length === 0) return 'invalid';
  return Object.freeze({
    documentId,
    filename: boundedText(seen.get('filename'), MAX_ARTIFACT_FILENAME_LENGTH) ?? '',
    mediaType: boundedText(seen.get('mediaType'), MAX_ARTIFACT_MEDIA_TYPE_LENGTH) ?? '',
  });
}

/** The canonical session projection is `{ conversation_id }` or absent; the
 *  conversation id grammar is the server's own `chat_` + 32 lowercase hex. */
function parseConversationLinkage(
  value: unknown,
): 'invalid' | 'absent' | string {
  if (value === undefined || value === null) return 'absent';
  if (typeof value !== 'object' || Array.isArray(value)) return 'invalid';
  const conversationId = (value as { conversation_id?: unknown }).conversation_id;
  if (typeof conversationId !== 'string' || !CANONICAL_CONVERSATION_ID_PATTERN.test(conversationId)) {
    return 'invalid';
  }
  return conversationId;
}

/** The canonical list projection does not carry a workspace linkage today, so
 *  absence is the normal case. When the canonical authority exposes one it is
 *  projected verbatim; a malformed value fails closed instead of being dropped
 *  or repaired here. */
function parseWorkspaceLinkage(
  value: unknown,
): 'invalid' | 'absent' | string {
  if (value === undefined || value === null) return 'absent';
  if (typeof value !== 'string' || !CANONICAL_WORKSPACE_ID_PATTERN.test(value)) {
    return 'invalid';
  }
  return value;
}

function boundedText(value: unknown, maximum: number): string | null {
  if (typeof value !== 'string') return null;
  return value.length > maximum ? value.slice(0, maximum) : value;
}
