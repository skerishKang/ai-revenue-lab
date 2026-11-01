// 북AI 로그인·계정 레인 공격 시험 (#3782 계열 auth flow) — 로컬 모의 전용.
// 실제 auth.padiem.net / chat.padiem.net / bookai.padiem.net 접속은 없다:
// fetcher가 JWKS·토큰·로그아웃·COM2를 대역으로 답하고, ECDSA 키는 시험 안에서 새로 만든다.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createBookAIAuth} from '../public/bookai-auth.mjs';

const enc = new TextEncoder();
const ORIGIN = 'https://bookai.padiem.net';
const b64 = b => Buffer.from(b).toString('base64url');
const CALLER_KEYS = await crypto.subtle.generateKey(
  {name: 'ECDSA', namedCurve: 'P-256'}, true, ['sign', 'verify']);
const AUTH_KEYS = await crypto.subtle.generateKey(
  {name: 'ECDSA', namedCurve: 'P-256'}, true, ['sign', 'verify']);
const callerJwk = await crypto.subtle.exportKey('jwk', CALLER_KEYS.privateKey);
const authPub = await crypto.subtle.exportKey('jwk', AUTH_KEYS.publicKey);
authPub.kid = 'test-auth'; authPub.alg = 'ES256'; authPub.use = 'sig';
const ACCOUNT = 'sub_test';
const ENV = {BOOKAI_AUTH_CLIENT_PRIVATE_JWK: JSON.stringify(callerJwk),
             BOOKAI_COM2_SYNC_SECRET: 'synthetic-test-secret'};

function signAccessToken({now, accountId = ACCOUNT, aud = 'b61', lifetime = 900}) {
  const header = b64(JSON.stringify({alg: 'ES256', typ: 'JWT', kid: 'test-auth'}));
  const payload = b64(JSON.stringify({
    iss: 'https://auth.padiem.net', aud, token_use: 'access',
    iat: Math.floor(now / 1000), exp: Math.floor(now / 1000) + lifetime,
    sub: 'subject', account_id: accountId, sid: 'session-' + Math.floor(now)}));
  return crypto.subtle.sign({name: 'ECDSA', hash: 'SHA-256'}, AUTH_KEYS.privateKey,
    enc.encode(header + '.' + payload)).then(sig => header + '.' + payload + '.' + b64(sig));
}

