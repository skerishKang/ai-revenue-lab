import test from 'node:test';
import assert from 'node:assert/strict';
import { createConsumerHttpHandler } from '../src/http/consumer-http.js';
import { D1B64MemberStore } from '../src/identity/member-store.js';
import { D1UserIncomeRepository } from '../src/income-pipeline/d1-user-income-repository.js';
import { newB64MemberId } from '../src/identity/session.js';
import { mintB64RewardSubject, readB64RewardSubject } from '../src/identity/reward-subject.js';
import {
  expectedAyetS2SSecurityHash,
  normalizeVerifiedAyetS2SRewardPostback,
  type AyetS2SParameters,
} from '../src/ad-click-first/ayet-s2s-postback.js';
import {
  AYET_S2S_CALLBACK_PATH,
  AYET_S2S_SECURITY_HASH_HEADER,
} from '../src/ad-click-first/ayet-callback.js';
import {
  buildStoredRewardEvent,
  D1RewardEventStore,
  UnboundRewardEventStore,
  type RewardEventStore,
  type StoredRewardEvent,
} from '../src/ad-click-first/reward-event-store.js';
import { applyProviderRewardEvent, type RewardStateRecord } from '../src/ad-click-first/reward-events.js';
import { createSqliteD1Binding, readAllMigrationsSql } from './d1-binding-helper.js';
import { TEST_ORIGIN, TEST_SESSION_SECRET } from './helpers/b64-identity-harness.js';

/**
 * The ayeT server-to-server reward postback, end to end through the real HTTP
 * handler and a real SQLite D1 binding (#987).
 *
 * The signature and the state rules were already reviewed pure functions; these
 * tests cover the connection and the provider's own transport contract, taken
 * from docs.ayetstudios.com rather than assumed: the signature arrives in the
 * `X-Ayetstudios-Security-Hash` header, the server must answer HTTP 200 or the
 * postback is resent twelve times over an hour, `{transaction_id}` is the
 * duplicate check, `{adslot_id}` must be validated when one URL serves several
 * adslots, and the rewarded-video macro table has no `callback_type`.
 *
 * Status codes here are transport policy; the row is the reward decision. A
 * refusal that a retry can never fix is acknowledged with 200 and writes
 * nothing, so a forged or misrouted callback cannot burn the provider's retry
 * budget, and a genuinely recoverable one is answered 503 so ayeT resends it.
 */

const PUBLISHER_API_KEY = 'ayet-test-publisher-api-key';
const PROVIDER_ID = 'SRC-AYET';
const ADSLOT_ID = '16';

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

/**
 * The shape ayeT actually sends for a rewarded video: the macros from the
 * rewarded-video callback table, no callback_type.
 */
function conversionParams(subject: string, transactionId: string, amount = '10'): AyetS2SParameters {
  return Object.freeze({
    network: 'ayetstudios',
    transaction_id: transactionId,
    external_identifier: subject,
    currency_amount: amount,
    currency_identifier: 'B64_COINS',
    adslot_id: ADSLOT_ID,
    payout_usd: '0.007',
  });
}

/** The offerwall-style chargeback macros, applied to the same transaction. */
function chargebackParams(subject: string, transactionId: string): AyetS2SParameters {
  return Object.freeze({
    network: 'ayetstudios',
    transaction_id: `r-${transactionId}`,
    external_identifier: subject,
    currency_amount: '-10',
    currency_identifier: 'B64_COINS',
    adslot_id: ADSLOT_ID,
    is_chargeback: '1',
  });
}

function signed(parameters: AyetS2SParameters, style: 'php' | 'urlsearchparams' = 'php'): string {
  return expectedAyetS2SSecurityHash(parameters, PUBLISHER_API_KEY, style);
}

/** The signature goes in the header only; every field goes in the query. */
async function postback(
  handler: (request: Request) => Promise<Response>,
  parameters: AyetS2SParameters,
  securityHash: string | null,
): Promise<Response> {
  const query = new URLSearchParams(
    Object.entries(parameters).map(([key, value]) => [key, String(value)]),
  );
  const headers: Record<string, string> = {};
  if (securityHash !== null) headers[AYET_S2S_SECURITY_HASH_HEADER] = securityHash;
  return handler(new Request(`${TEST_ORIGIN}${AYET_S2S_CALLBACK_PATH}?${query.toString()}`, { headers }));
}

async function rowCount(binding: ReturnType<typeof createSqliteD1Binding>['binding']): Promise<number> {
  const row = await binding.prepare('SELECT COUNT(*) AS n FROM b64_reward_event').first<{ n: number }>();
  return row!.n;
}

