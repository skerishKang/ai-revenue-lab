import test from 'node:test';
import assert from 'node:assert/strict';
import { createConsumerHttpHandler } from '../src/http/consumer-http.js';
import { createB64AuthResolver, signInWithGoogle } from '../src/identity/auth.js';
import {
  B64MemberStorageError,
  D1B64MemberStore,
  InMemoryB64MemberStore,
  UnboundB64MemberStore,
} from '../src/identity/member-store.js';
import {
  B64_GOOGLE_CALLBACK_PATH,
  B64_GOOGLE_START_PATH,
  B64_OAUTH_STATE_COOKIE_NAME,
  GOOGLE_AUTH_URL,
  GOOGLE_TOKEN_URL,
  GOOGLE_USERINFO_URL,
  GoogleAuthError,
  b64GoogleAuthorizationUrl,
  b64GoogleRedirectUri,
  exchangeGoogleCode,
  fetchGoogleVerifiedIdentity,
  isB64GoogleSubject,
  mintB64OAuthState,
  verifyB64OAuthState,
  type GoogleFetch,
} from '../src/identity/google.js';
import {
  B64_SESSION_COOKIE_NAME,
  mintB64SessionToken,
  newB64MemberId,
  newB64SessionId,
  verifyB64SessionToken,
} from '../src/identity/session.js';
import { D1UserIncomeRepository } from '../src/income-pipeline/d1-user-income-repository.js';
import { createSqliteD1Binding, readAllMigrationsSql } from './d1-binding-helper.js';
import {
  TEST_ORIGIN,
  TEST_SESSION_SECRET,
  getWithCookie,
  joinMember,
  postForm,
} from './helpers/b64-identity-harness.js';

/**
 * B64's Google login (#987 reuse). The provider contract is the repository's
 * already-proven one — authorization code, signed state cookie, `verified_email`
 * — and what these tests pin is the part that makes it B64's own: its cookie
 * purpose, its redirect origin, its member id, its session cookie, and the rule
 * that an email address never merges two accounts.
 */

const TEST_CLIENT_ID = 'b64-client-id.apps.googleusercontent.com';
const TEST_CLIENT_SECRET = 'b64-test-client-secret-must-never-be-returned';
const GOOGLE_SUB = '10293847560192837465';
const VERIFIED_USERINFO = { id: GOOGLE_SUB, email: 'Ghost@Example.com', verified_email: true, name: '사용자' };

interface GoogleStub {
  readonly tokenStatus?: number;
  readonly userinfoStatus?: number;
  readonly tokenBody?: unknown;
  readonly userinfoBody?: unknown;
  readonly throwOn?: 'token' | 'userinfo';
}

interface RecordedCall {
  readonly url: string;
  readonly form: URLSearchParams | null;
}

function createGoogleFetch(stub: GoogleStub = {}): {
  readonly fetchImpl: GoogleFetch;
  readonly calls: RecordedCall[];
} {
  const calls: RecordedCall[] = [];
  const fetchImpl: GoogleFetch = async (url, init) => {
    const body = init.body;
    calls.push({
      url,
      form: body instanceof URLSearchParams ? body : null,
    });
    const isTokenCall = url === GOOGLE_TOKEN_URL;
    if (stub.throwOn === (isTokenCall ? 'token' : 'userinfo')) throw new TypeError('network unreachable');
    const payload = isTokenCall
      ? (stub.tokenBody ?? { access_token: 'ya29.test-access-token', expires_in: 3600 })
      : (stub.userinfoBody ?? VERIFIED_USERINFO);
    return new Response(typeof payload === 'string' ? payload : JSON.stringify(payload), {
      status: isTokenCall ? (stub.tokenStatus ?? 200) : (stub.userinfoStatus ?? 200),
      headers: { 'content-type': 'application/json' },
    });
  };
  return { fetchImpl, calls };
}

function googleHandlerOptions(stub: GoogleStub = {}, overrides: Record<string, unknown> = {}) {
  const { fetchImpl, calls } = createGoogleFetch(stub);
  return { calls, options: {
    loadCandidates: () => [],
    loadPublicOpportunities: () => [],
    expectedBrowserOrigin: TEST_ORIGIN,
    sessionSecret: TEST_SESSION_SECRET,
    googleClientId: TEST_CLIENT_ID,
    googleClientSecret: TEST_CLIENT_SECRET,
    googleFetch: fetchImpl,
    ...overrides,
  } };
}

