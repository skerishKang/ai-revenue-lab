// Common login skin: brand selection is fixed by the registered client_id, the
// night/garden variant only comes from lt_theme, and the page makes no external
// font or image request. The PADIEM account line is always present.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../state.mjs';
import { createApp, AuthStateObject } from '../worker.mjs';
import { withProductBoundary } from './authority-products.mjs';
import { AUTH_BRANDS, resolveBrand, resolveLang, resolveTheme } from '../skin.mjs';
import { AUTH_SKIN_ASSETS } from '../skin-assets.mjs';

const url = 'https://auth.padiem.net';
const REDIRECT = 'https://lovetree.example/auth/callback';
const APP = dirname(fileURLToPath(import.meta.url));
const STATIC = join(APP, '..', 'static', 'auth-skin');
const b64 = (x) => Buffer.from(x).toString('base64url');
const rand = () => b64(crypto.getRandomValues(new Uint8Array(32)));
const sum = async (x) => b64(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(x)));
const PASSWORD = 'correct-horse-battery';
const USER_ID = 'usr_password0000000000000000000000';
const ACCOUNT_LINE_KO = 'PADIEM 계정으로 로그인합니다 · 하나의 계정으로 PADIEM 서비스를 이용할 수 있어요';
const ACCOUNT_LINE_EN = 'Signing in with a PADIEM account · One account works across PADIEM services';

function storage() {
  const db = new DatabaseSync(':memory:');
  return { sql: { exec(q, ...p) { const stmt = db.prepare(q); if (stmt.columns().length) { const rows = stmt.all(...p); return { toArray: () => rows }; } stmt.run(...p); return { toArray: () => [] }; } },
    transactionSync(fn) { db.exec('BEGIN'); try { const out = fn(); db.exec('COMMIT'); return out; } catch (e) { db.exec('ROLLBACK'); throw e; } } };
}

