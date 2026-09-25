import { createHmac, timingSafeEqual } from 'node:crypto';
import { ACTION_TYPES, COMPLETION_EVENT_TYPES, isSafeIdentifier, type SignedCompletionEvent } from './domain.js';

export const COMPLETION_SIGNATURE_VERSION = 'v1';
export const DEFAULT_MAX_SIGNATURE_AGE_MS = 5 * 60 * 1000;
/**
 * Maximum tolerated lead of the signed timestamp over server time. Small on purpose:
 * a callback that claims to be from the future is treated as a clock-attack attempt,
 * not as ordinary staleness.
 */
export const DEFAULT_MAX_SIGNATURE_FUTURE_SKEW_MS = 30 * 1000;
export const MAX_SIGNED_BODY_BYTES = 1024 * 1024;
const verifiedEnvelopes = new WeakSet<object>();

export interface VerifiedCompletionEnvelope {
  readonly event: SignedCompletionEvent;
  readonly signature: {
    readonly algorithm: 'HMAC_SHA256';
    readonly version: 'v1';
    readonly verified: true;
    readonly rawBodyBound: true;
  };
}

export function isVerifiedCompletionEnvelope(value: unknown): value is VerifiedCompletionEnvelope {
  return typeof value === 'object' && value !== null && verifiedEnvelopes.has(value);
}

export type CompletionVerificationDecision =
  | { readonly accepted: true; readonly envelope: VerifiedCompletionEnvelope }
  | { readonly accepted: false; readonly reason:
      | 'INVALID_SIGNATURE_HEADER'
      | 'INVALID_TIMESTAMP'
      | 'STALE_TIMESTAMP'
      | 'FUTURE_TIMESTAMP'
      | 'INVALID_SIGNATURE'
      | 'RAW_BODY_REPARSE_FORBIDDEN'
      | 'INVALID_EVENT' };

export interface CompletionVerificationInput {
  readonly providerId: string;
  readonly rawBody: string;
  readonly signedTimestamp: string;
  readonly signatureHeader: string;
  /** Test-only secret injection. The secret never enters the envelope or any projection. */
  readonly secret: string;
  readonly now: string;
  readonly maxAgeMs?: number;
  /** Maximum tolerated lead over `now`. Must be a positive safe integer when supplied. */
  readonly maxFutureSkewMs?: number;
}

function equalText(left: string, right: string): boolean {
  const a = Buffer.from(left);
  const b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
}

function isSafePositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
}

function validEvent(value: unknown): value is SignedCompletionEvent {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const event = value as Record<string, unknown>;
  return isSafeIdentifier(event.providerId)
    && isSafeIdentifier(event.offerId)
    && isSafeIdentifier(event.providerTransactionId)
    && isSafeIdentifier(event.externalUserId)
    && typeof event.actionType === 'string' && (ACTION_TYPES as readonly string[]).includes(event.actionType)
    && typeof event.eventType === 'string' && (COMPLETION_EVENT_TYPES as readonly string[]).includes(event.eventType)
    && isSafePositiveInteger(event.rewardAmountMinor)
    && typeof event.rewardCurrency === 'string' && /^[A-Z]{3}$/.test(event.rewardCurrency)
    && typeof event.occurredAt === 'string' && !Number.isNaN(Date.parse(event.occurredAt))
    && isSafeIdentifier(event.nonce);
}

/** Verify the exact received body. Parsed JSON must never be reserialized for signature checking. */
export function verifySignedCompletionEvent(input: CompletionVerificationInput): CompletionVerificationDecision {
  if (!isSafeIdentifier(input.providerId) || !input.rawBody || !input.secret || Buffer.byteLength(input.rawBody, 'utf8') > MAX_SIGNED_BODY_BYTES || !/^\d{13}$/.test(input.signedTimestamp)) {
    return { accepted: false, reason: 'INVALID_SIGNATURE_HEADER' };
  }
  if (!/^v1=[0-9a-fA-F]{64}$/.test(input.signatureHeader)) {
    return { accepted: false, reason: 'INVALID_SIGNATURE_HEADER' };
  }
  const timestamp = Date.parse(new Date(Number(input.signedTimestamp)).toISOString());
  const now = Date.parse(input.now);
  const maxAge = input.maxAgeMs ?? DEFAULT_MAX_SIGNATURE_AGE_MS;
  const maxFutureSkew = input.maxFutureSkewMs ?? DEFAULT_MAX_SIGNATURE_FUTURE_SKEW_MS;
  if (Number.isNaN(timestamp) || Number.isNaN(now) || !Number.isSafeInteger(maxAge) || maxAge <= 0 || maxAge > 24 * 60 * 60 * 1000) {
    return { accepted: false, reason: 'INVALID_TIMESTAMP' };
  }
  if (!Number.isSafeInteger(maxFutureSkew) || maxFutureSkew <= 0 || maxFutureSkew > 24 * 60 * 60 * 1000) {
    return { accepted: false, reason: 'INVALID_TIMESTAMP' };
  }
  // A signed timestamp ahead of server time is a distinct failure from a stale one.
  if (timestamp - now > maxFutureSkew) return { accepted: false, reason: 'FUTURE_TIMESTAMP' };
  if (now - timestamp > maxAge) return { accepted: false, reason: 'STALE_TIMESTAMP' };

  const signedContent = `${input.signedTimestamp}.${input.rawBody}`;
  const expected = createHmac('sha256', input.secret).update(signedContent, 'utf8').digest('hex');
  if (!equalText(expected, input.signatureHeader.slice(3).toLowerCase())) return { accepted: false, reason: 'INVALID_SIGNATURE' };

  let event: unknown;
  try {
    event = JSON.parse(input.rawBody) as unknown;
  } catch {
    return { accepted: false, reason: 'RAW_BODY_REPARSE_FORBIDDEN' };
  }
  if (!validEvent(event) || event.providerId !== input.providerId) return { accepted: false, reason: 'INVALID_EVENT' };
  const envelope = Object.freeze({
    event: Object.freeze(event),
    signature: Object.freeze({ algorithm: 'HMAC_SHA256' as const, version: 'v1' as const, verified: true as const, rawBodyBound: true as const }),
  });
  verifiedEnvelopes.add(envelope);
  return { accepted: true, envelope };
}
