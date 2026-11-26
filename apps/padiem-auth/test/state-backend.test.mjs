import test from 'node:test';
import assert from 'node:assert/strict';
import { stateBindingFor } from '../worker.mjs';
import { verifyStateRpc } from '../state-rpc.mjs';

const secret = 'synthetic-state-rpc-secret-at-least-32-bytes';

function durableBinding(calls) {
  return {
    idFromName(name) { return name; },
    get(name) {
      return { async fetch(url, init) {
        calls.push({ name, url, init });
        return Response.json({ value: { from: 'do' } });
      } };
    },
  };
}

test('missing or explicit do backend keeps the Durable Object wire contract', async () => {
  for (const backend of [undefined, 'do']) {
    const calls = [];
    const env = { AUTH_STATE: durableBinding(calls), ...(backend ? { AUTH_STATE_BACKEND: backend } : {}) };
    const value = await stateBindingFor(env)('synthetic-object').inspectRefresh({ id: 'synthetic' });
    assert.deepEqual(value, { from: 'do' });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].name, 'synthetic-object');
    assert.equal(calls[0].url, 'https://internal/inspectRefresh');
    assert.deepEqual(JSON.parse(calls[0].init.body), { id: 'synthetic' });
  }
});

test('com2 backend signs the exact body, path, timestamp and nonce', async () => {
  let captured;
  const fetcher = async (url, init) => {
    captured = { url, init };
    return Response.json({ value: { from: 'com2' } });
  };
  const state = stateBindingFor({
    AUTH_STATE_BACKEND: 'com2',
    AUTH_STATE_URL: 'https://state.example.invalid',
    AUTH_STATE_SECRET: secret,
  }, fetcher);
  assert.deepEqual(await state('synthetic-object').rotate({ id: 'synthetic' }), { from: 'com2' });
  assert.equal(captured.url, 'https://state.example.invalid/rpc/rotate');
  assert.equal(captured.init.method, 'POST');
  assert.equal(captured.init.redirect, 'manual');
  assert.deepEqual(JSON.parse(Buffer.from(captured.init.body).toString()), { name: 'synthetic-object', args: { id: 'synthetic' } });
  const verified = await verifyStateRpc({
    secret, method: captured.init.method, path: new URL(captured.url).pathname,
    body: new Uint8Array(captured.init.body), at: captured.init.headers['x-padiem-auth-at'],
    nonce: captured.init.headers['x-padiem-auth-nonce'], proof: captured.init.headers['x-padiem-auth-proof'],
    now: Math.floor(Date.now() / 1000),
  });
  assert.ok(verified);
});

test('com2 failures never fall back to the Durable Object', async () => {
  for (const failure of ['status', 'network', 'shape']) {
    let durableCalls = 0;
    const env = {
      AUTH_STATE_BACKEND: 'com2',
      AUTH_STATE_URL: 'https://state.example.invalid',
      AUTH_STATE_SECRET: secret,
      AUTH_STATE: durableBinding([]),
    };
    const originalGet = env.AUTH_STATE.get;
    env.AUTH_STATE.get = (name) => { durableCalls++; return originalGet(name); };
    const fetcher = async () => {
      if (failure === 'network') throw new Error('synthetic network failure');
      if (failure === 'shape') return Response.json({});
      return Response.json({ error: 'state_failure' }, { status: 503 });
    };
    await assert.rejects(() => stateBindingFor(env, fetcher)('synthetic-object').revoke({ id: 'synthetic' }));
    assert.equal(durableCalls, 0);
  }
});

