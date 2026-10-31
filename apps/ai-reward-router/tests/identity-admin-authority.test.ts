import test from 'node:test';
import assert from 'node:assert/strict';
import { createConsumerHttpHandler } from '../src/http/consumer-http.js';
import { createB64AuthResolver } from '../src/identity/auth.js';
import { isB64SuperAdmin } from '../src/identity/admin.js';
import {
  D1B64MemberStore,
  UnboundB64MemberStore,
  type B64MemberStore,
} from '../src/identity/member-store.js';
import { D1UserIncomeRepository } from '../src/income-pipeline/d1-user-income-repository.js';
import {
  B64_SESSION_COOKIE_NAME,
  mintB64SessionToken,
  newB64MemberId,
  newB64SessionId,
} from '../src/identity/session.js';
import { buildStoredRewardEvent, D1RewardEventStore } from '../src/ad-click-first/reward-event-store.js';
import { readB64OperationsSnapshot } from '../src/ops/operations-snapshot.js';
import { createSqliteD1Binding } from './d1-binding-helper.js';
import { TEST_ORIGIN, TEST_SESSION_SECRET } from './helpers/b64-identity-harness.js';

/**
 * B64's operator authority (#6001).
 *
 * The rule is the repository's existing one, ported from
 * `apps/padiem-chat/app/b66_member_admin.py`: an administrator is the account
 * whose Google-proven address equals the configured administrator address, a
 * password account can never be one, and no client-supplied flag is ever read.
 * What is B64's own is the store it checks against — `b64_member_google` in
 * B64's D1 — so no Chat cookie, Chat user table or Chat secret is in the path.
 */

const ADMIN_ADDRESS = 'operator@example.test';
const SECRET_API_KEY_VALUE = 'ayet-secret-api-key-should-never-render';
const SECRET_SESSION_VALUE = 'session-secret-should-never-render';

interface AdminHarness {
  readonly handler: (request: Request) => Promise<Response>;
  readonly members: D1B64MemberStore;
  readonly events: D1RewardEventStore;
  readonly income: D1UserIncomeRepository;
}

function createAdminHarness(adminEmail: string | undefined = ADMIN_ADDRESS): AdminHarness {
  const { binding } = createSqliteD1Binding();
  const members = new D1B64MemberStore(binding);
  const events = new D1RewardEventStore(binding);
  const income = new D1UserIncomeRepository(binding);
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [],
    loadPublicOpportunities: () => [],
    memberStore: members,
    sessionSecret: TEST_SESSION_SECRET,
    resolveAuth: createB64AuthResolver({ sessionSecret: TEST_SESSION_SECRET, members }),
    incomeRepository: income,
    expectedBrowserOrigin: TEST_ORIGIN,
    rewardEvents: events,
    ayetMode: 'DISABLED',
    ayetPublisherApiKey: SECRET_API_KEY_VALUE,
    adminEmail,
    operationsSnapshot: () => readB64OperationsSnapshot({
      db: binding,
      env: { B64_AYET_MODE: 'DISABLED', B64_AYET_PUBLISHER_API_KEY: SECRET_API_KEY_VALUE },
    }),
  });
  return { handler, members, events, income };
}

/**
 * Signs a member in the way production does: a Google link row plus a live
 * session row, then the cookie that row's token backs.
 */
async function googleSession(store: B64MemberStore, email: string): Promise<{ cookie: string; memberId: string }> {
  const memberId = newB64MemberId();
  const sessionId = newB64SessionId();
  const expiresAtSeconds = Math.floor(Date.now() / 1000) + 3600;
  await store.linkGoogleMember({
    googleSub: `sub-${memberId.slice(4)}`,
    memberId,
    email,
    linkedAt: new Date().toISOString(),
  });
  const token = await mintB64SessionToken({
    sessionSecret: TEST_SESSION_SECRET, memberId, sessionId, expiresAtSeconds,
  });
  await store.createSession({
    id: sessionId,
    memberId,
    expiresAt: new Date(expiresAtSeconds * 1000).toISOString(),
    revokedAt: null,
  });
  return { cookie: `${B64_SESSION_COOKIE_NAME}=${token}`, memberId };
}

