import test from 'node:test';
import assert from 'node:assert/strict';
import { createConsumerHttpHandler } from '../src/http/consumer-http.js';
import {
  createChatSessionStatusProbe,
  createPadiemSessionAuthResolver,
} from '../src/income-pipeline/padiem-session-auth.js';
import { D1UserIncomeRepository, UnboundUserIncomeRepository, type D1DatabaseLike } from '../src/income-pipeline/d1-user-income-repository.js';
import type { UserIncomeRepository } from '../src/income-pipeline/store.js';
import { createSqliteD1Binding } from './d1-binding-helper.js';
import { mintFixtureTokenSet } from './helpers/padiem-test-tokens.js';
/**
 * Session tokens are minted at RUNTIME, never committed: signed HMAC blobs
 * are credential-like material and secret scanners flag them. The verifier
 * under test is unchanged; tests/padiem-session-auth.test.ts carries the
 * cross-language proof against the REAL B62 authority.
 */
const FIXTURE_SECRET = 'b64-fixture-session-secret-0123456789abcdef';
const ISSUED_AT = 3999999999;
const MAX_AGE = 604800;
const FIXTURES = await mintFixtureTokenSet(FIXTURE_SECRET, ISSUED_AT, MAX_AGE);
const USER_A_TOKEN = FIXTURES.validToken;
const USER_B_TOKEN = FIXTURES.validTokenWithSid;
const EXPIRED_TOKEN = FIXTURES.expiredToken;
const USER_A = 'usr_fixture_user_0001';
const USER_B = 'usr_fixture_user_0002';

const EXPECTED_ORIGIN = 'https://chat.padiem.net';

function buildHandler(incomeRepository: UserIncomeRepository) {
  return createConsumerHttpHandler({
    loadCandidates: () => [],
    resolveAuth: createPadiemSessionAuthResolver({ sessionSecret: FIXTURE_SECRET }),
    incomeRepository,
    expectedBrowserOrigin: EXPECTED_ORIGIN,
  });
}

function saveRequest(userToken: string, body: string, origin = EXPECTED_ORIGIN): Request {
  return new Request(`${EXPECTED_ORIGIN}/pipeline`, {
    method: 'POST',
    headers: {
      cookie: `padiem_session=${userToken}`,
      origin,
      'content-type': 'application/x-www-form-urlencoded',
    },
    body,
  });
}

test('valid PADIEM session cookie authenticates a real save through the D1 repository', async () => {
  const { binding } = createSqliteD1Binding();
  const handler = buildHandler(new D1UserIncomeRepository(binding));
  const save = await handler(
    saveRequest(USER_A_TOKEN, 'action=save&title=PADIEM+session+save&vendor=Prolific&status=SAVED&expectedAmount=25&expectedCurrency=USD'),
  );
  assert.equal(save.status, 303);
  const page = await handler(new Request(`${EXPECTED_ORIGIN}/pipeline`, { headers: { cookie: `padiem_session=${USER_A_TOKEN}` } }));
  const html = await page.text();
  assert.match(html, /PADIEM session save/);
  assert.match(html, /Prolific/);
});

test('unauthenticated pipeline POST is rejected 401 and stores nothing', async () => {
  const { binding } = createSqliteD1Binding();
  const repo = new D1UserIncomeRepository(binding);
  const handler = buildHandler(repo);
  const res = await handler(new Request(`${EXPECTED_ORIGIN}/pipeline`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=Sneaky&vendor=Evil&status=SAVED',
  }));
  assert.equal(res.status, 401);
  assert.equal((await repo.getByUser(USER_A)).length, 0);
});

test('expired or tampered session cookies cannot save or read records', async () => {
  const { binding } = createSqliteD1Binding();
  const repo = new D1UserIncomeRepository(binding);
  const handler = buildHandler(repo);
  const expiredPost = await handler(saveRequest(EXPIRED_TOKEN, 'action=save&title=Expired&vendor=V&status=SAVED'));
  assert.equal(expiredPost.status, 401);
  const tamperedToken = USER_A_TOKEN.slice(0, -2) + (USER_A_TOKEN.endsWith('w') ? 'xx' : 'ww');
  const tamperedPost = await handler(saveRequest(tamperedToken, 'action=save&title=Tampered&vendor=V&status=SAVED'));
  assert.equal(tamperedPost.status, 401);
  const anonymousGet = await handler(new Request(`${EXPECTED_ORIGIN}/pipeline`));
  assert.equal(anonymousGet.status, 200);
  assert.doesNotMatch(await anonymousGet.text(), /Expired|Tampered/);
});

