import { chromium } from 'playwright';
import { writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const WORKSPACE = join(__dirname, '..');
const SERVER_URL = 'http://127.0.0.1:8000';

const STATES = ['cover', 'chronology', 'thread', 'lineage', 'witnesses', 'reconstruction', 'mobile'];
const VIEWPORTS = [
  { width: 1440, height: 1100, label: '1440x1100' },
  { width: 768, height: 1024, label: '768x1024' },
  { width: 390, height: 844, label: '390x844' },
];

async function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function run() {
  const browser = await chromium.launch({ headless: true });
  const results = { pass: true, details: [] };

  for (const vp of VIEWPORTS) {
    const page = await browser.newPage();
    await page.setViewportSize({ width: vp.width, height: vp.height });

    const consoleErrors = [];
    const pageErrors = [];
    const failedReqs = [];
    const externalReqs = [];
    page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
    page.on('pageerror', err => pageErrors.push(err.message));
    page.on('requestfailed', req => failedReqs.push(req.url));
    page.on('request', req => {
      if (!req.url().startsWith(SERVER_URL) && !req.url().startsWith('data:') && !req.url().startsWith('http://127.0.0.1')) {
        externalReqs.push(req.url());
      }
    });

    await page.goto(SERVER_URL, { waitUntil: 'networkidle' });
    await page.waitForSelector('[data-state-target]');
    await sleep(300);

    for (const state of STATES) {
      await page.click(`[data-state-target="${state}"]`);
      await sleep(400);

      const result = await page.evaluate((s) => {
        const el = document.querySelector(`[data-state="${s}"]`);
        if (!el) return { state: s, found: false };

        // Visible check
        const visible = !el.hidden;
        const otherHidden = Array.from(document.querySelectorAll('[data-state]')).every(e => e === el ? !e.hidden : e.hidden);

        // Tab state
        const tab = document.querySelector(`[data-state-target="${s}"]`);
        const ariaSelected = tab?.getAttribute('aria-selected');
        const isActive = tab?.classList.contains('is-active');

        // Overflow
        const htmlOverflow = document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2;

        // Text overflow
        const textOverflows = [];
        el.querySelectorAll('h1, h2, h3, p, b, span, figcaption, li, time, dd, dt, strong, em, small').forEach(e => {
          if (e.scrollWidth > e.clientWidth + 2) {
            textOverflows.push({ tag: e.tagName, text: e.textContent.trim().slice(0, 40), sw: e.scrollWidth, cw: e.clientWidth });
          }
        });

        // Check failing chronology event specifically
        let chronologyEventOk = true;
        if (s === 'chronology') {
          const events = el.querySelectorAll('.event');
          events.forEach(ev => {
            if (ev.scrollWidth > ev.clientWidth + 2) chronologyEventOk = false;
          });
        }

        return {
          state: s,
          found: true,
          visible, otherHidden, ariaSelected, isActive, htmlOverflow,
          textOverflowCount: textOverflows.length,
          textOverflows,
          chronologyEventOk,
        };
      }, state);

      if (!result.visible || !result.otherHidden || result.ariaSelected !== 'true' ||
          !result.htmlOverflow || result.textOverflowCount > 0 || (state === 'chronology' && !result.chronologyEventOk)) {
        results.pass = false;
        results.details.push({ viewport: vp.label, state, ...result });
      }
    }

    if (consoleErrors.length || pageErrors.length || failedReqs.length || externalReqs.length) {
      results.pass = false;
      results.details.push({ viewport: vp.label, errors: { console: consoleErrors, page: pageErrors, failed: failedReqs, external: externalReqs } });
    }

    await page.close();
  }

  console.log(JSON.stringify(results, null, 2));
  if (results.pass) console.log('\n=== 21/21 ALL PASS ===');
  else console.log('\n=== FAILURES DETECTED ===');
  await browser.close();
  process.exit(results.pass ? 0 : 1);
}

run().catch(e => { console.error(e); process.exit(1); });