interface GoogleHarness {
  readonly handler: (request: Request) => Promise<Response>;
  readonly members: D1B64MemberStore;
  readonly binding: ReturnType<typeof createSqliteD1Binding>['binding'];
  readonly calls: RecordedCall[];
}

function createGoogleHarness(stub: GoogleStub = {}, overrides: Record<string, unknown> = {}): GoogleHarness {
  const { binding } = createSqliteD1Binding();
  const members = new D1B64MemberStore(binding);
  const { calls, options } = googleHandlerOptions(stub, {
    memberStore: members,
    resolveAuth: createB64AuthResolver({ sessionSecret: TEST_SESSION_SECRET, members }),
    incomeRepository: new D1UserIncomeRepository(binding),
    ...overrides,
  });
  return { handler: createConsumerHttpHandler(options), members, binding, calls };
}

function setCookiePairs(response: Response): string[] {
  return response.headers.getSetCookie().map((cookie) => cookie.split(';')[0]!.trim());
}

function cookieAttributes(response: Response, name: string): string | null {
  for (const cookie of response.headers.getSetCookie()) {
    if (cookie.split(';')[0]!.trim().startsWith(`${name}=`)) return cookie;
  }
  return null;
}

/** Runs the real /start, so the callback carries a state this Worker signed. */
async function startLogin(handler: (request: Request) => Promise<Response>): Promise<{
  readonly stateCookie: string;
  readonly state: string;
  readonly location: URL;
}> {
  const response = await handler(getWithCookie(B64_GOOGLE_START_PATH));
  assert.equal(response.status, 303, 'a configured deployment sends the browser to Google');
  const location = new URL(response.headers.get('location')!);
  const state = location.searchParams.get('state');
  assert.ok(state, 'the authorization request carries a state');
  const cookie = cookieAttributes(response, B64_OAUTH_STATE_COOKIE_NAME);
  assert.ok(cookie, 'the state is stored in B64\'s own cookie');
  return { stateCookie: cookie!.split(';')[0]!.trim(), state, location };
}

async function callback(
  handler: (request: Request) => Promise<Response>,
  stateCookie: string,
  params: Record<string, string>,
  arrivingHost = TEST_ORIGIN,
): Promise<Response> {
  const query = new URLSearchParams(params).toString();
  return handler(new Request(`${arrivingHost}${B64_GOOGLE_CALLBACK_PATH}?${query}`, { headers: { cookie: stateCookie } }));
}

function sessionPair(response: Response): string {
  const pair = setCookiePairs(response).find((value) => value.startsWith(`${B64_SESSION_COOKIE_NAME}=`));
  assert.ok(pair, 'a session cookie is set');
  return pair!;
}

function errorPayload(response: Response): Promise<{ error: string }> {
  return response.json() as Promise<{ error: string }>;
}

/* ------------------------------- the state cookie --------------------------- */

test('the OAuth state is signed, bounded to ten minutes and single-purpose', async () => {
  const issued = await mintB64OAuthState({ sessionSecret: TEST_SESSION_SECRET, nowSeconds: 1_700_000_000 });
  assert.ok(issued.state.length >= 16, 'the state carries entropy');

  assert.equal(await verifyB64OAuthState({
    sessionSecret: TEST_SESSION_SECRET, state: issued.state, token: issued.token, nowSeconds: 1_700_000_600,
  }), true, 'accepted through the full window');
  assert.equal(await verifyB64OAuthState({
    sessionSecret: TEST_SESSION_SECRET, state: issued.state, token: issued.token, nowSeconds: 1_700_000_602,
  }), false, 'the window is a hard bound');
  assert.equal(await verifyB64OAuthState({
    sessionSecret: TEST_SESSION_SECRET, state: 'attacker-chosen-state', token: issued.token, nowSeconds: 1_700_000_001,
  }), false, 'the query state must equal the signed one');
  assert.equal(await verifyB64OAuthState({
    sessionSecret: undefined, state: issued.state, token: issued.token,
  }), false, 'nothing verifies without the secret');
});