async function setup() {
  const signing = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const refreshKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(8), 'AES-GCM', false, ['encrypt', 'decrypt']);
  const identityKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(9), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const publicSigning = await crypto.subtle.exportKey('jwk', signing.publicKey); publicSigning.kid = 'auth';
  const clientKey = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const publicClient = await crypto.subtle.exportKey('jwk', clientKey.publicKey); publicClient.kid = 'client';
  const objects = new Map();
  let queue = Promise.resolve();
  const authority = withProductBoundary({
    async resolve_or_create_product_link(v) {
      return { ok: true, link: { state: 'active', product_id: v.product_id, product_user_id: v.product_user_id, canonical_subject_id: 'sub_existing' } };
    },
  });
  const stateFor = (id) => {
    if (!objects.has(id)) {
      const state = { storage: storage(), blockConcurrencyWhile(fn) { const next = queue.then(fn); queue = next.catch(() => {}); return next; } };
      objects.set(id, id === 'google-account-registry' ? new AuthStateObject(state, { IDENTITY_AUTHORITY: authority }) : new AuthState(state));
    }
    return objects.get(id);
  };
  const app = createApp({
    clients: {
      // The production client id the LoveTree pages send.
      'lovetree-4-0': { id: 'lovetree-4-0', password_login: true, redirect_uris: [REDIRECT], jwks: { keys: [publicClient] } },
      'brandless': { id: 'brandless', password_login: true, redirect_uris: [REDIRECT], jwks: { keys: [publicClient] } },
      plain: { id: 'plain', redirect_uris: [REDIRECT], jwks: { keys: [publicClient] } },
    },
    googleClientId: 'google-client', googleClientSecret: 'synthetic', identityKey, refreshKey,
    adminSecret: 'synthetic-admin-secret', accountDeleteRpcSecret: 'synthetic-account-delete-secret-32chars',
    passwordRpcSecret: 'synthetic-password-rpc-secret-32chars-min', passwordRpcOrigin: 'https://chat.padiem.net',
    signingKey: signing.privateKey, signingKid: 'auth', jwks: { keys: [publicSigning] },
    stateFor, now: () => 1000,
    async fetcher(address, options) {
      const path = new URL(address).pathname;
      if (path === '/internal/password-verify') {
        const payload = JSON.parse(Buffer.from(options.body).toString());
        if (payload.password === PASSWORD) return Response.json({ ok: true, product_user_id: USER_ID, credential_epoch: '2026-11-12T00:00:00+00:00' });
        return Response.json({ error: { code: 'invalid_credentials' } }, { status: 401 });
      }
      if (path === '/internal/password-register') {
        return Response.json({ error: { code: 'account_exists' } }, { status: 409 });
      }
      throw new Error('unexpected fetch ' + address);
    },
  });
  async function begin(path = '/login', clientId = 'lovetree-4-0', extra = {}, headers = {}) {
    const verifier = rand(), state = rand();
    const q = new URLSearchParams({ client_id: clientId, redirect_uri: extra.redirect_uri || REDIRECT, state, code_challenge: await sum(verifier), code_challenge_method: 'S256' });
    if (extra.lt_theme) q.set('lt_theme', extra.lt_theme);
    const response = await app.fetch(new Request(`${url}${path}?${q}`, { headers }));
    const html = await response.text();
    const actionPath = path === '/signup' ? '/signup/password' : '/login/password';
    const match = html.match(new RegExp(actionPath.replace('/', '\\/') + '\\?state=([A-Za-z0-9._%-]+)'));
    return { response, html, cookie: response.headers.get('set-cookie')?.split(';')[0] || '', formState: match ? decodeURIComponent(match[1]) : '' };
  }
  const postForm = (actionPath, formState, cookie, fields, headers = {}) => app.fetch(new Request(
    `${url}${actionPath}?state=${encodeURIComponent(formState)}`,
    { method: 'POST', headers: { 'content-type': 'application/x-www-form-urlencoded', cookie, ...headers }, body: new URLSearchParams(fields) },
  ));
  return { app, begin, postForm, stateObjects: objects };
}

// Every URL the rendered page would fetch: src/href and CSS url().
function referencedUrls(html) {
  const refs = [];
  for (const match of html.matchAll(/(?:src|href)="([^"]+)"|url\('([^']+)'\)/g)) refs.push(match[1] || match[2]);
  return refs;
}

