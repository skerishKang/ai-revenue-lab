import test from 'node:test';
import assert from 'node:assert/strict';
import { createConsumerHttpHandler } from '../src/http/consumer-http.js';
import { createB64AuthResolver } from '../src/identity/auth.js';
import { D1B64MemberStore, UnboundB64MemberStore } from '../src/identity/member-store.js';
import { D1UserIncomeRepository } from '../src/income-pipeline/d1-user-income-repository.js';
import {
  createIdentityHarness,
  getWithCookie,
  joinMember,
  postForm,
  rawSessionCookie,
  sessionCookieOf,
  TEST_ORIGIN,
  TEST_SESSION_SECRET,
} from './helpers/b64-identity-harness.js';

/**
 * B64's own authentication boundary (#987, owner decision 2026-10-27): B64
 * members are created, signed in and signed out here, with no PADIEM Chat
 * account and no other product's Worker in the path. Everything the resolver
 * cannot positively confirm fails closed.
 */

const SAVE = { action: 'save', title: 'Prolific 리서치', vendor: 'Prolific', status: 'SAVED' };

test('join creates a member, opens a session and refuses a second account for the same address', async () => {
  const { handler, members } = createIdentityHarness();
  const first = await handler(postForm('/join', { email: 'Member@Example.com', password: 'correct horse battery' }));
  assert.equal(first.status, 303);
  assert.equal(first.headers.get('location'), '/pipeline');
  const cookie = sessionCookieOf(first);
  assert.match(cookie, /^b64_session=/);

  const stored = await members.findByEmail('member@example.com');
  assert.ok(stored, 'the address is stored normalized');
  assert.ok(stored!.passwordHash.startsWith('pbkdf2_sha512$100000$'), 'the reviewed KDF shape is stored at the platform cost');
  assert.ok(!stored!.passwordHash.includes('correct horse battery'), 'the password itself is never stored');

  const duplicate = await handler(postForm('/join', { email: 'member@example.com', password: 'another password 12' }));
  assert.equal(duplicate.status, 409);
  assert.equal((await duplicate.json() as { error: string }).error, 'member_exists');
});

test('join rejects malformed input before touching storage', async () => {
  const { handler } = createIdentityHarness();
  const cases: readonly [Record<string, string>, string][] = [
    [{ email: 'not-an-email', password: 'longenoughpassword' }, 'invalid_email'],
    [{ email: 'ok@example.com', password: 'short' }, 'invalid_password'],
  ];
  for (const [form, code] of cases) {
    const response = await handler(postForm('/join', form));
    assert.equal(response.status, 400, JSON.stringify(form));
    assert.equal((await response.json() as { error: string }).error, code);
  }
});

test('login opens a session for the right password and 401s for the wrong one or an unknown address', async () => {
  const { handler } = createIdentityHarness();
  await joinMember(handler, 'signin@example.com', 'correct horse battery');

  const wrong = await handler(postForm('/login', { email: 'signin@example.com', password: 'wrong password here' }));
  assert.equal(wrong.status, 401);
  assert.equal((await wrong.json() as { error: string }).error, 'invalid_credentials');

  const unknown = await handler(postForm('/login', { email: 'nobody@example.com', password: 'wrong password here' }));
  assert.equal(unknown.status, 401, 'an unregistered address answers the same way');

  const ok = await handler(postForm('/login', { email: 'signin@example.com', password: 'correct horse battery' }));
  assert.equal(ok.status, 303);
  const cookie = sessionCookieOf(ok);
  const page = await handler(getWithCookie('/pipeline', cookie));
  assert.match(await page.text(), /로그아웃/);
});