test('the purpose string keeps OAuth state and session tokens out of each other', async () => {
  const state = await mintB64OAuthState({ sessionSecret: TEST_SESSION_SECRET });
  assert.equal(await verifyB64SessionToken(state.token, TEST_SESSION_SECRET), null, 'a state is not a session');

  const sessionToken = await mintB64SessionToken({
    sessionSecret: TEST_SESSION_SECRET,
    memberId: newB64MemberId(),
    sessionId: newB64SessionId(),
    expiresAtSeconds: Math.floor(Date.now() / 1000) + 3600,
  });
  assert.equal(await verifyB64OAuthState({ sessionSecret: TEST_SESSION_SECRET, state: 'x', token: sessionToken }), false,
    'a session is not a state');
});

test('the state cookie is HttpOnly, Secure, SameSite=Lax, path-scoped and short', async () => {
  const { handler } = createGoogleHarness();
  const attributes = cookieAttributes(await handler(getWithCookie(B64_GOOGLE_START_PATH)), B64_OAUTH_STATE_COOKIE_NAME)!;
  assert.match(attributes, /HttpOnly/);
  assert.match(attributes, /Secure/);
  assert.match(attributes, /SameSite=Lax/);
  assert.match(attributes, /Path=\//);
  assert.match(attributes, /Max-Age=600/);
  assert.ok(!attributes.includes('Domain='), 'never widened to the parent domain');
});

/* -------------------------- the provider request shape --------------------- */

test('the redirect URI is B64\'s configured origin and refuses anything non-https', () => {
  assert.equal(b64GoogleRedirectUri(TEST_ORIGIN), `${TEST_ORIGIN}${B64_GOOGLE_CALLBACK_PATH}`);
  assert.equal(
    b64GoogleRedirectUri(`${TEST_ORIGIN}/anything/else`),
    `${TEST_ORIGIN}${B64_GOOGLE_CALLBACK_PATH}`,
    'only the reviewed origin is used, never a path or trailing slash',
  );
  for (const bad of [undefined, '', 'http://b64.example.test', 'not a url', 'https://', '//host']) {
    assert.throws(() => b64GoogleRedirectUri(bad), (error) => error instanceof GoogleAuthError
      && error.status === 503 && error.code === 'auth_unavailable', `refuses ${String(bad)}`);
  }
});

test('the authorization request is the reviewed parameter set, with no secret in the URL', () => {
  const url = new URL(b64GoogleAuthorizationUrl({
    clientId: TEST_CLIENT_ID,
    redirectUri: `${TEST_ORIGIN}${B64_GOOGLE_CALLBACK_PATH}`,
    state: 'abc123',
  }));
  assert.equal(`${url.origin}${url.pathname}`, GOOGLE_AUTH_URL);
  assert.equal(url.searchParams.get('response_type'), 'code');
  assert.equal(url.searchParams.get('client_id'), TEST_CLIENT_ID);
  assert.equal(url.searchParams.get('redirect_uri'), `${TEST_ORIGIN}${B64_GOOGLE_CALLBACK_PATH}`);
  assert.equal(url.searchParams.get('scope'), 'openid email profile');
  assert.equal(url.searchParams.get('state'), 'abc123');
  assert.equal(url.searchParams.get('include_granted_scopes'), 'true');
  assert.equal(url.searchParams.has('nonce'), false, 'no ID-token path is offered that this code would have to verify');
  assert.ok(!url.toString().includes(TEST_CLIENT_SECRET), 'the client secret is never in a browser-visible URL');
});

test('a missing B64 Google client fails closed instead of half-starting a login', async () => {
  const { fetchImpl } = createGoogleFetch();
  for (const partial of [{ clientId: undefined, clientSecret: TEST_CLIENT_SECRET }, { clientId: '', clientSecret: undefined }]) {
    await assert.rejects(
      exchangeGoogleCode({ code: 'c', ...partial, redirectUri: TEST_ORIGIN, fetchImpl }),
      (error) => error instanceof GoogleAuthError && error.status === 503 && error.code === 'auth_unavailable',
      JSON.stringify(partial),
    );
  }
  assert.throws(() => b64GoogleAuthorizationUrl({
    clientId: undefined, redirectUri: TEST_ORIGIN, state: 's',
  }), GoogleAuthError);
});

test('provider failures are refused, never turned into a login', async () => {
  const cases: ReadonlyArray<[GoogleStub, number, string]> = [
    [{ tokenStatus: 400, tokenBody: { error: 'invalid_grant' } }, 502, 'auth_provider_error'],
    [{ tokenBody: { token_type: 'Bearer' } }, 502, 'auth_provider_error'],
    [{ tokenBody: 'not json' }, 502, 'auth_provider_error'],
    [{ tokenBody: [1, 2, 3] }, 502, 'auth_provider_error'],
    [{ throwOn: 'token' }, 502, 'auth_provider_error'],
    [{ throwOn: 'userinfo' }, 502, 'auth_provider_error'],
    [{ userinfoStatus: 500, userinfoBody: { error: 'backendError' } }, 502, 'auth_provider_error'],
    [{ userinfoBody: { ...VERIFIED_USERINFO, verified_email: false } }, 403, 'auth_identity_unverified'],
    [{ userinfoBody: { ...VERIFIED_USERINFO, verified_email: 'true' } }, 403, 'auth_identity_unverified'],
    [{ userinfoBody: { ...VERIFIED_USERINFO, email: '' } }, 403, 'auth_identity_unverified'],
    [{ userinfoBody: { ...VERIFIED_USERINFO, id: '' } }, 403, 'auth_identity_unverified'],
    [{ userinfoBody: { ...VERIFIED_USERINFO, id: 'has spaces / bad' } }, 403, 'auth_identity_unverified'],
    [{ userinfoBody: { ...VERIFIED_USERINFO, email: 'not an email' } }, 403, 'auth_identity_unverified'],
    [{ userinfoBody: { ...VERIFIED_USERINFO, email: `${'x'.repeat(320)}@example.com` } }, 403, 'auth_identity_unverified'],
  ];
  for (const [stub, status, code] of cases) {
    const { fetchImpl } = createGoogleFetch(stub);
    await assert.rejects(
      (async () => {
        const accessToken = await exchangeGoogleCode({
          code: 'c', clientId: TEST_CLIENT_ID, clientSecret: TEST_CLIENT_SECRET, redirectUri: TEST_ORIGIN, fetchImpl,
        });
        await fetchGoogleVerifiedIdentity({ accessToken, fetchImpl });
      })(),
      (error) => error instanceof GoogleAuthError && error.status === status && error.code === code,
      JSON.stringify(stub),
    );
  }
});

test('an oversized provider response is refused instead of buffered and parsed', async () => {
  const huge: GoogleFetch = () => Promise.resolve(new Response('a'.repeat(2 * 1024 * 1024), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  }));
  await assert.rejects(
    fetchGoogleVerifiedIdentity({ accessToken: 't', fetchImpl: huge }),
    (error) => error instanceof GoogleAuthError && error.status === 502,
  );
});