test('forged identity headers and bearer tokens never authenticate', async () => {
  const { binding } = createSqliteD1Binding();
  const repo = new D1UserIncomeRepository(binding);
  const handler = buildHandler(repo);
  const forged = await handler(new Request(`${EXPECTED_ORIGIN}/pipeline`, {
    method: 'POST',
    headers: {
      'content-type': 'application/x-www-form-urlencoded',
      'x-padiem-user-id': USER_A,
      'authorization': `Bearer ${USER_A}`,
      'cf-ray': 'forged',
    },
    body: 'action=save&title=Forged&vendor=V&status=SAVED',
  }));
  assert.equal(forged.status, 401);
  assert.equal((await repo.getByUser(USER_A)).length, 0);
});

test('user B cannot read or delete user A records through the D1 repository', async () => {
  const { binding } = createSqliteD1Binding();
  const repo = new D1UserIncomeRepository(binding);
  const handler = buildHandler(repo);
  await handler(saveRequest(USER_A_TOKEN, 'action=save&title=A+secret+record&vendor=Outlier&status=SAVED'));

  const pageB = await handler(new Request(`${EXPECTED_ORIGIN}/pipeline`, { headers: { cookie: `padiem_session=${USER_B_TOKEN}` } }));
  assert.doesNotMatch(await pageB.text(), /A secret record/);

  // B deletes the only record id they can see from their own (empty) list:
  // deleting A's id through B's session removes nothing of A's.
  await handler(saveRequest(USER_B_TOKEN, 'action=delete&recordId=rec_does-not-matter'));
  const pageA = await handler(new Request(`${EXPECTED_ORIGIN}/pipeline`, { headers: { cookie: `padiem_session=${USER_A_TOKEN}` } }));
  assert.match(await pageA.text(), /A secret record/);
  assert.equal((await repo.getByUser(USER_A)).length, 1);
  assert.equal(await repo.delete(USER_B, 'rec_whatever'), false);
});

test('invalid transition and invalid amounts are rejected before storage', async () => {
  const { binding } = createSqliteD1Binding();
  const repo = new D1UserIncomeRepository(binding);
  const handler = buildHandler(repo);
  const saved = await handler(saveRequest(USER_A_TOKEN, 'action=save&title=Flow&vendor=V&status=SAVED'));
  assert.equal(saved.status, 303);
  const records = await repo.getByUser(USER_A);
  const recordId = records[0]!.id;

  // SAVED -> PAID is not a legal transition.
  const badTransition = await handler(saveRequest(USER_A_TOKEN, `action=save&id=${recordId}&title=Flow&vendor=V&status=PAID&actualAmount=5&actualCurrency=USD`));
  assert.equal(badTransition.status, 400);
  const body = (await badTransition.json()) as { error?: string };
  assert.equal(body.error, 'invalid_transition');

  const negativeAmount = await handler(saveRequest(USER_A_TOKEN, 'action=save&title=Negative&vendor=V&status=SAVED&expectedAmount=-5&expectedCurrency=USD'));
  assert.equal(negativeAmount.status, 400);

  // paidAt on a non-PAID record is invalid.
  const badPaidAt = await handler(saveRequest(USER_A_TOKEN, 'action=save&title=Bad+paidAt&vendor=V&status=SAVED&paidAt=2026-10-25T00:00:00.000Z'));
  assert.equal(badPaidAt.status, 400);

  assert.equal((await repo.getByUser(USER_A)).length, 1, 'rejected writes leave the stored record untouched');
  assert.equal((await repo.getByUser(USER_A))[0]!.status, 'SAVED');
});

test('legal transition SAVED -> APPLIED updates in place and preserves createdAt', async () => {
  const { binding } = createSqliteD1Binding();
  const repo = new D1UserIncomeRepository(binding);
  const handler = buildHandler(repo);
  await handler(saveRequest(USER_A_TOKEN, 'action=save&title=Flow&vendor=V&status=SAVED'));
  const original = (await repo.getByUser(USER_A))[0]!;
  const updated = await handler(saveRequest(USER_A_TOKEN, `action=save&id=${original.id}&title=Flow&vendor=V&status=APPLIED&appliedAt=2026-10-25T11:00:00.000Z`));
  assert.equal(updated.status, 303);
  const after = (await repo.getByUser(USER_A))[0]!;
  assert.equal(after.status, 'APPLIED');
  assert.equal(after.createdAt, original.createdAt);
  assert.equal((await repo.getByUser(USER_A)).length, 1);
});