function harness({clockNow = 1761960000000} = {}) {
  const state = {now: clockNow, usedCodes: new Set(), revokedRefresh: new Set(),
                 refusedCodes: new Set(), logins: [], logouts: [], upstream: []};
  const challengeFor = new Map();
  const fetcher = async (url, init) => {
    const u = String(url);
    if (u.endsWith('/.well-known/jwks.json'))
      return Response.json({keys: [authPub]});
    if (u.endsWith('/token')) {
      const params = new URLSearchParams(init.body);
      const assertionParts = params.get('client_assertion').split('.');
      const verified = await crypto.subtle.verify({name: 'ECDSA', hash: 'SHA-256'},
        CALLER_KEYS.publicKey, Buffer.from(assertionParts[2], 'base64url'),
        enc.encode(assertionParts[0] + '.' + assertionParts[1]));
      assert.equal(verified, true, 'client assertion signature');
      const grant = params.get('grant_type');
      if (grant === 'authorization_code') {
        const verifier = params.get('code_verifier');
        const code = params.get('code');
        const challenge = challengeFor.get(code);
        assert.equal(challenge !== undefined, true, 'unknown code replay');
        assert.equal(createHash('sha256').update(verifier).digest('base64url'), challenge,
          'PKCE verifier must match the login challenge');
        if (state.refusedCodes.has(code)) return Response.json({error: 'invalid_grant'}, {status: 400});
        if (state.usedCodes.has(code)) return Response.json({error: 'reused_code'}, {status: 400});
        state.usedCodes.add(code);
        const access = state.tokenOverride
          ? await state.tokenOverride
          : await signAccessToken({now: state.now});
        return Response.json({access_token: access, refresh_token: 'refresh-' + code});
      }
      if (grant === 'refresh_token') {
        const refresh = params.get('refresh_token');
        if (state.revokedRefresh.has(refresh))
          return Response.json({error: 'revoked_refresh'}, {status: 400});
        return Response.json({
          access_token: await signAccessToken({now: state.now, lifetime: 900}),
          refresh_token: refresh + '-rotated'});
      }
      throw Error('unexpected token grant ' + grant);
    }
    if (u.endsWith('/logout')) {
      const params = new URLSearchParams(init.body);
      state.logouts.push(params.get('refresh_token'));
      state.revokedRefresh.add(params.get('refresh_token'));
      return Response.json({ok: true});
    }
    if (u.startsWith('https://chat.padiem.net/api/bookai/records')) {
      state.upstream.push({url: u, headers: Object.fromEntries(init.headers || [])});
      return Response.json({records: [], next_since: 0, more: false});
    }
    throw Error('unexpected upstream ' + u);
  };
  const handler = createBookAIAuth({fetcher, clock: () => state.now});
  async function login() {
    const response = await handler(new Request(ORIGIN + '/auth/login'), ENV);
    assert.equal(response.status, 302, response.status);
    const target = new URL(response.headers.get('location'));
    const code = 'code-' + Math.random().toString(36).slice(2);
    challengeFor.set(code, target.searchParams.get('code_challenge'));
    const stateCookie = response.headers.getSetCookie().map(v => v.split(';')[0]).join('; ');
    return {response, target, code, stateCookie,
            stateValue: target.searchParams.get('state')};
  }
  async function callback({code, stateCookie, stateValue, extra = '', now} = {}) {
    const previous = state.now;
    if (now !== undefined) state.now = now;
    try {
      return await handler(new Request(
        ORIGIN + '/auth/callback?state=' + encodeURIComponent(stateValue) + '&code='
        + encodeURIComponent(code) + extra,
        {headers: {cookie: stateCookie}}), ENV);
    } finally {
      state.now = previous;
    }
  }
  return {handler, state, login, callback,
          sessionCookies: response => response.headers.getSetCookie().map(v => v.split(';')[0]).join('; ')};
}

test('callback redirect is fixed to the origin root under hostile redirect params', async () => {
  for (const extra of ['&redirect=//evil.com', '&redirect=https://evil.com',
                       '&redirect=/\\evil.com', '&redirect=%2F%2Fevil.com',
                       '&next=//evil.com&return=https://evil.com']) {
    const h = harness();
    const login = await h.login();
    const callback = await h.callback({...login, code: login.code, extra});
    assert.equal(callback.status, 303, extra);
    assert.equal(callback.headers.get('location'), '/', extra);
    const session = h.sessionCookies(callback);
    assert.match(session, /__Host_bookai_session=/, extra);
  }
});

test('state is required, single-use, expiring and cross-tenant', async () => {
  // state 파라미터 없음
  {
    const h = harness();
    const login = await h.login();
    const missing = await h.handler(new Request(
      ORIGIN + '/auth/callback?code=' + login.code, {headers: {cookie: login.stateCookie}}), ENV);
    assert.equal(missing.status, 503);
    assert.equal(missing.headers.getSetCookie().length, 0);
  }
  // state 쿠키 없음
  {
    const h = harness();
    const login = await h.login();
    const noCookie = await h.callback({code: login.code, stateCookie: ''});
    assert.equal(noCookie.status, 503);
    assert.equal(noCookie.headers.getSetCookie().length, 0);
  }
  // 만료(600초 + 1초)
  {
    const h = harness();
    const login = await h.login();
    const expired = await h.callback({...login, now: 1761960000000 + 601 * 1000});
    assert.equal(expired.status, 503);
    assert.equal(expired.headers.getSetCookie().length, 0);
  }
  // 다른 시크릿(다른 세션/배포)으로 봉인된 state
  {
    const other = harness({clockNow: 1761960000001});
    const mine = harness();
    const login = await mine.login();
    const foreign = await mine.callback({...login, stateCookie: (await other.login()).stateCookie});
    assert.equal(foreign.status, 503);
    assert.equal(foreign.headers.getSetCookie().length, 0);
  }
  // 성공한 callback 재사용: 코드는 1회용이고 state 쿠키는 비워진다 — 쿠키를 갖고
  // 다시 놀아도 토큰 교환은 거부되고 새 쿠키도 없다.
  {
    const h = harness();
    const login = await h.login();
    const first = await h.callback(login);
    assert.equal(first.status, 303);
    const replay = await h.callback({...login, stateCookie: login.stateCookie});
    assert.equal(replay.status, 503);
    assert.equal(replay.headers.getSetCookie().length, 0);
    assert.equal(h.state.usedCodes.size, 1);
  }
});

