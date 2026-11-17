#!/usr/bin/env node
// Local screenshots of the #7818 age-confirm gate across skins, viewports and
// checkbox states. Boots the real Worker with synthetic Google keys and
// in-memory state (no real login, no operations account), serves the gate plus
// the matching login screen from a local HTTP server, and records computed
// styles/geometry so the visual verdicts are checkable without guessing.
//
// Usage: node apps/padiem-auth/tools/shoot-age-confirm.mjs [output-folder]
// playwright is not a repository dependency: set PLAYWRIGHT_ROOT if the global
// install is not found.
import { execSync } from 'node:child_process';
import { createServer } from 'node:http';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../state.mjs';
import { createApp, AuthStateObject } from '../worker.mjs';
import { createSkinHarness } from '../test/skin-harness.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const app = join(here, '..');
const shots = resolve(process.argv[2] || join(tmpdir(), 'padiem-age-confirm-shots'));
const url = 'https://auth.padiem.net';

function playwrightRoot() {
  const candidates = [process.env.PLAYWRIGHT_ROOT, join(app, 'node_modules', 'playwright')];
  for (const shell of [undefined, 'cmd.exe']) {
    try {
      const root = execSync('npm root -g', { encoding: 'utf8', ...(shell ? { shell } : {}) }).trim();
      if (root) candidates.push(join(root, 'playwright'), join(root, 'playwright-core'));
    } catch { /* npm absent: fall through to the explicit candidates */ }
  }
  const found = candidates.find((path) => path && existsSync(join(path, 'package.json')));
  if (!found) throw new Error('playwright not found; set PLAYWRIGHT_ROOT to its install directory');
  return found;
}

const b64 = (x) => Buffer.from(x).toString('base64url');
const j64 = (x) => b64(JSON.stringify(x));
const sum = async (x) => b64(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(x)));
const rand = () => b64(crypto.getRandomValues(new Uint8Array(32)));

function storage() {
  const db = new DatabaseSync(':memory:');
  return {
    sql: { exec(q, ...p) { const s = db.prepare(q); if (s.columns().length) { const rows = s.all(...p); return { toArray: () => rows }; } s.run(...p); return { toArray: () => [] }; } },
    transactionSync(fn) { db.exec('BEGIN'); try { const out = fn(); db.exec('COMMIT'); return out; } catch (e) { db.exec('ROLLBACK'); throw e; } },
  };
}

// Drives a first Google login through the synthetic token endpoint until the
// 14-or-older gate is the response. Mirrors test/google-age-confirm-7818.test.mjs.
async function renderGate(clientId, theme, lang) {
  const subject = `shot-${clientId}-${theme || 'default'}-${lang}`;
  const google = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
  const googleJwk = await crypto.subtle.exportKey('jwk', google.publicKey); googleJwk.kid = 'google';
  const signing = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const client = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const publicClient = await crypto.subtle.exportKey('jwk', client.publicKey); publicClient.kid = 'client';
  const publicSigning = await crypto.subtle.exportKey('jwk', signing.publicKey); publicSigning.kid = 'auth';
  const refreshKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(8), 'AES-GCM', false, ['encrypt', 'decrypt']);
  const identityKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(9), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  let nonce = '';
  const authority = { async resolve_or_create_product_link() { return { ok: true, link: { state: 'active', product_id: 'p', product_user_id: 'u', canonical_subject_id: 'sub_shot' } }; } };
  const objects = new Map();
  const stateFor = (id) => {
    if (!objects.has(id)) {
      let queue = Promise.resolve();
      const state = { storage: storage(), blockConcurrencyWhile(fn) { const next = queue.then(fn); queue = next.catch(() => {}); return next; } };
      objects.set(id, id === 'google-account-registry' ? new AuthStateObject(state, { IDENTITY_AUTHORITY: authority }) : new AuthState(state));
    }
    return objects.get(id);
  };
  const app = createApp({
    clients: { [clientId]: { id: clientId, redirect_uris: ['https://client.example.invalid/callback'], jwks: { keys: [publicClient] } } },
    googleClientId: 'google-client', googleClientSecret: 'synthetic', identityKey, refreshKey,
    adminSecret: 'synthetic-admin-secret', accountDeleteRpcSecret: 'synthetic-account-delete-secret-32chars',
    signingKey: signing.privateKey, signingKid: 'auth', jwks: { keys: [publicSigning] },
    stateFor, now: () => 1000,
    async fetcher(address) {
      if (String(address).includes('/certs')) return Response.json({ keys: [googleJwk] });
      if (String(address).includes('/oauth2.googleapis.com/token')) {
        const h = j64({ alg: 'RS256', kid: 'google' });
        const p = j64({ iss: 'https://accounts.google.com', aud: 'google-client', sub: subject, nonce, iat: 999, exp: 1100 });
        const input = `${h}.${p}`;
        const sig = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', google.privateKey, new TextEncoder().encode(input));
        return Response.json({ id_token: `${input}.${b64(sig)}` });
      }
      throw new Error('unexpected fetch ' + address);
    },
  });
  const params = new URLSearchParams({ client_id: clientId, redirect_uri: 'https://client.example.invalid/callback', state: rand(), code_challenge: await sum(rand()), code_challenge_method: 'S256' });
  if (theme) params.set('lt_theme', theme);
  const begin = await app.fetch(new Request(`${url}/login/google?${params}`, { headers: { 'accept-language': lang } }));
  if (begin.status !== 302) throw new Error(`google login begin ${begin.status} for ${clientId}`);
  const googleURL = new URL(begin.headers.get('location'));
  nonce = googleURL.searchParams.get('nonce');
  const cb = new URL(`${url}/oauth/google/callback`);
  cb.searchParams.set('state', googleURL.searchParams.get('state'));
  cb.searchParams.set('code', 'synthetic-code');
  const cookie = begin.headers.get('set-cookie').split(';')[0];
  const response = await app.fetch(new Request(cb, { headers: { cookie, 'accept-language': lang } }));
  const html = await response.text();
  if (response.status !== 200 || !html.includes('age_confirm')) {
    throw new Error(`gate not rendered for ${clientId}/${theme}: ${response.status}`);
  }
  return html;
}