/* --------------------------------- the subject -------------------------------- */

test('the reward subject is B64-signed, member-bound and fits the provider limit', async () => {
  const memberId = newB64MemberId();
  const subject = await subjectFor(memberId);
  assert.ok(subject.length <= 128, `the provider caps externalIdentifier at 128, got ${subject.length}`);
  assert.equal(await readB64RewardSubject(subject, TEST_SESSION_SECRET), memberId);
  assert.equal(await readB64RewardSubject(subject, 'another-products-own-secret-0123456789'), null,
    'a subject signed elsewhere resolves to nobody');
  assert.equal(await readB64RewardSubject('not-a-subject-at-all', TEST_SESSION_SECRET), null);
  const other = await subjectFor(newB64MemberId());
  assert.equal(await readB64RewardSubject(`${other.slice(0, -4)}aaaa`, TEST_SESSION_SECRET), null,
    'a tampered subject fails the signature');
});

/* ------------------------- the documented callback shape --------------------- */

test('a rewarded-video callback without callback_type is accepted and stored', async () => {
  const { handler, events } = createCallbackHarness();
  const memberId = newB64MemberId();
  const subject = await subjectFor(memberId);
  const parameters = conversionParams(subject, 'tx-rv');
  assert.equal(stringParamOf(parameters, 'callback_type'), undefined, 'the rewarded-video table lists no callback_type');

  const response = await postback(handler, parameters, signed(parameters));
  assert.equal(response.status, 200);
  assert.equal(await response.text(), 'OK');

  const stored = await events.load(PROVIDER_ID, 'tx-rv');
  assert.ok(stored);
  assert.equal(stored!.memberId, memberId);
  assert.equal(stored!.state, 'CONFIRMED');
  assert.equal(stored!.amount, 10);
  assert.equal(stored!.unit, 'B64_COINS');
});

test('a chargeback carrying only is_chargeback reverses the named transaction', async () => {
  const { handler, events } = createCallbackHarness();
  const subject = await subjectFor(newB64MemberId());
  const conversion = conversionParams(subject, 'tx-cb');
  await postback(handler, conversion, signed(conversion)).then((r) => r.text());

  const chargeback = chargebackParams(subject, 'tx-cb');
  assert.equal((await postback(handler, chargeback, signed(chargeback))).status, 200);

  const stored = await events.load(PROVIDER_ID, 'tx-cb');
  assert.equal(stored!.state, 'REVERSED');
  assert.ok(stored!.reversedAt, 'the cancellation time is recorded');
});

test('a non-reward callback_type ayeT documents for other integrations is not credited', async () => {
  const { handler, binding } = createCallbackHarness();
  const subject = await subjectFor(newB64MemberId());
  for (const type of ['installation', 'optional', 'iap', 'iaa', 'survey']) {
    const parameters = Object.freeze({ ...conversionParams(subject, `tx-${type}`), callback_type: type });
    const response = await postback(handler, parameters, signed(parameters));
    assert.equal(response.status, 200, `${type} is acknowledged so ayeT stops resending it`);
    await response.text();
  }
  assert.equal(await rowCount(binding), 0, 'none of them became a reward');
});

test('the same parameters verify under either canonicalization the docs publish', async () => {
  const { handler, events } = createCallbackHarness();
  const subject = await subjectFor(newB64MemberId());
  // `*` is the one character the PHP and JavaScript recipes disagree on.
  const parameters = Object.freeze({ ...conversionParams(subject, 'tx*star'), currency_identifier: 'B64*COINS' });

  assert.notEqual(signed(parameters, 'php'), signed(parameters, 'urlsearchparams'),
    'the two documented recipes really differ for *');
  assert.equal((await postback(handler, parameters, signed(parameters, 'php'))).status, 200);
  const first = await events.load(PROVIDER_ID, 'tx*star');
  assert.ok(first, 'the PHP reference verifies');

  const otherSubject = await subjectFor(newB64MemberId());
  const second = Object.freeze({ ...parameters, external_identifier: otherSubject, transaction_id: 'tx*star2' });
  assert.equal((await postback(handler, second, signed(second, 'urlsearchparams'))).status, 200);
  assert.ok(await events.load(PROVIDER_ID, 'tx*star2'), 'the JavaScript reference verifies too');

  const forged = Object.freeze({ ...parameters, transaction_id: 'tx*star3' });
  assert.equal((await postback(handler, forged, expectedAyetS2SSecurityHash(forged, 'nope', 'php'))).status, 200);
  assert.equal(await events.load(PROVIDER_ID, 'tx*star3'), null, 'and neither accepts a wrong key');
});

