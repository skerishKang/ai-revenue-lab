import test from 'node:test';
import assert from 'node:assert/strict';
import { handleRequest, REVOKE_PATH, MINT_PATH, LOVETREE_PRODUCT_ID } from '../worker.mjs';

const SECRET = 'caller-secret-value';
const SID = 'sess_' + 'b'.repeat(32);

function authority(rows = {}) {
  const calls = [];
  return {
    calls,
    async revoke_auth_session(payload) {
      calls.push(['revoke_auth_session', payload]);
      if (rows.unreachable) throw new Error('권위 장애');
      if (rows.notOurs) return { ok: false, error: { code: 'canonical_auth_session_not_found' } };
      return { ok: true, session: { session_id: payload.session_id, product_id: payload.product_id, state: 'revoked' } };
    },
    async resolve_or_create_product_link(payload) { calls.push(['resolve_or_create_product_link', payload]); return { ok: true }; },
    async establish_auth_session(payload) { calls.push(['establish_auth_session', payload]); return { ok: true }; }
  };
}

const post = (path, body, token = SECRET) => new Request(`https://lovetree-auth-caller.example${path}`, {
  method: 'POST',
  headers: { 'content-type': 'application/json', ...(token ? { authorization: `Bearer ${token}` } : {}) },
  body: typeof body === 'string' ? body : JSON.stringify(body)
});

test('minting stays closed for every input', async () => {
  const made = authority();
  for (const attempt of [
    post(MINT_PATH, { product_user_id: 'usr_any', provider_subject: 'whoever' }, SECRET),
    post(MINT_PATH, {}, null),
    post(MINT_PATH, 'not-json', SECRET)
  ]) {
    const response = await handleRequest(attempt, { LOVETREE_CALLER_SECRET: SECRET, IDENTITY_AUTHORITY: made });
    assert.equal(response.status, 501);
    assert.equal((await response.json()).error.code, 'mint_policy_undecided');
  }
  assert.deepEqual(made.calls, [], '발급 경로가 링크·세션 RPC를 불러서는 안 된다');
});

test('revocation pins the product to LoveTree and requires the caller bearer', async () => {
  const made = authority();
  const env = { LOVETREE_CALLER_SECRET: SECRET, IDENTITY_AUTHORITY: made };

  assert.equal((await handleRequest(post(REVOKE_PATH, { session_id: SID }, null), env)).status, 401);
  assert.equal((await handleRequest(post(REVOKE_PATH, { session_id: SID }, 'wrong'), env)).status, 401);
  assert.equal((await handleRequest(post(REVOKE_PATH, { session_id: SID }), { IDENTITY_AUTHORITY: made })).status, 503);

  for (const bad of [{ session_id: SID, product_id: 'b62' }, { session_id: 'sess_!bad' }, {}, { session_id: 'x'.repeat(200) }]) {
    const response = await handleRequest(post(REVOKE_PATH, bad), env);
    assert.equal(response.status, 400);
  }
  assert.deepEqual(made.calls, []);

  const ok = await handleRequest(post(REVOKE_PATH, { session_id: SID, product_id: 'b62' }, 'x'), env);
  assert.equal(ok.status, 401, ' caller 비밀이 틀리면 폐기되지 않는다');

  const revoked = await handleRequest(post(REVOKE_PATH, { session_id: SID }), env);
  assert.equal(revoked.status, 200);
  assert.deepEqual(made.calls, [['revoke_auth_session', { product_id: LOVETREE_PRODUCT_ID, session_id: SID }]]);
  const body = await revoked.json();
  assert.equal(body.revoked.state, 'revoked');
  assert.equal(revoked.headers.get('cache-control'), 'no-store');
});

test('a session the authority will not hand back is not reported as revoked', async () => {
  const made = authority({ notOurs: true });
  const response = await handleRequest(post(REVOKE_PATH, { session_id: SID }), { LOVETREE_CALLER_SECRET: SECRET, IDENTITY_AUTHORITY: made });
  assert.equal(response.status, 401);
  assert.equal((await response.json()).error.code, 'session_not_revoked');

  const unreachable = await handleRequest(post(REVOKE_PATH, { session_id: SID }), { LOVETREE_CALLER_SECRET: SECRET, IDENTITY_AUTHORITY: authority({ unreachable: true }) });
  assert.equal(unreachable.status, 503);

  const noBinding = await handleRequest(post(REVOKE_PATH, { session_id: SID }), { LOVETREE_CALLER_SECRET: SECRET });
  assert.equal(noBinding.status, 503);
});

test('health and auth-check describe the closed mint without leaking the secret', async () => {
  const made = authority();
  const env = { LOVETREE_CALLER_SECRET: SECRET, IDENTITY_AUTHORITY: made };
  const health = await handleRequest(new Request('https://lovetree-auth-caller.example/health'), env);
  assert.equal(health.status, 200);
  assert.equal((await health.json()).mint, 'closed');

  const check = await handleRequest(post('/auth-check', undefined, SECRET), env);
  assert.equal(check.status, 200);
  const text = JSON.stringify(await check.json());
  assert.equal(text.includes(SECRET), false);
  assert.equal((await handleRequest(post('/whatever', {}, SECRET), env)).status, 404);
});
