#!/usr/bin/env node
// Local screenshots of the screens that follow the login and signup forms
// (#7679), starting with the signup confirmation screen.
//
// Boots the Worker in a local HTTP server (synthetic clients, a synthetic
// signup, no real account, no mail), then shoots each screen at 1440 and 390,
// plain and inside the LoveTree skin. Any request that leaves the local server
// is blocked and fails the run. Nothing is written into the repository: the
// output folder is the first argument, or a folder under the OS temp dir.
//
// Usage: node apps/padiem-auth/tools/shoot-auth-flow.mjs [output-folder]
// playwright is not a repository dependency: set PLAYWRIGHT_ROOT to a
// playwright or playwright-core install if the global one is not found.
import { execSync } from 'node:child_process';
import { createServer } from 'node:http';
import { existsSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createSkinHarness, EN } from '../test/skin-harness.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const shots = resolve(process.argv[2] || join(tmpdir(), 'padiem-auth-flow-shots'));

function playwrightRoot() {
  const candidates = [process.env.PLAYWRIGHT_ROOT, join(here, '..', 'node_modules', 'playwright')];
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

const SCREENS = [
  { name: 'signup-complete-plain-ko', client: 'brandless', theme: '', lang: 'ko' },
  { name: 'signup-complete-plain-en', client: 'brandless', theme: '', lang: 'en' },
  { name: 'signup-complete-lovetree-night-ko', client: 'lovetree-4-0', theme: 'night', lang: 'ko' },
  { name: 'signup-complete-lovetree-garden-en', client: 'lovetree-4-0', theme: 'garden', lang: 'en' },
];

const harness = await createSkinHarness();
let people = 0;
const server = createServer(async (req, res) => {
  const target = new URL(req.url, 'https://auth.padiem.net');
  try {
    if (target.pathname === '/signup-complete') {
      // A new synthetic person per shot: a second signup with one address is refused.
      const page = await harness.signup(`minji.kim+${++people}@example.com`, target.searchParams.get('client'),
        { lt_theme: target.searchParams.get('theme') || '' }, target.searchParams.get('lang') === 'en' ? EN : {});
      res.writeHead(page.response.status, { 'content-type': 'text/html;charset=utf-8' });
      res.end(page.html);
      return;
    }
    const response = await harness.app.fetch(new Request(`https://auth.padiem.net${target.pathname}${target.search}`));
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

const external = [];
const rows = [];
for (const width of [1440, 390]) {
  const context = await browser.newContext({ viewport: { width, height: width === 1440 ? 900 : 844 }, deviceScaleFactor: 1, reducedMotion: 'reduce' });
  // The screen returns to the service by itself after a few seconds; that
  // address is not local, so it is refused here and counted if it is tried.
  await context.route('**/*', (route) => {
    const url = route.request().url();
    if (url.startsWith(origin) || url.startsWith('data:') || url.startsWith('blob:')) return route.continue();
    external.push(`${width} ${url}`);
    return route.abort();
  });
  for (const screen of SCREENS) {
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(String(error)));
    const query = new URLSearchParams({ client: screen.client, theme: screen.theme, lang: screen.lang });
    await page.goto(`${origin}/signup-complete?${query}`, { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(250);
    await page.screenshot({ path: join(shots, `${screen.name}-${width}.jpg`), type: 'jpeg', quality: 86, fullPage: false });
    const measured = await page.evaluate(() => {
      const box = (element) => { const r = element.getBoundingClientRect(); return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) }; };
      const card = document.querySelector('main');
      const button = document.querySelector('main a');
      return {
        card: box(card), button: box(button),
        email: document.querySelector('.done-email')?.textContent || '',
        overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      };
    });
    rows.push({ width, name: screen.name, errors, ...measured });
    await page.close();
  }
  await context.close();
}
await browser.close();
server.close();

for (const row of rows) {
  console.log(`${row.width} ${row.name}: card ${row.card.w}x${row.card.h}@${row.card.x},${row.card.y} button ${row.button.w}x${row.button.h} email "${row.email}" overflow-x ${row.overflowX}${row.errors.length ? ` errors ${row.errors.join(' | ')}` : ''}`);
}
if (external.length) {
  console.error(`external request(s): ${external.length}`);
  for (const line of external) console.error('  ' + line);
  process.exit(1);
}
console.log(`wrote ${rows.length} screenshots to ${shots}, 0 external requests`);
