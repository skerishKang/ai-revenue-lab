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
 *
 * #3095 (CLAW5) adds exactly ONE bounded allowlisted transfer field so the
 * trusted runner boundary can receive the one-time pairing code:
 *
 *   PAIRING_CODE_TRANSFER_BOUNDED=YES
 *   PAIRING_CODE_GENERAL_PERSISTENCE=NO
 *   PAIRING_CODE_LOGGED=NO
 *   PAIRING_CODE_RENDERER_DIAGNOSTIC=NO
 *   PAIRING_AUTHORITY_IMPLEMENTED=NO   (still owned by #3080)
 *   SECOND_DEEPLINK_PARSER=0
 *
 * The pairing code is single-use handoff material, not application state: it is
 * carried in a frozen, explicitly-cleared field, is never written to the
 * bounded log, never returned to the renderer, and never generalises into any
 * other parameter name.
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
  // #3095: the single allowlisted transfer parameter and its exact shape.
  PAIRING_CODE_PARAM: 'code',
  PAIRING_CODE_HEX_CHARS: 32,
  PAIRING_CODE_TRANSFER_BOUNDED: true,
  PAIRING_CODE_GENERAL_PERSISTENCE: false,
  PAIRING_CODE_LOGGED: false,
  PAIRING_CODE_RENDERER_DIAGNOSTIC: false,
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
  /** Names only — every non-allowlisted value is deliberately not returned. */
  readonly valueHandling: 'names-only';
  /**
   * #3095 bounded transfer. Exactly one allowlisted pairing code may cross the
   * seam to the trusted runner boundary. It is `null` whenever the deep link
   * carries no code, and it must be cleared by the consumer after handoff.
   */
  readonly pairingCodeTransfer: string | null;
  readonly pairingCodeTransferBounded: true;
}

/**
 * #3095: bound the *transferred* value without failing the whole parse.
 *
 * A malformed code is not a malformed deep link: the #3083 seam must keep
 * behaving exactly as before for every other input, and rejecting here would
 * turn an unusable handoff into a broken shell. Instead the code only crosses
 * the seam when it already has the exact #3080 shape, so the trusted runner
 * boundary can never receive an out-of-shape value. Anything else yields
 * `null` and is rejected downstream by the canonical #3080 redemption client.
 */
function pairingCodeOrNull(value: string): string | null {
  if (value.length !== PAIRING_SEAM.PAIRING_CODE_HEX_CHARS) return null;
  if (!/^[0-9a-f]+$/.test(value)) return null;
  return value;
}

/**
 * #3095: consume a transferred pairing code exactly once.
 *
 * The value is a function argument rather than object state, so the shell keeps
 * no pairing-code field to persist, log, or reflect to the renderer. After this
 * call the caller holds the only reference and is responsible for handing it to
 * the #3080 redemption caller.
 */
export function takePairingCodeTransfer(parsed: ParsedPairingDeepLink): string | null {
  if (!parsed || parsed.pairingCodeTransferBounded !== true) {
    return null;
  }
  return parsed.pairingCodeTransfer;
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
  // #3095: only the single allowlisted parameter may yield a value. Every other
  // parameter keeps the names-only behaviour it always had.
  let pairingCodeTransfer: string | null = null;
  let codeParamSeen = false;
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
    if (lower === PAIRING_SEAM.PAIRING_CODE_PARAM) {
      if (codeParamSeen) {
        throw new PairingDeepLinkError(
          'PAIRING_CODE_REPEATED',
          'deep link must not repeat the pairing code parameter',
        );
      }
      codeParamSeen = true;
      pairingCodeTransfer = pairingCodeOrNull(value);
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
    pairingCodeTransfer,
    pairingCodeTransferBounded: true as const,
  });
}