test('com2 keeps password recovery orchestration and its existing secrets in the Worker', async () => {
  const calls = [];
  const env = {
    AUTH_STATE_BACKEND: 'com2',
    AUTH_STATE_URL: 'https://state.example.invalid',
    AUTH_STATE_SECRET: secret,
    PADIEM_AUTH_EMAIL_RECOVERY_ENABLED: true,
    PADIEM_AUTH_PASSWORD_RPC_SECRET: 'synthetic-chat-rpc-secret-at-least-32-bytes',
    PADIEM_CHAT_PASSWORD_RPC_ORIGIN: 'https://chat.example.invalid',
    PADIEM_AUTH_IDENTITY_HMAC_KEY: Buffer.alloc(32, 7).toString('base64url'),
  };
  const fetcher = async (url, init) => {
    calls.push({ url, init });
    if (url.includes('/rpc/')) {
      const method = new URL(url).pathname.split('/').at(-1);
      const values = {
        emailRecoveryCandidate: { account_id: 'sub_synthetic', credential_epoch: '2026-11-26T00:00:00+00:00' },
        beginAccountDeletion: true,
        indexedAccountSessions: [],
        releaseAccountDeletion: true,
      };
      return Response.json({ value: values[method] });
    }
    const action = new URL(url).pathname.split('/').at(-1);
    if (action === 'inspect') return Response.json({ ok: true, email: 'user@example.invalid', account_id: 'sub_synthetic', credential_epoch: '2026-11-26T00:00:00+00:00' });
    if (action === 'status') return Response.json({ ok: true, available: true });
    if (action === 'complete') return Response.json({ ok: true, product_user_id: 'usr_' + 'a'.repeat(32), account_id: 'sub_synthetic', credential_epoch: '2026-11-26T00:00:00+00:00' });
    throw new Error('unexpected synthetic route');
  };
  const result = await stateBindingFor(env, fetcher)('google-account-registry').completeEmailRecovery({ token: 't'.repeat(43), newPassword: 'synthetic-password', now: 1000 });
  assert.deepEqual(result, { ok: true });
  assert.equal(calls.some(call => call.url.includes('/rpc/completeEmailRecovery')), false);
  assert.equal(calls.filter(call => call.url.includes('chat.example.invalid')).length, 3);
});

test('com2 deletion recovery hands Chat cleanup back to the Worker without exposing the handoff', async () => {
  const calls = [];
  const env = {
    AUTH_STATE_BACKEND: 'com2',
    AUTH_STATE_URL: 'https://state.example.invalid',
    AUTH_STATE_SECRET: secret,
    PADIEM_AUTH_PASSWORD_RPC_SECRET: 'synthetic-chat-rpc-secret-at-least-32-bytes',
    PADIEM_CHAT_PASSWORD_RPC_ORIGIN: 'https://chat.example.invalid',
  };
  const fetcher = async (url, init) => {
    calls.push({ url, init });
    if (url.includes('/rpc/')) {
      const method = new URL(url).pathname.split('/').at(-1);
      const values = {
        resolveAccount: { state: 'deleted', accountIdHash: 'a'.repeat(64) },
        pendingChatAccountDeletions: ['usr_synthetic'],
        completeChatAccountDeletion: true,
      };
      return Response.json({ value: values[method] });
    }
    assert.equal(new URL(url).pathname, '/internal/account-delete');
    return Response.json({ ok: true, deleted: true });
  };
  const result = await stateBindingFor(env, fetcher)('google-account-registry').resolveAccount({ fingerprint: 'synthetic' });
  assert.deepEqual(result, { state: 'deleted' });
  assert.equal(calls.filter(call => call.url.includes('chat.example.invalid')).length, 1);
  await assert.rejects(() => stateBindingFor(env, async () => Response.json({ value: { state: 'deleted' } }))('google-account-registry').resolveAccount({ fingerprint: 'synthetic' }), /state failed/);
});

test('invalid backend selection and incomplete com2 configuration fail closed', () => {
  assert.throws(() => stateBindingFor({ AUTH_STATE_BACKEND: 'other', AUTH_STATE: durableBinding([]) }), /invalid auth state backend/);
  assert.throws(() => stateBindingFor({ AUTH_STATE_BACKEND: 'com2' }), /configuration missing/);
  assert.throws(() => stateBindingFor({}), /binding missing/);
});