test('cookie-carrying POSTs require the reviewed same-origin (#3476 policy)', async () => {
  const { binding } = createSqliteD1Binding();
  const handler = buildHandler(new D1UserIncomeRepository(binding));
  const crossOrigin = await handler(saveRequest(USER_A_TOKEN, 'action=save&title=CSRF&vendor=V&status=SAVED', 'https://evil.example'));
  assert.equal(crossOrigin.status, 403);
  assert.equal(((await crossOrigin.json()) as { error: string }).error, 'origin_rejected');

  const noOrigin = await handler(new Request(`${EXPECTED_ORIGIN}/pipeline`, {
    method: 'POST',
    headers: {
      cookie: `padiem_session=${USER_A_TOKEN}`,
      'content-type': 'application/x-www-form-urlencoded',
    },
    body: 'action=save&title=NoOrigin&vendor=V&status=SAVED',
  }));
  assert.equal(noOrigin.status, 403);
  assert.equal(((await noOrigin.json()) as { error: string }).error, 'origin_rejected');
});

test('cookie-carrying POSTs with no reviewed origin configured fail closed with 503', async () => {
  const { binding } = createSqliteD1Binding();
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [],
    resolveAuth: createPadiemSessionAuthResolver({ sessionSecret: FIXTURE_SECRET }),
    incomeRepository: new D1UserIncomeRepository(binding),
    // expectedBrowserOrigin deliberately unconfigured
  });
  const res = await handler(saveRequest(USER_A_TOKEN, 'action=save&title=Unguarded&vendor=V&status=SAVED'));
  assert.equal(res.status, 503);
  assert.equal(((await res.json()) as { error: string }).error, 'origin_guard_unavailable');
});

test('non-cookie POSTs are not CSRF subjects and keep their 401 semantics', async () => {
  const { binding } = createSqliteD1Binding();
  const handler = buildHandler(new D1UserIncomeRepository(binding));
  const res = await handler(new Request(`${EXPECTED_ORIGIN}/pipeline`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded', origin: 'https://evil.example' },
    body: 'action=save&title=NoCookie&vendor=V&status=SAVED',
  }));
  assert.equal(res.status, 401);
});

test('a revoked/logged-out session is blocked when the chat liveness relay is bound', async () => {
  const { binding } = createSqliteD1Binding();
  let sessionLive = false;
  const chatService = {
    async fetch(input: Request) {
      assert.equal(new URL(input.url).pathname, '/api/auth/status');
      assert.ok(input.headers.get('cookie'), 'the relay must forward the cookie header');
      return new Response(
        JSON.stringify({
          ready: true,
          authenticated: sessionLive,
          session_state: sessionLive ? 'signed_in' : 'expired',
        }),
        { status: 200, headers: { 'content-type': 'application/json; charset=utf-8' } },
      );
    },
  };
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [],
    resolveAuth: createPadiemSessionAuthResolver({
      sessionSecret: FIXTURE_SECRET,
      sessionLivenessProbe: createChatSessionStatusProbe({ chatService }),
    }),
    incomeRepository: new D1UserIncomeRepository(binding),
    expectedBrowserOrigin: EXPECTED_ORIGIN,
  });

  // The cookie itself is perfectly signed and unexpired — the canonical
  // authority saying the session is gone must still block access.
  const revokedSave = await handler(saveRequest(USER_A_TOKEN, 'action=save&title=Revoked&vendor=V&status=SAVED'));
  assert.equal(revokedSave.status, 401);
  const revokedRead = await handler(
    new Request(`${EXPECTED_ORIGIN}/pipeline`, { headers: { cookie: `padiem_session=${USER_A_TOKEN}` } }),
  );
  assert.equal(revokedRead.status, 200);
  assert.doesNotMatch(await revokedRead.text(), /Revoked/);
  assert.equal((await new D1UserIncomeRepository(binding).getByUser(USER_A)).length, 0);

  // Once the same session is live again upstream, the very same cookie works.
  sessionLive = true;
  const liveSave = await handler(saveRequest(USER_A_TOKEN, 'action=save&title=Live+again&vendor=V&status=SAVED'));
  assert.equal(liveSave.status, 303);
  assert.equal((await new D1UserIncomeRepository(binding).getByUser(USER_A)).length, 1);
});

