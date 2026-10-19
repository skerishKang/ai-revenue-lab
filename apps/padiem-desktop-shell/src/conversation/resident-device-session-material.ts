/**
 * #3436 B2d — the main-process material provider over the trusted local
 * resident boundary.
 *
 * The resident host already holds everything: its canonical broker session
 * (opened by the host itself), its binding, and the existing protected
 * credential store. This module asks the supervised resident for a bounded
 * projection of that current state over the EXISTING stdio line channel the
 * pairing handoff already uses — no socket, no listener, no second spawn path.
 *
 *   DESKTOP_SESSION_OPEN=0        this module never opens a session; if the
 *                                 resident cannot project one, the answer is
 *                                 null and the conversation surface stays
 *                                 "canonical conversation unavailable".
 *   RENDERER_MATERIAL_API=0       nothing here is reachable from the renderer:
 *                                 no IPC channel, no preload method. The
 *                                 consumer is main.ts's port composition only.
 *   RAW_CREDENTIAL_SECOND_PERSISTENCE=0
 *                                 the material is consumed within the current
 *                                 call; nothing is cached, written, or
 *                                 retained between calls.
 *
 * Every failure is the same fail-closed null: no resident, a refused send, a
 * timeout, a malformed line, an expired projection, a shape that the B2c
 * validator does not accept exactly.
 */

import type { CanonicalDeviceSessionMaterial } from './desktop-canonical-conversation-port.js';
import { validateDeviceSessionMaterial } from './desktop-canonical-conversation-port.js';
import type { DeviceSessionMaterialProvider } from './desktop-canonical-conversation-port.js';

export const MATERIAL_REQUEST_CONTRACT_VERSION = 'claw-desktop-session-material-request.v1';
export const MATERIAL_RESPONSE_CONTRACT_VERSION = 'claw-desktop-session-material.v1';

/** The one request the resident answers. Bounded, closed, no parameters. */
export const MATERIAL_REQUEST_LINE = JSON.stringify({
  contract_version: MATERIAL_REQUEST_CONTRACT_VERSION,
  request: 'desktop_device_session_material',
});

const DEFAULT_RESPONSE_TIMEOUT_MS = 3_000;
const DEFAULT_POLL_INTERVAL_MS = 100;
const MAX_RESPONSE_LINE_CHARS = 65_536;

/** The narrow supervisor surface the provider may touch — main process only. */
export interface ResidentMaterialBoundary {
  readonly sendResidentLine: (line: string) => boolean;
  readonly takeResidentMaterialLine: () => string | null;
  readonly residentRunning: () => boolean;
}

/**
 * The exact closed success schema. A success response carrying ANY other key
 * — account_ref, workspace_ref, user_id, tenant, an arbitrary extra — is not
 * the B2d contract and fails closed, even though no field beyond the three
 * material values would ever be forwarded.
 */
const ALLOWED_RESPONSE_KEYS: ReadonlySet<string> = new Set([
  'event',
  'contract_version',
  'ok',
  'session_id',
  'binding_ref',
  'credential_b64',
  'credential_generation',
  'expires_at',
]);

function boundedText(value: unknown, maximum: number): string | null {
  return typeof value === 'string' && value.length > 0 && value.length <= maximum ? value : null;
}

/**
 * Parses one resident response line into the exact B2c material shape, or
 * null. The success schema is exact-closed (unknown key → null), and the
 * final `validateDeviceSessionMaterial` call is the single shape authority:
 * a line it would refuse never becomes material.
 */
export function parseResidentMaterialLine(
  line: string,
  now: Date = new Date(),
): CanonicalDeviceSessionMaterial | null {
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
  if (record['event'] !== 'desktop_device_session_material') return null;
  if (record['contract_version'] !== MATERIAL_RESPONSE_CONTRACT_VERSION) return null;
  if (record['ok'] !== true) return null;
  for (const key of Object.keys(record)) {
    if (!ALLOWED_RESPONSE_KEYS.has(key)) return null;
  }
  const sessionId = boundedText(record['session_id'], 512);
  const bindingRef = boundedText(record['binding_ref'], 512);
  const credentialB64 = boundedText(record['credential_b64'], 24_000);
  const expiresAt = boundedText(record['expires_at'], 64);
  if (sessionId === null || bindingRef === null || credentialB64 === null || expiresAt === null) {
    return null;
  }
  const expires = Date.parse(expiresAt);
  if (!Number.isFinite(expires) || expires <= now.getTime()) {
    return null;
  }
  if (
    typeof record['credential_generation'] !== 'number' ||
    !Number.isInteger(record['credential_generation']) ||
    record['credential_generation'] < 1
  ) {
    return null;
  }
  // The closed-shape authority: the same validator the authenticated port
  // applies before any request leaves the process.
  return validateDeviceSessionMaterial({ sessionId, bindingRef, credentialB64 });
}

/**
 * The B2d material provider: one bounded request/response exchange with the
 * supervised resident per call. Calls are serialized, so at most one exchange
 * is in flight; the raw line is consumed (taken) exactly once and dropped.
 */
export function createResidentDeviceSessionMaterialProvider(input: {
  boundary: ResidentMaterialBoundary;
  responseTimeoutMs?: number;
  pollIntervalMs?: number;
  now?: () => Date;
}): DeviceSessionMaterialProvider {
  if (typeof input.boundary.sendResidentLine !== 'function') {
    throw new Error('boundary.sendResidentLine must be callable');
  }
  if (typeof input.boundary.takeResidentMaterialLine !== 'function') {
    throw new Error('boundary.takeResidentMaterialLine must be callable');
  }
  if (typeof input.boundary.residentRunning !== 'function') {
    throw new Error('boundary.residentRunning must be callable');
  }
  const timeoutMs = input.responseTimeoutMs ?? DEFAULT_RESPONSE_TIMEOUT_MS;
  const pollIntervalMs = input.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS;
  const now = input.now ?? (() => new Date());

  let inFlight: Promise<unknown> = Promise.resolve(null);

  async function requestOnce(): Promise<CanonicalDeviceSessionMaterial | null> {
    if (!input.boundary.residentRunning()) return null;
    if (!input.boundary.sendResidentLine(MATERIAL_REQUEST_LINE)) return null;
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const line = input.boundary.takeResidentMaterialLine();
      if (line !== null) return parseResidentMaterialLine(line, now());
      if (!input.boundary.residentRunning()) return null;
      await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
    }
    return null;
  }

  return async () => {
    const next = inFlight.then(requestOnce, requestOnce);
    inFlight = next.then(
      () => undefined,
      () => undefined,
    );
    return next;
  };
}
