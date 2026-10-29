import test from 'node:test';
import assert from 'node:assert/strict';
import { createApp } from '../worker.mjs';

test('callback diagnostics identify token failures without exposing sensitive values', async () => {
  const fakeSecret = 'synthetic-secret-should-never-be-logged';
  const logs = [];
  const old = console.error;
  console.error = line => logs.push(String(line));
  const token = 'a'.repeat(43);
  const stateFor = () => ({ async consumeLogin() { return { client: 'trial', redirect: 'https://trial.example/auth/callback', google_verifier: fakeSecret }; } });
  try {
    for (const fetcher of [
      async () => Response.json({error:'invalid_client', error_description:fakeSecret}, {status:401}),
      async () => { throw new TypeError(fakeSecret); },
    ]) {
      const app = createApp({clients:{trial:{redirect_uris:['https://trial.example/auth/callback']}}, googleClientId:'synthetic', googleClientSecret:fakeSecret, stateFor, fetcher});
      const req = new Request(`https://auth.padiem.net/oauth/google/callback?state=${token}.${token}&code=${fakeSecret}`, {headers:{cookie:`__Host-padiem-auth-state=${token}`}});
      const response = await app.fetch(req);
      assert.equal(response.status, 503);
      assert.deepEqual(await response.json(), {error:'authentication_unavailable'});
    }
    assert.ok(logs.some(line => line.includes('invalid_client')));
    assert.ok(logs.some(line => line.includes('TypeError')));
    assert.ok(logs.every(line => line.includes('google_token_exchange_failed')));
    assert.equal(logs.join('\n').includes(fakeSecret), false);
    assert.equal(logs.join('\n').includes(token), false);
  } finally { console.error = old; }
});
