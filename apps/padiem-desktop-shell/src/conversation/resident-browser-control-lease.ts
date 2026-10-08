/**
 * #3669 — the Desktop's canonical browser-control lease admission port.
 *
 * The Desktop trusted main owns the ephemeral view, but it owns no durable
 * store (`DESKTOP_DURABLE_LEASE_STORE=0`, `DESKTOP_DURABLE_LEASE_AUTHORITY=NO`),
 * so it must not be the lease budget/idle/replay authority either. The
 * canonical admission lives with the agent (`BrowserControlLeaseStore` plus
 * the P01 evidence authority), and this module is the Desktop half of the
 * *existing* trusted local boundary:
 *
 *   trusted main -> supervisor.sendResidentLine(...) -> supervised resident stdin
 *     -> resident closed dispatcher (browser_control_lease_resolve /
 *        browser_control_lease_consume) -> agent-side canonical admission -> stdout
 *     -> dedicated bounded response slot -> BrowserActionLeaseAuthority.{resolve,consume}
 *
 * No new transport authority, no second socket, no inbound listener and no
 * generic command dispatch: this adds exactly TWO literal request kinds to the
 * pipe that already carries #3436 B2d material and #3611 redemption. Both
 * kinds share ONE bounded response event (`browser_control_lease`) and ONE
 * dedicated supervisor slot; the kind is carried on the response itself, so a
 * stale line of the other kind is recognised and skipped, never misrouted.
 *
 * The request carries only the correlation the trusted composition bound it
 * to: the lease request context (fingerprint, browser session, device, run,
 * workspace, owner, origin scope, action classes, TTL, budget) and, for the
 * PHASE B consume, the observed origin from the fresh observation. A raw P01
 * payload, a credential, a cookie, an arbitrary grant object or any page
 * content is not representable in it. The request body never supplies
 * authority values — they are bound once at composition, not per action.
 */

import {
  LEASE_ELIGIBLE_ACTIONS,
  LEASE_MAX_ACTIONS_HARD_CAP,
  LEASE_TTL_MAX_SECONDS,
  type LeaseEligibleAction,
} from '../browser/browser-action-contract.js';
import type { BrowserActionLeaseAuthority } from '../browser/browser-action-host.js';

export const BROWSER_CONTROL_LEASE_REQUEST_CONTRACT_VERSION =
  'claw-browser-control-lease-request.v1';
export const BROWSER_CONTROL_LEASE_RESPONSE_CONTRACT_VERSION = 'claw-browser-control-lease.v1';
export const BROWSER_CONTROL_LEASE_EVENT = 'browser_control_lease';
export const BROWSER_CONTROL_LEASE_RESOLVE_KIND = 'browser_control_lease_resolve';
export const BROWSER_CONTROL_LEASE_CONSUME_KIND = 'browser_control_lease_consume';

const DEFAULT_RESPONSE_TIMEOUT_MS = 3_000;
const DEFAULT_POLL_INTERVAL_MS = 100;
const MAX_RESPONSE_LINE_CHARS = 2_048;
const MAX_LEASE_REF_CHARS = 256;
const MAX_LEASE_ORIGIN_CHARS = 255;
const LEASE_FINGERPRINT_PATTERN = /^[0-9a-f]{64}$/;
const SAFE_REF = /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$/;
const ORIGIN_PATTERN = /^https:\/\/[a-z0-9.-]+(?::\d{1,5})?$|^http:\/\/[a-z0-9.-]+(?::\d{1,5})?$/;

/** The narrow supervisor surface the port may touch — main process only. */
export interface ResidentBrowserControlLeaseBoundary {
  readonly sendResidentLine: (line: string) => boolean;
  readonly takeResidentBrowserControlLeaseLine: () => string | null;
  readonly residentRunning: () => boolean;
}

/**
 * The trusted lease context: bound ONCE at composition, never re-derivable
 * from an action request. The agent-side authority recomputes and re-checks
 * every one of these facts; the Desktop only ever carries copies.
 */