function assertNoExternalRequest(html) {
  const external = referencedUrls(html).filter((value) => /^(?:[a-z]+:)?\/\//i.test(value) && !value.startsWith('//assets/'));
  assert.deepEqual(external, [], `external request(s): ${external.join(', ')}`);
  assert.ok(!html.includes('fonts.googleapis.com'));
  assert.ok(!html.includes('fonts.gstatic.com'));
}

test('lovetree night: brand skin, official Google mark, PADIEM account line, zero external requests', async () => {
  const f = await setup();
  const page = await f.begin('/login', 'lovetree-4-0');
  assert.equal(page.response.status, 200);
  const html = page.html;
  assert.ok(html.includes('<body class="night">'));
  assert.ok(html.includes('LoveTree에 로그인'));
  assert.ok(html.includes('PADIEM 계정'));
  assert.ok(html.includes('Google 계정으로 계속'));
  assert.ok(html.includes(ACCOUNT_LINE_KO));
  assert.ok(html.includes('/assets/auth-skin/googleg-standard-color.svg'));
  for (const card of ['card-1.webp', 'card-2.webp', 'card-3.webp']) assert.ok(html.includes(`/assets/auth-skin/${card}`));
  assert.ok(html.includes('/assets/auth-skin/fonts/GowunBatang-Bold.latin.woff2'));
  assert.ok(html.includes('/assets/auth-skin/fonts/Roboto-Medium.latin.woff2'));
  assertNoExternalRequest(html);

  const assets = referencedUrls(html).filter((value) => value.startsWith('/assets/auth-skin/'));
  assert.ok(assets.length >= 6, `expected the skin to reference its assets, got ${assets.length}`);
  for (const path of assets) {
    const response = await f.app.fetch(new Request(`${url}${path}`));
    assert.equal(response.status, 200, path);
    assert.ok(['font/woff2', 'image/webp', 'image/svg+xml'].includes(response.headers.get('content-type')), path);
  }
});

test('lovetree garden: garden tokens, serif heading, decision line still present', async () => {
  const f = await setup();
  const page = await f.begin('/login', 'lovetree-4-0', { lt_theme: 'garden' });
  assert.equal(page.response.status, 200);
  assert.ok(page.html.includes('<body class="garden">'));
  assert.ok(page.html.includes('--lt-google-fill:#ffffff'));
  assert.ok(page.html.includes("font-family:'Gowun Batang'"));
  assert.ok(page.html.includes(ACCOUNT_LINE_KO));
  assertNoExternalRequest(page.html);
});

test('lt_theme missing or invalid stays on night; night is explicit too', async () => {
  const f = await setup();
  for (const extra of [{}, { lt_theme: 'evil' }, { lt_theme: 'NIGHT ' }, { lt_theme: 'day' }]) {
    const page = await f.begin('/login', 'lovetree-4-0', extra);
    assert.ok(page.html.includes('<body class="night">'), JSON.stringify(extra));
    assert.ok(!page.html.includes('<body class="garden">'));
  }
  const night = await f.begin('/login', 'lovetree-4-0', { lt_theme: 'night' });
  assert.ok(night.html.includes('<body class="night">'));
});

test('the signed-in skin is chosen only by the registered client_id, never by the address', async () => {
  const f = await setup();
  // A registered client without a brand entry keeps the plain PADIEM screen,
  // even when the URL asks for the LoveTree variant or a brand name.
  const brandless = await f.begin('/login', 'brandless', { lt_theme: 'garden' });
  assert.equal(brandless.response.status, 200);
  assert.ok(brandless.html.includes('PADIEM 로그인'));
  assert.ok(!brandless.html.includes('LoveTree'));
  assert.ok(brandless.html.includes(ACCOUNT_LINE_KO));

  // Copying another client's id fails its own redirect_uri check.
  const copied = await f.begin('/login', 'lovetree-4-0', { redirect_uri: 'https://brandless.example/auth/callback' });
  assert.equal(copied.response.status, 400);
  assert.deepEqual(JSON.parse(copied.html), { error: 'invalid_request' });

  // An unregistered client_id is still rejected and renders no screen.
  const unknown = await f.begin('/login', 'lovetree-9-9', { lt_theme: 'garden' });
  assert.equal(unknown.response.status, 400);

  // A service query parameter does not select a skin.
  const verifier = rand(), state = rand();
  const q = new URLSearchParams({ client_id: 'brandless', redirect_uri: REDIRECT, state, code_challenge: await sum(verifier), code_challenge_method: 'S256', service: 'lovetree-4-0' });
  const serviced = await f.app.fetch(new Request(`${url}/login?${q}`));
  const servicedHtml = await serviced.text();
  assert.equal(serviced.status, 200);
  assert.ok(!servicedHtml.includes('LoveTree'));
});

test('the existing redirect_uri allowlist keeps deciding where the flow returns', async () => {
  const f = await setup();
  const rejected = await f.begin('/login', 'lovetree-4-0', { redirect_uri: 'https://evil.example/auth/callback' });
  assert.equal(rejected.response.status, 400);
  const accepted = await f.begin('/login', 'lovetree-4-0');
  const done = await f.postForm('/login/password', accepted.formState, accepted.cookie, { email: 'user@example.invalid', password: PASSWORD, lt_theme: 'garden' });
  assert.equal(done.status, 302);
  const target = new URL(done.headers.get('location'));
  assert.equal(target.origin + target.pathname, REDIRECT);
  assert.ok(target.searchParams.get('code'));
});

test('signup uses the same brand card, theme carry and decision line', async () => {
  const f = await setup();
  const page = await f.begin('/signup', 'lovetree-4-0', { lt_theme: 'garden' });
  assert.equal(page.response.status, 200);
  assert.ok(page.html.includes('<body class="garden">'));
  assert.ok(page.html.includes('이메일로 회원가입'));
  assert.ok(!page.html.includes('PADIEM 계정 하나로 LoveTree와 Chat을 함께 써요.'));
  assert.ok(page.html.includes(ACCOUNT_LINE_KO));
  assert.ok(page.html.includes('name="name"'));
  const loginHref = page.html.match(/class="alt-link" href="([^"]+)"/)?.[1] || '';
  assert.ok(loginHref.startsWith('/login?'));
  assert.ok(loginHref.includes('lt_theme=garden'));
  assertNoExternalRequest(page.html);
});