test('a body that is not UTF-8 JSON is a provider failure, not a crash', async () => {
  const binary: GoogleFetch = () => Promise.resolve(new Response(new Uint8Array([0xff, 0xfe, 0x00, 0xff]), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  }));
  await assert.rejects(
    fetchGoogleVerifiedIdentity({ accessToken: 't', fetchImpl: binary }),
    (error) => error instanceof GoogleAuthError && error.status === 502 && error.code === 'auth_provider_error',
  );
});

test('a verified identity arrives normalized and the subject grammar is bounded', async () => {
  const { fetchImpl } = createGoogleFetch();
  const identity = await fetchGoogleVerifiedIdentity({ accessToken: 't', fetchImpl });
  assert.equal(identity.googleSub, GOOGLE_SUB, 'the subject is the durable key');
  assert.equal(identity.email, 'ghost@example.com', 'the address is stored normalized');
  assert.equal(isB64GoogleSubject(GOOGLE_SUB), true);
  assert.equal(isB64GoogleSubject('1234567'), false, 'shorter than the bound is refused');
  assert.equal(isB64GoogleSubject('x'.repeat(200)), false, 'longer than the bound is refused');
  assert.equal(isB64GoogleSubject('-leading'), false);
});

/* ----------------------------- the two HTTP routes ------------------------- */

