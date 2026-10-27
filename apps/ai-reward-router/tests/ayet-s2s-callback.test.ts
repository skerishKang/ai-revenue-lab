import test from 'node:test';
import assert from 'node:assert/strict';
import { createConsumerHttpHandler } from '../src/http/consumer-http.js';
import { D1B64MemberStore } from '../src/identity/member-store.js';
import { D1UserIncomeRepository } from '../src/income-pipeline/d1-user-income-repository.js';
import { newB64MemberId } from '../src/identity/session.js';
import { mintB64RewardSubject, readB64RewardSubject } from '../src/identity/reward-subject.js';
import { expectedAyetS2SSecurityHash, type AyetS2SParameters } from '../src/ad-click-first/ayet-s2s-postback.js';
import {
  AYET_S2S_CALLBACK_PATH,
  AYET_S2S_SECURITY_HASH_HEADER,
} from '../src/ad-click-first/ayet-callback.js';
import {
  buildStoredRewardEvent,
  D1RewardEventStore,
  UnboundRewardEventStore,
} from '../src/ad-click-first/reward-event-store.js';
import { applyProviderRewardEvent, type RewardStateRecord } from '../src/ad-click-first/reward-events.js';
import { createSqliteD1Binding, readAllMigrationsSql } from './d1-binding-helper.js';
import { TEST_ORIGIN, TEST_SESSION_SECRET } from './helpers/b64-identity-harness.js';

/**
 * The ayeT server-to-server reward postback, end to end through the real HTTP
 * handler and a real SQLite D1 binding (#987).
 *
 * The signature and the state rules were already reviewed pure functions; what
 * these tests cover is the connection: the header the provider actually sends
 * the signature in, the signed subject that resolves a callback to one member,
 * the provider transaction key that makes a retry harmless, and the fact that
 * none of this touches an income record or a balance.
 */

const PUBLISHER_API_KEY = 'ayet-test-publisher-api-key';
const PROVIDER_ID = 'SRC-AYET';

interface Harness {
  readonly handler: (request: Request) => Promise<Response>;
  readonly events: D1RewardEventStore;
  readonly income: D1UserIncomeRepository;
  readonly binding: ReturnType<typeof createSqliteD1Binding>['binding'];
}

function createCallbackHarness(overrides: Record<string, unknown> = {}): Harness {
  const { binding } = createSqliteD1Binding();
  const events = new D1RewardEventStore(binding);
  const income = new D1UserIncomeRepository(binding);
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [],
    loadPublicOpportunities: () => [],
    memberStore: new D1B64MemberStore(binding),
    sessionSecret: TEST_SESSION_SECRET,
    incomeRepository: income,
    expectedBrowserOrigin: TEST_ORIGIN,
    rewardEvents: events,
    ayetMode: 'CONFIGURED',
    ayetPublisherApiKey: PUBLISHER_API_KEY,
    ...overrides,
  });
  return { handler, events, income, binding };
}

async function subjectFor(memberId: string): Promise<string> {
  return mintB64RewardSubject({ signingSecret: TEST_SESSION_SECRET, memberId });
}

function conversionParams(subject: string, transactionId: string, amount = '100'): AyetS2SParameters {
  return Object.freeze({
    callback_type: 'conversion',
    currency_amount: amount,
    currency_identifier: 'KRW_POINTS',
    external_identifier: subject,
    is_chargeback: '0',
    transaction_id: transactionId,
  });
}

function chargebackParams(subject: string, transactionId: string): AyetS2SParameters {
  return Object.freeze({
    callback_type: 'chargeback',
    currency_amount: '-100',
    currency_identifier: 'KRW_POINTS',
    external_identifier: subject,
    is_chargeback: '1',
    transaction_id: `r-${transactionId}`,
  });
}

/** Mirrors the provider: signature in the header, every field in the query. */
async function postback(
  handler: (request: Request) => Promise<Response>,
  parameters: AyetS2SParameters,
  securityHash: string | null,
): Promise<Response> {
  const query = new URLSearchParams(
    Object.entries(parameters).map(([key, value]) => [key, String(value)]),
  );
  // The provider also appends security_hash to the URL; it must not leak into
  // the canonical string the signature is computed over.
  if (securityHash !== null) query.set('security_hash', securityHash);
  const headers: Record<string, string> = {};
  if (securityHash !== null) headers[AYET_S2S_SECURITY_HASH_HEADER] = securityHash;
  return handler(new Request(`${TEST_ORIGIN}${AYET_S2S_CALLBACK_PATH}?${query.toString()}`, { headers }));
}

