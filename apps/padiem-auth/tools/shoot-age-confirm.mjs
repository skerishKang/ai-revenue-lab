#!/usr/bin/env node
// Local screenshots of the #7818 auth flow across skins, viewports and screens.
// Boots the real Worker with synthetic Google keys and in-memory state (no real
// login, no operations account), serves login/signup/age-confirm from a local
// HTTP server, and records computed styles/geometry for the visual verdicts.
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
const shots = resolve(process.argv[2] || join(tmpdir(), 'padiem-auth-flow-shots'));
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
const screens = { login: new Map(), signup: new Map(), age: new Map() };
for (const v of VARIANTS) {
  screens.age.set(v.key, await renderGate(v.clientId, v.theme, v.lang));
  const extra = v.theme ? { lt_theme: v.theme } : {};
  screens.login.set(v.key, (await harness.begin('/login', v.clientId, extra)).html);
  screens.signup.set(v.key, (await harness.begin('/signup', v.clientId, extra)).html);
}

const server = createServer(async (req, res) => {
  const target = new URL(req.url, 'http://127.0.0.1');
  try {
    if (['/login', '/signup', '/age'].includes(target.pathname)) {
      const map = screens[target.pathname.slice(1)];
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

const measurePage = () => {
  const cs = (el) => el ? getComputedStyle(el) : null;
  const box = (el) => { if (!el) return null; const r = el.getBoundingClientRect(); return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) }; };
  const title = document.querySelector('#age-confirm-title') || document.querySelector('h1');
  const eyebrow = document.querySelector('.eyebrow');
  const btn = document.querySelector('button.btn.primary.submit')
    || document.querySelector('button#signupSubmit')
    || document.querySelector('button.btn.btn-primary')
    || document.querySelector('button.btn');
  const check = document.querySelector('#ageConfirm');
  const label = document.querySelector('.check') || document.querySelector('.padiem-check');
  const card = document.querySelector('.auth-card') || document.querySelector('main');
  const t = cs(title), b = cs(btn), c = cs(check);
  return {
    viewportW: window.innerWidth,
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
    card: box(card),
    eyebrowToTitleGap: (eyebrow && title) ? box(title).y - (box(eyebrow).y + box(eyebrow).h) : null,
    title: { font: t?.fontFamily, size: t?.fontSize, weight: t?.fontWeight },
    bodyFont: cs(document.body)?.fontFamily,
    btn: { font: b?.fontFamily, size: b?.fontSize, weight: b?.fontWeight, h: box(btn)?.h, radius: b?.borderRadius, disabled: btn?.disabled },
    check: check ? { w: box(check)?.w, h: box(check)?.h, border: c?.border, background: c?.backgroundColor, checked: check.checked } : null,
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
    for (const screen of ['login', 'signup', 'age']) {
      const states = screen === 'age' ? ['unchecked', 'checked'] : ['default'];
      for (const state of states) {
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', (e) => errors.push(String(e)));
        await page.goto(`${origin}/${screen}?v=${v.key}`, { waitUntil: 'load' });
        await page.evaluate(() => document.fonts.ready);
        if (state === 'checked') await page.locator('#ageConfirm').check();
        await page.waitForTimeout(150);
        const name = `${screen}-${v.key}-${width}${state === 'default' ? '' : `-${state}`}`;
        await page.screenshot({ path: join(shots, `${name}.png`), fullPage: true });
        const measured = await page.evaluate(measurePage);
        measured.renderedFont = await (async () => {
          const cdp = await context.newCDPSession(page);
          await cdp.send('DOM.enable');
          await cdp.send('CSS.enable');
          const { root } = await cdp.send('DOM.getDocument');
          const fontsFor = async (selector) => {
            const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector });
            if (!nodeId) return null;
            return (await cdp.send('CSS.getPlatformFontsForNode', { nodeId })).fonts
              .map((font) => `${font.familyName} (${font.glyphCount} glyphs)`);
          };
          const title = await fontsFor('#age-confirm-title, h1');
          const button = await fontsFor('button.btn.primary.submit, button.btn.btn-primary, button#signupSubmit');
          await cdp.detach();
          return { title, button };
        })();
        if (screen === 'age') {
          await page.locator('#ageConfirm').focus();
          measured.focus = await page.evaluate(() => {
            const el = document.querySelector('#ageConfirm');
            const s = getComputedStyle(el);
            return { focusVisible: el.matches(':focus-visible'), outline: `${s.outlineStyle} ${s.outlineWidth} ${s.outlineColor}` };
          });
        }
        rows.push({ name, screen, variant: v.key, width, state, ...measured, errors, external: [...external] });
        await page.close();
      }
    }
    await context.close();
  }
}
await browser.close();
server.close();
writeFileSync(join(shots, 'measurements.json'), JSON.stringify(rows, null, 2));
for (const row of rows) {
  console.log(`${row.name}: title ${row.title.size}/${row.title.weight} rendered=${JSON.stringify(row.renderedFont?.title)} | body ${row.bodyFont?.split(',')[0]} | btn ${row.btn.size}/${row.btn.weight} rendered=${JSON.stringify(row.renderedFont?.button)} h${row.btn.h} r${row.btn.radius} | scroll ${row.scrollW}/${row.clientW} | err ${row.errors.length} ext ${row.external.length}`);
}
console.log(`wrote ${rows.length} screenshots + measurements.json to ${shots}`);