test('an unconfigured deployment hides the Google entry and 503s the route', async () => {
  const { handler } = createGoogleHarness({}, { googleClientId: undefined, googleClientSecret: undefined });
  const start = await handler(getWithCookie(B64_GOOGLE_START_PATH));
  assert.equal(start.status, 503);
  assert.equal((await errorPayload(start)).error, 'auth_unavailable');

  const html = await (await handler(getWithCookie('/pipeline'))).text();
  assert.ok(!html.includes(B64_GOOGLE_START_PATH), 'no link is offered that would only fail');
  assert.ok(html.includes('action="/join"'), 'the existing email entry stays available');
});

test('/start sends the browser to Google with the state its cookie carries', async () => {
  const { handler } = createGoogleHarness();
  const first = await startLogin(handler);
  assert.equal(first.location.origin, new URL(GOOGLE_AUTH_URL).origin, 'the browser leaves for Google, not for a peer');
  assert.ok(first.stateCookie.startsWith(`${B64_OAUTH_STATE_COOKIE_NAME}=`));
  assert.equal(cookieAttributes(await handler(getWithCookie(B64_GOOGLE_START_PATH)), B64_SESSION_COOKIE_NAME), null,
    'no session exists before Google has answered');
  const second = await startLogin(handler);
  assert.notEqual(second.location.searchParams.get('state'), first.location.searchParams.get('state'),
    'two logins get two states');
});

test('a callback whose state does not match is refused and the state is spent', async () => {
  const { handler } = createGoogleHarness();
  const forged = await mintB64OAuthState({ sessionSecret: 'another-products-own-secret-0123456789' });

  const unsigned = await callback(handler, `${B64_OAUTH_STATE_COOKIE_NAME}=not-a-signed-token`, {
    code: 'sample-code', state: forged.state,
  });
  assert.equal(unsigned.status, 403);
  assert.equal((await errorPayload(unsigned)).error, 'invalid_state');
  assert.match(cookieAttributes(unsigned, B64_OAUTH_STATE_COOKIE_NAME)!, /Max-Age=0/, 'the cookie is cleared either way');

  assert.equal((await handler(new Request(
    `${TEST_ORIGIN}${B64_GOOGLE_CALLBACK_PATH}?code=c&state=${forged.state}`,
  ))).status, 403, 'a visitor holding no state cookie has no login in flight');

  assert.equal((await callback(handler, `${B64_OAUTH_STATE_COOKIE_NAME}=${forged.token}`, {
    code: 'c', state: forged.state,
  })).status, 403, 'a state signed with someone else\'s key is not ours');

  const { stateCookie } = await startLogin(handler);
  assert.equal((await callback(handler, stateCookie, { error: 'access_denied' })).status, 403,
    'a refusal from Google creates no account');
});

test('POST is refused on the Google routes and the email endpoints keep their own rules', async () => {
  const { handler } = createGoogleHarness();
  assert.equal((await handler(postForm(B64_GOOGLE_START_PATH, {}))).status, 405,
    'the OAuth round trip is a navigation, not a form target');
  const getLogin = await handler(getWithCookie('/login'));
  assert.equal(getLogin.status, 303);
  assert.equal(getLogin.headers.get('location'), '/pipeline');
});

/* --------------------------- login, member and session --------------------- */

