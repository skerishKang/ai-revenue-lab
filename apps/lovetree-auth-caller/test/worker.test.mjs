import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { handleRequest, REVOKE_PATH, MINT_PATH, LOVETREE_PRODUCT_ID, LOVETREE_HANDOFF_RECIPIENT } from '../worker.mjs';

const SECRET = 'caller-secret-value';
const SID = 'sess_' + 'b'.repeat(32);
const SUB = 'subj_' + 'c'.repeat(24);
const TICKET = 'lovt_0123456789abcdef';
const AT = Date.UTC(2026, 9, 27, 0, 5, 0);
const iso = (ms) => new Date(ms).toISOString().slice(0, 19) + 'Z';
const FUTURE = iso(AT + 600_000);
const PAST = iso(AT - 600_000);
const clock = { clock: () => AT };
const STATE_SHA = 'a'.repeat(64);
const OTHER_SHA = 'b'.repeat(64);
const mintBody = (ticket = TICKET, sha = STATE_SHA) => ({ handoff_ticket: ticket, login_request_sha256: sha });

function rowFor(overrides = {}) {
  return {
    ticket_id: TICKET,
    product_id: LOVETREE_PRODUCT_ID,
    recipient: LOVETREE_HANDOFF_RECIPIENT,
    state_sha256: STATE_SHA,
    status: 'ready',
    pending_user_id: 'usr_lovetree_1',
    auth_provider: 'google',
    provider_subject: 'provider-subject-1',
    created_at: iso(AT - 60_000),
    updated_at: iso(AT - 60_000),
    expires_at: FUTURE,
    ...overrides
  };
}

/**
 * D1 대신 같은 조건으로 전이하는 이중이다. 조건(제품·수신자·로그인 요청 해시·status='ready'·만료)이
 * SQL에 그대로 남아 있는지도 함께 확인하고, 실제 SQL 검증은
 * `apps/padiem-chat/tests/test_lovetree_login_handoff.py`가 sqlite3로 한다.
 */
function handoffDb(rows = [rowFor()]) {
  const byTicket = new Map(rows.map(row => [row.ticket_id, row]));
  const seen = [];
  return {
    seen,
    prepare(sql) {
      let params = [];
      const statement = {
        bind(...values) { params = values; return statement; },
        async first() {
          seen.push({ sql, params });
          if (!sql.includes('UPDATE lovetree_login_handoffs') || !sql.includes("SET status='claimed'")
            || !sql.includes("status='ready'") || !sql.includes('product_id = ?')
            || !sql.includes('recipient = ?') || !sql.includes('state_sha256 = ?')
            || !sql.includes('expires_at > ?')) return null;
          const [claimedAt, , ticketId, productId, recipient, stateSha, now] = params;
          const row = byTicket.get(ticketId);
          if (!row) return null;
          // 소비 조건에 실패하면 행은 그대로 남는다 — 남의 요청이 표를 소모하지 못한다.
          if (row.status !== 'ready' || row.product_id !== productId || row.recipient !== recipient
            || row.state_sha256 !== stateSha || row.expires_at <= now) return null;
          row.status = 'claimed';
          row.claimed_at = claimedAt;
          row.updated_at = claimedAt;
          return { ...row };
        }
      };
      return statement;
    }
  };
}

function authority(answer = {}) {
  const calls = [];
  return {
    calls,
    async resolve_or_create_product_link(payload) {
      calls.push(['resolve_or_create_product_link', payload]);
      if (answer.linkThrows) throw new Error('권위 장애');
      if (answer.linkInactive) return { ok: true, link: { canonical_subject_id: SUB, state: 'pending' } };
      if (answer.linkBad) return { ok: true, link: { canonical_subject_id: 'sub$bad', state: 'active' } };
      return { ok: true, link: { canonical_subject_id: SUB, state: 'active' } };
    },
    async establish_auth_session(payload) {
      calls.push(['establish_auth_session', payload]);
      if (answer.establishThrows) throw new Error('권위 장애');
      if (answer.otherProduct) {
        return { ok: true, session: { session_id: SID, product_id: 'b62', subject: payload.subject, state: 'active', expires_at: FUTURE } };
      }
      if (answer.expired) {
        return { ok: true, session: { session_id: SID, product_id: LOVETREE_PRODUCT_ID, subject: payload.subject, state: 'active', expires_at: PAST } };
      }
      return { ok: true, session: { session_id: SID, product_id: LOVETREE_PRODUCT_ID, subject: payload.subject, state: 'active', expires_at: FUTURE } };
    },
    async revoke_auth_session(payload) {
      calls.push(['revoke_auth_session', payload]);
      if (answer.unreachable) throw new Error('권위 장애');
      if (answer.notOurs) return { ok: false, error: { code: 'canonical_auth_session_not_found' } };
      return { ok: true, session: { session_id: payload.session_id, product_id: payload.product_id, state: 'revoked' } };
    }
  };
}

