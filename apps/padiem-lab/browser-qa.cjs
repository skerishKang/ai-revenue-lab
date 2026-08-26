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

async function inspectB01(page, response, label, options) {
  const runtime = await page.evaluate(() => ({
    robots: document.querySelector('meta[name="robots"]')?.getAttribute('content') || '',
    privateLinks: Array.from(document.querySelectorAll('[href],[src],[action]'))
      .map(element => element.getAttribute('href') || element.getAttribute('src') || element.getAttribute('action') || '')
      .filter(value => /(?:^|\/)(?:admin|preview-states)(?:\/|$)/i.test(value)),
    externalRuntimeRefs: Array.from(document.querySelectorAll('[href],[src]'))
      .map(element => element.getAttribute('href') || element.getAttribute('src') || '')
      .filter(value => {
        try {
          const parsed = new URL(value, window.location.href);
          return /^https?:$/.test(parsed.protocol) && parsed.origin !== window.location.origin;
        } catch (_) {
          return true;
        }
      }),
    forms: Array.from(document.forms).map(form => ({
      action: form.getAttribute('action') || '',
      method: (form.getAttribute('method') || 'get').toLowerCase()
    })),
    scripts: document.scripts.length,
    inlineHandlers: Array.from(document.querySelectorAll('*')).some(element =>
      Array.from(element.attributes).some(attribute => /^on/i.test(attribute.name))
    ),
    productionReview: document.body?.dataset?.staticProductionReview || '',
    ownerApproved: document.querySelector('[data-owner-ui-approved]')?.getAttribute('data-owner-ui-approved') ||
      document.body?.getAttribute('data-owner-ui-approved') || ''
  }));

  if (!/noindex/i.test(runtime.robots) || !/nofollow/i.test(runtime.robots)) {
    throw new Error(`B01 robots boundary incomplete ${JSON.stringify(runtime)}`);
  }
  if (runtime.privateLinks.length || runtime.externalRuntimeRefs.length) {
    throw new Error(`B01 public boundary incomplete ${JSON.stringify(runtime)}`);
  }
  if (runtime.forms.some(form => form.action !== '#' || form.method !== 'get')) {
    throw new Error(`B01 form boundary incomplete ${JSON.stringify(runtime)}`);
  }
  if (runtime.scripts !== 0 || runtime.inlineHandlers) {
    throw new Error(`B01 script boundary incomplete ${JSON.stringify(runtime)}`);
  }
  if (options.b01Root) {
    if (runtime.productionReview !== 'b1-v7-collectible-glass') {
      throw new Error(`B01 current production-review marker missing ${JSON.stringify(runtime)}`);
    }
    if (runtime.ownerApproved !== 'false') {
      throw new Error(`B01 owner-approval boundary changed ${JSON.stringify(runtime)}`);
    }
    for (const privatePath of ['admin/', 'preview-states/']) {
      const privateResponse = await page.context().request.get(`${base}/b01/${privatePath}`, { failOnStatusCode: false });
      if (privateResponse.status() !== 404) {
        throw new Error(`B01 private path published ${privatePath} HTTP ${privateResponse.status()}`);
      }
    }
  }
  if (live) {
    const headers = await response.allHeaders();
    const csp = headers['content-security-policy'] || '';
    const robots = headers['x-robots-tag'] || '';
    if (!/script-src 'none'/.test(csp) || !/connect-src 'none'/.test(csp) ||
        !/form-action 'none'/.test(csp) || !/object-src 'none'/.test(csp)) {
      throw new Error(`B01 live CSP boundary incomplete ${JSON.stringify({ csp })}`);
    }
    if (!/noindex/i.test(robots) || !/nofollow/i.test(robots)) {
      throw new Error(`B01 live X-Robots boundary incomplete ${JSON.stringify({ robots })}`);
    }
  }
}

