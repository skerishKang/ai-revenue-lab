import test from 'node:test';
import assert from 'node:assert/strict';
import { handleRequest, resolveIdentity, LOVETREE_PRODUCT_ID, RESOLVE_SESSION_PATH } from '../worker.mjs';

const SECRET = 'caller-secret-value';
const SID = 'sess_0123456789abcdef0123456789abcdef';

function authority(rows = {}) {
  const calls = [];
  return {
    calls,
    async resolve_auth_session(payload) {
      calls.push(['resolve_auth_session', payload]);
      return rows.session ?? { ok: true, session: { session_id: SID, product_id: LOVETREE_PRODUCT_ID, subject: { subject_type: 'user', subject_id: 'sub_1' }, state: 'active', expires_at: '2999-01-01T00:00:00.000Z' } };
    },
    async resolve_product_user_for_subject(payload) {
      calls.push(['resolve_product_user_for_subject', payload]);
      return rows.link ?? { ok: true, product_user_id: 'usr_abc' };
    },
    async establish_auth_session(payload) {
      calls.push(['establish_auth_session', payload]);
      return { ok: true };
    }
  };
}

function post(path, { body, token = SECRET, origin = 'https://lovetree-caller.example' } = {}) {
  return new Request(`${origin}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...(token ? { authorization: `Bearer ${token}` } : {}) },
    body: typeof body === 'string' ? body : JSON.stringify(body)
  });
}

test('health is open and reports the service', async () => {
  const response = await handleRequest(new Request('https://lovetree-caller.example/health'), {});
  assert.equal(response.status, 200);
  assert.equal((await response.json()).service, 'lovetree-authority-caller');
});

test('auth-check separates missing secret from a wrong caller token', async () => {
  const noSecret = await handleRequest(post('/auth-check', { token: 'x' }), {});
  assert.equal(noSecret.status, 503);
  assert.equal((await noSecret.json()).error.code, 'caller_credential_unavailable');

  const wrong = await handleRequest(post('/auth-check', { token: 'wrong' }), { LOVETREE_CALLER_SECRET: SECRET });
  assert.equal(wrong.status, 401);

  const missingBinding = await handleRequest(post('/auth-check', { token: SECRET }), { LOVETREE_CALLER_SECRET: SECRET });
  assert.equal(missingBinding.status, 503);
  assert.equal((await missingBinding.json()).error.code, 'authority_binding_unavailable');

  const ready = await handleRequest(post('/auth-check', { token: SECRET }), { LOVETREE_CALLER_SECRET: SECRET, IDENTITY_AUTHORITY: authority() });
  assert.equal(ready.status, 200);
});

test('resolve requires the caller bearer and a closed body', async () => {
  const made = authority();
  const env = { LOVETREE_CALLER_SECRET: SECRET, IDENTITY_AUTHORITY: made };
  assert.equal((await handleRequest(post(RESOLVE_SESSION_PATH, { body: { session_id: SID }, token: null }), env)).status, 401);
  assert.equal((await handleRequest(post(RESOLVE_SESSION_PATH, { body: { session_id: SID, product_user_id: 'usr_attack' }, token: SECRET }), env)).status, 400);
  assert.equal((await handleRequest(post(RESOLVE_SESSION_PATH, { body: 'not-json', token: SECRET }), env)).status, 400);
  assert.equal((await handleRequest(post(RESOLVE_SESSION_PATH, { body: { session_id: 'sess_!bad' }, token: SECRET }), env)).status, 400);
  assert.equal((await handleRequest(post(RESOLVE_SESSION_PATH, { body: { session_id: 'x'.repeat(300) }, token: SECRET }), env)).status, 400);
  assert.deepEqual(made.calls, []);
});

test('a verified LoveTree session returns only the bounded identity', async () => {
  const made = authority();
  const response = await handleRequest(post(RESOLVE_SESSION_PATH, { body: { session_id: SID }, token: SECRET }), { LOVETREE_CALLER_SECRET: SECRET, IDENTITY_AUTHORITY: made });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, identity: { product_id: LOVETREE_PRODUCT_ID, subject_id: 'sub_1', expires_at: '2999-01-01T00:00:00.000Z' } });
  assert.deepEqual(made.calls.map(c => c[0]), ['resolve_auth_session', 'resolve_product_user_for_subject']);
  assert.equal(response.headers.get('cache-control'), 'no-store');
});

for (const [name, rows] of [
  ['a b62 session', { session: { ok: true, session: { session_id: SID, product_id: 'b62', subject: { subject_type: 'user', subject_id: 'sub_1' }, state: 'active', expires_at: '2999-01-01T00:00:00.000Z' } } }],
  ['a revoked session', { session: { ok: true, session: { session_id: SID, product_id: LOVETREE_PRODUCT_ID, subject: { subject_type: 'user', subject_id: 'sub_1' }, state: 'revoked', expires_at: '2999-01-01T00:00:00.000Z' } } }],
  ['an expired session', { session: { ok: true, session: { session_id: SID, product_id: LOVETREE_PRODUCT_ID, subject: { subject_type: 'user', subject_id: 'sub_1' }, state: 'active', expires_at: '2020-01-01T00:00:00.000Z' } } }],
  ['an anonymous subject', { session: { ok: true, session: { session_id: SID, product_id: LOVETREE_PRODUCT_ID, subject: { subject_type: 'anonymous', subject_id: 'sub_1' }, state: 'active', expires_at: '2999-01-01T00:00:00.000Z' } } }],
  ['a missing product link', { link: { ok: false, error: { code: 'canonical_product_identity_link_not_active' } } }]
]) {
  test(`the caller lane refuses ${name}`, async () => {
    const made = authority(rows);
    const response = await handleRequest(post(RESOLVE_SESSION_PATH, { body: { session_id: SID }, token: SECRET }), { LOVETREE_CALLER_SECRET: SECRET, IDENTITY_AUTHORITY: made });
    assert.equal(response.status, 401);
    assert.equal((await response.json()).error.code, 'unauthenticated');
  });
}

test('the relay exposes no write RPC and reports authority failures as 503', async () => {
  const made = authority();
  const refused = await resolveIdentity({ ...made, resolve_auth_session: undefined }, { sessionId: SID });
  assert.deepEqual(refused, { ok: false, status: 503, code: 'authority_unavailable' });

  const throwing = {
    async resolve_auth_session() { throw new Error('권위 장애'); },
    async resolve_product_user_for_subject() { return { ok: true, product_user_id: 'usr_abc' }; }
  };
  const response = await handleRequest(post(RESOLVE_SESSION_PATH, { body: { session_id: SID }, token: SECRET }), { LOVETREE_CALLER_SECRET: SECRET, IDENTITY_AUTHORITY: throwing });
  assert.equal(response.status, 503);

  const writableOnly = authority();
  const attack = await handleRequest(post('/establish', { body: { session_id: SID }, token: SECRET }), { LOVETREE_CALLER_SECRET: SECRET, IDENTITY_AUTHORITY: writableOnly });
  assert.equal(attack.status, 404);
  assert.equal(writableOnly.calls.filter(c => c[0] === 'establish_auth_session').length, 0);
});

test('unknown paths and oversized authority answers are refused', async () => {
  const env = { LOVETREE_CALLER_SECRET: SECRET, IDENTITY_AUTHORITY: authority() };
  assert.equal((await handleRequest(post('/anything', { body: {}, token: SECRET }), env)).status, 404);
  assert.equal((await handleRequest(new Request('https://lovetree-caller.example/resolve-session'), env)).status, 404);

  const huge = { session_id: SID, product_id: LOVETREE_PRODUCT_ID, subject: { subject_type: 'user', subject_id: `sub_${'y'.repeat(70_000)}` }, state: 'active', expires_at: '2999-01-01T00:00:00.000Z' };
  const response = await handleRequest(post(RESOLVE_SESSION_PATH, { body: { session_id: SID }, token: SECRET }), {
    LOVETREE_CALLER_SECRET: SECRET,
    IDENTITY_AUTHORITY: authority({ session: { ok: true, session: huge } })
  });
  assert.equal(response.status, 502);
  assert.equal((await response.json()).error.code, 'authority_response_too_large');
});