test('a verified Google login opens a B64 session and links the subject to its member', async () => {
  const { handler, members, calls } = createGoogleHarness();
  const { stateCookie, state } = await startLogin(handler);
  const response = await callback(handler, stateCookie, { code: 'sample-code', state });
  assert.equal(response.status, 303);
  assert.equal(response.headers.get('location'), '/pipeline');

  const pairs = setCookiePairs(response);
  assert.equal(pairs.length, 2, 'the session is set and the single-use state is cleared');
  const sessionCookie = sessionPair(response);
  assert.ok(sessionCookie.length > `${B64_SESSION_COOKIE_NAME}=`.length + 16, 'a real token, not an empty one');
  assert.equal(pairs.find((pair) => pair.startsWith(`${B64_OAUTH_STATE_COOKIE_NAME}=`)), `${B64_OAUTH_STATE_COOKIE_NAME}=`);
  assert.match(cookieAttributes(response, B64_SESSION_COOKIE_NAME)!, /HttpOnly/);
  assert.ok(!setCookiePairs(response).join(' ').includes(TEST_CLIENT_SECRET));

  const memberId = await members.findMemberIdByGoogleSub(GOOGLE_SUB);
  assert.match(memberId!, /^b64m_[a-f0-9]{24}$/, 'B64 mints its own member id');

  const html = await (await handler(getWithCookie('/pipeline', sessionCookie))).text();
  assert.ok(html.includes('action="/logout"'), 'the member view is the one an email login reaches');
  assert.equal(await members.findByEmail('ghost@example.com'), null, 'Google linking writes no password credential');

  assert.equal(calls.length, 2);
  assert.equal(calls[0]!.url, GOOGLE_TOKEN_URL);
  assert.equal(calls[0]!.form!.get('grant_type'), 'authorization_code');
  assert.equal(calls[0]!.form!.get('code'), 'sample-code');
  assert.equal(calls[0]!.form!.get('client_id'), TEST_CLIENT_ID);
  assert.equal(calls[0]!.form!.get('redirect_uri'), `${TEST_ORIGIN}${B64_GOOGLE_CALLBACK_PATH}`);
  assert.equal(calls[1]!.url, GOOGLE_USERINFO_URL);
});

test('the same subject returns to the same member, and the record stays its own', async () => {
  const { handler, members, binding } = createGoogleHarness();
  const repository = new D1UserIncomeRepository(binding);

  const first = await startLogin(handler);
  const cookieA = sessionPair(await callback(handler, first.stateCookie, { code: 'code-1', state: first.state }));
  const memberId = (await members.findMemberIdByGoogleSub(GOOGLE_SUB))!;

  const saved = await handler(new Request(`${TEST_ORIGIN}/pipeline`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded', origin: TEST_ORIGIN, cookie: cookieA },
    body: new URLSearchParams({ action: 'save', title: '첫 기록', vendor: 'Prolific', status: 'SAVED' }).toString(),
  }));
  assert.equal(saved.status, 303);

  const second = await startLogin(handler);
  const again = await callback(handler, second.stateCookie, { code: 'code-2', state: second.state });
  assert.equal(again.status, 303);
  assert.equal(await members.findMemberIdByGoogleSub(GOOGLE_SUB), memberId, 'the subject is the account key');

  const records = await repository.getByUser(memberId);
  assert.equal(records.length, 1, 'the returning member sees its own one record');
  assert.equal((await repository.getByUser(newB64MemberId())).length, 0, 'nobody else reads it');
  assert.notEqual(sessionPair(again), cookieA, 'each login opens its own session row');
});

test('a Google login never merges onto an email/password member by address', async () => {
  const { handler, members } = createGoogleHarness();
  const emailCookie = await joinMember(handler, 'ghost@example.com', 'correct horse battery');
  const passwordMember = await members.findByEmail('ghost@example.com');
  assert.ok(passwordMember);

  const { stateCookie, state } = await startLogin(handler);
  assert.equal((await callback(handler, stateCookie, { code: 'sample-code', state })).status, 303);

  const googleMemberId = (await members.findMemberIdByGoogleSub(GOOGLE_SUB))!;
  assert.ok(googleMemberId);
  assert.notEqual(googleMemberId, passwordMember!.id, 'same address, different account — no silent merge');
  assert.ok(!emailCookie.includes(googleMemberId), 'the email session is not rewritten by the Google login');
  assert.equal((await handler(getWithCookie('/pipeline', emailCookie))).status, 200,
    'the password member keeps its own session');
});