const post = (path, body, token = SECRET) => new Request(`https://lovetree-auth-caller.example${path}`, {
  method: 'POST',
  headers: { 'content-type': 'application/json', ...(token ? { authorization: `Bearer ${token}` } : {}) },
  body: typeof body === 'string' ? body : JSON.stringify(body)
});

test('a verified handoff mints exactly one LoveTree session', async () => {
  const made = authority();
  const db = handoffDb();
  const response = await handleRequest(post(MINT_PATH, mintBody()), { LOVETREE_CALLER_SECRET: SECRET, LOVETREE_LOGIN_DB: db, IDENTITY_AUTHORITY: made }, clock);
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.session.session_id, SID);
  assert.equal(body.session.product_id, LOVETREE_PRODUCT_ID);
  assert.equal(body.session.subject_id, SUB);
  assert.equal(response.headers.get('cache-control'), 'no-store');

  // 근거는 표 한 장이고, 권위에 가는 신원은 행이 가진 값뿐이다.
  assert.deepEqual(made.calls[0], ['resolve_or_create_product_link', {
    product_id: LOVETREE_PRODUCT_ID,
    product_user_id: 'usr_lovetree_1',
    auth_provider: 'google',
    provider_subject: 'provider-subject-1'
  }]);
  assert.deepEqual(made.calls[1], ['establish_auth_session', {
    product_id: LOVETREE_PRODUCT_ID,
    subject: { subject_type: 'user', subject_id: SUB },
    authenticated_at: new Date(AT).toISOString(),
    not_after: new Date(AT + 3600_000).toISOString()
  }]);

  // 응답에는 발급 사실과 식별자만 담긴다 — 표의 신원을 호출자에게 되돌려 주지 않는다.
  const text = JSON.stringify(body);
  assert.equal(text.includes('provider-subject-1'), false);
  assert.equal(text.includes('usr_lovetree_1'), false);
  assert.equal(text.includes(SECRET), false);

  // 클레임 타임스탬프는 migration의 고정 UTC 형식이라야 문자열 만료 비교가 맞다.
  assert.match(db.seen[0].params[0], /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
});

test('the same ticket cannot mint twice, even concurrently', async () => {
  const made = authority();
  const db = handoffDb();
  const env = { LOVETREE_CALLER_SECRET: SECRET, LOVETREE_LOGIN_DB: db, IDENTITY_AUTHORITY: made };
  const raced = await Promise.all([
    handleRequest(post(MINT_PATH, mintBody()), env, clock),
    handleRequest(post(MINT_PATH, mintBody()), env, clock),
    handleRequest(post(MINT_PATH, mintBody()), env, clock)
  ]);
  const statuses = await Promise.all(raced.map(response => response.status));
  assert.equal(statuses.filter(status => status === 200).length, 1, '발급은 하나만 성공');
  assert.deepEqual(statuses.filter(status => status !== 200), [401, 401]);
  assert.equal(made.calls.filter(call => call[0] === 'establish_auth_session').length, 1);

  const late = await handleRequest(post(MINT_PATH, mintBody()), env, clock);
  assert.equal(late.status, 401);
  assert.equal((await late.json()).error.code, 'invalid_handoff');
});

// A/B 동시 로그인의 교차 교환: 표는 자기를 만든 로그인 요청의 해시와 맞을 때만 소비된다.
test('a ticket presented by another login request is refused without consuming it', async () => {
  const made = authority();
  const db = handoffDb();
  const env = { LOVETREE_CALLER_SECRET: SECRET, LOVETREE_LOGIN_DB: db, IDENTITY_AUTHORITY: made };

  const crossed = await handleRequest(post(MINT_PATH, mintBody(TICKET, OTHER_SHA)), env, clock);
  assert.equal(crossed.status, 401, '남의 요청으로는 발급하지 않는다');
  assert.equal((await crossed.json()).error.code, 'invalid_handoff');
  assert.deepEqual(made.calls, [], '거부는 권위에 닿지 않는다');

  const rightful = await handleRequest(post(MINT_PATH, mintBody()), env, clock);
  assert.equal(rightful.status, 200, '거부된 시도는 정당한 요청을 방해하지 않는다');
  assert.equal(made.calls.filter(call => call[0] === 'establish_auth_session').length, 1);

  const afterClaim = await handleRequest(post(MINT_PATH, mintBody(TICKET, OTHER_SHA)), env, clock);
  assert.equal(afterClaim.status, 401, '소진된 뒤에도 같은 코드로 닫힌다');

  const codes = new Set(db.seen.map(entry => entry.params[2]));
  assert.deepEqual([...codes], [TICKET], '클레임은 항상 같은 표 조건에서만 나온다');
});

