import test from 'node:test';
import assert from 'node:assert/strict';
import { createConsumerHttpHandler } from '../src/http/consumer-http.js';
import { createB64AuthResolver } from '../src/identity/auth.js';
import { D1B64MemberStore } from '../src/identity/member-store.js';
import { D1UserIncomeRepository } from '../src/income-pipeline/d1-user-income-repository.js';
import { B64_SESSION_COOKIE_NAME, verifyB64SessionToken } from '../src/identity/session.js';
import { createSqliteD1Binding } from './d1-binding-helper.js';
import {
  TEST_ORIGIN,
  TEST_SESSION_SECRET,
  createIdentityHarness,
  getWithCookie,
} from './helpers/b64-identity-harness.js';

/**
 * The #3476 origin boundary against the request shapes a real browser sends.
 *
 * Live measurement on 2026-10-28 (Chrome 154, deployed Worker): every B64
 * mutation is a top-level HTML form POST, because the consumer surface runs
 * under `script-src 'none'`, and such a request arrives with `Origin: null`
 * plus `Sec-Fetch-Site: same-origin`. The strict compare then answered
 * 403 origin_rejected to the visitor's own Save / Login / Logout button —
 * reproducible only in a browser, never with a tool that sets Origin by hand.
 *
 * These tests hold both halves: the browser's own form POST must work, and
 * every shape that is not actually same-origin must stay denied.
 */

interface BrowserPost {
  readonly path: string;
  readonly form?: Record<string, string>;
  readonly origin?: string | null;
  readonly secFetchSite?: string | null;
  readonly cookie?: string;
  readonly host?: string;
}

function browserPost(input: BrowserPost): Request {
  const headers: Record<string, string> = { 'content-type': 'application/x-www-form-urlencoded' };
  if (input.origin !== undefined && input.origin !== null) headers.origin = input.origin;
  if (input.secFetchSite !== undefined && input.secFetchSite !== null) headers['sec-fetch-site'] = input.secFetchSite;
  if (input.cookie) headers.cookie = input.cookie;
  return new Request(`${input.host ?? TEST_ORIGIN}${input.path}`, {
    method: 'POST',
    headers,
    body: new URLSearchParams(input.form ?? {}).toString(),
  });
}

/** Exactly what Chrome sends when a visitor clicks a B64 form button. */
function topLevelFormPost(input: BrowserPost): Request {
  return browserPost({ origin: 'null', secFetchSite: 'same-origin', ...input });
}

const VALID_JOIN = { email: 'browser@example.com', password: 'correct horse battery' };
const SAVE_FORM = { action: 'save', title: 'Prolific 리서치', vendor: 'Prolific', status: 'SAVED' };

test('a browser top-level form POST creates the member and returns the session cookie', async () => {
  const { handler, members } = createIdentityHarness();
  const response = await handler(topLevelFormPost({ path: '/join', form: VALID_JOIN }));
  assert.equal(response.status, 303, 'the visitor own button must work');
  assert.equal(response.headers.get('location'), '/pipeline');
  const cookie = response.headers.getSetCookie().find((value) => value.startsWith(`${B64_SESSION_COOKIE_NAME}=`));
  assert.ok(cookie, 'a real session cookie came back');
  assert.ok(await members.findByEmail('browser@example.com'), 'the member row was written');
});

test('a browser top-level form POST signs an existing member in', async () => {
  const { handler } = createIdentityHarness();
  await handler(topLevelFormPost({ path: '/join', form: VALID_JOIN }));
  const response = await handler(topLevelFormPost({
    path: '/login',
    form: { email: 'browser@example.com', password: 'correct horse battery' },
  }));
  assert.equal(response.status, 303);
});

test('a browser top-level form POST saves a record the member can read back', async () => {
  const { binding } = createSqliteD1Binding();
  const members = new D1B64MemberStore(binding);
  const repository = new D1UserIncomeRepository(binding);
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [],
    resolveAuth: createB64AuthResolver({ sessionSecret: TEST_SESSION_SECRET, members }),
    memberStore: members,
    sessionSecret: TEST_SESSION_SECRET,
    incomeRepository: repository,
    expectedBrowserOrigin: TEST_ORIGIN,
  });

  const joined = await handler(topLevelFormPost({ path: '/join', form: VALID_JOIN }));
  const cookie = joined.headers.getSetCookie()
    .find((value) => value.startsWith(`${B64_SESSION_COOKIE_NAME}=`))!
    .split(';')[0]!;
  const claims = await verifyB64SessionToken(cookie.slice(B64_SESSION_COOKIE_NAME.length + 1), TEST_SESSION_SECRET);
  assert.ok(claims);

  const saved = await handler(topLevelFormPost({ path: '/pipeline', form: SAVE_FORM, cookie }));
  assert.equal(saved.status, 303, 'the Save button is a same-origin mutation');
  const records = await repository.getByUser(claims!.memberId);
  assert.equal(records.length, 1, 'the record is stored under that member');
  assert.equal(records[0]!.title, 'Prolific 리서치');

  const page = await (await handler(getWithCookie('/pipeline', cookie))).text();
  assert.ok(page.includes('Prolific'), 'and it renders back to the member');
});