export interface BrowserControlLeaseContext {
  readonly requestFingerprint: string;
  readonly browserSessionRef: string;
  readonly deviceRef: string;
  readonly runRef: string;
  readonly workspaceRef: string;
  readonly ownerRef: string;
  readonly originScope: string;
  readonly allowedActionClasses: readonly string[];
  readonly ttlSeconds: number;
  readonly maxActions: number;
}

function assertLeaseRef(value: unknown, field: string): string {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > MAX_LEASE_REF_CHARS ||
    !SAFE_REF.test(value.trim())
  ) {
    throw new ResidentLeaseRefusalError('host_unavailable', `${field} is not a bounded lease context ref`);
  }
  return value.trim();
}

function assertLeaseOrigin(value: unknown, field: string): string {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > MAX_LEASE_ORIGIN_CHARS ||
    !ORIGIN_PATTERN.test(value.trim().toLowerCase())
  ) {
    throw new ResidentLeaseRefusalError('host_unavailable', `${field} is not a bounded bare origin`);
  }
  return value.trim().toLowerCase();
}

/**
 * The canonical 64-character request fingerprint. It is a COPY of the value
 * the agent-side authority computed; the request carries it only for
 * correlation and never mints anything.
 */
function assertLeaseFingerprint(value: unknown): string {
  if (typeof value !== 'string' || !LEASE_FINGERPRINT_PATTERN.test(value)) {
    throw new ResidentLeaseRefusalError(
      'host_unavailable',
      'requestFingerprint must be the canonical 64-character lowercase digest',
    );
  }
  return value;
}

export function validateBrowserControlLeaseContext(input: BrowserControlLeaseContext): void {
  assertLeaseFingerprint(input.requestFingerprint);
  assertLeaseRef(input.browserSessionRef, 'browserSessionRef');
  assertLeaseRef(input.deviceRef, 'deviceRef');
  assertLeaseRef(input.runRef, 'runRef');
  assertLeaseRef(input.workspaceRef, 'workspaceRef');
  assertLeaseRef(input.ownerRef, 'ownerRef');
  assertLeaseOrigin(input.originScope, 'originScope');
  if (
    !Array.isArray(input.allowedActionClasses) ||
    input.allowedActionClasses.length < 1 ||
    input.allowedActionClasses.length > LEASE_ELIGIBLE_ACTIONS.length
  ) {
    throw new ResidentLeaseRefusalError(
      'host_unavailable',
      'allowedActionClasses must be a bounded non-empty set',
    );
  }
  for (const entry of input.allowedActionClasses) {
    if (!(LEASE_ELIGIBLE_ACTIONS as readonly string[]).includes(entry)) {
      throw new ResidentLeaseRefusalError(
        'host_unavailable',
        'allowedActionClasses carries a non-lease-eligible class',
      );
    }
  }
  if (
    typeof input.ttlSeconds !== 'number' ||
    !Number.isInteger(input.ttlSeconds) ||
    input.ttlSeconds < 1 ||
    input.ttlSeconds > LEASE_TTL_MAX_SECONDS
  ) {
    throw new ResidentLeaseRefusalError(
      'host_unavailable',
      `ttlSeconds must be an integer in 1..${LEASE_TTL_MAX_SECONDS}`,
    );
  }
  if (
    typeof input.maxActions !== 'number' ||
    !Number.isInteger(input.maxActions) ||
    input.maxActions < 1 ||
    input.maxActions > LEASE_MAX_ACTIONS_HARD_CAP
  ) {
    throw new ResidentLeaseRefusalError(
      'host_unavailable',
      `maxActions must be an integer in 1..${LEASE_MAX_ACTIONS_HARD_CAP}`,
    );
  }
}

/** One bounded lease refusal carrying only a closed desktop code. */
export class ResidentLeaseRefusalError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = 'ResidentLeaseRefusalError';
    this.code = code;
  }
}