test('logout revokes a Google-opened session exactly like a password one', async () => {
  const { handler, members } = createGoogleHarness();
  const { stateCookie, state } = await startLogin(handler);
  const sessionCookie = sessionPair(await callback(handler, stateCookie, { code: 'sample-code', state }));

  const claims = await verifyB64SessionToken(sessionCookie.split('=')[1], TEST_SESSION_SECRET);
  assert.ok(claims);
  assert.ok(await members.findLiveSession(claims!.sessionId), 'the row is live right after login');

  const logout = await handler(new Request(`${TEST_ORIGIN}/logout`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded', origin: TEST_ORIGIN, cookie: sessionCookie },
    body: '',
  }));
  assert.equal(logout.status, 303);
  assert.equal(await members.findLiveSession(claims!.sessionId), null,
    'the row is revoked, so the still-valid signature buys nothing');
  const html = await (await handler(getWithCookie('/pipeline', sessionCookie))).text();
  assert.ok(html.includes('action="/login"'), 'back to the gate');
});

test('the redirect URI sent to Google is the configured origin, not the request host', async () => {
  const { handler, calls } = createGoogleHarness();
  const { stateCookie, state } = await startLogin(handler);
  const response = await callback(handler, stateCookie, { code: 'sample-code', state }, 'https://someone-elses-host.example');
  assert.equal(response.status, 303);
  assert.equal(calls[0]!.form!.get('redirect_uri'), `${TEST_ORIGIN}${B64_GOOGLE_CALLBACK_PATH}`);
});

test('a deployment whose D1 binding is missing refuses to complete a Google login', async () => {
  const unbound = new UnboundB64MemberStore('B64_INCOME_DB');
  const { options, calls } = googleHandlerOptions({}, {
    memberStore: unbound,
    resolveAuth: createB64AuthResolver({ sessionSecret: TEST_SESSION_SECRET, members: unbound }),
  });
  const handler = createConsumerHttpHandler(options);
  const { stateCookie, state } = await startLogin(handler);
  const response = await callback(handler, stateCookie, { code: 'c', state });
  assert.equal(response.status, 503, 'no durable store, no account created');
  assert.equal((await errorPayload(response)).error, 'storage_unavailable');
  assert.match(cookieAttributes(response, B64_OAUTH_STATE_COOKIE_NAME)!, /Max-Age=0/, 'the state is spent either way');
  assert.equal(calls.length, 2, 'the refusal happens at the member link, after Google answered');
});

test('a google subject is linked once, and a bad key is refused before storage', async () => {
  const store = new InMemoryB64MemberStore();
  const memberId = newB64MemberId();
  await store.linkGoogleMember({ googleSub: GOOGLE_SUB, memberId, email: 'a@example.com', linkedAt: '2026-10-27T00:00:00.000Z' });
  assert.equal(await store.findMemberIdByGoogleSub(GOOGLE_SUB), memberId);
  await assert.rejects(
    store.linkGoogleMember({ googleSub: GOOGLE_SUB, memberId, email: 'a@example.com', linkedAt: '2026-10-27T00:00:00.000Z' }),
    B64MemberStorageError, 'one subject cannot be re-linked to a second member',
  );
  await assert.rejects(store.findMemberIdByGoogleSub('not a subject'), B64MemberStorageError);
  await assert.rejects(
    store.linkGoogleMember({ googleSub: '10293847560192837466', memberId: 'pm_user_1', email: 'a@example.com', linkedAt: 'x' }),
    B64MemberStorageError, 'a link must point at a B64 member id',
  );
  const unbound = new UnboundB64MemberStore('B64_INCOME_DB');
  await assert.rejects(unbound.findMemberIdByGoogleSub(GOOGLE_SUB), B64MemberStorageError);
  await assert.rejects(unbound.linkGoogleMember({
    googleSub: GOOGLE_SUB, memberId, email: 'a@example.com', linkedAt: '2026-10-27T00:00:00.000Z',
  }), B64MemberStorageError);
});

test('a concurrent first login adopts the link that won instead of failing the visitor', async () => {
  const store = new InMemoryB64MemberStore();
  const winner = newB64MemberId();
  await store.linkGoogleMember({ googleSub: GOOGLE_SUB, memberId: winner, email: 'a@example.com', linkedAt: '2026-10-27T00:00:00.000Z' });
  const { fetchImpl } = createGoogleFetch();
  const issued = await signInWithGoogle({
    store,
    sessionSecret: TEST_SESSION_SECRET,
    clientId: TEST_CLIENT_ID,
    clientSecret: TEST_CLIENT_SECRET,
    publicBaseUrl: TEST_ORIGIN,
    code: 'c',
    fetchImpl,
  });
  const claims = await verifyB64SessionToken(issued.cookieHeader.split(';')[0]!.split('=')[1], TEST_SESSION_SECRET);
  assert.equal(claims!.memberId, winner, 'the row that won the race names the member');
});

