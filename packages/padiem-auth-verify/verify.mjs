const ISSUER = 'https://auth.padiem.net';
const JWKS_URL = `${ISSUER}/.well-known/jwks.json`;
const dec = new TextDecoder('utf-8', { fatal: true });
function from64(text) {
  if (typeof text !== 'string' || !/^[A-Za-z0-9_-]+$/.test(text)) throw new Error('invalid_encoding');
  return Uint8Array.from(atob(text.replaceAll('-', '+').replaceAll('_', '/').padEnd(Math.ceil(text.length / 4) * 4, '=')), x => x.charCodeAt(0));
}
export function createVerifier({ audience, fetcher = fetch, clock = () => Date.now(), cacheMs = 300000 } = {}) {
  if (!audience || typeof audience !== 'string' || cacheMs <= 0) throw new Error('invalid_configuration');
  let cached = null, expires = 0;
  async function keys(force) {
    if (!force && cached && clock() < expires) return cached;
    const response = await fetcher(JWKS_URL, { redirect: 'manual' });
    if (!response.ok) throw new Error('jwks_unavailable');
    const data = await response.json();
    if (!Array.isArray(data?.keys)) throw new Error('invalid_jwks');
    cached = data.keys; expires = clock() + cacheMs; return cached;
  }
  async function find(kid) {
    const match = list => list.filter(k => k.kid === kid && k.kty === 'EC' && k.crv === 'P-256' && !k.d && (!k.alg || k.alg === 'ES256') && (!k.use || k.use === 'sig'));
    let candidates = match(await keys(false));
    if (!candidates.length) candidates = match(await keys(true));
    if (candidates.length !== 1) throw new Error('unknown_key');
    return candidates[0];
  }
  return async function verify(token) {
    if (typeof token !== 'string') throw new Error('invalid_token');
    const p = token.split('.'); if (p.length !== 3) throw new Error('invalid_token');
    const head = JSON.parse(dec.decode(from64(p[0]))), body = JSON.parse(dec.decode(from64(p[1])));
    if (head.alg !== 'ES256' || head.typ !== 'JWT' || typeof head.kid !== 'string' || !head.kid || head.crit || head.jku || head.jwk || head.x5u) throw new Error('invalid_header');
    const key = await crypto.subtle.importKey('jwk', await find(head.kid), { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
    if (!await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, key, from64(p[2]), new TextEncoder().encode(`${p[0]}.${p[1]}`))) throw new Error('invalid_signature');
    const now = Math.floor(clock()/1000);
    // #7821: name the time conditions separately, like #7699 in the comparison
    // flow, so a host clock trailing the issuer no longer looks like a forged
    // claim. Which tokens are refused is unchanged.
    if (body.iss !== ISSUER || body.aud !== audience || body.token_use !== 'access') throw new Error('invalid_claims');
    if (!Number.isSafeInteger(body.iat)) throw new Error('invalid_claims');
    if (body.iat > now) throw new Error('token_not_yet_valid');
    if (!Number.isSafeInteger(body.exp)) throw new Error('invalid_claims');
    if (body.exp <= now) throw new Error('token_expired');
    if (body.exp > body.iat + 900 ||
        typeof body.sub !== 'string' || !body.sub || !/^sub_[A-Za-z0-9_-]+$/.test(body.account_id ?? '') || typeof body.sid !== 'string' || !body.sid ||
        ('account_created_at' in body && (!Number.isSafeInteger(body.account_created_at) || body.account_created_at < 0 || body.account_created_at > body.iat)) ||
        ('amr' in body && (!Array.isArray(body.amr) || !body.amr.length || !body.amr.every(x => typeof x === 'string' && x.length > 0)))) throw new Error('invalid_claims');
    const result = { subject: body.sub, accountId: body.account_id, sessionId: body.sid, expiresAt: body.exp };
    if ('account_created_at' in body) result.accountCreatedAt = body.account_created_at;
    if ('amr' in body) result.amr = Object.freeze([...body.amr]);
    return Object.freeze(result);
  };
}