test('a failing liveness relay blocks instead of degrading to offline trust', async () => {
  const { binding } = createSqliteD1Binding();
  for (const [label, chatService] of [
    ['upstream 500', { async fetch() { return new Response('boom', { status: 500 }); } }],
    ['upstream network error', { async fetch() { throw new Error('connect refused'); } }],
    ['non-authenticated body', { async fetch() { return new Response(JSON.stringify({ ready: true, authenticated: false, session_state: 'expired' }), { status: 200 }); } }],
    ['auth store not ready', { async fetch() { return new Response(JSON.stringify({ ready: false, authenticated: false }), { status: 200 }); } }],
    ['unparsable body', { async fetch() { return new Response('<html>not json</html>', { status: 200 }); } }],
  ] as const) {
    const handler = createConsumerHttpHandler({
      loadCandidates: () => [],
      resolveAuth: createPadiemSessionAuthResolver({
        sessionSecret: FIXTURE_SECRET,
        sessionLivenessProbe: createChatSessionStatusProbe({ chatService }),
      }),
      incomeRepository: new D1UserIncomeRepository(binding),
      expectedBrowserOrigin: EXPECTED_ORIGIN,
    });
    const save = await handler(saveRequest(USER_A_TOKEN, 'action=save&title=Degraded&vendor=V&status=SAVED'));
    assert.equal(save.status, 401, label);
    assert.equal((await new D1UserIncomeRepository(binding).getByUser(USER_A)).length, 0, label);
  }
});

test('without a bound liveness relay the resolver keeps the offline signature-only posture', async () => {
  const { binding } = createSqliteD1Binding();
  const handler = buildHandler(new D1UserIncomeRepository(binding));
  const save = await handler(saveRequest(USER_A_TOKEN, 'action=save&title=Offline+posture&vendor=V&status=SAVED'));
  assert.equal(save.status, 303, 'offline verification still authenticates a valid signature');
  const expired = await handler(saveRequest(EXPIRED_TOKEN, 'action=save&title=Expired&vendor=V&status=SAVED'));
  assert.equal(expired.status, 401, 'offline verification still rejects an expired signature');
});

test('storage failures answer 503 storage_unavailable instead of silent data loss', async () => {
  const handler = buildHandler(new UnboundUserIncomeRepository('B64_INCOME_DB'));
  const save = await handler(saveRequest(USER_A_TOKEN, 'action=save&title=Lost&vendor=V&status=SAVED'));
  assert.equal(save.status, 503);
  assert.equal(((await save.json()) as { error: string }).error, 'storage_unavailable');
  const read = await handler(new Request(`${EXPECTED_ORIGIN}/pipeline`, { headers: { cookie: `padiem_session=${USER_A_TOKEN}` } }));
  assert.equal(read.status, 503);
  assert.equal(((await read.json()) as { error: string }).error, 'storage_unavailable');
});

test('a mid-request D1 error surfaces as 503, never as a false 303 success', async () => {
  let failNext = false;
  const inner = createSqliteD1Binding();
  const flaky: D1DatabaseLike = {
    prepare(sql: string) {
      if (failNext) throw new Error('d1 connection reset');
      return inner.binding.prepare(sql);
    },
  };
  const handler = buildHandler(new D1UserIncomeRepository(flaky));
  const ok = await handler(saveRequest(USER_A_TOKEN, 'action=save&title=Before+failure&vendor=V&status=SAVED'));
  assert.equal(ok.status, 303);
  failNext = true;
  const failed = await handler(saveRequest(USER_A_TOKEN, 'action=delete&recordId=nonexistent'));
  assert.equal(failed.status, 503);
  failNext = false;
  // The earlier successful write is intact.
  const read = await handler(new Request(`${EXPECTED_ORIGIN}/pipeline`, { headers: { cookie: `padiem_session=${USER_A_TOKEN}` } }));
  assert.match(await read.text(), /Before failure/);
});

