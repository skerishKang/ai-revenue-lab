/**
 * CLAW4 #3083 — bounded `padiem://` pairing deep-link SEAM.
 *
 * This parser is intentionally *only* a seam:
 *
 *   PAIRING_AUTHORITY_IMPLEMENTED=NO
 *   SESSION_MINT_IMPLEMENTED=NO
 *   CREDENTIAL_PERSISTENCE=NO
 *   BROKER_TRANSPORT_IMPLEMENTED=NO
 *
 * #3080 owns the canonical pairing/broker contract. This module produces a
 * deterministic, non-secret correlation reference so the shell can later hand
 * the payload to the #3080 contract without changing the shell's shape.
 */

export const PAIRING_SEAM = Object.freeze({
  SCHEME: 'padiem',
  MAX_URL_LENGTH: 2048,
  MAX_PARAM_COUNT: 16,
  MAX_PARAM_VALUE_LENGTH: 512,
  PAIRING_AUTHORITY_IMPLEMENTED: false,
  SESSION_MINT_IMPLEMENTED: false,
  CREDENTIAL_PERSISTENCE: false,
  BROKER_TRANSPORT_IMPLEMENTED: false,
  AUTHORITY_OWNER: '#3080',
} as const);

export class PairingDeepLinkError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = 'PairingDeepLinkError';
    this.code = code;
  }
}

export interface ParsedPairingDeepLink {
  readonly kind: 'pair';
  readonly correlationRef: string;
  readonly paramNames: readonly string[];
  /** Names only — values are deliberately not returned to the renderer. */
  readonly valueHandling: 'names-only';
}

/**
 * Deterministic, non-cryptographic correlation reference.
 *
 * It is a UI/UX correlation aid for the M1 shell, NOT a pairing token: it
 * contains no secret, is never persisted, and cannot mint a session.
 */
function correlationRefFrom(canonical: string): string {
  let h1 = 0x811c9dc5;
  let h2 = 0x01000193;
  for (let i = 0; i < canonical.length; i += 1) {
    const c = canonical.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0;
    h2 = Math.imul(h2 + c + i, 0x85ebca6b) >>> 0;
  }
  return `pairref-${h1.toString(16).padStart(8, '0')}${h2.toString(16).padStart(8, '0')}`;
}

const PARAM_NAME_PATTERN = /^[a-z0-9_]{1,64}$/;

export function parsePairingDeepLink(raw: unknown): ParsedPairingDeepLink {
  if (typeof raw !== 'string') {
    throw new PairingDeepLinkError('NOT_A_STRING', 'deep link must be a string');
  }
  if (raw.length === 0) {
    throw new PairingDeepLinkError('EMPTY', 'deep link must not be empty');
  }
  if (raw.length > PAIRING_SEAM.MAX_URL_LENGTH) {
    throw new PairingDeepLinkError(
      'TOO_LONG',
      `deep link exceeds ${PAIRING_SEAM.MAX_URL_LENGTH} characters`,
    );
  }
  if (/[\u0000-\u001f\u007f]/.test(raw)) {
    throw new PairingDeepLinkError(
      'CONTROL_CHARACTER',
      'deep link must not contain control characters',
    );
  }
  if (!raw.toLowerCase().startsWith(`${PAIRING_SEAM.SCHEME}://`)) {
    throw new PairingDeepLinkError(
      'SCHEME_MISMATCH',
      `deep link scheme must be ${PAIRING_SEAM.SCHEME}://`,
    );
  }

  const url = new URL(raw);
  const kind = url.hostname.toLowerCase();
  if (kind !== 'pair') {
    throw new PairingDeepLinkError('UNKNOWN_KIND', `unsupported deep link host: ${kind}`);
  }

  const names: string[] = [];
  let paramCount = 0;
  for (const [name, value] of url.searchParams.entries()) {
    paramCount += 1;
    if (paramCount > PAIRING_SEAM.MAX_PARAM_COUNT) {
      throw new PairingDeepLinkError(
        'TOO_MANY_PARAMS',
        `deep link exceeds ${PAIRING_SEAM.MAX_PARAM_COUNT} parameters`,
      );
    }
    const lower = name.toLowerCase();
    if (!PARAM_NAME_PATTERN.test(lower)) {
      throw new PairingDeepLinkError('BAD_PARAM_NAME', `unsupported parameter name: ${name}`);
    }
    if (value.length > PAIRING_SEAM.MAX_PARAM_VALUE_LENGTH) {
      throw new PairingDeepLinkError(
        'PARAM_VALUE_TOO_LONG',
        `parameter ${name} exceeds ${PAIRING_SEAM.MAX_PARAM_VALUE_LENGTH} characters`,
      );
    }
    names.push(lower);
  }

  const canonical = [
    PAIRING_SEAM.SCHEME,
    kind,
    ...[...names].sort(),
  ].join('/');

  return Object.freeze({
    kind: 'pair' as const,
    correlationRef: correlationRefFrom(canonical),
    paramNames: Object.freeze([...names].sort()),
    valueHandling: 'names-only' as const,
  });
}
