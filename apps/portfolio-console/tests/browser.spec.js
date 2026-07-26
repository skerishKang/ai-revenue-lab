const { test, expect } = require('@playwright/test');

test.describe('Portfolio Console Browser Tests', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
  });

  test('renders 13 project cards', async ({ page }) => {
    await expect(page.locator('.pd-card')).toHaveCount(13);
  });

  test('all project cards have name and stage badge', async ({ page }) => {
    const cards = page.locator('.pd-card');
    const count = await cards.count();
    for (let i = 0; i < count; i++) {
      const card = cards.nth(i);
      await expect(card.locator('.pd-card-name')).not.toBeEmpty();
      await expect(card.locator('.status-badge')).not.toBeEmpty();
    }
  });

  test('자세히 보기 button exists on all cards', async ({ page }) => {
    await expect(page.locator('.pd-card-detail-btn')).toHaveCount(13);
  });

  test('service links count is 9', async ({ page }) => {
    await expect(page.locator('.pd-card-service-link')).toHaveCount(9);
  });

  test('active service links have security attributes', async ({ page }) => {
    const links = page.locator('.pd-card-service-link');
    const count = await links.count();
    for (let i = 0; i < count; i++) {
      await expect(links.nth(i)).toHaveAttribute('target', '_blank');
      await expect(links.nth(i)).toHaveAttribute('rel', 'noopener noreferrer');
      await expect(links.nth(i)).toHaveAttribute('href', /^https:\/\//);
    }
  });

  test('LoveBud service link has correct href', async ({ page }) => {
    const link = page.locator('.pd-card[data-project-id="lovebud"] .pd-card-service-link');
    await expect(link).toHaveAttribute('href', 'https://lovebud.pages.dev/');
  });

  test('Korean AI Platform has service link with correct href', async ({ page }) => {
    const link = page.locator('.pd-card[data-project-id="korean-ai-platform"] .pd-card-service-link');
    await expect(link).toHaveCount(1);
    await expect(link).toHaveAttribute('href', 'https://ai-revenue-korean-ai-platform.charliekant.workers.dev/workspace');
  });

  test('Living Fiction has no service link', async ({ page }) => {
    await expect(page.locator('.pd-card[data-project-id="living-fiction"] .pd-card-service-link')).toHaveCount(0);
  });

  test('no button nested inside anchor link', async ({ page }) => {
    const nested = page.locator('.pd-card a button');
    await expect(nested).toHaveCount(0);
  });

  test('no console errors', async ({ page }) => {
    const errors = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
    page.on('pageerror', err => errors.push(err.message));
    await page.reload({ waitUntil: 'networkidle' });
    expect(errors).toHaveLength(0);
  });

  test('no failed local requests', async ({ page }) => {
    const failed = [];
    page.on('requestfailed', req => {
      if (!req.url().startsWith('data:') && !req.url().startsWith('ws:')) failed.push(req.url());
    });
    await page.reload({ waitUntil: 'networkidle' });
    expect(failed).toHaveLength(0);
  });

  test('no horizontal overflow on desktop', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('no horizontal overflow on tablet', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('no horizontal overflow on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('Korean is default language', async ({ page }) => {
    await expect(page.locator('#topbar-title')).toContainText('내 비즈니스 관리');
  });

  test('EN switch works', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await expect(page.locator('#topbar-title')).toContainText('Business Operations');
  });

  test('Korean click restores Korean', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await expect(page.locator('#topbar-title')).toContainText('Business Operations');
    await page.click('#lang-ko');
    await page.waitForTimeout(200);
    await expect(page.locator('#topbar-title')).toContainText('내 비즈니스 관리');
  });

  test('language toggle buttons show active state', async ({ page }) => {
    await expect(page.locator('#lang-ko')).toHaveClass(/is-active/);
    await expect(page.locator('#lang-en')).not.toHaveClass(/is-active/);
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await expect(page.locator('#lang-en')).toHaveClass(/is-active/);
    await expect(page.locator('#lang-ko')).not.toHaveClass(/is-active/);
  });

  test('initial html lang is ko', async ({ page }) => {
    const lang = await page.evaluate(() => document.documentElement.lang);
    expect(lang).toBe('ko');
  });

  test('EN click sets html lang to en', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    const lang = await page.evaluate(() => document.documentElement.lang);
    expect(lang).toBe('en');
  });

  test('theme toggle switches to light and back', async ({ page }) => {
    await page.click('#theme-toggle');
    await page.waitForTimeout(100);
    let theme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    expect(theme).toBe('light');
    await page.click('#theme-toggle');
    await page.waitForTimeout(100);
    theme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    expect(theme).toBe('dark');
  });

  test('dialog shows on detail click', async ({ page }) => {
    await page.locator('.pd-card-detail-btn').first().click();
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();
    await page.keyboard.press('Escape');
  });

  test('자세히 보기 button opens dialog', async ({ page }) => {
    await page.locator('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn').click();
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('h2')).toHaveText('LoveBud');
    await page.keyboard.press('Escape');
  });

  test('dialog Escape returns focus to calling button', async ({ page }) => {
    const btn = page.locator('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn');
    await btn.click();
    await page.waitForTimeout(300);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    const activeId = await page.evaluate(() => {
      const el = document.activeElement;
      return el ? el.dataset.projectId : null;
    });
    expect(activeId).toBe('lovebud');
  });

  test('B01 displayed on Personal Edition card', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="personal-edition"]');
    await expect(card.locator('.pd-card-biznumber')).toHaveText('B01');
  });

  test('Portfolio Console shows PROJECT label', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="portfolio-console"]');
    await expect(card.locator('.pd-card-biznumber')).toHaveText('PROJECT');
  });

  test('work button exists and is a real button', async ({ page }) => {
    const workBtn = page.locator('.view-nav-item[data-view="work"]');
    await expect(workBtn).toHaveCount(1);
    const tagName = await workBtn.evaluate(el => el.tagName);
    expect(tagName).toBe('BUTTON');
  });

  test('business view shows 15 items', async ({ page }) => {
    await page.click('.view-nav-item[data-view="business"]');
    await page.waitForTimeout(200);
    await expect(page.locator('.biz-item')).toHaveCount(15);
  });

  test('sidebar shows exactly 4 view buttons', async ({ page }) => {
    await expect(page.locator('.view-nav-item')).toHaveCount(4);
  });

  test('copy workspace button works in dialog', async ({ page }) => {
    await page.locator('.pd-card[data-project-id="living-travel"] .pd-card-detail-btn').click();
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();

    await page.evaluate(() => {
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: async (text) => { window.__copiedText = text; } },
        writable: true, configurable: true
      });
    });

    await dialog.locator('#dlg-copy-workspace').click();
    await page.waitForTimeout(100);

    const copiedValue = await page.evaluate(() => window.__copiedText);
    expect(copiedValue).toBe('apps/living-travel/');
    await page.keyboard.press('Escape');
  });

  test('no data modification — projects and businesses data unchanged', async ({ page }) => {
    await page.waitForTimeout(500);
    const pCount = await page.evaluate(() => window.ARL_PROJECTS.length);
    const bCount = await page.evaluate(() => window.ARL_BUSINESSES.length);
    expect(pCount).toBe(13);
    expect(bCount).toBe(15);
  });
});
