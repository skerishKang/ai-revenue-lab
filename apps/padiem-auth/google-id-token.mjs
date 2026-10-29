const decoder = new TextDecoder();
const encoder = new TextEncoder();
const validPart = /^[A-Za-z0-9_-]+$/;

function decode(part) {
  if (!validPart.test(part)) throw new Error('invalid token encoding');
  const raw = atob(part.replaceAll('-', '+').replaceAll('_', '/').padEnd(Math.ceil(part.length / 4) * 4, '='));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

// jwks must come from the fixed Google JWKS endpoint, never from token headers.
// The caller must consume and check the login state and nonce before trusting this result.
export async function verifyGoogleIdToken({ token, jwks, clientId, nonce, now }) {
  if (typeof token !== 'string' || !clientId || !nonce || !Number.isSafeInteger(now)) throw new Error('invalid token arguments');
  const parts = token.split('.');
  if (parts.length !== 3) throw new Error('invalid token');
  const header = JSON.parse(decoder.decode(decode(parts[0])));
  const claims = JSON.parse(decoder.decode(decode(parts[1])));
  if (header.alg !== 'RS256' || typeof header.kid !== 'string' || !header.kid || header.crit || header.jku || header.jwk || header.x5u) throw new Error('unsupported token header');
  const matching = (Array.isArray(jwks?.keys) ? jwks.keys : []).filter((key) => key.kid === header.kid && key.kty === 'RSA' && (!key.alg || key.alg === 'RS256') && (!key.use || key.use === 'sig'));
  if (matching.length !== 1) throw new Error('untrusted signing key');
  const key = await crypto.subtle.importKey('jwk', matching[0], { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify']);
  const good = await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, decode(parts[2]), encoder.encode(`${parts[0]}.${parts[1]}`));
  if (!good) throw new Error('invalid token signature');
  const aud = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  if (!['https://accounts.google.com', 'accounts.google.com'].includes(claims.iss) ||
      !aud.includes(clientId) || (aud.length > 1 && claims.azp !== clientId) ||
      (claims.azp !== undefined && claims.azp !== clientId) ||
      !Number.isSafeInteger(claims.exp) || claims.exp <= now ||
      !Number.isSafeInteger(claims.iat) || claims.iat > now ||
      claims.nonce !== nonce || typeof claims.sub !== 'string' || !claims.sub) {
    throw new Error('invalid token claims');
  }
  return { sub: claims.sub };
}
