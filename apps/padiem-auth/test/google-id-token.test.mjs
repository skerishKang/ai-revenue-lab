import test from 'node:test';
import assert from 'node:assert/strict';
import { verifyGoogleIdToken } from '../google-id-token.mjs';

const json64 = (x) => Buffer.from(JSON.stringify(x)).toString('base64url');
async function fixture(changes = {}, headerChanges = {}) {
  const keys = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
  const jwk = await crypto.subtle.exportKey('jwk', keys.publicKey); jwk.kid = 'synthetic';
  const header = json64({ alg: 'RS256', kid: 'synthetic', ...headerChanges });
  const payload = json64({ iss: 'https://accounts.google.com', aud: 'client', exp: 200, iat: 90, nonce: 'nonce', sub: 'synthetic-sub', ...changes });
  const input = `${header}.${payload}`;
  const signature = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', keys.privateKey, new TextEncoder().encode(input));
  return { token: `${input}.${Buffer.from(signature).toString('base64url')}`, jwks: { keys: [jwk] }, clientId: 'client', nonce: 'nonce', now: 100 };
}

test('accepts a signed and bound synthetic ID token', async () => {
  assert.deepEqual(await verifyGoogleIdToken(await fixture()), { sub: 'synthetic-sub' });
});

test('rejects incorrect audience, issuer, expiration, nonce and algorithm', async () => {
  for (const claims of [{ aud: 'wrong' }, { iss: 'wrong' }, { exp: 100 }, { nonce: 'wrong' }, { aud: ['client', 'other'] }]) {
    await assert.rejects(() => fixture(claims).then(verifyGoogleIdToken));
  }
  await assert.rejects(() => fixture({}, { alg: 'none' }).then(verifyGoogleIdToken));
});

test('rejects altered signature and ambiguous keys', async () => {
  const args = await fixture();
  const parts = args.token.split('.'); parts[2] = Buffer.alloc(256).toString('base64url');
  await assert.rejects(() => verifyGoogleIdToken({ ...args, token: parts.join('.') }));
  await assert.rejects(() => verifyGoogleIdToken({ ...args, jwks: { keys: [args.jwks.keys[0], args.jwks.keys[0]] } }));
});