/** PHASE A request line: the trusted session context, bounded only. */
export function browserControlLeaseResolveRequestLine(context: BrowserControlLeaseContext): string {
  validateBrowserControlLeaseContext(context);
  return JSON.stringify({
    contract_version: BROWSER_CONTROL_LEASE_REQUEST_CONTRACT_VERSION,
    request: BROWSER_CONTROL_LEASE_RESOLVE_KIND,
    requestFingerprint: context.requestFingerprint,
    browserSessionRef: context.browserSessionRef,
    deviceRef: context.deviceRef,
    runRef: context.runRef,
    workspaceRef: context.workspaceRef,
    ownerRef: context.ownerRef,
    originScope: context.originScope,
    allowedActionClasses: [...context.allowedActionClasses],
    ttlSeconds: context.ttlSeconds,
    maxActions: context.maxActions,
  });
}

/** PHASE B request line: the exact consume fact, bounded only. */
export function browserControlLeaseConsumeRequestLine(
  context: BrowserControlLeaseContext,
  input: { readonly action: LeaseEligibleAction; readonly observedOrigin: string },
): string {
  validateBrowserControlLeaseContext(context);
  if (!(LEASE_ELIGIBLE_ACTIONS as readonly string[]).includes(input.action)) {
    throw new ResidentLeaseRefusalError('lease_invalid', 'the consume action is not lease-eligible');
  }
  const observedOrigin = assertLeaseOrigin(input.observedOrigin, 'observedOrigin');
  return JSON.stringify({
    contract_version: BROWSER_CONTROL_LEASE_REQUEST_CONTRACT_VERSION,
    request: BROWSER_CONTROL_LEASE_CONSUME_KIND,
    requestFingerprint: context.requestFingerprint,
    browserSessionRef: context.browserSessionRef,
    runRef: context.runRef,
    workspaceRef: context.workspaceRef,
    ownerRef: context.ownerRef,
    action: input.action,
    observedOrigin,
  });
}

/**
 * The closed response schemas. Both kinds share the event tag and the
 * correlation fields; each kind owns exactly one payload key (`lease` for
 * the resolve, `consumed_actions` for the consume). A response carrying any
 * other key is not this contract and fails closed.
 */
const RESOLVE_RESPONSE_KEYS: ReadonlySet<string> = new Set([
  'event',
  'contract_version',
  'request',
  'ok',
  'request_fingerprint',
  'reason',
  'lease',
]);
const CONSUME_RESPONSE_KEYS: ReadonlySet<string> = new Set([
  'event',
  'contract_version',
  'request',
  'ok',
  'request_fingerprint',
  'reason',
  'consumed_actions',
]);

export interface BrowserControlLeaseAnswer {
  readonly ok: boolean;
  readonly requestFingerprint: string;
  readonly reason: string | null;
  readonly lease: Record<string, unknown> | null;
  readonly consumedActions: number | null;
}

function recognizedLine(line: string, kind: string): Record<string, unknown> | null {
  if (typeof line !== 'string' || line.length === 0 || line.length > MAX_RESPONSE_LINE_CHARS) return null;
  if (!line.startsWith('{')) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(line);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  const record = parsed as Record<string, unknown>;
  if (record['event'] !== BROWSER_CONTROL_LEASE_EVENT) return null;
  if (record['contract_version'] !== BROWSER_CONTROL_LEASE_RESPONSE_CONTRACT_VERSION) return null;
  if (record['request'] !== kind) return null;
  if (record['ok'] !== true && record['ok'] !== false) return null;
  if (typeof record['request_fingerprint'] !== 'string') return null;
  const keys = kind === BROWSER_CONTROL_LEASE_RESOLVE_KIND ? RESOLVE_RESPONSE_KEYS : CONSUME_RESPONSE_KEYS;
  for (const key of Object.keys(record)) {
    if (!keys.has(key)) return null;
  }
  return record;
}

/**
 * Recognition helper for the shared slot: is this line a bounded answer of
 * THIS kind at all? A stale answer of the other kind — the slot is shared —
 * is recognised here so the caller can skip it instead of misrouting it.
 */
export function isBrowserControlLeaseAnswerLine(line: string, kind: string): boolean {
  return recognizedLine(line, kind) !== null;
}