function get(path: string, cookie?: string): Request {
  return new Request(`${TEST_ORIGIN}${path}`, cookie ? { headers: { cookie } } : {});
}

/* -------------------------------- the rule --------------------------------- */

test('the administrator is the account Google proved with the configured address', async () => {
  const { handler, members } = createAdminHarness();
  const { cookie } = await googleSession(members, ADMIN_ADDRESS);

  const page = await handler(get('/admin', cookie));
  assert.equal(page.status, 200);
  const html = await page.text();
  assert.ok(html.includes('B64 운영 상태'));
  assert.ok(html.includes('읽기 전용'), 'the console says what it is');

  const status = await handler(get('/admin/status', cookie));
  assert.equal(status.status, 200);
  const snapshot = await status.json() as { storageConnected: boolean; members: number };
  assert.equal(snapshot.storageConnected, true);
  assert.equal(snapshot.members, 0, 'a Google-only member has no password row, and the count says so');
});

test('a password account with the same address is never an administrator', async () => {
  const { handler, members } = createAdminHarness();
  const memberId = newB64MemberId();
  await members.createMember({
    id: memberId,
    email: ADMIN_ADDRESS,
    passwordHash: 'pbkdf2_sha512$220000$cm9sZW1hc3RlcjEyMzQ1Ng==$0kY1oCQx1lQ3rDz3lHq0m1lTQ3rDz3lHq0m1lTQ3rDz3lHq0m1lTQ3rDz3lHq0m1',
    createdAt: new Date().toISOString(),
  });
  const sessionId = newB64SessionId();
  const expiresAtSeconds = Math.floor(Date.now() / 1000) + 3600;
  const token = await mintB64SessionToken({ sessionSecret: TEST_SESSION_SECRET, memberId, sessionId, expiresAtSeconds });
  await members.createSession({ id: sessionId, memberId, expiresAt: new Date(expiresAtSeconds * 1000).toISOString(), revokedAt: null });
  const cookie = `${B64_SESSION_COOKIE_NAME}=${token}`;

  const response = await handler(get('/admin', cookie));
  assert.equal(response.status, 403);
  assert.equal((await response.json() as { error: string }).error, 'admin_forbidden');
  assert.equal(await isB64SuperAdmin({ adminEmail: ADMIN_ADDRESS, members, memberId }), false,
    'the address alone is not authority; the Google proof is');
});

test('the address comparison ignores case and surrounding space, like the reviewed rule', async () => {
  const { members } = createAdminHarness();
  const memberId = newB64MemberId();
  await members.linkGoogleMember({
    googleSub: 'sub-mixed-case',
    memberId,
    email: '  Operator@Example.TEST  ',
    linkedAt: new Date().toISOString(),
  });
  assert.equal(await isB64SuperAdmin({ adminEmail: ADMIN_ADDRESS, members, memberId }), true);
  assert.equal(await isB64SuperAdmin({ adminEmail: `  ${ADMIN_ADDRESS.toUpperCase()} `, members, memberId }), true);
});

test('an unset administrator address means nobody is an administrator', async () => {
  const { handler, members } = createAdminHarness('');
  const { cookie, memberId } = await googleSession(members, ADMIN_ADDRESS);
  assert.equal((await handler(get('/admin', cookie))).status, 403);
  assert.equal(await isB64SuperAdmin({ adminEmail: '', members, memberId }), false);
  assert.equal(await isB64SuperAdmin({ adminEmail: '   ', members, memberId }), false);
});

test('another Google member with another address is denied and learns nothing', async () => {
  const { handler, members } = createAdminHarness();
  await googleSession(members, ADMIN_ADDRESS);
  const { cookie } = await googleSession(members, 'someone.else@example.test');

  const response = await handler(get('/admin', cookie));
  assert.equal(response.status, 403);
  const body = await response.text();
  assert.equal(body.includes('B64 운영 상태'), false);
  assert.equal(body.includes('rewardEvents'), false, 'no operational data on a denial');
});

test('an anonymous request is denied before any authority is consulted', async () => {
  const { handler } = createAdminHarness();
  const response = await handler(get('/admin'));
  assert.equal(response.status, 401);
  assert.equal((await response.json() as { error: string }).error, 'unauthenticated');
});