test('the brand screens state PADIEM only in the eyebrow and the footer', async () => {
  const f = await setup();
  for (const path of ['/login', '/signup']) {
    const page = await f.begin(path, 'lovetree-4-0');
    assert.equal(page.response.status, 200, path);
    assert.ok(page.html.includes('<p class="eyebrow">PADIEM 계정</p>'), path);
    assert.ok(page.html.includes(ACCOUNT_LINE_KO), path);
    assert.ok(!page.html.includes('class="lead"'), path);
    assert.ok(!page.html.includes('PADIEM 계정으로 Chat'), path);
    assert.ok(!page.html.includes('PADIEM 계정 하나로 LoveTree'), path);
  }
});

test('a failed email login re-renders the same brand without trusting the submitted brand', async () => {
  const f = await setup();
  const begun = await f.begin('/login', 'lovetree-4-0', { lt_theme: 'garden' });
  const done = await f.postForm('/login/password', begun.formState, begun.cookie, {
    email: 'user@example.invalid', password: 'wrong-password', lt_theme: 'garden',
  });
  assert.equal(done.status, 200);
  const html = await done.text();
  assert.ok(html.includes('<body class="garden">'));
  assert.ok(html.includes('LoveTree에 로그인'));
  assert.ok(html.includes('이메일 또는 비밀번호가 올바르지 않습니다.'));
  assert.ok(html.includes(ACCOUNT_LINE_KO));
  assert.ok(!html.includes('Google 계정으로 계속'), 'the error page has no rebuilt Google href');

  // A tampered theme value cannot leave the registered brand's two themes.
  const second = await f.begin('/login', 'lovetree-4-0', { lt_theme: 'garden' });
  const tampered = await f.postForm('/login/password', second.formState, second.cookie, {
    email: 'user@example.invalid', password: 'wrong-password', lt_theme: 'evil',
  });
  const tamperedHtml = await tampered.text();
  assert.ok(tamperedHtml.includes('<body class="night">'));
  assert.ok(tamperedHtml.includes('LoveTree에 로그인'));
});

test('the PADIEM account line is present in Korean and English on every screen', async () => {
  const f = await setup();
  const en = { 'accept-language': 'en-US,en;q=0.9,ko;q=0.8' };
  const loginEn = await f.begin('/login', 'lovetree-4-0', {}, en);
  assert.ok(loginEn.html.includes('<html lang="en">'));
  assert.ok(loginEn.html.includes('Sign in to LoveTree'));
  assert.ok(loginEn.html.includes(ACCOUNT_LINE_EN));
  assert.ok(loginEn.html.includes('Continue with Google'));
  assert.ok(!loginEn.html.includes('One PADIEM account also works'));

  const signupEn = await f.begin('/signup', 'lovetree-4-0', {}, en);
  assert.ok(signupEn.html.includes(ACCOUNT_LINE_EN));

  const brandlessEn = await f.begin('/login', 'brandless', {}, en);
  assert.ok(brandlessEn.html.includes(ACCOUNT_LINE_EN));

  const ko = await f.begin('/login', 'lovetree-4-0');
  assert.ok(ko.html.includes('<html lang="ko">'));

  const begun = await f.begin('/login', 'lovetree-4-0');
  const failed = await f.postForm('/login/password', begun.formState, begun.cookie, { email: 'user@example.invalid', password: 'nope' }, en);
  assert.ok((await failed.text()).includes(ACCOUNT_LINE_EN));
});