test('the Google entry is offered only when the deployment is configured', async () => {
  const { handler } = createGoogleHarness();
  const html = await (await handler(getWithCookie('/pipeline'))).text();
  assert.ok(html.includes(`href="${B64_GOOGLE_START_PATH}"`), 'the entry is a plain link (script-src \'none\' forbids a widget)');
  assert.ok(html.includes('Google 로그인'));
  assert.ok(html.indexOf('Google 로그인') < html.indexOf('action="/join"'), 'Google is offered first');
});

/* ---------------------------------- schema --------------------------------- */

test('0003 is additive and replay-safe next to the live schema', () => {
  const { db, binding } = createSqliteD1Binding();
  const members = new D1B64MemberStore(binding);
  const before = db.prepare('SELECT COUNT(*) AS n FROM b64_member_google').get() as { n: number };
  assert.equal(before.n, 0, 'the table exists and starts empty');

  // One prepared statement per migration file: re-running the whole set is what
  // the provision gate does when a dispatch is retried.
  db.exec(readAllMigrationsSql());
  db.exec(readAllMigrationsSql());

  const tables = (db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all() as Array<{ name: string }>)
    .map((row) => row.name);
  for (const expected of ['b64_user_income', 'b64_member', 'b64_session', 'b64_member_google']) {
    assert.ok(tables.includes(expected), `${expected} survives a replayed migration set`);
  }

  const indexes = db.prepare("PRAGMA index_list('b64_member_google')").all() as Array<{ name: string; unique: number }>;
  const onMember = indexes.find((row) => row.name === 'idx_b64_member_google_member');
  assert.ok(onMember, 'the member id is indexed');
  assert.equal(onMember!.unique, 1, 'one B64 member backs exactly one Google subject');
});

test('a Google link is stored as one row and read back by subject only', async () => {
  const { binding } = createSqliteD1Binding();
  const store = new D1B64MemberStore(binding);
  const memberId = newB64MemberId();
  await store.linkGoogleMember({ googleSub: GOOGLE_SUB, memberId, email: 'ghost@example.com', linkedAt: '2026-10-27T00:00:00.000Z' });
  assert.equal(await store.findMemberIdByGoogleSub(GOOGLE_SUB), memberId);
  assert.equal(await store.findMemberIdByGoogleSub('10293847560192837466'), null, 'a neighbour subject is its own row');
  const rows = await binding.prepare('SELECT COUNT(*) AS n FROM b64_member_google').bind().first<{ n: number }>();
  assert.equal(rows!.n, 1, 'linking adds one row and rewrites no other');
});

/* --------------------------------- independence ---------------------------- */

test('no other product\'s login surface appears anywhere in the Google round trip', async () => {
  const { handler, calls } = createGoogleHarness();
  const { stateCookie, state, location } = await startLogin(handler);
  const response = await callback(handler, stateCookie, { code: 'sample-code', state });

  // What a browser, or a peer site that can read one, ever sees.
  const browserVisible = [
    location.toString(),
    response.headers.get('location') ?? '',
    ...setCookiePairs(response),
  ].join(' ');
  // What only this Worker holds.
  const serverSide = calls.map((call) => `${call.url} ${call.form?.toString() ?? ''}`).join(' ');
  for (const surface of [browserVisible, serverSide]) {
    for (const forbidden of ['padiem', 'chat.padiem.net', 'control-plane', 'control_plane']) {
      assert.ok(!surface.toLowerCase().includes(forbidden.toLowerCase()), `free of ${forbidden}`);
    }
  }
  assert.ok(!browserVisible.includes(TEST_CLIENT_SECRET), 'the client secret never reaches the browser');
  assert.ok(!browserVisible.includes(GOOGLE_USERINFO_URL), 'the userinfo read is server-side only');
});