test('a Chat session cookie grants nothing here', async () => {
  const { handler } = createAdminHarness();
  const response = await handler(get('/admin', 'padiem_session=eyJ2IjoxLCJ1aWQiOiJ1c3JfZmFrZSJ9.bm90dXNl'));
  assert.equal(response.status, 401, 'B64 reads its own cookie and its own store only');
});

test('a storage failure is reported as unavailable, never as a silent denial or grant', async () => {
  const unbound = new UnboundB64MemberStore('B64_INCOME_DB');
  await assert.rejects(
    isB64SuperAdmin({ adminEmail: ADMIN_ADDRESS, members: unbound, memberId: newB64MemberId() }),
    /not configured/,
  );

  const { binding } = createSqliteD1Binding();
  const members = new D1B64MemberStore(binding);
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [],
    memberStore: members,
    sessionSecret: TEST_SESSION_SECRET,
    resolveAuth: createB64AuthResolver({ sessionSecret: TEST_SESSION_SECRET, members }),
    expectedBrowserOrigin: TEST_ORIGIN,
    adminEmail: ADMIN_ADDRESS,
    operationsSnapshot: () => {
      throw new Error('storage down');
    },
  });
  const { cookie } = await googleSession(members, ADMIN_ADDRESS);
  const response = await handler(get('/admin', cookie));
  assert.equal(response.status, 503);
  assert.equal((await response.json() as { error: string }).error, 'admin_unavailable');
});

test('an authority lookup that fails is answered unavailable, not forbidden', async () => {
  const { binding } = createSqliteD1Binding();
  const members = new D1B64MemberStore(binding);
  const { cookie } = await googleSession(members, ADMIN_ADDRESS);
  const failing: B64MemberStore = {
    findLiveSession: (id: string) => members.findLiveSession(id),
    findGoogleLinkByMemberId: async () => {
      throw new Error('storage down');
    },
  } as unknown as B64MemberStore;
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [],
    memberStore: failing,
    sessionSecret: TEST_SESSION_SECRET,
    resolveAuth: createB64AuthResolver({ sessionSecret: TEST_SESSION_SECRET, members }),
    expectedBrowserOrigin: TEST_ORIGIN,
    adminEmail: ADMIN_ADDRESS,
    operationsSnapshot: async () => readB64OperationsSnapshot({ db: binding, env: {} }),
  });
  const response = await handler(get('/admin', cookie));
  assert.equal(response.status, 503, 'a broken check is not a denial the operator would miss');
  assert.equal((await response.json() as { error: string }).error, 'admin_unavailable');
});

test('the console is read-only and keeps the consumer security headers', async () => {
  const { handler, members } = createAdminHarness();
  const { cookie } = await googleSession(members, ADMIN_ADDRESS);
  const post = await handler(new Request(`${TEST_ORIGIN}/admin`, {
    method: 'POST',
    headers: { origin: TEST_ORIGIN, cookie },
    body: '',
  }));
  assert.equal(post.status, 405);

  const page = await handler(get('/admin', cookie));
  assert.match(page.headers.get('content-security-policy')!, /script-src 'none'/);
  assert.equal(page.headers.get('cache-control'), 'no-store');
  assert.equal(page.headers.get('x-frame-options'), 'DENY');
});

test('no credential, address or secret value appears in the console output', async () => {
  const { handler, members } = createAdminHarness();
  const { cookie } = await googleSession(members, ADMIN_ADDRESS);

  const html = await (await handler(get('/admin', cookie))).text();
  const json = await (await handler(get('/admin/status', cookie))).text();
  for (const surface of [html, json]) {
    assert.equal(surface.includes(SECRET_API_KEY_VALUE), false, 'the publisher api key is never rendered');
    assert.equal(surface.includes(SECRET_SESSION_VALUE), false, 'no signing secret is rendered');
    assert.equal(surface.includes(TEST_SESSION_SECRET), false, 'no session secret is rendered');
    assert.equal(surface.includes(ADMIN_ADDRESS), false, 'the administrator address itself is not displayed');
    assert.equal(surface.includes('b64_session='), false, 'no token material is displayed');
  }
  assert.ok(html.includes('누락 설정'), 'settings are reported by name in a column that carries no values');
  assert.equal(html.includes('=' + SECRET_API_KEY_VALUE), false);
});