test('PKCE binds the login challenge to the token exchange', async () => {
  const h = harness();
  const login = await h.login();
  const challenge = login.target.searchParams.get('code_challenge');
  assert.equal(login.target.searchParams.get('code_challenge_method'), 'S256');
  await h.callback(login);
  const tokenCall = h.state.usedCodes;
  assert.equal(tokenCall.size, 1);
  // challenge는 로그인 URL에서, verifier는 봉인된 state에서 왔다 — fetcher가
  // 두 값을 대조했으므로 여기서는 결속 사실만 고정한다.
  assert.match(challenge, /^[A-Za-z0-9_-]{43,}$/);
  const callback = await h.callback({...login, code: 'second-try'});
  assert.equal(callback.status, 503); // 같은 challenge의 두 번째 교환은 코드가 없어 실패
});

test('session cookies carry the __Host_ grammar and logout clears and revokes', async () => {
  const h = harness();
  const login = await h.login();
  const callback = await h.callback(login);
  const setCookies = callback.headers.getSetCookie();
  for (const line of setCookies) {
    assert.match(line, /^__Host_/);
    assert.ok(line.includes('HttpOnly') && line.includes('Secure') && line.includes('SameSite=Lax'),
      line);
    assert.ok(line.includes('Path=/'), line);
  }
  const session = h.sessionCookies(callback);
  const who = await h.handler(new Request(ORIGIN + '/auth/session', {headers: {cookie: session}}), ENV);
  assert.equal((await who.json()).authenticated, true);
  // 로그아웃: AUTH 로그아웃 호출로 refresh를 폐기하고 쿠키를 Max-Age=0으로 비운다.
  const logout = await h.handler(new Request(ORIGIN + '/auth/logout',
    {method: 'POST', headers: {origin: ORIGIN, cookie: session}}), ENV);
  assert.equal(logout.status, 200);
  assert.equal(h.state.logouts.length, 1);
  const cleared = logout.headers.getSetCookie();
  for (const line of cleared) assert.ok(line.includes('Max-Age=0'), line);
  const after = await h.handler(new Request(ORIGIN + '/auth/session', {headers: {cookie: session}}), ENV);
  assert.equal((await after.json()).authenticated, false);
  // 폐기된 refresh의 재사용: 토큰 교환 거부, 새 쿠키 없음.
  const refresh = await h.handler(new Request(ORIGIN + '/auth/refresh',
    {method: 'POST', headers: {origin: ORIGIN, cookie: session}}), ENV);
  assert.equal(refresh.status, 503);
  assert.equal(refresh.headers.getSetCookie().length, 0);
});