const VARIANTS = [
  { key: 'chat-light', clientId: 'b62', theme: '', lang: 'ko' },
  { key: 'chat-dark', clientId: 'b62', theme: 'dark', lang: 'ko' },
  { key: 'lovetree-night', clientId: 'lovetree-4-0', theme: 'night', lang: 'ko' },
  { key: 'lovetree-garden', clientId: 'lovetree-4-0', theme: 'garden', lang: 'ko' },
  { key: 'plain', clientId: 'brandless', theme: '', lang: 'ko' },
];

const harness = await createSkinHarness();
const gates = new Map();
const logins = new Map();
for (const v of VARIANTS) {
  gates.set(v.key, await renderGate(v.clientId, v.theme, v.lang));
  const page = await harness.begin('/login', v.clientId, v.theme ? { lt_theme: v.theme } : {});
  logins.set(v.key, page.html);
}

const server = createServer(async (req, res) => {
  const target = new URL(req.url, 'http://127.0.0.1');
  try {
    if (target.pathname === '/gate' || target.pathname === '/login') {
      const map = target.pathname === '/gate' ? gates : logins;
      const html = map.get(target.searchParams.get('v'));
      if (!html) { res.writeHead(404); res.end('missing variant'); return; }
      res.writeHead(200, { 'content-type': 'text/html;charset=utf-8' });
      res.end(html);
      return;
    }
    const response = await harness.app.fetch(new Request(`${url}${target.pathname}${target.search}`));
    res.writeHead(response.status, Object.fromEntries(response.headers));
    res.end(Buffer.from(await response.arrayBuffer()));
  } catch (error) {
    res.writeHead(500, { 'content-type': 'text/plain' });
    res.end(String(error));
  }
});
await new Promise((done) => server.listen(0, '127.0.0.1', done));
const origin = `http://127.0.0.1:${server.address().port}`;

const playwright = await import(pathToFileURL(resolve(playwrightRoot(), 'index.js')).href);
const { chromium } = playwright.default ?? playwright;
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || 'chrome' });
mkdirSync(shots, { recursive: true });