test('a signed cookie is not enough without its live session row', async () => {
  const { handler } = createIdentityHarness();
  // Well-formed and correctly signed, but no b64_session row was ever created
  // for it: the signature proves who issued the token, not that it is live.
  const forged = await rawSessionCookie();
  const save = await handler(postForm('/pipeline', SAVE, forged.cookie));
  assert.equal(save.status, 401, 'a token with no session row cannot write');
  const page = await handler(getWithCookie('/pipeline', forged.cookie));
  assert.match(await page.text(), /B64 계정으로 이용할 수 있습니다/, 'and cannot read a dashboard');
});

test('logout revokes the session row so the same cookie stops working', async () => {
  const { handler } = createIdentityHarness();
  const cookie = await joinMember(handler, 'logout@example.com', 'correct horse battery');
  const before = await handler(postForm('/pipeline', { ...SAVE, title: 'Before logout' }, cookie));
  assert.equal(before.status, 303);

  const out = await handler(postForm('/logout', {}, cookie));
  assert.equal(out.status, 303);
  assert.match(out.headers.get('set-cookie') ?? '', /b64_session=;|Max-Age=0/, 'the cookie is cleared');

  const after = await handler(postForm('/pipeline', { ...SAVE, title: 'After logout' }, cookie));
  assert.equal(after.status, 401, 'a replayed cookie whose row is revoked is refused');
  const page = await handler(getWithCookie('/pipeline', cookie));
  assert.match(await page.text(), /B64 계정으로 이용할 수 있습니다/);
});

test('expired tokens and foreign signing keys are refused', async () => {
  const { handler } = createIdentityHarness();
  const expired = await rawSessionCookie({ expiresInSeconds: -60 });
  assert.equal((await handler(getWithCookie('/pipeline', expired.cookie))).status, 200);
  const expiredPage = await handler(getWithCookie('/pipeline', expired.cookie));
  assert.match(await expiredPage.text(), /B64 계정으로 이용할 수 있습니다/);

  const foreign = await rawSessionCookie({ secret: 'a-completely-different-secret-0123456789' });
  const foreignPage = await handler(getWithCookie('/pipeline', foreign.cookie));
  assert.match(await foreignPage.text(), /B64 계정으로 이용할 수 있습니다/, 'a token signed elsewhere is not B64 identity');
});

test('identity mutations require the reviewed origin', async () => {
  const { handler } = createIdentityHarness();
  const crossSite = new Request(`${TEST_ORIGIN}/join`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded', origin: 'https://evil.example' },
    body: new URLSearchParams({ email: 'evil@example.com', password: 'longenoughpassword' }).toString(),
  });
  const rejected = await handler(crossSite);
  assert.equal(rejected.status, 403);
  assert.equal((await rejected.json() as { error: string }).error, 'origin_rejected');

  const noOrigin = new Request(`${TEST_ORIGIN}/login`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ email: 'a@example.com', password: 'longenoughpassword' }).toString(),
  });
  assert.equal((await handler(noOrigin)).status, 403, 'a missing Origin is denied, not assumed');

  const unconfigured = createConsumerHttpHandler({
    loadCandidates: () => [],
    memberStore: new D1B64MemberStore(createIdentityHarness().binding),
    sessionSecret: TEST_SESSION_SECRET,
  });
  const denied = await unconfigured(postForm('/join', { email: 'x@example.com', password: 'longenoughpassword' }));
  assert.equal(denied.status, 503, 'no reviewed origin means no answer other than fail closed');
});

test('without the account store the endpoints refuse instead of faking accounts', async () => {
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [],
    resolveAuth: createB64AuthResolver({ sessionSecret: TEST_SESSION_SECRET, members: new UnboundB64MemberStore('B64_INCOME_DB') }),
    memberStore: new UnboundB64MemberStore('B64_INCOME_DB'),
    sessionSecret: TEST_SESSION_SECRET,
    expectedBrowserOrigin: TEST_ORIGIN,
  });
  const join = await handler(postForm('/join', { email: 'nodb@example.com', password: 'longenoughpassword' }));
  assert.equal(join.status, 503);
  assert.equal((await join.json() as { error: string }).error, 'storage_unavailable');

  const noSecret = createConsumerHttpHandler({
    loadCandidates: () => [],
    memberStore: new D1B64MemberStore(createIdentityHarness().binding),
    expectedBrowserOrigin: TEST_ORIGIN,
  });
  const unavailable = await noSecret(postForm('/join', { email: 'nodb@example.com', password: 'longenoughpassword' }));
  assert.equal(unavailable.status, 503);
  assert.equal((await unavailable.json() as { error: string }).error, 'identity_unavailable');
});

