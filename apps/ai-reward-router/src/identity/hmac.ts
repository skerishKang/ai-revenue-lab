/**
 * The one HMAC token primitive B64 signs with (issue #987).
 *
 * Construction is the repository's reviewed shape, the same one
 * `apps/padiem-chat/app/auth.py` uses: `key = HMAC-SHA256(secret, purpose)`
 * then `signature = HMAC-SHA256(key, body)` over a base64url JSON body, joined
 * by a dot. The PURPOSE string is what keeps tokens from crossing products or
 * crossing uses — a B64 session token and a B64 OAuth state are both signed by
 * the same secret but neither verifies under the other's purpose.
 *
 * Reusing this single helper is what keeps the Google sign-in adapter from
 * becoming a second signing implementation.
 */

const B64URL_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

export function utf8Bytes(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

export function bytesToBase64Url(bytes: Uint8Array): string {
  let output = '';
  for (let index = 0; index < bytes.length; index += 16) {
    output += String.fromCharCode(...bytes.subarray(index, index + 16));
  }
  return btoa(output).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function base64UrlToBytes(text: string): Uint8Array | null {
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

export function timingSafeEqualBytes(left: Uint8Array, right: Uint8Array): boolean {
  if (left.length !== right.length) return false;
  let diff = 0;
  for (let index = 0; index < left.length; index += 1) diff |= left[index]! ^ right[index]!;
  return diff === 0;
}

export async function hmacSha256(keyBytes: Uint8Array, message: Uint8Array): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey(
    'raw',
    keyBytes as unknown as ArrayBuffer,
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const signature = await crypto.subtle.sign('HMAC', key, message as unknown as ArrayBuffer);
  return new Uint8Array(signature);
}

async function signingKey(secret: string, purpose: string): Promise<Uint8Array> {
  return hmacSha256(utf8Bytes(secret), utf8Bytes(purpose));
}

export async function signB64Token(
  secret: string,
  purpose: string,
  claims: Record<string, unknown>,
): Promise<string> {
  const body = bytesToBase64Url(utf8Bytes(JSON.stringify(claims)));
  const signature = await hmacSha256(await signingKey(secret, purpose), utf8Bytes(body));
  return `${body}.${bytesToBase64Url(signature)}`;
}

/**
 * Verifies the signature and the `exp` claim only. Claim shapes belong to the
 * caller: a token that parses but carries unexpected fields is returned for the
 * caller to reject, so this one function cannot silently redefine another
 * token's contract.
 */
export async function readB64Token(
  secret: string | undefined,
  purpose: string,
  token: string | null | undefined,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): Promise<Record<string, unknown> | null> {
  if (!token || !secret) return null;
  const separatorIndex = token.indexOf('.');
  if (separatorIndex <= 0) return null;
  const body = token.slice(0, separatorIndex);
  const suppliedSignature = base64UrlToBytes(token.slice(separatorIndex + 1));
  if (!suppliedSignature) return null;

  const expected = await hmacSha256(await signingKey(secret, purpose), utf8Bytes(body));
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
  const expiresAt = claims['exp'];
  if (typeof expiresAt !== 'number' || !Number.isInteger(expiresAt) || expiresAt < nowSeconds) return null;
  return claims;
}
