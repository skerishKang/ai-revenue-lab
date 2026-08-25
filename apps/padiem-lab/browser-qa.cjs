"use strict";

const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PW || 'playwright');
const routes = require('./route-registry.cjs');

const base = (process.env.BASE_URL || 'http://127.0.0.1:4173').replace(/\/$/, '');
const screenshotDir = process.env.SCREENSHOT_DIR || '';
const live = process.env.QA_MODE === 'live';
const baseOrigin = new URL(base).origin;

function isSameOrigin(url) {
  try {
    return new URL(url).origin === baseOrigin;
  } catch (_) {
    return false;
  }
}

function isExpectedB06ArtworkAbort(request, options) {
  if (!options.b06 || request.resourceType() !== 'image') return false;
  const failure = request.failure();
  return /\/b06\/assets\/images\/[^/?#]+\.svg(?:[?#].*)?$/i.test(request.url())
    && /ERR_ABORTED/i.test(failure?.errorText || '');
}

async function inspect(page, url, label, marker, options = {}) {
  const consoleErrors = [];
  const localFailures = [];
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('requestfailed', request => {
    if (!isSameOrigin(request.url()) || isExpectedB06ArtworkAbort(request, options)) return;
    const errorText = request.failure()?.errorText || 'unknown';
    localFailures.push(`${request.url()} (${errorText})`);
  });

  const response = await page.goto(url, { waitUntil: 'networkidle' });
  if (!response || response.status() !== 200) throw new Error(`${label} HTTP ${response?.status()}`);

  const state = await page.evaluate(expectedMarker => ({
    title: document.title,
    marker: document.title.includes(expectedMarker) || document.body.textContent.includes(expectedMarker),
    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
  }), marker);

  if (!state.title || !state.marker) throw new Error(`${label} content mismatch ${JSON.stringify(state)}`);
  if (state.overflow) throw new Error(`${label} horizontal overflow ${JSON.stringify(state)}`);

  if (options.b06) {
    const runtime = await page.evaluate(() => ({
      artwork: document.documentElement.dataset.worldFeedArt || '',
      photoArtwork: Number(document.documentElement.dataset.photoArtwork || '0')
    }));
    if (runtime.artwork !== 'real-photo-workspace-v4' || runtime.photoArtwork < 1) {
      throw new Error(`B06 artwork runtime incomplete ${JSON.stringify(runtime)}`);
    }
  }

  if (options.b60) {
    await page.waitForFunction(() => Boolean(window.B60_EDITORIAL_RADAR && window.B60_OPPORTUNITY_DETAIL));
    const runtime = await page.evaluate(() => ({
      radar: Boolean(window.B60_EDITORIAL_RADAR),
      detail: Boolean(window.B60_OPPORTUNITY_DETAIL),
      operatorText: /PUBLICATION BOUNDARY|후보 생성만|GitHub 쓰기/.test(document.body.textContent)
    }));
    if (!runtime.radar || !runtime.detail) throw new Error(`B60 runtime incomplete ${JSON.stringify(runtime)}`);
    if (runtime.operatorText) throw new Error(`B60 operator surface leaked ${JSON.stringify(runtime)}`);
  }

  if (consoleErrors.length) throw new Error(`${label} console errors ${consoleErrors.join(' | ')}`);
  if (localFailures.length) throw new Error(`${label} local request failures ${localFailures.join(' | ')}`);
}

async function inspectRoot(page) {
  const response = await page.goto(`${base}/`, { waitUntil: 'networkidle' });
  if (!response || response.status() !== 200) throw new Error(`root HTTP ${response?.status()}`);
  await page.waitForSelector('.business-card');
  const state = await page.evaluate(() => ({
    title: document.title,
    brand: document.querySelector('.brand')?.textContent?.replace(/\s+/g, ' ').trim() || '',
    cards: document.querySelectorAll('.business-card').length,
    storyMemory: document.body.textContent.includes('StoryMemory') || document.body.textContent.includes('스토리메모리'),
    internalOps: /프로젝트 현황|작업 중|백엔드|Pull Request|GitHub CI/.test(document.body.textContent),
    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    localLinks: Array.from(document.querySelectorAll('.open-link')).map(link => ({
      href: link.getAttribute('href'),
      target: link.getAttribute('target')
    }))
  }));
  if (!state.title.startsWith('Padiem Lab')) throw new Error(`bad Lab title ${JSON.stringify(state)}`);
  if (!state.brand.includes('PADIEM LAB')) throw new Error(`bad Lab brand ${JSON.stringify(state)}`);
  if (state.cards < routes.length) throw new Error(`public work missing ${JSON.stringify(state)}`);
  if (state.storyMemory || state.internalOps) throw new Error(`private data exposed ${JSON.stringify(state)}`);
  if (state.overflow) throw new Error(`root horizontal overflow ${JSON.stringify(state)}`);

  for (const route of routes) {
    const expected = `/${route.route}/`;
    if (!state.localLinks.some(link => link.href === expected && !link.target)) {
      throw new Error(`Portal root missing same-origin ${expected} link`);
    }
  }
}

async function screenshot(page, label, viewportName) {
  if (!screenshotDir) return;
  fs.mkdirSync(screenshotDir, { recursive: true });
  await page.screenshot({ path: path.join(screenshotDir, `padiem-lab-${label}-${viewportName}.png`), fullPage: true });
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const viewports = live
    ? [{ name: 'desktop', width: 1440, height: 1000 }]
    : [
        { name: 'desktop', width: 1440, height: 1000 },
        { name: 'mobile', width: 390, height: 844 }
      ];

  for (const viewport of viewports) {
    const root = await browser.newPage({ viewport });
    await inspectRoot(root);
    await screenshot(root, 'root', viewport.name);
    await root.close();

    for (const route of routes) {
      const page = await browser.newPage({ viewport });
      await inspect(page, `${base}/${route.route}/`, route.route, route.marker, {
        b06: route.number === 6,
        b60: route.number === 60
      });
      await screenshot(page, route.route, viewport.name);
      await page.close();
      console.log(`${route.route}/${viewport.name} PASS`);
    }
  }

  await browser.close();
  console.log(`PADIEM LAB QA PASS ${base} routes=${routes.map(route => route.route).join(',')}`);
})().catch(error => {
  console.error(error);
  process.exit(1);
});
