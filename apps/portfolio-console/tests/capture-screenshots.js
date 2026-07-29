const { chromium } = require('@playwright/test');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const EXACT_HEAD = '27b9057fac2d944fb341fba38f24cc865a83b2a0';

const DESKTOP = { width: 1440, height: 1100 };
const MOBILE = { width: 390, height: 844 };

async function capture(page, { filename, viewport, theme, lang, state, description }) {
  await page.setViewportSize(viewport);
  await page.goto('http://127.0.0.1:4173/', { waitUntil: 'networkidle', timeout: 15000 });
  await page.waitForTimeout(500);

  // Set theme
  await page.evaluate(t => {
    localStorage.setItem('arl-portfolio-theme', t);
    document.documentElement.setAttribute('data-theme', t);
  }, theme);
  await page.waitForTimeout(200);

  // Set language
  if (lang === 'en') {
    await page.evaluate(() => {
      const btn = document.querySelector('#lang-en');
      if (btn) btn.click();
    });
    await page.waitForTimeout(300);
  }

  // Set state
  if (state === 'project-detail') {
    await page.locator('.pd-card-detail-btn').first().click();
    await page.waitForTimeout(300);
  } else if (state === 'search-filter') {
    await page.evaluate(() => {
      const btn = document.querySelector('.view-nav-item[data-view="search"]');
      if (btn) btn.click();
    });
    await page.waitForTimeout(200);
  } else if (state === 'work-view') {
    await page.evaluate(() => {
      const btn = document.querySelector('.view-nav-item[data-view="work"]');
      if (btn) btn.click();
    });
    await page.waitForTimeout(200);
  } else if (state === 'business-index') {
    await page.evaluate(() => {
      const btn = document.querySelector('.view-nav-item[data-view="business"]');
      if (btn) btn.click();
    });
    await page.waitForTimeout(200);
  } else if (state === 'navigation-drawer') {
    await page.locator('#menu-toggle').click();
    await page.waitForTimeout(300);
  }

  // Capture viewport screenshot
  const outputDir = path.join(__dirname, '..', 'docs', 'visual-review');
  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

  const filepath = path.join(outputDir, filename);
  await page.screenshot({ path: filepath, fullPage: false });

  // Read back for SHA
  const buf = fs.readFileSync(filepath);
  const sha = crypto.createHash('sha256').update(buf).digest('hex');
  const png = fs.statSync(filepath).size;

  // Get actual rendered dimensions
  const actualViewport = await page.evaluate(() => ({
    w: window.innerWidth,
    h: window.innerHeight
  }));

  return {
    filename,
    css_viewport: `${viewport.width}x${viewport.height}`,
    device_scale_factor: 1,
    physical_png: `${actualViewport.w}x${actualViewport.h}`,
    sha256: sha,
    bytes: png,
    captured_state: state || 'dashboard',
    theme,
    language: lang
  };
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  const screenshots = [
    // Desktop 1440x1100
    { filename: 'desktop-dashboard-dark.png', viewport: DESKTOP, theme: 'dark', lang: 'ko', state: null },
    { filename: 'desktop-dashboard-light.png', viewport: DESKTOP, theme: 'light', lang: 'ko', state: null },
    { filename: 'desktop-project-detail-dark.png', viewport: DESKTOP, theme: 'dark', lang: 'ko', state: 'project-detail' },
    { filename: 'desktop-project-detail-light.png', viewport: DESKTOP, theme: 'light', lang: 'ko', state: 'project-detail' },
    { filename: 'desktop-search-filter-dark.png', viewport: DESKTOP, theme: 'dark', lang: 'ko', state: 'search-filter' },
    { filename: 'desktop-work-view-dark.png', viewport: DESKTOP, theme: 'dark', lang: 'ko', state: 'work-view' },
    { filename: 'desktop-business-index-dark.png', viewport: DESKTOP, theme: 'dark', lang: 'ko', state: 'business-index' },
    // Mobile 390x844
    { filename: 'mobile-dashboard-dark.png', viewport: MOBILE, theme: 'dark', lang: 'ko', state: null },
    { filename: 'mobile-dashboard-light.png', viewport: MOBILE, theme: 'light', lang: 'ko', state: null },
    { filename: 'mobile-project-detail-dark.png', viewport: MOBILE, theme: 'dark', lang: 'ko', state: 'project-detail' },
    { filename: 'mobile-navigation-drawer-dark.png', viewport: MOBILE, theme: 'dark', lang: 'ko', state: 'navigation-drawer' },
    { filename: 'mobile-search-filter-dark.png', viewport: MOBILE, theme: 'dark', lang: 'ko', state: 'search-filter' },
  ];

  const results = [];
  for (const s of screenshots) {
    console.log(`Capturing ${s.filename}...`);
    const r = await capture(page, s);
    results.push(r);
  }

  await browser.close();

  const manifest = {
    exact_head: EXACT_HEAD,
    generated_at: new Date().toISOString(),
    screenshots: results
  };

  const manifestPath = path.join(__dirname, '..', 'docs', 'visual-review', 'manifest.json');
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
  console.log(`Manifest written to ${manifestPath}`);
  console.log(JSON.stringify(manifest, null, 2));
})().catch(err => { console.error(err); process.exit(1); });
