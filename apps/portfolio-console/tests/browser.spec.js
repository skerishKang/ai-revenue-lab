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
    await expect(page.locator('.pd-card a button')).toHaveCount(0);
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

  for (const [label, width, height] of [['desktop', 1440, 1100], ['tablet', 768, 1024], ['mobile', 390, 844]]) {
    test(`no horizontal overflow on ${label}`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
      expect(overflow).toBeFalsy();
    });
  }

  test('Korean is default language', async ({ page }) => {
    await expect(page.locator('#topbar-title')).toContainText('내 비즈니스 관리');
  });

  test('EN switch works and Korean restores', async ({ page }) => {
    await page.click('#lang-en');
    await expect(page.locator('#topbar-title')).toContainText('Business Operations');
    await expect(page.locator('#lang-en')).toHaveClass(/is-active/);
    await page.click('#lang-ko');
    await expect(page.locator('#topbar-title')).toContainText('내 비즈니스 관리');
    await expect(page.locator('#lang-ko')).toHaveClass(/is-active/);
  });

  test('initial html lang is ko and EN click sets en', async ({ page }) => {
    expect(await page.evaluate(() => document.documentElement.lang)).toBe('ko');
    await page.click('#lang-en');
    expect(await page.evaluate(() => document.documentElement.lang)).toBe('en');
  });

  test('theme toggle switches to light and back', async ({ page }) => {
    await page.click('#theme-toggle');
    expect(await page.evaluate(() => document.documentElement.getAttribute('data-theme'))).toBe('light');
    await page.click('#theme-toggle');
    expect(await page.evaluate(() => document.documentElement.getAttribute('data-theme'))).toBe('dark');
  });

  test('dialog shows on detail click', async ({ page }) => {
    await page.locator('.pd-card-detail-btn').first().click();
    await expect(page.locator('#project-dialog')).toBeVisible();
    await page.keyboard.press('Escape');
  });

  test('자세히 보기 button opens LoveBud dialog', async ({ page }) => {
    await page.locator('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn').click();
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('h2')).toHaveText('LoveBud');
    await page.keyboard.press('Escape');
  });

  test('dialog Escape returns focus to calling button', async ({ page }) => {
    const btn = page.locator('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn');
    await btn.click();
    await page.keyboard.press('Escape');
    await page.waitForTimeout(100);
    expect(await page.evaluate(() => document.activeElement?.dataset.projectId || null)).toBe('lovebud');
  });

  test('B01 displayed on Personal Edition card', async ({ page }) => {
    await expect(page.locator('.pd-card[data-project-id="personal-edition"] .pd-card-biznumber')).toHaveText('B01');
  });

  test('Portfolio Console shows PROJECT label', async ({ page }) => {
    await expect(page.locator('.pd-card[data-project-id="portfolio-console"] .pd-card-biznumber')).toHaveText('PROJECT');
  });

  test('work button exists and is a real button', async ({ page }) => {
    const workBtn = page.locator('.view-nav-item[data-view="work"]');
    await expect(workBtn).toHaveCount(1);
    expect(await workBtn.evaluate(el => el.tagName)).toBe('BUTTON');
  });

  test('business view shows 58 represented Businesses through B59', async ({ page }) => {
    await page.click('.view-nav-item[data-view="business"]');
    await expect(page.locator('.biz-item')).toHaveCount(58);
    await expect(page.locator('.biz-item[data-biz-number="38"]')).toContainText('AI 운동 코치');
    await expect(page.locator('.biz-item[data-biz-number="54"]')).toContainText('한국형 AI 코드 에이전트');
    await expect(page.locator('.biz-item[data-biz-number="57"]')).toHaveCount(1);
    await expect(page.locator('.biz-item[data-biz-number="58"]')).toHaveCount(1);
    await expect(page.locator('.biz-item[data-biz-number="59"]')).toHaveCount(1);
    await expect(page.locator('.biz-item[data-biz-number="56"]')).toHaveCount(0);
  });

  test('sidebar shows exactly 4 view buttons', async ({ page }) => {
    await expect(page.locator('.view-nav-item')).toHaveCount(4);
  });

  test('copy workspace button works in dialog', async ({ page }) => {
    await page.locator('.pd-card[data-project-id="living-travel"] .pd-card-detail-btn').click();
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();
    await page.evaluate(() => {
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: async (text) => { window.__copiedText = text; } },
        writable: true, configurable: true
      });
    });
    await dialog.locator('#dlg-copy-workspace').click();
    expect(await page.evaluate(() => window.__copiedText)).toBe('apps/living-travel/');
    await page.keyboard.press('Escape');
  });

  test('projects remain 13 while Business registry expands to 58', async ({ page }) => {
    await page.waitForTimeout(100);
    expect(await page.evaluate(() => window.ARL_PROJECTS.length)).toBe(13);
    expect(await page.evaluate(() => window.ARL_BUSINESSES.length)).toBe(58);
  });
});