/* ----------------------------- idempotency and state ------------------------- */

test('a retried postback for the same provider transaction credits nothing twice', async () => {
  const { handler, events, binding } = createCallbackHarness();
  const memberId = newB64MemberId();
  const subject = await subjectFor(memberId);
  const parameters = conversionParams(subject, 'tx-retry');

  assert.equal((await postback(handler, parameters, signed(parameters))).status, 200);
  const second = await postback(handler, parameters, signed(parameters));
  assert.equal(second.status, 200, 'a duplicate is acknowledged, not an error worth retrying');
  await second.text();

  assert.equal(await rowCount(binding), 1, 'one provider transaction is one row');
  assert.equal((await events.listForMember(memberId)).length, 1);
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
    unit: 'B64_COINS',
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

/* ------------------------------ refusals: no retry -------------------------- */

test('a missing or wrong signature is acknowledged and stores nothing', async () => {
  const { handler, events, binding } = createCallbackHarness();
  const subject = await subjectFor(newB64MemberId());
  const parameters = conversionParams(subject, 'tx-forged');

  for (const hash of [null, signed({ ...parameters, currency_amount: '999999' }), 'zzzz', '0'.repeat(64)]) {
    const response = await postback(handler, parameters, hash);
    assert.equal(response.status, 200, 'a retry cannot fix a bad signature, so do not burn twelve of them');
    await response.text();
  }
  assert.equal(await events.load(PROVIDER_ID, 'tx-forged'), null);
  assert.equal(await rowCount(binding), 0);
});

test('a callback naming a subject this Worker never signed is acknowledged and refused', async () => {
  const { handler, binding } = createCallbackHarness();
  const foreign = await mintB64RewardSubject({
    signingSecret: 'another-products-own-secret-0123456789',
    memberId: newB64MemberId(),
  });
  const parameters = conversionParams(foreign, 'tx-foreign');
  const response = await postback(handler, parameters, signed(parameters));
  assert.equal(response.status, 200);
  assert.equal(await response.text(), 'OK');
  assert.equal(await rowCount(binding), 0, 'a well-signed provider request still needs a B64 subject');
});

test('one provider transaction cannot be re-pointed at another member', async () => {
  const { handler, events } = createCallbackHarness();
  const ownerA = newB64MemberId();
  const intruderB = newB64MemberId();
  const first = conversionParams(await subjectFor(ownerA), 'tx-steal');
  assert.equal((await postback(handler, first, signed(first))).status, 200);

  const replay = conversionParams(await subjectFor(intruderB), 'tx-steal');
  const response = await postback(handler, replay, signed(replay));
  assert.equal(response.status, 200, 'permanent: acknowledged, never credited');
  await response.text();

  assert.equal((await events.load(PROVIDER_ID, 'tx-steal'))!.memberId, ownerA, 'the row keeps its owner');
  assert.equal((await events.listForMember(intruderB)).length, 0, 'the intruder gains nothing');
});

test('a changed amount on an existing transaction does not silently rewrite the record', async () => {
  const { handler, events } = createCallbackHarness();
  const subject = await subjectFor(newB64MemberId());
  const first = conversionParams(subject, 'tx-value');
  await postback(handler, first, signed(first)).then((r) => r.text());

  const inflated = conversionParams(subject, 'tx-value', '5000');
  const response = await postback(handler, inflated, signed(inflated));
  assert.equal(response.status, 200);
  await response.text();
  assert.equal((await events.load(PROVIDER_ID, 'tx-value'))!.amount, 10);
});

/* ------------------------- adslot scoping, per the docs ---------------------- */

test('an adslot B64 did not ask for is refused once the adslot is configured', async () => {
  const scoped = createCallbackHarness({ ayetRewardedAdslotId: ADSLOT_ID });
  const subject = await subjectFor(newB64MemberId());

  const other = Object.freeze({ ...conversionParams(subject, 'tx-other-slot'), adslot_id: '99' });
  assert.equal((await postback(scoped.handler, other, signed(other))).status, 200);
  assert.equal(await scoped.events.load(PROVIDER_ID, 'tx-other-slot'), null);

  const missing: AyetS2SParameters = Object.freeze({
    network: 'ayetstudios', transaction_id: 'tx-no-slot', external_identifier: subject,
    currency_amount: '10', currency_identifier: 'B64_COINS', payout_usd: '0.007',
  });
  assert.equal((await postback(scoped.handler, missing, signed(missing))).status, 200);
  assert.equal(await scoped.events.load(PROVIDER_ID, 'tx-no-slot'), null);

  const mine = conversionParams(subject, 'tx-right-slot');
  assert.equal((await postback(scoped.handler, mine, signed(mine))).status, 200);
  assert.ok(await scoped.events.load(PROVIDER_ID, 'tx-right-slot'), 'the configured adslot is accepted');
});

test('with no adslot configured the callback is not gated on it', async () => {
  const { handler, events } = createCallbackHarness();
  const subject = await subjectFor(newB64MemberId());
  const parameters = Object.freeze({ ...conversionParams(subject, 'tx-anyslot'), adslot_id: '77' });
  assert.equal((await postback(handler, parameters, signed(parameters))).status, 200);
  assert.ok(await events.load(PROVIDER_ID, 'tx-anyslot'));
});

/* --------------------------- retryable: answer 503 --------------------------- */

test('a reversal that arrives before its conversion is retried, not dropped', async () => {
  const { handler, binding } = createCallbackHarness();
  const subject = await subjectFor(newB64MemberId());
  const parameters = chargebackParams(subject, 'tx-early');
  const response = await postback(handler, parameters, signed(parameters));
  assert.equal(response.status, 503, 'ayeT resends for an hour, which is the recovery path here');
  assert.equal(await response.text(), '');
  assert.equal(await rowCount(binding), 0);
});

test('the callback stays closed while the provider is unconfigured, and the site answers', async () => {
  const disabled = createCallbackHarness({ ayetMode: 'DISABLED' });
  const subject = await subjectFor(newB64MemberId());
  const parameters = conversionParams(subject, 'tx-disabled');
  assert.equal((await postback(disabled.handler, parameters, signed(parameters))).status, 503);
  assert.equal((await postback(createCallbackHarness({ ayetPublisherApiKey: undefined }).handler, parameters, signed(parameters))).status, 503);

  const pipeline = await (await disabled.handler(new Request(`${TEST_ORIGIN}/pipeline`))).text();
  assert.ok(pipeline.includes('action="/join"'), 'a disabled provider must not break the consumer site');
});

test('without the D1 binding the callback is refused for retry rather than answered OK', async () => {
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [],
    sessionSecret: TEST_SESSION_SECRET,
    expectedBrowserOrigin: TEST_ORIGIN,
    ayetMode: 'LIVE_AUTHORIZED',
    ayetPublisherApiKey: PUBLISHER_API_KEY,
  });
  const subject = await subjectFor(newB64MemberId());
  const parameters = conversionParams(subject, 'tx-nostore');
  assert.equal((await postback(handler, parameters, signed(parameters))).status, 503);
});