/* --------------------------- what it actually shows ------------------------ */

test('the snapshot reports the real operational state of each table', async () => {
  const { handler, members, events, income } = createAdminHarness();
  const admin = await googleSession(members, ADMIN_ADDRESS);

  await members.createMember({
    id: newB64MemberId(),
    email: 'member@example.test',
    passwordHash: 'pbkdf2_sha512$220000$c3RvcmVkLXNhbHQtcGFkZGluZzEyMzQ1Ng==$0kY1oCQx1lQ3rDz3lHq0m1lTQ3rDz3lHq0m1lTQ3rDz3lHq0m1lTQ3rDz3lHq0m1',
    createdAt: new Date().toISOString(),
  });
  await income.save({
    id: 'rec-1',
    userId: admin.memberId,
    opportunityId: null,
    externalRef: null,
    sourceType: 'MANUAL',
    title: '수동 기록',
    vendor: 'Prolific',
    status: 'SAVED',
    expectedAmount: null,
    expectedCurrency: null,
    actualAmount: null,
    actualCurrency: null,
    appliedAt: null,
    acceptedAt: null,
    completedAt: null,
    paidAt: null,
    expiresAt: null,
    note: null,
    sourceUrl: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  });
  for (const [transactionId, state] of [['tx-a', 'CONFIRMED'], ['tx-b', 'PENDING_PROVIDER_CONFIRMATION'], ['tx-c', 'REVERSED']] as const) {
    const event = {
      providerId: 'SRC-AYET',
      providerTransactionId: transactionId,
      externalUserId: 'subject',
      amount: 10,
      unit: 'B64_COINS',
      state,
      firstObservedAt: new Date().toISOString(),
      lastObservedAt: new Date().toISOString(),
      cashCustodyAction: 'NONE' as const,
      memberId: admin.memberId,
      confirmedAt: state === 'CONFIRMED' ? new Date().toISOString() : null,
      reversedAt: state === 'REVERSED' ? new Date().toISOString() : null,
    };
    await events.insert(buildStoredRewardEvent(event, admin.memberId));
  }

  const snapshot = await (await handler(get('/admin/status', admin.cookie))).json() as {
    members: number;
    googleLinkedMembers: number;
    liveSessions: number;
    incomeRecords: number;
    rewardEvents: { total: number; pending: number; confirmed: number; reversed: number };
    allProvidersDisabled: boolean;
    providerAssessment: { providers: { AYET: { mode: string } } };
  };
  assert.equal(snapshot.members, 1, 'one password member row');
  assert.equal(snapshot.googleLinkedMembers, 1, 'one Google link');
  assert.equal(snapshot.liveSessions, 1, 'the admin session itself');
  assert.equal(snapshot.incomeRecords, 1);
  assert.deepEqual(snapshot.rewardEvents, { total: 3, pending: 1, confirmed: 1, reversed: 1 });
  assert.equal(snapshot.allProvidersDisabled, true);
  assert.equal(snapshot.providerAssessment.providers.AYET.mode, 'DISABLED');
});

test('operator access does not weaken member isolation', async () => {
  const { handler, members, income } = createAdminHarness();
  const admin = await googleSession(members, ADMIN_ADDRESS);
  const other = await googleSession(members, 'someone.else@example.test');
  await income.save({
    id: 'rec-private',
    userId: other.memberId,
    opportunityId: null,
    externalRef: null,
    sourceType: 'MANUAL',
    title: '남의 수익 기록',
    vendor: 'Prolific',
    status: 'SAVED',
    expectedAmount: null,
    expectedCurrency: null,
    actualAmount: null,
    actualCurrency: null,
    appliedAt: null,
    acceptedAt: null,
    completedAt: null,
    paidAt: null,
    expiresAt: null,
    note: null,
    sourceUrl: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  });

  const adminPage = await (await handler(get('/pipeline', admin.cookie))).text();
  assert.equal(adminPage.includes('남의 수익 기록'), false, 'the operator page is still the member view');
  assert.equal((await income.getByUser(admin.memberId)).length, 0);
  assert.equal((await income.getByUser(other.memberId)).length, 1);

  const denied = await handler(get('/admin', other.cookie));
  assert.equal(denied.status, 403);
});
