/**
 * B64 product-local session tokens (issue #987, owner boundary decision
 * 2026-10-27).
 *
 * B64 signs its own cookies with its own secret. The construction is the
 * repository's already-reviewed one — `key = HMAC-SHA256(secret, purpose)`
 * then `signature = HMAC-SHA256(key, body)` over a base64url JSON body — with
 * a B64-specific purpose string, so a token minted for B64 can never be
 * replayed against another product's verifier and vice versa.
 *
 * The signature only proves the token was issued here and has not expired.
 * Whether it is still VALID is answered by the session row in D1
 * (`member-store.ts`), which is what makes logout and revocation real:
 * a signed token the member has revoked stays refused until its expiry.
 */

export const B64_SESSION_COOKIE_NAME = 'b64_session';
export const B64_SESSION_TOKEN_PURPOSE = 'b64-reward/session/v1';
export const B64_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 14;

const B64URL_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
const SESSION_ID_RE = /^b64s_[a-f0-9]{24}$/;
const MEMBER_ID_RE = /^b64m_[a-f0-9]{24}$/;

export interface B64SessionClaims {
  readonly memberId: string;
  readonly sessionId: string;
  readonly expiresAtSeconds: number;
}

function utf8Bytes(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

function bytesToBase64Url(bytes: Uint8Array): string {
  let output = '';
  for (let index = 0; index < bytes.length; index += 16) {
    output += String.fromCharCode(...bytes.subarray(index, index + 16));
  }
  return btoa(output).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function base64UrlToBytes(text: string): Uint8Array | null {
  if (text.length % 4 === 1) return null;
  for (const character of text) {
    if (!B64URL_ALPHABET.includes(character)) return null;
  }
  let bits = 0;
  let accumulator = 0;
  const bytes: number[] = [];
  for (const character of text) {
    accumulator = (accumulator << 6) | B64URL_ALPHABET.indexOf(character);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      bytes.push((accumulator >> bits) & 0xff);
    }
  }
  return new Uint8Array(bytes);
}

function timingSafeEqualBytes(left: Uint8Array, right: Uint8Array): boolean {
  if (left.length !== right.length) return false;
  let diff = 0;
  for (let index = 0; index < left.length; index += 1) diff |= left[index]! ^ right[index]!;
  return diff === 0;
}

async function hmacSha256(keyBytes: Uint8Array, message: Uint8Array): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey('raw', keyBytes as unknown as ArrayBuffer, {
    name: 'HMAC',
    hash: 'SHA-256',
  }, false, ['sign']);
  const signature = await crypto.subtle.sign('HMAC', key, message as unknown as ArrayBuffer);
  return new Uint8Array(signature);
}

async function signingKey(sessionSecret: string): Promise<Uint8Array> {
  return hmacSha256(utf8Bytes(sessionSecret), utf8Bytes(B64_SESSION_TOKEN_PURPOSE));
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
  const body = bytesToBase64Url(
    utf8Bytes(JSON.stringify({ v: 1, mid: input.memberId, sid: input.sessionId, exp: input.expiresAtSeconds })),
  );
  const signature = await hmacSha256(await signingKey(input.sessionSecret), utf8Bytes(body));
  return `${body}.${bytesToBase64Url(signature)}`;
}

/**
 * Verifies the signature and the expiry claim only. Returns null for anything
 * that is not a well-formed, unexpired B64 token; the caller still has to
 * confirm the session row is live.
 */
export async function verifyB64SessionToken(
  token: string | null | undefined,
  sessionSecret: string | undefined,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): Promise<B64SessionClaims | null> {
  if (!token || !sessionSecret) return null;
  const separatorIndex = token.indexOf('.');
  if (separatorIndex <= 0) return null;
  const body = token.slice(0, separatorIndex);
  const suppliedSignature = base64UrlToBytes(token.slice(separatorIndex + 1));
  if (!suppliedSignature) return null;

  const expected = await hmacSha256(await signingKey(sessionSecret), utf8Bytes(body));
  if (!timingSafeEqualBytes(expected, suppliedSignature)) return null;

  const payloadBytes = base64UrlToBytes(body);
  if (!payloadBytes) return null;
  let payload: unknown;
  try {
    payload = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(payloadBytes));
  } catch {
    return null;
  }
  if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) return null;
  const claims = payload as Record<string, unknown>;
  if (claims['v'] !== 1) return null;
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