/** The full closed parse: recognition plus the payload type checks. */
export function parseBrowserControlLeaseLine(
  line: string,
  kind: string,
): BrowserControlLeaseAnswer | null {
  const record = recognizedLine(line, kind);
  if (record === null) return null;
  let lease: Record<string, unknown> | null = null;
  let consumedActions: number | null = null;
  if (kind === BROWSER_CONTROL_LEASE_RESOLVE_KIND) {
    if (!('lease' in record)) return null;
    const candidate = record['lease'];
    if (candidate !== null && (candidate === undefined || typeof candidate !== 'object' || Array.isArray(candidate))) {
      return null;
    }
    lease = candidate as Record<string, unknown> | null;
  } else {
    if (!('consumed_actions' in record)) return null;
    const candidate = record['consumed_actions'];
    if (candidate !== null && (typeof candidate !== 'number' || !Number.isInteger(candidate))) return null;
    consumedActions = candidate as number | null;
  }
  return {
    ok: record['ok'] === true,
    requestFingerprint: record['request_fingerprint'] as string,
    reason: typeof record['reason'] === 'string' ? record['reason'] : null,
    lease,
    consumedActions,
  };
}

/**
 * Maps one agent-side refusal reason onto the closed desktop codes. The
 * store's own budget/idle/origin facts mean the same thing here and pass
 * through; the issuance and evidence failures (P01 material) and every other
 * code collapse into lease_invalid so no approval text can escape.
 */
const REASON_PASSTHROUGH: ReadonlySet<string> = new Set([
  'action_budget_exhausted',
  'lease_idle_exceeded',
  'origin_scope_exceeded',
]);

function refusalCodeForReason(reason: string | null): string {
  if (reason !== null && REASON_PASSTHROUGH.has(reason)) return reason;
  if (reason === 'lease_unavailable') return 'host_unavailable';
  return 'lease_invalid';
}

export interface ResidentBrowserControlLeaseAuthorityInput {
  readonly context: BrowserControlLeaseContext;
  readonly boundary: ResidentBrowserControlLeaseBoundary;
  readonly timeoutMs?: number;
  readonly pollIntervalMs?: number;
  /** Injected in tests so awaiting never depends on real time. */
  readonly sleep?: (ms: number) => Promise<void>;
}

/**
 * Builds the real two-phase `BrowserActionLeaseAuthority` over the supervised
 * resident pipe.
 *
 * `resolve` resolves only when the agent-side PHASE A returned a bounded
 * lease dict (the host re-validates it with `assertBoundedActionLease` before
 * anything dispatches). `consume` resolves to the new durable count only when
 * the agent-side PHASE B succeeded. Any refusal — an expired or revoked
 * lease, a spent budget, an idle or cross-origin fact, a missing resident, a
 * timeout, a correlation mismatch, an unparsable answer — rejects, and the
 * host therefore never dispatches.
 */
