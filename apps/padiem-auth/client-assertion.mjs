const enc = new TextEncoder();
function decode(x) {
  if (typeof x !== 'string' || !/^[A-Za-z0-9_-]+$/.test(x)) throw new Error('bad assertion');
  return Uint8Array.from(atob(x.replaceAll('-', '+').replaceAll('_', '/').padEnd(Math.ceil(x.length / 4) * 4, '=')), c => c.charCodeAt(0));
}

// The replay check must be shared across all instances and durable.
export async function verifyClientAssertion({ assertion, clientId, jwks, audience, now, claim }) {
  if (typeof assertion !== 'string' || typeof clientId !== 'string') throw new Error('bad assertion');
  const parts = assertion.split('.');
  if (parts.length !== 3) throw new Error('bad assertion');
  const header = JSON.parse(new TextDecoder().decode(decode(parts[0])));
  const body = JSON.parse(new TextDecoder().decode(decode(parts[1])));
  if (header.alg !== 'ES256' || typeof header.kid !== 'string' || header.crit || header.jku || header.jwk || header.x5u) throw new Error('bad header');
  const keys = (jwks?.keys ?? []).filter(k => k.kid === header.kid && k.kty === 'EC' && k.crv === 'P-256' && !k.d && (!k.use || k.use === 'sig') && (!k.alg || k.alg === 'ES256'));
  if (keys.length !== 1 || body.iss !== clientId || body.sub !== clientId || body.aud !== audience ||
      !Number.isSafeInteger(body.exp) || body.exp <= now || body.exp > now + 300 ||
      !Number.isSafeInteger(body.iat) || body.iat > now || body.iat < now - 300 ||
      typeof body.jti !== 'string' || !/^[A-Za-z0-9_-]{22,128}$/.test(body.jti)) throw new Error('bad assertion claims');
  const key = await crypto.subtle.importKey('jwk', keys[0], { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
  const good = await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, key, decode(parts[2]), enc.encode(`${parts[0]}.${parts[1]}`));
  if (!good || !await claim({ key: `${clientId}:${body.jti}`, expires: body.exp, now })) throw new Error('bad or replayed assertion');
  return true;
}