test('a caller-asserted identity never reaches the store or the authority', async () => {
  const made = authority();
  const db = handoffDb();
  const env = { LOVETREE_CALLER_SECRET: SECRET, LOVETREE_LOGIN_DB: db, IDENTITY_AUTHORITY: made };
  for (const attempt of [
    post(MINT_PATH, { handoff_ticket: TICKET, product_user_id: 'usr_someone_else', provider_subject: 'whoever' }),
    post(MINT_PATH, { product_user_id: 'usr_any', provider_subject: 'whoever' }),
    post(MINT_PATH, { handoff_ticket: TICKET }),
    post(MINT_PATH, { handoff_ticket: TICKET, login_request_sha256: 'not-a-digest' }),
    post(MINT_PATH, { handoff_ticket: TICKET, login_request_sha256: STATE_SHA, provider_subject: 'whoever' }),
    post(MINT_PATH, { handoff_ticket: 'x'.repeat(200) }),
    post(MINT_PATH, { handoff_ticket: 'lovt$bad' }),
    post(MINT_PATH, {}),
    post(MINT_PATH, 'not-json'),
    post(MINT_PATH, mintBody(), null),
    post(MINT_PATH, mintBody(), 'wrong-secret')
  ]) {
    const response = await handleRequest(attempt, env, clock);
    assert.ok([400, 401].includes(response.status), `${response.status}`);
  }
  assert.deepEqual(made.calls, [], '거부된 요청은 권위에 닿지 않는다');
  assert.equal(db.seen.length, 0, '거부된 요청은 표를 소비하지 않는다');

  const viaGet = await handleRequest(new Request(`https://lovetree-auth-caller.example${MINT_PATH}`, { headers: { authorization: `Bearer ${SECRET}` } }), env, clock);
  assert.equal(viaGet.status, 405);
});

test('an unbound, expired, or foreign handoff is refused without minting', async () => {
  for (const [name, row] of [
    ['awaiting login', rowFor({ status: 'awaiting_login' })],
    ['already claimed', rowFor({ status: 'claimed' })],
    ['expired', rowFor({ expires_at: PAST })],
    ['another product', rowFor({ product_id: 'b62' })],
    ['another recipient', rowFor({ recipient: 'someone-else' })],
    ['no verified identity', rowFor({ pending_user_id: null, auth_provider: null, provider_subject: null })]
  ]) {
    const made = authority();
    const db = handoffDb([row]);
    const env = { LOVETREE_CALLER_SECRET: SECRET, LOVETREE_LOGIN_DB: db, IDENTITY_AUTHORITY: made };
    const response = await handleRequest(post(MINT_PATH, mintBody(row.ticket_id)), env, clock);
    assert.equal(response.status, 401, name);
    assert.equal((await response.json()).error.code, 'invalid_handoff', name);
    assert.deepEqual(made.calls, [], `${name}: 발급 RPC를 부르지 않는다`);
  }
});

test('a mint that fails after the claim leaves the ticket spent', async () => {
  for (const [name, answer] of [
    ['authority down', { establishThrows: true }],
    ['link refused', { linkInactive: true }],
    ['link malformed', { linkBad: true }],
    ['other product session', { otherProduct: true }],
    ['session already past', { expired: true }]
  ]) {
    const made = authority(answer);
    const db = handoffDb();
    const env = { LOVETREE_CALLER_SECRET: SECRET, LOVETREE_LOGIN_DB: db, IDENTITY_AUTHORITY: made };
    const first = await handleRequest(post(MINT_PATH, mintBody()), env, clock);
    assert.equal(first.status, 503, name);
    assert.ok(['session_not_minted', 'authority_unavailable'].includes((await first.json()).error.code), name);

    const retry = await handleRequest(post(MINT_PATH, mintBody()), env, clock);
    assert.equal(retry.status, 401, `${name}: 소진된 표로 재시도할 수 없다`);
  }
});