function signed(parameters: AyetS2SParameters): string {
  return expectedAyetS2SSecurityHash(parameters, PUBLISHER_API_KEY);
}

/* --------------------------------- the subject -------------------------------- */

test('the reward subject is B64-signed, member-bound and fits the provider limit', async () => {
  const memberId = newB64MemberId();
  const subject = await subjectFor(memberId);
  assert.ok(subject.length <= 128, `provider caps externalIdentifier at 128, got ${subject.length}`);
  assert.equal(await readB64RewardSubject(subject, TEST_SESSION_SECRET), memberId);
  assert.equal(await readB64RewardSubject(subject, 'another-products-own-secret-0123456789'), null,
    'a subject signed elsewhere resolves to nobody');
  assert.equal(await readB64RewardSubject('not-a-subject-at-all', TEST_SESSION_SECRET), null);
  const notMine = await mintB64RewardSubject({ signingSecret: TEST_SESSION_SECRET, memberId: newB64MemberId() });
  assert.equal(await readB64RewardSubject(`${notMine.slice(0, -4)}aaaa`, TEST_SESSION_SECRET), null,
    'a tampered subject fails the signature');
});

/* -------------------------------- the callback -------------------------------- */

test('a signed conversion postback stores one confirmed event for its member', async () => {
  const { handler, events } = createCallbackHarness();
  const memberId = newB64MemberId();
  const subject = await subjectFor(memberId);
  const parameters = conversionParams(subject, 'tx-1001');

  const response = await postback(handler, parameters, signed(parameters));
  assert.equal(response.status, 200);
  assert.equal(await response.text(), 'OK');

  const stored = await events.load(PROVIDER_ID, 'tx-1001');
  assert.ok(stored);
  assert.equal(stored!.memberId, memberId, 'the row belongs to the member the subject names');
  assert.equal(stored!.state, 'CONFIRMED');
  assert.equal(stored!.amount, 100);
  assert.equal(stored!.unit, 'KRW_POINTS');
  assert.equal(stored!.cashCustodyAction, 'NONE');
  assert.ok(stored!.confirmedAt, 'the confirmation time is recorded');
  assert.equal(stored!.reversedAt, null);
});

test('a retried postback for the same provider transaction credits nothing twice', async () => {
  const { handler, events, binding } = createCallbackHarness();
  const subject = await subjectFor(newB64MemberId());
  const parameters = conversionParams(subject, 'tx-retry');

  assert.equal((await postback(handler, parameters, signed(parameters))).status, 200);
  const second = await postback(handler, parameters, signed(parameters));
  assert.equal(second.status, 200, 'an idempotent duplicate is acknowledged, not an error');
  await second.text();

  const rows = await binding.prepare('SELECT COUNT(*) AS n FROM b64_reward_event').first<{ n: number }>();
  assert.equal(rows!.n, 1, 'one provider transaction is one row');
  assert.equal((await events.listForMember((await events.load(PROVIDER_ID, 'tx-retry'))!.memberId)).length, 1);
});

test('a confirmed postback advances a provisional event and records the time', async () => {
  const { handler, events } = createCallbackHarness();
  const memberId = newB64MemberId();
  const subject = await subjectFor(memberId);
  const provisional: RewardStateRecord = Object.freeze({
    providerId: PROVIDER_ID,
    providerTransactionId: 'tx-pending',
    externalUserId: subject,
    amount: 55,
    unit: 'KRW_POINTS',
    state: 'PENDING_PROVIDER_CONFIRMATION',
    firstObservedAt: '2026-10-27T00:00:00.000Z',
    lastObservedAt: '2026-10-27T00:00:00.000Z',
    cashCustodyAction: 'NONE',
  });
  await events.insert(buildStoredRewardEvent(provisional, memberId));

  const parameters = Object.freeze({ ...conversionParams(subject, 'tx-pending'), currency_amount: '55' });
  assert.equal((await postback(handler, parameters, signed(parameters))).status, 200);

  const stored = await events.load(PROVIDER_ID, 'tx-pending');
  assert.equal(stored!.state, 'CONFIRMED');
  assert.ok(stored!.confirmedAt && stored!.confirmedAt > provisional.firstObservedAt);
  assert.equal(stored!.firstObservedAt, provisional.firstObservedAt, 'the original observation is kept');
});