test('a mid-request income storage failure answers 503, never a false 303', async () => {
  const { handler, binding } = createIdentityHarness();
  const cookie = await joinMember(handler, 'flaky@example.com', 'long enough password');
  const members = new D1B64MemberStore(binding);
  let failNext = false;
  const flaky = {
    prepare(sql: string) {
      if (failNext) throw new Error('d1 connection reset');
      return binding.prepare(sql);
    },
  };
  // Identity stays available; only the income write fails, which is the case
  // that used to be able to answer 303 while nothing was stored.
  const rewired = createConsumerHttpHandler({
    loadCandidates: () => [],
    resolveAuth: createB64AuthResolver({ sessionSecret: TEST_SESSION_SECRET, members }),
    memberStore: members,
    sessionSecret: TEST_SESSION_SECRET,
    incomeRepository: new D1UserIncomeRepository(flaky),
    expectedBrowserOrigin: TEST_ORIGIN,
  });
  const ok = await rewired(postForm('/pipeline', { action: 'save', title: 'Before failure', vendor: 'V', status: 'SAVED' }, cookie));
  assert.equal(ok.status, 303);
  failNext = true;
  const failed = await rewired(postForm('/pipeline', { action: 'delete', recordId: 'nonexistent' }, cookie));
  assert.equal(failed.status, 503, 'a storage failure is never reported as a completed write');
  assert.equal((await failed.json() as { error: string }).error, 'storage_unavailable');
});

test('members cannot read or write each other records', async () => {
  const { handler } = createIdentityHarness();
  const memberA = await joinMember(handler, 'a-records@example.com', 'correct horse battery');
  const memberB = await joinMember(handler, 'b-records@example.com', 'correct horse battery');

  const saved = await handler(postForm('/pipeline', { ...SAVE, title: 'A private record' }, memberA));
  assert.equal(saved.status, 303);

  const pageB = await handler(getWithCookie('/pipeline', memberB));
  const htmlB = await pageB.text();
  assert.ok(!htmlB.includes('A private record'), 'member B never sees member A record');
  assert.match(htmlB, /아직 추적 중인 기회가 없습니다/);

  const pageA = await handler(getWithCookie('/pipeline', memberA));
  assert.match(await pageA.text(), /A private record/);
});

test('knowing another member id does not let a client become them', async () => {
  const { handler, members } = createIdentityHarness();
  const victimCookie = await joinMember(handler, 'victim@example.com', 'correct horse battery');
  const victim = await members.findByEmail('victim@example.com');
  assert.ok(victim);
  await handler(postForm('/pipeline', { ...SAVE, title: 'Victor record' }, victimCookie));

  // The attacker signs a token for the victim's member id with their own fresh
  // session id. The signature is valid — B64 minted nothing like it, but even a
  // correctly signed token resolves to nobody without its own session row.
  const impersonation = await rawSessionCookie({ memberId: victim!.id });
  const page = await handler(getWithCookie('/pipeline', impersonation.cookie));
  assert.match(await page.text(), /B64 계정으로 이용할 수 있습니다/, 'no dashboard for an unbacked token');
  const write = await handler(postForm('/pipeline', { ...SAVE, title: 'Injected' }, impersonation.cookie));
  assert.equal(write.status, 401);

  // And the victim data is still only theirs.
  const victimPage = await handler(getWithCookie('/pipeline', victimCookie));
  assert.match(await victimPage.text(), /Victor record/);
});