export function createResidentBrowserControlLeaseAuthority(
  input: ResidentBrowserControlLeaseAuthorityInput,
): BrowserActionLeaseAuthority {
  const context = input.context;
  validateBrowserControlLeaseContext(context);
  const boundary = input.boundary;
  if (!boundary || typeof boundary.sendResidentLine !== 'function') {
    throw new ResidentLeaseRefusalError(
      'host_unavailable',
      'boundary.sendResidentLine must be callable',
    );
  }
  if (typeof boundary.takeResidentBrowserControlLeaseLine !== 'function') {
    throw new ResidentLeaseRefusalError(
      'host_unavailable',
      'boundary.takeResidentBrowserControlLeaseLine must be callable',
    );
  }
  if (typeof boundary.residentRunning !== 'function') {
    throw new ResidentLeaseRefusalError('host_unavailable', 'boundary.residentRunning must be callable');
  }
  const timeoutMs = input.timeoutMs ?? DEFAULT_RESPONSE_TIMEOUT_MS;
  const pollIntervalMs = input.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS;
  const sleep =
    input.sleep ?? ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)));

  const assertSessionBinding = (browserSessionRef: string): void => {
    if (browserSessionRef !== context.browserSessionRef) {
      throw new ResidentLeaseRefusalError(
        'lease_invalid',
        'the host addressed a browser session the trusted lease context does not bind',
      );
    }
  };

  const runPhase = async (kind: string, requestLine: string): Promise<BrowserControlLeaseAnswer> => {
    if (!boundary.sendResidentLine(requestLine)) {
      throw new ResidentLeaseRefusalError(
        'host_unavailable',
        'the supervised resident is not running',
      );
    }
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const line = boundary.takeResidentBrowserControlLeaseLine();
      if (line !== null) {
        if (!isBrowserControlLeaseAnswerLine(line, kind)) {
          // The slot is shared between the two kinds and one-shot: a stale
          // answer of the other kind, or a malformed line, is not this
          // answer. It is already consumed from the slot; keep polling.
        } else {
          const answer = parseBrowserControlLeaseLine(line, kind);
          if (answer === null) {
            throw new ResidentLeaseRefusalError(
              'lease_invalid',
              'the canonical lease authority returned a malformed answer',
            );
          }
          if (answer.requestFingerprint !== context.requestFingerprint) {
            // An answer for a different lease request is never accepted for
            // this one.
            throw new ResidentLeaseRefusalError(
              'lease_invalid',
              'the canonical lease authority answered a different request',
            );
          }
          if (!answer.ok) {
            throw new ResidentLeaseRefusalError(
              refusalCodeForReason(answer.reason),
              `the canonical lease authority refused this request: ${answer.reason ?? 'refused'}`,
            );
          }
          return answer;
        }
      }
      if (Date.now() >= deadline) {
        throw new ResidentLeaseRefusalError(
          'host_unavailable',
          'the canonical lease authority did not answer in time',
        );
      }
      if (!boundary.residentRunning()) {
        throw new ResidentLeaseRefusalError(
          'host_unavailable',
          'the supervised resident exited before answering',
        );
      }
      await sleep(pollIntervalMs);
    }
  };

  return Object.freeze({
    configured: true,
    resolve: async (request: { readonly browserSessionRef: string; readonly action: LeaseEligibleAction }) => {
      assertSessionBinding(request.browserSessionRef);
      const answer = await runPhase(
        BROWSER_CONTROL_LEASE_RESOLVE_KIND,
        browserControlLeaseResolveRequestLine(context),
      );
      if (answer.lease === null) {
        // Defensive: the closed parser guarantees a dict on ok.
        throw new ResidentLeaseRefusalError('lease_invalid', 'the canonical lease answer carried no lease');
      }
      return answer.lease;
    },
    consume: async (request: {
      readonly browserSessionRef: string;
      readonly action: LeaseEligibleAction;
      readonly observedOrigin: string;
    }) => {
      assertSessionBinding(request.browserSessionRef);
      const answer = await runPhase(
        BROWSER_CONTROL_LEASE_CONSUME_KIND,
        browserControlLeaseConsumeRequestLine(context, request),
      );
      if (answer.consumedActions === null) {
        // Defensive: the closed parser guarantees an integer count on ok.
        throw new ResidentLeaseRefusalError('lease_invalid', 'the canonical lease answer carried no count');
      }
      return answer.consumedActions;
    },
  });
}

export const BROWSER_CONTROL_LEASE_USES_EXISTING_PIPE = true;
export const BROWSER_CONTROL_LEASE_NEW_LISTENER = false;
export const BROWSER_CONTROL_LEASE_SECOND_READER = false;
export const BROWSER_CONTROL_LEASE_REQUEST_KINDS_ADDED = 2;
export const BROWSER_CONTROL_LEASE_CARRIES_P01_PAYLOAD = false;
export const BROWSER_CONTROL_LEASE_CARRIES_CREDENTIAL = false;
export const BROWSER_CONTROL_LEASE_CARRIES_PAGE_CONTENT = false;
/** The request body carries correlation copies only; it never mints a lease. */
export const BROWSER_CONTROL_LEASE_REQUEST_MINTS_LEASE = false;
export const BROWSER_CONTROL_LEASE_REFUND_SUPPORTED = false;