/**
 * The two CONFLICT branches are the only thing standing between two postbacks
 * for one provider transaction and two writes. No sequence of real requests
 * reaches them: the second callback reads the row the first one committed and
 * takes the idempotent path. They are reached here by handing a handler the read
 * it would have taken a moment before the other callback committed, against the
 * same binding — which is exactly the interleaving the guard exists for.
 */
function storeThatReads(
  inner: D1RewardEventStore,
  staleRead: () => StoredRewardEvent | null,
): RewardEventStore {
  return {
    load: () => Promise.resolve(staleRead()),
    insert: (record) => inner.insert(record),
    transition: (record, expectedState) => inner.transition(record, expectedState),
    listForMember: (memberId) => inner.listForMember(memberId),
  };
}

function handlerOnTheSameStore(
  binding: ReturnType<typeof createSqliteD1Binding>['binding'],
  rewardEvents: RewardEventStore,
) {
  return createConsumerHttpHandler({
    loadCandidates: () => [],
    loadPublicOpportunities: () => [],
    memberStore: new D1B64MemberStore(binding),
    sessionSecret: TEST_SESSION_SECRET,
    incomeRepository: new D1UserIncomeRepository(binding),
    expectedBrowserOrigin: TEST_ORIGIN,
    rewardEvents,
    ayetMode: 'CONFIGURED',
    ayetPublisherApiKey: PUBLISHER_API_KEY,
  });
}

