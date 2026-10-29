import test from 'node:test';
import assert from 'node:assert/strict';
import { issueAccessToken } from '../access-token.mjs';

test('access token carries bound claims and verifies with the public key', async () => {
  const keys = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const token = await issueAccessToken({ key: keys.privateKey, kid: 'test', issuer: 'https://auth.padiem.net', audience: 'lovetree', subject: 'synthetic', sessionId: 'session', now: 1000 });
  const [h, p, s] = token.split('.');
  assert.deepEqual(JSON.parse(Buffer.from(h, 'base64url')), { alg: 'ES256', typ: 'JWT', kid: 'test' });
  assert.deepEqual(JSON.parse(Buffer.from(p, 'base64url')), { iss: 'https://auth.padiem.net', aud: 'lovetree', sub: 'synthetic', sid: 'session', iat: 1000, exp: 1900, token_use: 'access' });
  assert.equal(await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, keys.publicKey, Buffer.from(s, 'base64url'), new TextEncoder().encode(`${h}.${p}`)), true);
  assert.equal(await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, keys.publicKey, Buffer.from(s, 'base64url'), new TextEncoder().encode(`${h}.${p}x`)), false);
});

test('rejects public signing key and invalid input', async () => {
  const keys = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  await assert.rejects(() => issueAccessToken({ key: keys.publicKey, kid: 'k', issuer: 'i', audience: 'a', subject: 's', sessionId: 's', now: 0 }));
});