test('a Google-only client still redirects straight to Google', async () => {
  const f = await setup();
  const plain = await f.begin('/login', 'plain');
  assert.equal(plain.response.status, 302);
  assert.ok(plain.response.headers.get('location').startsWith('https://accounts.google.com/o/oauth2/v2/auth'));
});

test('skin assets are served from the auth origin and unknown names are 404', async () => {
  const f = await setup();
  const known = await f.app.fetch(new Request(`${url}/assets/auth-skin/fonts/Roboto-Medium.latin.woff2`));
  assert.equal(known.status, 200);
  assert.equal(known.headers.get('content-type'), 'font/woff2');
  assert.ok(known.headers.get('cache-control').includes('max-age'));
  assert.ok((await known.arrayBuffer()).byteLength > 0);
  const svg = await f.app.fetch(new Request(`${url}/assets/auth-skin/googleg-standard-color.svg`));
  assert.equal(svg.status, 200);
  assert.equal(svg.headers.get('content-type'), 'image/svg+xml');
  const missing = await f.app.fetch(new Request(`${url}/assets/auth-skin/nope.webp`));
  assert.equal(missing.status, 404);
  assert.equal(f.stateObjects.size, 0);
});

test('the generated base64 module matches the checked-in static files', () => {
  const files = {
    'card-1.webp': 'assets/card-1.webp',
    'card-2.webp': 'assets/card-2.webp',
    'card-3.webp': 'assets/card-3.webp',
    'googleg-standard-color.svg': 'assets/googleg-standard-color.svg',
    'fonts/GowunBatang-Bold.latin.woff2': 'assets/fonts/GowunBatang-Bold.latin.woff2',
    'fonts/Roboto-Medium.latin.woff2': 'assets/fonts/Roboto-Medium.latin.woff2',
    'fonts/Roboto-Medium.latin-ext.woff2': 'assets/fonts/Roboto-Medium.latin-ext.woff2',
  };
  assert.deepEqual(Object.keys(AUTH_SKIN_ASSETS).sort(), Object.keys(files).sort());
  for (const [name, file] of Object.entries(files)) {
    const raw = readFileSync(join(STATIC, file)).toString('base64');
    assert.equal(AUTH_SKIN_ASSETS[name].base64, raw, `${name} is stale; run tools/build-auth-skin-assets.mjs`);
  }
});

test('brand, theme and language resolution are closed tables', () => {
  assert.equal(resolveBrand('lovetree-4-0'), AUTH_BRANDS['lovetree-4-0']);
  assert.equal(resolveBrand('b62'), null);
  assert.equal(resolveBrand('__proto__'), null);
  assert.equal(resolveTheme(AUTH_BRANDS['lovetree-4-0'], 'garden'), 'garden');
  assert.equal(resolveTheme(AUTH_BRANDS['lovetree-4-0'], ''), 'night');
  assert.equal(resolveTheme(AUTH_BRANDS['lovetree-4-0'], 'evil'), 'night');
  assert.equal(resolveTheme(null, 'garden'), '');
  assert.equal(resolveLang(''), 'ko');
  assert.equal(resolveLang('ko-KR,ko;q=0.9'), 'ko');
  assert.equal(resolveLang('en-US,en;q=0.9,ko;q=0.8'), 'en');
  assert.equal(resolveLang('fr-FR,en;q=0.4'), 'en');
  assert.equal(resolveLang('fr-FR'), 'ko');
});