async function inspectB02(page, response) {
  const runtime = await page.evaluate(() => ({
    robots: document.querySelector('meta[name="robots"]')?.getAttribute('content') || '',
    privateLinks: Array.from(document.querySelectorAll('[href],[src],[action]'))
      .map(element => element.getAttribute('href') || element.getAttribute('src') || element.getAttribute('action') || '')
      .filter(value => /(?:^|\/)(?:operator|staging)(?:\/|$)/i.test(value)),
    externalRuntimeRefs: Array.from(document.querySelectorAll('[href],[src]'))
      .map(element => element.getAttribute('href') || element.getAttribute('src') || '')
      .filter(value => {
        try {
          const parsed = new URL(value, window.location.href);
          return /^https?:$/.test(parsed.protocol) && parsed.origin !== window.location.origin;
        } catch (_) {
          return true;
        }
      }),
    backendForms: Array.from(document.forms).map(form => ({
      action: form.getAttribute('action') || '',
      method: (form.getAttribute('method') || 'get').toLowerCase()
    })).filter(form => form.method === 'post' || /^\/(?!b02(?:\/|$)|$)/.test(form.action))
  }));
  if (!/noindex/i.test(runtime.robots) || !/nofollow/i.test(runtime.robots)) {
    throw new Error(`B02 robots boundary incomplete ${JSON.stringify(runtime)}`);
  }
  if (runtime.privateLinks.length || runtime.externalRuntimeRefs.length || runtime.backendForms.length) {
    throw new Error(`B02 public boundary incomplete ${JSON.stringify(runtime)}`);
  }
  if (live) {
    const headers = await response.allHeaders();
    const csp = headers['content-security-policy'] || '';
    const robots = headers['x-robots-tag'] || '';
    if (!/connect-src 'none'/.test(csp) || !/form-action 'none'/.test(csp) || !/object-src 'none'/.test(csp)) {
      throw new Error(`B02 live CSP boundary incomplete ${JSON.stringify({ csp })}`);
    }
    if (!/noindex/i.test(robots) || !/nofollow/i.test(robots)) {
      throw new Error(`B02 live X-Robots boundary incomplete ${JSON.stringify({ robots })}`);
    }
  }
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

  if (options.b01) await inspectB01(page, response, label, options);
  if (options.b02) await inspectB02(page, response);

  if (options.b06) {
    const runtime = await page.evaluate(() => ({
      artwork: document.documentElement.dataset.worldFeedArt || '',
      photoArtwork: Number(document.documentElement.dataset.photoArtwork || '0')
    }));
    if (runtime.artwork !== 'real-photo-workspace-v4' || runtime.photoArtwork < 1) {
      throw new Error(`B06 artwork runtime incomplete ${JSON.stringify(runtime)}`);
    }
  }

  if (options.b13) {
    const runtime = await page.evaluate(() => ({
      robots: document.querySelector('meta[name="robots"]')?.getAttribute('content') || '',
      scripts: document.scripts.length,
      inlineHandlers: Array.from(document.querySelectorAll('*')).some(element =>
        Array.from(element.attributes).some(attribute => /^on/i.test(attribute.name))
      )
    }));
    if (!/noindex/i.test(runtime.robots) || !/nofollow/i.test(runtime.robots)) {
      throw new Error(`B13 robots boundary incomplete ${JSON.stringify(runtime)}`);
    }
    if (runtime.scripts !== 0 || runtime.inlineHandlers) {
      throw new Error(`B13 script boundary incomplete ${JSON.stringify(runtime)}`);
    }
    if (live) {
      const headers = await response.allHeaders();
      const csp = headers['content-security-policy'] || '';
      const robots = headers['x-robots-tag'] || '';
      if (!/script-src 'none'/.test(csp) || !/form-action 'none'/.test(csp)) {
        throw new Error(`B13 live CSP boundary incomplete ${JSON.stringify({ csp })}`);
      }
      if (!/noindex/i.test(robots) || !/nofollow/i.test(robots)) {
        throw new Error(`B13 live X-Robots boundary incomplete ${JSON.stringify({ robots })}`);
      }
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
        b01: route.number === 1,
        b01Root: route.number === 1,
        b02: route.number === 2,
        b06: route.number === 6,
        b13: route.number === 13,
        b60: route.number === 60
      });
      await screenshot(page, route.route, viewport.name);
      await page.close();
      console.log(`${route.route}/${viewport.name} PASS`);

      if (route.number === 1) {
        for (const relative of [
          'guide/',
          'preview/participant/empty/',
          'preview/participant/input/',
          'preview/participant/published/'
        ]) {
          const detail = await browser.newPage({ viewport });
          const key = relative.replace(/\/$/, '').replace(/\//g, '-');
          await inspect(detail, `${base}/b01/${relative}`, `b01-${key}`, route.marker, { b01: true });
          await screenshot(detail, `b01-${key}`, viewport.name);
          await detail.close();
          console.log(`b01/${relative}${viewport.name} PASS`);
        }
      }

      if (route.number === 2) {
        for (const relative of ['demo/preferences.html', 'demo/traveler-home.html', 'demo/pending.html']) {
          const detail = await browser.newPage({ viewport });
          const key = relative.replace(/\.html$/, '').replace(/\//g, '-');
          await inspect(detail, `${base}/b02/${relative}`, `b02-${key}`, route.marker, { b02: true });
          await screenshot(detail, `b02-${key}`, viewport.name);
          await detail.close();
          console.log(`b02/${relative}/${viewport.name} PASS`);
        }
      }
    }
  }

  await browser.close();
  console.log(`PADIEM LAB QA PASS ${base} routes=${routes.map(route => route.route).join(',')}`);
})().catch(error => {
  console.error(error);
  process.exit(1);
});