test('a browser top-level form POST logs the member out and revokes the session row', async () => {
  const { handler, members } = createIdentityHarness();
  const joined = await handler(topLevelFormPost({ path: '/join', form: VALID_JOIN }));
  const cookie = joined.headers.getSetCookie()
    .find((value) => value.startsWith(`${B64_SESSION_COOKIE_NAME}=`))!
    .split(';')[0]!;
  const claims = await verifyB64SessionToken(cookie.slice(B64_SESSION_COOKIE_NAME.length + 1), TEST_SESSION_SECRET);
  assert.ok(claims);

  const logout = await handler(topLevelFormPost({ path: '/logout', cookie }));
  assert.equal(logout.status, 303);
  assert.equal(await members.findLiveSession(claims!.sessionId), null, 'the row is revoked');
});

test('only a request that is genuinely same-origin gets the form-POST allowance', async () => {
  const { handler } = createIdentityHarness();
  const cases: ReadonlyArray<[BrowserPost, string]> = [
    [{ path: '/join', form: VALID_JOIN, origin: 'null', secFetchSite: 'cross-site' }, 'cross-site form'],
    [{ path: '/join', form: VALID_JOIN, origin: 'null', secFetchSite: 'same-site' },
      'same-site sibling, the case #3476 exists for'],
    [{ path: '/join', form: VALID_JOIN, origin: 'null' }, 'Origin null with no Sec-Fetch-Site'],
    [{ path: '/join', form: VALID_JOIN }, 'neither Origin nor Sec-Fetch-Site'],
    [{ path: '/join', form: VALID_JOIN, origin: 'https://evil.example', secFetchSite: 'same-origin' },
      'a real Origin that is not the reviewed one'],
    [{ path: '/join', form: VALID_JOIN, origin: 'null', secFetchSite: 'none' }, 'address-bar shaped request'],
    [{ path: '/join', form: VALID_JOIN, origin: 'null', secFetchSite: 'same-origin',
      host: 'https://someone-elses-host.example' }, 'addressed at another host'],
  ];
  for (const [input, label] of cases) {
    const response = await handler(browserPost(input));
    assert.equal(response.status, 403, `${label} must stay denied`);
    assert.equal((await response.json() as { error: string }).error, 'origin_rejected', label);
  }
});

test('a same-origin form POST that omits Origin entirely is still accepted', async () => {
  // Chrome sends `Origin: null` on a top-level form POST; other engines omit
  // the header. `Sec-Fetch-Site: same-origin` plus a request addressed at the
  // reviewed origin is the browser-verified fact either way.
  const { handler } = createIdentityHarness();
  const response = await handler(browserPost({
    path: '/join', form: VALID_JOIN, secFetchSite: 'same-origin',
  }));
  assert.equal(response.status, 303);
});

test('a cookie-carrying pipeline mutation from a cross-site document is denied', async () => {
  const { handler } = createIdentityHarness();
  const joined = await handler(topLevelFormPost({ path: '/join', form: VALID_JOIN }));
  const cookie = joined.headers.getSetCookie()
    .find((value) => value.startsWith(`${B64_SESSION_COOKIE_NAME}=`))!
    .split(';')[0]!;
  const attack = await handler(browserPost({
    path: '/pipeline', form: SAVE_FORM, cookie, origin: 'null', secFetchSite: 'cross-site',
  }));
  assert.equal(attack.status, 403);
});

test('the guard still refuses everything when no reviewed origin is configured', async () => {
  const handler = createConsumerHttpHandler({ loadCandidates: () => [], sessionSecret: TEST_SESSION_SECRET });
  const response = await handler(topLevelFormPost({ path: '/join', form: VALID_JOIN }));
  assert.equal(response.status, 503);
  assert.equal((await response.json() as { error: string }).error, 'origin_guard_unavailable');
});