test('a chargeback reverses the event it names and stamps the reversal', async () => {
  const { handler, events } = createCallbackHarness();
  const subject = await subjectFor(newB64MemberId());
  const conversion = conversionParams(subject, 'tx-rev');
  await postback(handler, conversion, signed(conversion)).then((r) => r.text());

  const chargeback = chargebackParams(subject, 'tx-rev');
  assert.equal((await postback(handler, chargeback, signed(chargeback))).status, 200);

  const stored = await events.load(PROVIDER_ID, 'tx-rev');
  assert.equal(stored!.state, 'REVERSED');
  assert.ok(stored!.reversedAt, 'the cancellation time is recorded');
});

test('a reversal with no matching conversion is refused and stores nothing', async () => {
  const { handler, events, binding } = createCallbackHarness();
  const subject = await subjectFor(newB64MemberId());
  const parameters = chargebackParams(subject, 'tx-never');
  const response = await postback(handler, parameters, signed(parameters));
  assert.equal(response.status, 409);
  assert.equal(await events.load(PROVIDER_ID, 'tx-never'), null);
  const rows = await binding.prepare('SELECT COUNT(*) AS n FROM b64_reward_event').first<{ n: number }>();
  assert.equal(rows!.n, 0, 'an orphan reversal never creates a row');
});

/* ------------------------------ forgery and refusal ---------------------------- */

test('an unsigned or wrongly signed callback is refused before anything is read', async () => {
  const { handler, events, binding } = createCallbackHarness();
  const subject = await subjectFor(newB64MemberId());
  const parameters = conversionParams(subject, 'tx-forged');

  const missing = await postback(handler, parameters, null);
  assert.equal(missing.status, 403, 'the provider hash is optional upstream and mandatory here');
  await missing.text();

  const wrong = await postback(handler, parameters, signed({ ...parameters, currency_amount: '999999' }));
  assert.equal(wrong.status, 403);
  await wrong.text();

  const notHex = await postback(handler, parameters, 'zzzz');
  assert.equal(notHex.status, 403);
  await notHex.text();

  assert.equal(await events.load(PROVIDER_ID, 'tx-forged'), null);
  const rows = await binding.prepare('SELECT COUNT(*) AS n FROM b64_reward_event').first<{ n: number }>();
  assert.equal(rows!.n, 0);
});

test('a callback naming a subject this Worker never signed is refused', async () => {
  const { handler } = createCallbackHarness();
  const foreign = await mintB64RewardSubject({
    signingSecret: 'another-products-own-secret-0123456789',
    memberId: newB64MemberId(),
  });
  const parameters = conversionParams(foreign, 'tx-foreign');
  const response = await postback(handler, parameters, signed(parameters));
  assert.equal(response.status, 403, 'a well-signed provider request still needs a B64 subject');
  assert.ok((await response.text()) === '');
});

test('one provider transaction cannot be re-pointed at another member', async () => {
  const { handler, events } = createCallbackHarness();
  const ownerA = newB64MemberId();
  const intruderB = newB64MemberId();
  const subjectA = await subjectFor(ownerA);
  const subjectB = await subjectFor(intruderB);

  const first = conversionParams(subjectA, 'tx-steal');
  assert.equal((await postback(handler, first, signed(first))).status, 200);

  const replay = conversionParams(subjectB, 'tx-steal');
  const response = await postback(handler, replay, signed(replay));
  assert.equal(response.status, 409, 'the same transaction for a different member is a review case');
  await response.text();

  const stored = await events.load(PROVIDER_ID, 'tx-steal');
  assert.equal(stored!.memberId, ownerA, 'the row keeps its original owner');
  assert.equal((await events.listForMember(intruderB)).length, 0, 'the intruder gains nothing');
});

test('a changed amount on an existing transaction does not silently rewrite the record', async () => {
  const { handler, events } = createCallbackHarness();
  const subject = await subjectFor(newB64MemberId());
  const first = conversionParams(subject, 'tx-value');
  await postback(handler, first, signed(first)).then((r) => r.text());

  const inflated = conversionParams(subject, 'tx-value', '5000');
  const response = await postback(handler, inflated, signed(inflated));
  assert.equal(response.status, 409);
  await response.text();
  assert.equal((await events.load(PROVIDER_ID, 'tx-value'))!.amount, 100);
});

