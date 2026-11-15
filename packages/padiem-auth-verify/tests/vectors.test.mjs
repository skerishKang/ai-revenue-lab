import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createVerifier } from '../verify.mjs';
import { issueAccessToken } from '../../../apps/padiem-auth/access-token.mjs';
const vector = JSON.parse(await readFile(new URL('./vectors.json', import.meta.url)));
test('shared ES256 vectors and cached JWKS', async () => {
  let calls = 0;
  const verify = createVerifier({ audience: vector.audience, clock: () => vector.now * 1000, fetcher: async (url) => { assert.equal(url, 'https://auth.padiem.net/.well-known/jwks.json'); calls++; return Response.json(vector.jwks); } });
  assert.equal((await verify(vector.tokens.valid)).accountId, 'sub_existing');
  for (const name of ['wrong_audience', 'wrong_issuer', 'expired', 'forged']) await assert.rejects(() => verify(vector.tokens[name]));
  assert.equal(calls, 1);
});

test('account_created_at is optional, returned when valid, and clock-bound', async () => {
  const keys = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const publicJwk = await crypto.subtle.exportKey('jwk', keys.publicKey); publicJwk.kid = 'k1';
  const verify = createVerifier({ audience: 'b62', clock: () => 1000 * 1000, fetcher: async () => Response.json({ keys: [publicJwk] }) });
  const base = { key: keys.privateKey, kid: 'k1', issuer: 'https://auth.padiem.net', audience: 'b62', subject: 'synthetic', accountId: 'sub_existing', sessionId: 'sid', now: 1000 };
  const without = await issueAccessToken(base);
  assert.equal('accountCreatedAt' in (await verify(without)), false);
  const withDate = await issueAccessToken({ ...base, accountCreatedAt: 700 });
  assert.equal((await verify(withDate)).accountCreatedAt, 700);
  const header = Buffer.from(JSON.stringify({ alg: 'ES256', typ: 'JWT', kid: 'k1' })).toString('base64url');
  const body = Buffer.from(JSON.stringify({ iss: 'https://auth.padiem.net', aud: 'b62', sub: 'synthetic', account_id: 'sub_existing', sid: 'sid', amr: ['google'], iat: 1000, exp: 1900, token_use: 'access', account_created_at: 1001 })).toString('base64url');
  const input = `${header}.${body}`;
  const signature = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, keys.privateKey, new TextEncoder().encode(input));
  const future = `${input}.${Buffer.from(signature).toString('base64url')}`;
  await assert.rejects(() => verify(future), /invalid_claims/);
});
