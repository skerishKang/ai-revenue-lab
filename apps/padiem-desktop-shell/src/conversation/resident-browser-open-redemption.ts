/**
 * #3611 — the Desktop's canonical browser-open redemption port.
 *
 * The Desktop trusted main owns the ephemeral view, but it owns no durable store
 * (`DESKTOP_RUN_DATABASE=0`), so it must not become the replay authority either.
 * The durable one-shot lives with the agent, and this module is the Desktop half
 * of the *existing* trusted local boundary:
 *
 *   trusted main -> supervisor.sendResidentLine(...) -> supervised resident stdin
 *     -> resident bounded dispatcher -> agent-side durable redemption -> stdout
 *     -> dedicated bounded response slot -> BrowserOpenRedemptionPort.redeem(...)
 *
 * No new transport authority, no second socket, no inbound listener and no
 * generic command dispatch: this adds exactly one literal request kind to the
 * pipe that already carries #3436 B2d device-session material.
 *
 * The request carries only the correlation the port already needs. A raw URL, a
 * raw P01 payload, a credential, a cookie, an arbitrary grant object or any page
 * content is not representable in it.
 */

import { BrowserOpenRefusalError, type BrowserOpenRedemptionPort } from '../browser/browser-open-host.js';

export const BROWSER_OPEN_REDEMPTION_REQUEST_CONTRACT_VERSION =
  'claw-browser-open-redemption-request.v1';
export const BROWSER_OPEN_REDEMPTION_RESPONSE_CONTRACT_VERSION =
  'claw-browser-open-redemption.v1';
export const BROWSER_OPEN_REDEMPTION_EVENT = 'browser_open_redemption';

const DEFAULT_RESPONSE_TIMEOUT_MS = 3_000;
const DEFAULT_POLL_INTERVAL_MS = 100;
const MAX_RESPONSE_LINE_CHARS = 2_048;
const MAX_CORRELATION_CHARS = 512;
const SAFE_REF = /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$/;
const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$/;

/** The narrow supervisor surface the port may touch — main process only. */
export interface ResidentBrowserOpenRedemptionBoundary {
  readonly sendResidentLine: (line: string) => boolean;
  readonly takeResidentBrowserOpenRedemptionLine: () => string | null;
  readonly residentRunning: () => boolean;
}

export interface BrowserOpenRedemptionCorrelation {
  readonly redemptionRef: string;
  readonly requestFingerprint: string;
  readonly openId: string;
  readonly runRef: string;
}

function assertBounded(value: unknown, pattern: RegExp, field: string): string {
  if (typeof value !== 'string' || value.length === 0 || value.length > MAX_CORRELATION_CHARS) {
    throw new BrowserOpenRefusalError('grant_rejected', `${field} is not a bounded correlation`);
  }
  const trimmed = value.trim();
  if (!pattern.test(trimmed)) {
    throw new BrowserOpenRefusalError('grant_rejected', `${field} is not a bounded correlation`);
  }
  return trimmed;
}

/** The one redemption request. Four correlation fields, and nothing else. */
export function browserOpenRedemptionRequestLine(
  input: BrowserOpenRedemptionCorrelation,
): string {
  return JSON.stringify({
    contract_version: BROWSER_OPEN_REDEMPTION_REQUEST_CONTRACT_VERSION,
    request: BROWSER_OPEN_REDEMPTION_EVENT,
    redemptionRef: assertBounded(input.redemptionRef, SAFE_REF, 'redemptionRef'),
    requestFingerprint: assertBounded(input.requestFingerprint, SAFE_REF, 'requestFingerprint'),
    openId: assertBounded(input.openId, SAFE_ID, 'openId'),
    runRef: assertBounded(input.runRef, SAFE_REF, 'runRef'),
  });
}

/**
 * The closed response schema. A response carrying any other key is not this
 * contract and fails closed, even though no extra value would be forwarded.
 */
const ALLOWED_RESPONSE_KEYS: ReadonlySet<string> = new Set([
  'event',
  'contract_version',
  'ok',
  'redemption_ref',
  'request_fingerprint',
  'reason',
]);

export interface BrowserOpenRedemptionAnswer {
  readonly ok: boolean;
  readonly redemptionRef: string;
  readonly requestFingerprint: string;
  readonly reason: string | null;
}