/* -------------------------------- fail closed --------------------------------- */

test('the callback is closed until the provider is configured, and the site still answers', async () => {
  const disabled = createCallbackHarness({ ayetMode: 'DISABLED' });
  const subject = await subjectFor(newB64MemberId());
  const parameters = conversionParams(subject, 'tx-disabled');
  const response = await postback(disabled.handler, parameters, signed(parameters));
  assert.equal(response.status, 503);
  assert.equal(await response.text(), '');

  const noKey = createCallbackHarness({ ayetPublisherApiKey: undefined });
  assert.equal((await postback(noKey.handler, parameters, signed(parameters))).status, 503);

  const pipeline = await (await disabled.handler(new Request(`${TEST_ORIGIN}/pipeline`))).text();
  assert.ok(pipeline.includes('action="/join"'), 'a disabled provider must not break the consumer site');
});

test('without the D1 binding the callback is refused rather than answered OK', async () => {
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [],
    sessionSecret: TEST_SESSION_SECRET,
    expectedBrowserOrigin: TEST_ORIGIN,
    ayetMode: 'LIVE_AUTHORIZED',
    ayetPublisherApiKey: PUBLISHER_API_KEY,
  });
  const subject = await subjectFor(newB64MemberId());
  const parameters = conversionParams(subject, 'tx-nostore');
  const response = await postback(handler, parameters, signed(parameters));
  assert.equal(response.status, 503);
});

test('the callback is a GET route and keeps the consumer CSP', async () => {
  const { handler } = createCallbackHarness();
  const post = await handler(new Request(`${TEST_ORIGIN}${AYET_S2S_CALLBACK_PATH}`, { method: 'POST' }));
  assert.equal(post.status, 405);

  const subject = await subjectFor(newB64MemberId());
  const parameters = conversionParams(subject, 'tx-csp');
  const response = await postback(handler, parameters, signed(parameters));
  assert.match(response.headers.get('content-security-policy')!, /script-src 'none'/);
  assert.equal(response.headers.get('cache-control'), 'no-store');
});

/* ------------------------- the honesty boundary and schema -------------------- */

test('a confirmed provider reward never becomes income or a payable balance', async () => {
  const { handler, income } = createCallbackHarness();
  const memberId = newB64MemberId();
  const subject = await subjectFor(memberId);
  const parameters = conversionParams(subject, 'tx-money');
  await postback(handler, parameters, signed(parameters)).then((r) => r.text());

  assert.equal((await income.getByUser(memberId)).length, 0,
    'provider reporting is not a B64 income record and not money');
});

test('0004 is additive and replay-safe next to the live schema', () => {
  const { db } = createSqliteD1Binding();
  db.exec(readAllMigrationsSql());
  db.exec(readAllMigrationsSql());
  const tables = (db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all() as Array<{ name: string }>)
    .map((row) => row.name);
  for (const expected of ['b64_user_income', 'b64_member', 'b64_session', 'b64_member_google', 'b64_reward_event']) {
    assert.ok(tables.includes(expected), `${expected} survives a replayed migration set`);
  }
  const indexes = db.prepare("PRAGMA index_list('b64_reward_event')").all() as Array<{ name: string; unique: number }>;
  assert.ok(indexes.some((row) => row.name === 'idx_b64_reward_event_member'), 'member reads are indexed');
});

test('the store refuses a row that is not linked to a B64 member', async () => {
  const { binding } = createSqliteD1Binding();
  const store = new UnboundRewardEventStore('B64_INCOME_DB');
  await assert.rejects(store.load(PROVIDER_ID, 'x'), /not configured/);
  const subject = await subjectFor(newB64MemberId());
  const transition = applyProviderRewardEvent(null, {
    providerId: PROVIDER_ID,
    providerTransactionId: 'tx-bad',
    externalUserId: subject,
    eventType: 'CONFIRMED',
    amount: 10,
    unit: 'KRW_POINTS',
    observedAt: '2026-10-28T00:00:00.000Z',
  });
  const record = buildStoredRewardEvent(transition.next!, 'pm_chat_user_1');
  await assert.rejects(
    new D1RewardEventStore(binding).insert(record),
    /linked to a B64 member/,
    'a PADIEM Chat user id cannot name a B64 reward row',
  );
});