test('deployment worker wires the real bindings end to end', async () => {
  const worker = (await import('../src/worker.js')).default;
  const { binding } = createSqliteD1Binding();
  const liveChatService = {
    async fetch(input: Request) {
      assert.equal(new URL(input.url).pathname, '/api/auth/status');
      return new Response(JSON.stringify({ ready: true, authenticated: true, session_state: 'signed_in' }), { status: 200 });
    },
  };
  const revokedChatService = {
    async fetch() {
      return new Response(JSON.stringify({ ready: true, authenticated: false, session_state: 'expired' }), { status: 200 });
    },
  };
  const env = {
    PADIEM_SESSION_SECRET: FIXTURE_SECRET,
    PADIEM_B64_PUBLIC_BASE_URL: EXPECTED_ORIGIN,
    B64_INCOME_DB: binding,
    PADIEM_CHAT_SERVICE: liveChatService,
  };
  const save = await worker.fetch(
    saveRequest(USER_A_TOKEN, 'action=save&title=Worker+env+wiring&vendor=Prolific&status=SAVED'),
    env,
  );
  assert.equal(save.status, 303, 'a live canonical session saves through the wired bindings');
  const page = await worker.fetch(
    new Request(`${EXPECTED_ORIGIN}/pipeline`, { headers: { cookie: `padiem_session=${USER_A_TOKEN}` } }),
    env,
  );
  assert.match(await page.text(), /Worker env wiring/);

  const revoked = await worker.fetch(
    saveRequest(USER_A_TOKEN, 'action=save&title=Revoked&vendor=V&status=SAVED'),
    { ...env, PADIEM_CHAT_SERVICE: revokedChatService },
  );
  assert.equal(revoked.status, 401, 'the wired worker blocks a session the chat authority says is gone');

  const unbound = await worker.fetch(
    saveRequest(USER_A_TOKEN, 'action=save&title=No+DB&vendor=V&status=SAVED'),
    {
      PADIEM_SESSION_SECRET: FIXTURE_SECRET,
      PADIEM_B64_PUBLIC_BASE_URL: EXPECTED_ORIGIN,
      PADIEM_CHAT_SERVICE: liveChatService,
    },
  );
  assert.equal(unbound.status, 503);
  assert.equal(((await unbound.json()) as { error: string }).error, 'storage_unavailable');

  const noSecret = await worker.fetch(
    new Request(`${EXPECTED_ORIGIN}/pipeline`, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: 'action=save&title=No+secret&vendor=V&status=SAVED',
    }),
    { B64_INCOME_DB: binding, PADIEM_CHAT_SERVICE: liveChatService },
  );
  assert.equal(noSecret.status, 401, 'without the session secret no request is authenticated');
});

test("CENTRAL gap: a missing Chat binding blocks even a validly-signed session (no offline fallback on the deployed path)", async () => {
  const worker = (await import('../src/worker.js')).default;
  const { binding } = createSqliteD1Binding();
  // Perfectly signed, unexpired cookie for a session whose canonical liveness
  // CANNOT be confirmed because PADIEM_CHAT_SERVICE is not configured: the
  // deployed path must deny it instead of trusting the signature alone.
  const save = await worker.fetch(
    saveRequest(USER_A_TOKEN, 'action=save&title=No+chat+binding&vendor=V&status=SAVED'),
    {
      PADIEM_SESSION_SECRET: FIXTURE_SECRET,
      PADIEM_B64_PUBLIC_BASE_URL: EXPECTED_ORIGIN,
      B64_INCOME_DB: binding,
      // PADIEM_CHAT_SERVICE deliberately absent
    },
  );
  assert.equal(save.status, 401, 'missing liveness dependency must block authentication');

  const read = await worker.fetch(
    new Request(`${EXPECTED_ORIGIN}/pipeline`, { headers: { cookie: `padiem_session=${USER_A_TOKEN}` } }),
    {
      PADIEM_SESSION_SECRET: FIXTURE_SECRET,
      PADIEM_B64_PUBLIC_BASE_URL: EXPECTED_ORIGIN,
      B64_INCOME_DB: binding,
    },
  );
  assert.equal(read.status, 200);
  const html = await read.text();
  assert.doesNotMatch(html, /usr_fixture_user_0001/, 'the unauthenticated session must see no records');

  const probe = (await import('../src/income-pipeline/padiem-session-auth.js'))
    .createUnconfiguredLivenessProbe('PADIEM_CHAT_SERVICE');
  await assert.rejects(() => probe('padiem_session=whatever'), /not configured/);
});
