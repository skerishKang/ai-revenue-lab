/**
 * B64 product-local session tokens (issue #987, owner boundary decision
 * 2026-10-27).
 *
 * B64 signs its own cookies with its own secret. The construction is the
 * repository's already-reviewed one, shared through `hmac.ts` and the same one
 * `apps/padiem-chat/app/auth.py` uses: `key = HMAC-SHA256(secret, purpose)`
 * then `signature = HMAC-SHA256(key, body)` over a base64url JSON body — with a
 * B64-specific purpose string, so a token minted for B64 can never be replayed
 * against another product's verifier and vice versa.
 *
 * The signature only proves the token was issued here and has not expired.
 * Whether it is still VALID is answered by the session row in D1
 * (`member-store.ts`), which is what makes logout and revocation real:
 * a signed token the member has revoked stays refused until its expiry.
 */

import { readB64Token, signB64Token } from './hmac.js';

export const B64_SESSION_COOKIE_NAME = 'b64_session';
export const B64_SESSION_TOKEN_PURPOSE = 'b64-reward/session/v1';
export const B64_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 14;

const SESSION_ID_RE = /^b64s_[a-f0-9]{24}$/;
const MEMBER_ID_RE = /^b64m_[a-f0-9]{24}$/;

export interface B64SessionClaims {
  readonly memberId: string;
  readonly sessionId: string;
  readonly expiresAtSeconds: number;
}

export function newB64SessionId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(12));
  return `b64s_${Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')}`;
}

export function newB64MemberId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(12));
  return `b64m_${Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')}`;
}

export function isB64MemberId(value: unknown): value is string {
  return typeof value === 'string' && MEMBER_ID_RE.test(value);
}

export function isB64SessionId(value: unknown): value is string {
  return typeof value === 'string' && SESSION_ID_RE.test(value);
}

export async function mintB64SessionToken(input: {
  readonly sessionSecret: string;
  readonly memberId: string;
  readonly sessionId: string;
  readonly expiresAtSeconds: number;
}): Promise<string> {
  if (!input.sessionSecret) throw new Error('B64_SESSION_SECRET is required to mint a session');
  if (!isB64MemberId(input.memberId)) throw new Error('member id is not a B64 member id');
  if (!isB64SessionId(input.sessionId)) throw new Error('session id is not a B64 session id');
  return signB64Token(input.sessionSecret, B64_SESSION_TOKEN_PURPOSE, {
    v: 1,
    mid: input.memberId,
    sid: input.sessionId,
    exp: input.expiresAtSeconds,
  });
}

/**
 * Verifies the signature and the expiry claim, then the B64 claim shape.
 * Returns null for anything that is not a well-formed, unexpired B64 session
 * token; the caller still has to confirm the session row is live.
 */
export async function verifyB64SessionToken(
  token: string | null | undefined,
  sessionSecret: string | undefined,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): Promise<B64SessionClaims | null> {
  const claims = await readB64Token(sessionSecret, B64_SESSION_TOKEN_PURPOSE, token, nowSeconds);
  if (!claims) return null;
  const memberId = claims['mid'];
  const sessionId = claims['sid'];
  const expiresAt = claims['exp'];
  if (!isB64MemberId(memberId) || !isB64SessionId(sessionId)) return null;
  if (typeof expiresAt !== 'number' || !Number.isInteger(expiresAt) || expiresAt < nowSeconds) return null;
  return Object.freeze({ memberId, sessionId, expiresAtSeconds: expiresAt });
}

export function b64SessionCookieValue(token: string, maxAgeSeconds = B64_SESSION_MAX_AGE_SECONDS): string {
  return [
    `${B64_SESSION_COOKIE_NAME}=${token}`,
    'Path=/',
    `Max-Age=${maxAgeSeconds}`,
    'HttpOnly',
    'SameSite=Lax',
    'Secure',
  ].join('; ');
}

/** The value a browser sends back after Max-Age=0 removes the cookie. */
export function b64SessionClearCookieValue(): string {
  return b64SessionCookieValue('', 0);
}