test('cross-origin state changing calls are refused and read-only GET stays closed', async () => {
  const h = harness();
  const login = await h.login();
  const callback = await h.callback(login);
  const session = h.sessionCookies(callback);
  const body = JSON.stringify({records: []});
  for (const [path, method] of [['/auth/refresh', 'POST'], ['/auth/logout', 'POST'],
                                ['/api/bookai/records', 'POST']]) {
    for (const origin of ['https://evil.example', 'null']) {
      const answer = await h.handler(new Request(ORIGIN + path, {
        method, headers: {origin, cookie: session, 'content-type': 'application/json'}, body}), ENV);
      assert.equal(answer.status, 403, path + ' ' + origin);
    }
    const missing = await h.handler(new Request(ORIGIN + path, {
      method, headers: {cookie: session, 'content-type': 'application/json'}, body}), ENV);
    assert.equal(missing.status, 403, path + ' missing origin');
  }
  // 같은 Origin이면 POST 통과 (대조).
  const same = await h.handler(new Request(ORIGIN + '/api/bookai/records', {
    method: 'POST', headers: {origin: ORIGIN, cookie: session,
    'content-type': 'application/json'}, body}), ENV);
  assert.equal(same.status, 200);
});

test('records proxy derives the signed subject from the session, never from the body', async () => {
  const h = harness();
  const login = await h.login();
  const callback = await h.callback(login);
  const session = h.sessionCookies(callback);
  const body = JSON.stringify({sub: 'sub_other', subject: 'sub_other',
                               account_id: 'sub_other', records: []});
  const answer = await h.handler(new Request(ORIGIN + '/api/bookai/records', {
    method: 'POST', headers: {origin: ORIGIN, cookie: session,
    'content-type': 'application/json'}, body}), ENV);
  assert.equal(answer.status, 200, answer.status);
  assert.equal(h.state.upstream.length, 1);
  const forwarded = h.state.upstream[0].headers;
  assert.equal(forwarded['x-bookai-subject'], ACCOUNT);   // 세션이 유일한 sub 근거
  assert.notEqual(forwarded['x-bookai-subject'], 'sub_other');
  assert.equal(forwarded['x-bookai-timestamp'], String(Math.floor(1761960000000 / 1000)));
  assert.equal(forwarded['x-bookai-signature'].length, 64);
  // 세션 토큰이나 봉인 state가 업스트림으로 전달되지 않는다.
  const headersText = JSON.stringify(forwarded).toLowerCase();
  assert.ok(!headersText.includes('bearer') && !headersText.includes('refresh'));
});

test('identity surface leaks no token material and duplicate cookies are refused', async () => {
  const h = harness();
  const login = await h.login();
  const callback = await h.callback(login);
  const session = h.sessionCookies(callback);
  const token = session.split('; ').find(v => v.startsWith('__Host_bookai_session='));
  const accessToken = token.split('=')[1];
  const who = await h.handler(new Request(ORIGIN + '/auth/session', {headers: {cookie: session}}), ENV);
  const body = await who.json();
  assert.deepEqual(Object.keys(body).sort(), ['account_id', 'authenticated']);
  assert.ok(!JSON.stringify(body).includes(accessToken));
  const duplicate = await h.handler(new Request(ORIGIN + '/auth/session', {
    headers: {cookie: session + '; ' + token}}), ENV);
  assert.equal(duplicate.status, 503);
});

test('hostile access tokens are refused before any session cookie exists', async () => {
  // 검증기(verify)가 거부하는 토큰 — 문법 밖 account_id, 다른 audience, 만료,
  // 수명 초과 — 는 교환 자체를 실패시켜 503, 세션 쿠키는 0개다.
  const hostile = [
    {tokenOverride: signAccessToken({now: 1761960000000, accountId: 'admin'})},
    {tokenOverride: signAccessToken({now: 1761960000000, aud: 'other'})},
    {tokenOverride: signAccessToken({now: 1761960000000, lifetime: -10})},
    {tokenOverride: signAccessToken({now: 1761960000000, lifetime: 3600})},
  ];
  for (const override of hostile) {
    const h = harness();
    const login = await h.login();
    h.state.tokenOverride = override.tokenOverride;
    const answer = await h.callback(login);
    assert.equal(answer.status, 503, override.tokenOverride);
    assert.equal(answer.headers.getSetCookie().length, 0, override.tokenOverride);
    assert.equal(h.state.upstream.length, 0);
  }
});

