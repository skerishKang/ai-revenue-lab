#!/usr/bin/env node
// Screenshots of the real auth Worker skin for docs/auth-skin-347.
//
// Boots the Worker in a local HTTP server (synthetic clients, no real login),
// then shoots the LoveTree login screen in both themes at 1440 and 390 while
// recording every request so an external one would fail the run. Also prints
// the measured photo boxes, which is how the "four photos, three at 390" claim
// is checked without looking at pixels.
//
// Usage: node apps/padiem-auth/tools/shoot-auth-skin.mjs
// playwright is not a repository dependency: set PLAYWRIGHT_ROOT if the global
// install is not found.
import { execSync } from 'node:child_process';
import { createServer } from 'node:http';
import { existsSync, mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createSkinHarness } from '../test/skin-harness.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const app = join(here, '..');
const shots = join(app, 'docs', 'auth-skin-347');

function playwrightRoot() {
  const candidates = [process.env.PLAYWRIGHT_ROOT, join(app, 'node_modules', 'playwright')];
  for (const shell of [undefined, 'cmd.exe']) {
    try {
      const root = execSync('npm root -g', { encoding: 'utf8', ...(shell ? { shell } : {}) }).trim();
      if (root) candidates.push(join(root, 'playwright'));
    } catch { /* npm absent: fall through to the explicit candidates */ }
  }
  const found = candidates.find((path) => path && existsSync(join(path, 'package.json')));
  if (!found) throw new Error('playwright not found; set PLAYWRIGHT_ROOT to its install directory');
  return found;
}

const harness = await createSkinHarness();
const external = [];
const server = createServer(async (req, res) => {
  const target = new URL(req.url, 'https://auth.padiem.net');
  try {
    if (target.pathname === '/login' || target.pathname === '/signup') {
      const page = await harness.begin(target.pathname, 'lovetree-4-0', { lt_theme: target.searchParams.get('theme') || 'night' });
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

const geometry = [];
for (const width of [1440, 390]) {
  const context = await browser.newContext({ viewport: { width, height: width === 1440 ? 900 : 844 }, deviceScaleFactor: 1, reducedMotion: 'reduce' });
  context.on('request', (request) => {
    const url = request.url();
    if (!url.startsWith(origin) && !url.startsWith('data:') && !url.startsWith('blob:')) external.push(`${width} ${url}`);
  });
  for (const theme of ['night', 'garden']) {
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(String(error)));
    await page.goto(`${origin}/login?theme=${theme}`, { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(250);
    // JPEG keeps each file well under the 300 KB the PR body allows.
    await page.screenshot({ path: join(shots, `login-${theme}-${width}.jpg`), type: 'jpeg', quality: 86, fullPage: false });
    const measured = await page.evaluate(() => {
      const box = (element) => { const r = element.getBoundingClientRect(); return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) }; };
      const photos = [...document.querySelectorAll('.orbit')].map((element) => ({
        cls: element.className.replace('orbit ', ''),
        src: element.getAttribute('src').split('/').pop(),
        opacity: getComputedStyle(element).opacity,
        visible: getComputedStyle(element).display !== 'none' && element.getClientRects().length > 0,
        box: box(element),
      }));
      return { photos, card: box(document.querySelector('.auth-card')), scrollHeight: document.documentElement.scrollHeight };
    });
    geometry.push({ width, theme, errors, ...measured });
    await page.close();
  }
  await context.close();
}
await browser.close();
server.close();

for (const row of geometry) {
  const visible = row.photos.filter((photo) => photo.visible);
  console.log(`${row.width} ${row.theme}: visible ${visible.length}/4 [${visible.map((p) => `${p.cls}=${p.src}@${p.box.x},${p.box.y} ${p.box.w}x${p.box.h} a${p.opacity}`).join(' | ')}] card ${row.card.w}x${row.card.h} scroll ${row.scrollHeight}${row.errors.length ? ` errors ${row.errors.join(' | ')}` : ''}`);
}
if (external.length) {
  console.error(`external request(s): ${external.length}`);
  for (const line of external) console.error('  ' + line);
  process.exit(1);
}
console.log(`wrote ${geometry.length} screenshots to ${shots}, 0 external requests`);