export function parseBrowserOpenRedemptionLine(line: string): BrowserOpenRedemptionAnswer | null {
  if (typeof line !== 'string' || line.length === 0 || line.length > MAX_RESPONSE_LINE_CHARS) {
    return null;
  }
  if (!line.startsWith('{')) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(line);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  const record = parsed as Record<string, unknown>;
  if (record['event'] !== BROWSER_OPEN_REDEMPTION_EVENT) return null;
  if (record['contract_version'] !== BROWSER_OPEN_REDEMPTION_RESPONSE_CONTRACT_VERSION) {
    return null;
  }
  if (record['ok'] !== true && record['ok'] !== false) return null;
  for (const key of Object.keys(record)) {
    if (!ALLOWED_RESPONSE_KEYS.has(key)) return null;
  }
  const redemptionRef =
    typeof record['redemption_ref'] === 'string' ? record['redemption_ref'] : null;
  const requestFingerprint =
    typeof record['request_fingerprint'] === 'string' ? record['request_fingerprint'] : null;
  if (redemptionRef === null || requestFingerprint === null) return null;
  const reason = typeof record['reason'] === 'string' ? record['reason'] : null;
  return {
    ok: record['ok'] === true,
    redemptionRef,
    requestFingerprint,
    reason,
  };
}

export interface ResidentBrowserOpenRedemptionPortInput {
  readonly boundary: ResidentBrowserOpenRedemptionBoundary;
  readonly timeoutMs?: number;
  readonly pollIntervalMs?: number;
  /** Injected in tests so awaiting never depends on real time. */
  readonly sleep?: (ms: number) => Promise<void>;
}

/**
 * Builds the real `BrowserOpenRedemptionPort` over the supervised resident pipe.
 *
 * `redeem` resolves only when the agent-side durable transition succeeded. Any
 * refusal — a stale or replayed grant, an expired command, a missing resident, a
 * timeout, an unparsable answer — rejects, and the host therefore never creates a
 * view.
 */
export function createResidentBrowserOpenRedemptionPort(
  input: ResidentBrowserOpenRedemptionPortInput,
): BrowserOpenRedemptionPort {
  const boundary = input.boundary;
  if (!boundary || typeof boundary.sendResidentLine !== 'function') {
    throw new BrowserOpenRefusalError(
      'redemption_unavailable',
      'boundary.sendResidentLine must be callable',
    );
  }
  if (typeof boundary.takeResidentBrowserOpenRedemptionLine !== 'function') {
    throw new BrowserOpenRefusalError(
      'redemption_unavailable',
      'boundary.takeResidentBrowserOpenRedemptionLine must be callable',
    );
  }
  const timeoutMs = input.timeoutMs ?? DEFAULT_RESPONSE_TIMEOUT_MS;
  const pollIntervalMs = input.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS;
  const sleep =
    input.sleep ?? ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)));

  return Object.freeze({
    configured: true,
    redeem: async (correlation: BrowserOpenRedemptionCorrelation): Promise<void> => {
      const requestLine = browserOpenRedemptionRequestLine(correlation);
      if (!boundary.sendResidentLine(requestLine)) {
        throw new BrowserOpenRefusalError(
          'redemption_unavailable',
          'the supervised resident is not running',
        );
      }
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        const line = boundary.takeResidentBrowserOpenRedemptionLine();
        if (line !== null) {
          const answer = parseBrowserOpenRedemptionLine(line);
          if (answer === null) {
            throw new BrowserOpenRefusalError(
              'grant_rejected',
              'canonical redemption returned an unparsable answer',
            );
          }
          if (
            answer.redemptionRef !== correlation.redemptionRef ||
            answer.requestFingerprint !== correlation.requestFingerprint
          ) {
            // A response for a different open is never accepted for this one.
            throw new BrowserOpenRefusalError(
              'grant_rejected',
              'canonical redemption answered a different open',
            );
          }
          if (!answer.ok) {
            throw new BrowserOpenRefusalError(
              'grant_rejected',
              `canonical redemption refused this browser open: ${answer.reason ?? 'refused'}`,
            );
          }
          return;
        }
        if (!boundary.residentRunning()) {
          throw new BrowserOpenRefusalError(
            'redemption_unavailable',
            'the supervised resident exited before answering',
          );
        }
        await sleep(pollIntervalMs);
      }
      throw new BrowserOpenRefusalError(
        'redemption_unavailable',
        'canonical redemption did not answer in time',
      );
    },
  });
}

export const BROWSER_OPEN_REDEMPTION_USES_EXISTING_PIPE = true;
export const BROWSER_OPEN_REDEMPTION_NEW_LISTENER = false;
export const BROWSER_OPEN_REDEMPTION_SECOND_READER = false;
export const BROWSER_OPEN_REDEMPTION_CARRIES_RAW_URL = false;
export const BROWSER_OPEN_REDEMPTION_CARRIES_P01_PAYLOAD = false;
export const BROWSER_OPEN_REDEMPTION_CARRIES_CREDENTIAL = false;
export const BROWSER_OPEN_REDEMPTION_CARRIES_PAGE_CONTENT = false;