test('mint fails closed when a binding is missing', async () => {
  const made = authority();
  const noStore = await handleRequest(post(MINT_PATH, mintBody()), { LOVETREE_CALLER_SECRET: SECRET, IDENTITY_AUTHORITY: made }, clock);
  assert.equal(noStore.status, 503);
  assert.equal((await noStore.json()).error.code, 'handoff_store_unavailable');

  const noSecret = await handleRequest(post(MINT_PATH, mintBody()), { LOVETREE_LOGIN_DB: handoffDb(), IDENTITY_AUTHORITY: made }, clock);
  assert.equal(noSecret.status, 503);
  assert.equal((await noSecret.json()).error.code, 'caller_credential_unavailable');

  const noAuthority = await handleRequest(post(MINT_PATH, mintBody()), { LOVETREE_CALLER_SECRET: SECRET, LOVETREE_LOGIN_DB: handoffDb() }, clock);
  assert.equal(noAuthority.status, 503);
  assert.equal((await noAuthority.json()).error.code, 'authority_unavailable');

  const brokenStore = await handleRequest(post(MINT_PATH, mintBody()), {
    LOVETREE_CALLER_SECRET: SECRET,
    LOVETREE_LOGIN_DB: { prepare: () => { throw new Error('D1 없음'); } },
    IDENTITY_AUTHORITY: made
  }, clock);
  assert.equal(brokenStore.status, 503);
  assert.equal((await brokenStore.json()).error.code, 'handoff_store_unavailable');
  assert.deepEqual(made.calls, []);
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

  const revoked = await handleRequest(post(REVOKE_PATH, { session_id: SID }), env);
  assert.equal(revoked.status, 200);
  assert.deepEqual(made.calls, [['revoke_auth_session', { product_id: LOVETREE_PRODUCT_ID, session_id: SID }]]);
  assert.equal((await revoked.json()).revoked.state, 'revoked');
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

test('health and auth-check describe the durable handoff mint without leaking the secret', async () => {
  const made = authority();
  const env = { LOVETREE_CALLER_SECRET: SECRET, IDENTITY_AUTHORITY: made };
  const health = await handleRequest(new Request('https://lovetree-auth-caller.example/health'), env);
  assert.equal(health.status, 200);
  assert.equal((await health.json()).mint, 'durable-handoff');

  const check = await handleRequest(post('/auth-check', undefined, SECRET), env);
  assert.equal(check.status, 200);
  const body = await check.json();
  assert.deepEqual(body.methods, ['revoke-session', 'mint-session']);
  assert.equal(JSON.stringify(body).includes(SECRET), false);
  assert.equal((await handleRequest(post('/whatever', {}, SECRET), env)).status, 404);
});

// migration 076과 저장소(app/lovetree_auth_store.py)가 이 중계가 쓰는 표·상태·고정값과
// 같은지 이 lane에서 묶는다. 실제 SQL 실행 검증은 B62 Chat CI lane의
// tests/test_lovetree_login_handoff.py가 sqlite3로 한다 — 이 lane은 Chat 의존성이 없다.
test('the table contract and the store still match what this relay claims', async () => {
  const migration = await readFile(new URL('../../padiem-chat/migrations/076_lovetree_login_handoff.sql', import.meta.url), 'utf8');
  const store = await readFile(new URL('../../padiem-chat/app/lovetree_auth_store.py', import.meta.url), 'utf8');

  for (const fragment of [
    'CREATE TABLE IF NOT EXISTS lovetree_login_handoffs',
    `CHECK (product_id = '${LOVETREE_PRODUCT_ID}')`,
    `CHECK (recipient = '${LOVETREE_HANDOFF_RECIPIENT}')`,
    "CHECK (status IN ('awaiting_login', 'ready', 'claimed'))",
    'state_sha256 TEXT NOT NULL CHECK (length(state_sha256) = 64)'
  ]) {
    assert.ok(migration.includes(fragment), fragment);
  }

  for (const fragment of [
    'lovetree_login_handoffs',
    "status='ready'",
    "status='claimed'",
    'AND state_sha256=?',
    'expires_at > ?',
    'RETURNING',
    LOVETREE_PRODUCT_ID,
    LOVETREE_HANDOFF_RECIPIENT
  ]) {
    assert.ok(store.includes(fragment), fragment);
  }
});