test('the loser of an insert race is asked to retry and writes no second row', async () => {
  const { handler, events, binding } = createCallbackHarness();
  const memberId = newB64MemberId();
  const subject = await subjectFor(memberId);
  const parameters = conversionParams(subject, 'tx-race-create');
  assert.equal((await postback(handler, parameters, signed(parameters))).status, 200);

  // A second callback that still believes the transaction is unseen.
  const racing = handlerOnTheSameStore(binding, storeThatReads(events, () => null));
  const response = await postback(racing, parameters, signed(parameters));
  assert.equal(response.status, 503, 'CONFLICT on insert is recoverable, so ayeT must be allowed to retry');
  await response.text();
  assert.equal(await rowCount(binding), 1, 'one provider transaction stays one row');
  assert.equal((await events.listForMember(memberId)).length, 1);
});

test('a transition built on a stale read cannot overwrite the newer state', async () => {
  const { handler, events, binding } = createCallbackHarness();
  const memberId = newB64MemberId();
  const subject = await subjectFor(memberId);
  const conversion = conversionParams(subject, 'tx-race-transition');
  assert.equal((await postback(handler, conversion, signed(conversion))).status, 200);

  const confirmed = await events.load(PROVIDER_ID, 'tx-race-transition');
  assert.ok(confirmed, 'the conversion left a row to reverse');

  const reversal = chargebackParams(subject, 'tx-race-transition');
  assert.equal((await postback(handler, reversal, signed(reversal))).status, 200);
  assert.equal((await events.load(PROVIDER_ID, 'tx-race-transition'))?.state, 'REVERSED');

  // The same reversal, decided from the pre-reversal snapshot.
  const racing = handlerOnTheSameStore(binding, storeThatReads(events, () => confirmed));
  const response = await postback(racing, reversal, signed(reversal));
  assert.equal(response.status, 503, 'CONFLICT on transition is a stale write, not a permanent refusal');
  await response.text();
  assert.equal((await events.load(PROVIDER_ID, 'tx-race-transition'))?.state, 'REVERSED',
    'the guarded write left the newer state alone');
  assert.equal(await rowCount(binding), 1);
});

test('the callback is a GET route and keeps the consumer CSP', async () => {
  const { handler } = createCallbackHarness();
  assert.equal((await handler(new Request(`${TEST_ORIGIN}${AYET_S2S_CALLBACK_PATH}`, { method: 'POST' }))).status, 405);

  const subject = await subjectFor(newB64MemberId());
  const parameters = conversionParams(subject, 'tx-csp');
  const response = await postback(handler, parameters, signed(parameters));
  assert.match(response.headers.get('content-security-policy')!, /script-src 'none'/);
  assert.equal(response.headers.get('cache-control'), 'no-store');
});

/* ------------------------- the honesty boundary and schema ------------------- */

test('a confirmed provider reward never becomes income or a payable balance', async () => {
  const { handler, income } = createCallbackHarness();
  const memberId = newB64MemberId();
  const subject = await subjectFor(memberId);
  const parameters = conversionParams(subject, 'tx-money');
  await postback(handler, parameters, signed(parameters)).then((r) => r.text());

  assert.equal((await income.getByUser(memberId)).length, 0,
    "provider reporting is not a B64 income record and not money");
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
  await assert.rejects(new UnboundRewardEventStore('B64_INCOME_DB').load(PROVIDER_ID, 'x'), /not configured/);
  const transition = applyProviderRewardEvent(null, {
    providerId: PROVIDER_ID,
    providerTransactionId: 'tx-bad',
    externalUserId: await subjectFor(newB64MemberId()),
    eventType: 'CONFIRMED',
    amount: 10,
    unit: 'B64_COINS',
    observedAt: '2026-10-28T00:00:00.000Z',
  });
  await assert.rejects(
    new D1RewardEventStore(binding).insert(buildStoredRewardEvent(transition.next!, 'pm_chat_user_1')),
    /linked to a B64 member/,
    'a PADIEM Chat user id cannot name a B64 reward row',
  );
});

test('the normalizer still refuses a chargeback whose explicit type is another integration', () => {
  const result = normalizeVerifiedAyetS2SRewardPostback({
    parameters: Object.freeze({ ...chargebackParams('whatever', 'tx-x'), callback_type: 'survey' }),
    securityHash: '0'.repeat(64),
    publisherApiKey: PUBLISHER_API_KEY,
    observedAt: '2026-10-28T00:00:00.000Z',
  });
  assert.equal(result.accepted, false);
  assert.equal(result.decision, 'REJECT_INVALID_SIGNATURE');
});

function stringParamOf(parameters: AyetS2SParameters, key: string): string | undefined {
  const value = parameters[key];
  return value === undefined ? undefined : String(value);
}