const measurePage = (isLogin) => {
  const cs = (el) => el ? getComputedStyle(el) : null;
  const box = (el) => { if (!el) return null; const r = el.getBoundingClientRect(); return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) }; };
  if (isLogin) {
    const btn = document.querySelector('.btn.primary.submit') || document.querySelector('.btn.btn-primary') || document.querySelector('.btn');
    const b = cs(btn);
    return { btn: { h: box(btn)?.h, radius: b?.borderRadius, size: b?.fontSize, weight: b?.fontWeight } };
  }
  const title = document.querySelector('#age-confirm-title') || document.querySelector('h1');
  const eyebrow = document.querySelector('.eyebrow');
  const notice = document.querySelector('.notice') || document.querySelector('.padiem-notice');
  const btn = document.querySelector('#signupSubmit');
  const check = document.querySelector('#ageConfirm');
  const label = document.querySelector('.check') || document.querySelector('.padiem-check');
  const card = document.querySelector('.auth-card') || document.querySelector('main');
  const t = cs(title), n = cs(notice), b = cs(btn), c = cs(check);
  return {
    viewportW: window.innerWidth,
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
    card: box(card),
    eyebrowToTitleGap: (eyebrow && title) ? box(title).y - (box(eyebrow).y + box(eyebrow).h) : null,
    title: { font: t?.fontFamily, size: t?.fontSize, weight: t?.fontWeight },
    notice: { font: n?.fontFamily, size: n?.fontSize },
    bodyFont: cs(document.body)?.fontFamily,
    btn: { h: box(btn)?.h, radius: b?.borderRadius, size: b?.fontSize, weight: b?.fontWeight, disabled: btn?.disabled },
    check: { w: box(check)?.w, h: box(check)?.h, border: c?.border, background: c?.backgroundColor, appearance: c?.appearance, accent: c?.accentColor, checked: check?.checked },
    labelH: box(label)?.h,
  };
};

const rows = [];
for (const v of VARIANTS) {
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: width === 1440 ? 900 : 844 }, deviceScaleFactor: 1, reducedMotion: 'reduce', colorScheme: 'light' });
    const external = [];
    context.on('request', (request) => {
      const u = request.url();
      if (!u.startsWith(origin) && !u.startsWith('data:') && !u.startsWith('blob:')) external.push(u);
    });
    for (const checked of [false, true]) {
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(String(e)));
      await page.goto(`${origin}/gate?v=${v.key}`, { waitUntil: 'load' });
      await page.evaluate(() => document.fonts.ready);
      if (checked) await page.locator('#ageConfirm').check();
      await page.waitForTimeout(150);
      const name = `age-${v.key}-${width}-${checked ? 'checked' : 'unchecked'}`;
      await page.screenshot({ path: join(shots, `${name}.png`), fullPage: true });
      const measured = await page.evaluate(measurePage, false);
      await page.locator('#ageConfirm').focus();
      measured.focus = await page.evaluate(() => {
        const el = document.querySelector('#ageConfirm');
        const s = getComputedStyle(el);
        return { focusVisible: el.matches(':focus-visible'), outline: `${s.outlineStyle} ${s.outlineWidth} ${s.outlineColor}` };
      });
      rows.push({ name, variant: v.key, width, checked, ...measured, errors, external: [...external] });
      await page.close();
    }
    const loginPage = await context.newPage();
    await loginPage.goto(`${origin}/login?v=${v.key}`, { waitUntil: 'load' });
    await loginPage.evaluate(() => document.fonts.ready);
    const loginBtn = await loginPage.evaluate(measurePage, true);
    rows.push({ name: `login-${v.key}-${width}`, variant: v.key, width, loginBtn });
    await loginPage.close();
    await context.close();
  }
}
await browser.close();
server.close();
writeFileSync(join(shots, 'measurements.json'), JSON.stringify(rows, null, 2));
for (const row of rows) {
  if (row.loginBtn) {
    console.log(`LOGIN ${row.variant} ${row.width}: btn ${JSON.stringify(row.loginBtn.btn)}`);
  } else {
    console.log(`${row.name}: title ${row.title.size}/${row.title.weight} ${row.title.font?.split(',')[0]} | body ${row.bodyFont?.split(',')[0]} | eyebrow-gap ${row.eyebrowToTitleGap} | scroll ${row.scrollW}/${row.clientW} | btn h${row.btn.h} r${row.btn.radius} ${row.btn.size}/${row.btn.weight} | check ${row.check.w}x${row.check.h} ${row.check.border} bg=${row.check.background} | focus ${row.focus?.outline} (${row.focus?.focusVisible}) | err ${row.errors.length} ext ${row.external.length}`);
  }
}
console.log(`wrote ${rows.filter((r) => !r.loginBtn).length} screenshots + measurements.json to ${shots}`);
