const { test, expect } = require('@playwright/test');

test.describe('Work In Progress Queue', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
  });

  test('initial state shows projects active and work view hidden', async ({ page }) => {
    const projectsBtn = page.locator('.view-nav-item[data-view="projects"]');
    await expect(projectsBtn).toHaveClass(/is-active/);
    await expect(projectsBtn).toHaveAttribute('aria-current', 'page');
    await expect(page.locator('#view-work')).toBeHidden();
    await expect(page.locator('.pd-card')).toHaveCount(13);
  });

  test('clicking work shows work view and hides projects', async ({ page }) => {
    await page.click('.view-nav-item[data-view="work"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#view-work')).toBeVisible();
    await expect(page.locator('#view-projects')).toBeHidden();
    const workBtn = page.locator('.view-nav-item[data-view="work"]');
    await expect(workBtn).toHaveClass(/is-active/);
    await expect(workBtn).toHaveAttribute('aria-current', 'page');
    const projectsBtn = page.locator('.view-nav-item[data-view="projects"]');
    await expect(projectsBtn).not.toHaveClass(/is-active/);
  });

  test('shows exactly 10 work items', async ({ page }) => {
    await page.click('.view-nav-item[data-view="work"]');
    await page.waitForTimeout(200);
    const items = page.locator('.work-item');
    await expect(items).toHaveCount(10);
  });

  test('shows review group count 4 and active group count 6', async ({ page }) => {
    await page.click('.view-nav-item[data-view="work"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#work-summary-text')).toContainText('4');
    await expect(page.locator('#work-summary-text')).toContainText('6');
  });

  test('no duplicate project IDs in work queue', async ({ page }) => {
    await page.click('.view-nav-item[data-view="work"]');
    await page.waitForTimeout(200);
    const ids = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('.work-item')).map(el => el.getAttribute('data-project-id'));
    });
    const uniqueIds = new Set(ids);
    expect(ids.length).toBe(uniqueIds.size);
  });

  test('Portfolio Console shows in work items', async ({ page }) => {
    await page.click('.view-nav-item[data-view="work"]');
    await page.waitForTimeout(200);
    const pcItem = page.locator('.work-item[data-project-id="portfolio-console"]');
    await expect(pcItem).toContainText('80%');
  });

  test('LoveBud shows 50% progress', async ({ page }) => {
    await page.click('.view-nav-item[data-view="work"]');
    await page.waitForTimeout(200);
    const lbItem = page.locator('.work-item[data-project-id="lovebud"]');
    await expect(lbItem).toContainText('50%');
  });

  test('work items have stage badge', async ({ page }) => {
    await page.click('.view-nav-item[data-view="work"]');
    await page.waitForTimeout(200);
    const items = page.locator('.work-item');
    const count = await items.count();
    for (let i = 0; i < count; i++) {
      await expect(items.nth(i).locator('.status-badge')).not.toBeEmpty();
    }
  });

  test('work items have developmentMode badge', async ({ page }) => {
    await page.click('.view-nav-item[data-view="work"]');
    await page.waitForTimeout(200);
    const items = page.locator('.work-item');
    const count = await items.count();
    for (let i = 0; i < count; i++) {
      await expect(items.nth(i).locator('.pd-card-devmode')).not.toBeEmpty();
    }
  });

  test('work items show currentWork', async ({ page }) => {
    await page.click('.view-nav-item[data-view="work"]');
    await page.waitForTimeout(200);
    const items = page.locator('.work-item');
    const count = await items.count();
    for (let i = 0; i < count; i++) {
      const currentWork = await items.nth(i).locator('.work-item-current').first().textContent();
      expect(currentWork.length).toBeGreaterThan(0);
    }
  });

  test('view detail button opens project dialog', async ({ page }) => {
    await page.click('.view-nav-item[data-view="work"]');
    await page.waitForTimeout(200);
    await page.locator('.work-detail-btn').first().click();
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();
    await page.keyboard.press('Escape');
  });

  test('language switch preserves work view', async ({ page }) => {
    await page.click('.view-nav-item[data-view="work"]');
    await page.waitForTimeout(200);
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await expect(page.locator('#view-work')).toBeVisible();
    await expect(page.locator('#header-count')).toContainText('IN PROGRESS');
    await page.click('#lang-ko');
    await page.waitForTimeout(200);
    await expect(page.locator('#view-work')).toBeVisible();
  });

  test('no console errors', async ({ page }) => {
    const errors = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
    page.on('pageerror', err => errors.push(err.message));
    await page.click('.view-nav-item[data-view="work"]');
    await page.waitForTimeout(200);
    await page.reload({ waitUntil: 'networkidle' });
    expect(errors).toHaveLength(0);
  });

  test('no horizontal overflow at desktop', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
    await page.click('.view-nav-item[data-view="work"]');
    await page.waitForTimeout(200);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('no horizontal overflow at mobile', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.click('#menu-toggle');
    await page.waitForTimeout(300);
    await page.locator('.view-nav-item[data-view="work"]').click({ force: true });
    await page.waitForTimeout(200);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });
});
