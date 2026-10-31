const encoder = new TextEncoder();
export const ACCESS_TTL_SECONDS = 15 * 60;

function b64url(bytes) {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
}

function json64(value) { return b64url(encoder.encode(JSON.stringify(value))); }

// key is an ES256 CryptoKey imported from a padiem-auth-only secret by the caller.
// The caller must verify the subject, service binding and session before signing.
export async function issueAccessToken({ key, kid, issuer, audience, subject, accountId, sessionId, now }) {
  if (!key || key.type !== 'private' || key.algorithm?.name !== 'ECDSA' || key.algorithm?.namedCurve !== 'P-256' ||
      ![kid, issuer, audience, subject, accountId, sessionId].every((v) => typeof v === 'string' && v.length > 0) ||
      !Number.isSafeInteger(now)) throw new TypeError('invalid signing arguments');
  const header = json64({ alg: 'ES256', typ: 'JWT', kid });
  const payload = json64({ iss: issuer, aud: audience, sub: subject, account_id: accountId, sid: sessionId, iat: now, exp: now + ACCESS_TTL_SECONDS, token_use: 'access' });
  const input = `${header}.${payload}`;
  const signature = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, key, encoder.encode(input));
  if (signature.byteLength !== 64) throw new Error('unexpected ES256 signature format');
  return `${input}.${b64url(new Uint8Array(signature))}`;
}
