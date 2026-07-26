const { test, expect } = require('@playwright/test');

function goSearch(page) {
  return page.click('.view-nav-item[data-view="search"]');
}

test.describe('Search & Filter — Basic State', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
  });

  test('search view is hidden on initial load', async ({ page }) => {
    await expect(page.locator('#view-search')).toBeHidden();
  });

  test('project view is visible on initial load', async ({ page }) => {
    await expect(page.locator('#view-projects')).toBeVisible();
  });

  test('renders 13 project cards', async ({ page }) => {
    await expect(page.locator('.pd-card')).toHaveCount(13);
  });

  test('project status menu is active on initial load', async ({ page }) => {
    const btn = page.locator('.view-nav-item[data-view="projects"]');
    await expect(btn).toHaveClass(/is-active/);
    await expect(btn).toHaveAttribute('aria-current', 'page');
  });

  test('search filter button is not active initially', async ({ page }) => {
    const btn = page.locator('.view-nav-item[data-view="search"]');
    await expect(btn).not.toHaveClass(/is-active/);
    await expect(btn).not.toHaveAttribute('aria-current');
  });
});

test.describe('Search & Filter — View Switch', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
  });

  test('clicking search opens search view', async ({ page }) => {
    await goSearch(page);
    await page.waitForTimeout(200);
    await expect(page.locator('#view-search')).toBeVisible();
    await expect(page.locator('#view-projects')).toBeHidden();
  });

  test('search button is active in search view', async ({ page }) => {
    await goSearch(page);
    await page.waitForTimeout(200);
    const btn = page.locator('.view-nav-item[data-view="search"]');
    await expect(btn).toHaveClass(/is-active/);
    await expect(btn).toHaveAttribute('aria-current', 'page');
  });

  test('clicking project status returns to projects', async ({ page }) => {
    await goSearch(page);
    await page.fill('#sf-search-input', 'love');
    await page.waitForTimeout(200);
    await page.click('.view-nav-item[data-view="projects"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#view-projects')).toBeVisible();
    await expect(page.locator('#view-search')).toBeHidden();
    await expect(page.locator('.pd-card')).toHaveCount(13);
  });
});

test.describe('Search & Filter — Text Search', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
    await goSearch(page);
  });

  test('search by English name: Portfolio Console', async ({ page }) => {
    await page.fill('#sf-search-input', 'Portfolio Console');
    await page.waitForTimeout(200);
    await expect(page.locator('#search-grid .pd-card')).toHaveCount(1);
    await expect(page.locator('#search-grid .pd-card-name').first()).toHaveText('Portfolio Console');
  });

  test('search by Korean name: 러브버드', async ({ page }) => {
    await page.fill('#sf-search-input', '러브버드');
    await page.waitForTimeout(200);
    await expect(page.locator('#search-grid .pd-card')).toHaveCount(1);
  });

  test('search by business number: 14', async ({ page }) => {
    await page.fill('#sf-search-input', '14');
    await page.waitForTimeout(200);
    const count = await page.locator('#search-grid .pd-card').count();
    expect(count).toBeGreaterThanOrEqual(1);
  });

  test('search by workspace: apps/living-travel', async ({ page }) => {
    await page.fill('#sf-search-input', 'apps/living-travel');
    await page.waitForTimeout(200);
    await expect(page.locator('#search-grid .pd-card')).toHaveCount(1);
  });

  test('search is case-insensitive', async ({ page }) => {
    await page.fill('#sf-search-input', 'LOVEBUD');
    await page.waitForTimeout(200);
    await expect(page.locator('#search-grid .pd-card')).toHaveCount(1);
  });
});

test.describe('Search & Filter — Stage Filter', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
    await goSearch(page);
  });

  test('filter by live stage shows 7 cards', async ({ page }) => {
    await page.selectOption('#sf-stage-filter', 'live');
    await page.waitForTimeout(200);
    await expect(page.locator('#search-grid .pd-card')).toHaveCount(7);
  });

  test('filter by review stage shows 3 cards', async ({ page }) => {
    await page.selectOption('#sf-stage-filter', 'review');
    await page.waitForTimeout(200);
    await expect(page.locator('#search-grid .pd-card')).toHaveCount(3);
  });

  test('filter by planned stage shows 3 cards', async ({ page }) => {
    await page.selectOption('#sf-stage-filter', 'planned');
    await page.waitForTimeout(200);
    await expect(page.locator('#search-grid .pd-card')).toHaveCount(3);
  });
});

test.describe('Search & Filter — Development Mode Filter', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
    await goSearch(page);
  });

  test('filter by active-development shows 6 cards', async ({ page }) => {
    await page.selectOption('#sf-devmode-filter', 'active-development');
    await page.waitForTimeout(200);
    await expect(page.locator('#search-grid .pd-card')).toHaveCount(6);
  });

  test('filter by needs-improvement shows 4 cards', async ({ page }) => {
    await page.selectOption('#sf-devmode-filter', 'needs-improvement');
    await page.waitForTimeout(200);
    await expect(page.locator('#search-grid .pd-card')).toHaveCount(4);
  });

  test('filter by not-started shows 3 cards', async ({ page }) => {
    await page.selectOption('#sf-devmode-filter', 'not-started');
    await page.waitForTimeout(200);
    await expect(page.locator('#search-grid .pd-card')).toHaveCount(3);
  });
});

test.describe('Search & Filter — Combination', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
    await goSearch(page);
  });

  test('text + stage: love + live shows 2 cards', async ({ page }) => {
    await page.fill('#sf-search-input', 'love');
    await page.selectOption('#sf-stage-filter', 'live');
    await page.waitForTimeout(200);
    await expect(page.locator('#search-grid .pd-card')).toHaveCount(2);
  });

  test('reset restores all filters', async ({ page }) => {
    await page.fill('#sf-search-input', 'love');
    await page.selectOption('#sf-stage-filter', 'live');
    await page.selectOption('#sf-devmode-filter', 'active-development');
    await page.selectOption('#sf-sort-filter', 'progress-desc');
    await page.waitForTimeout(200);
    await page.click('#sf-reset-filter');
    await page.waitForTimeout(200);
    await expect(page.locator('#search-grid .pd-card')).toHaveCount(13);
    await expect(page.locator('#sf-search-input')).toHaveValue('');
    await expect(page.locator('#sf-stage-filter')).toHaveValue('all');
    await expect(page.locator('#sf-devmode-filter')).toHaveValue('all');
    await expect(page.locator('#sf-sort-filter')).toHaveValue('default');
  });
});

test.describe('Search & Filter — EN Labels', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await goSearch(page);
  });

  test('reset button switches to EN', async ({ page }) => {
    await expect(page.locator('#sf-reset-filter')).toHaveText('RESET');
  });

  test('result count shows EN format', async ({ page }) => {
    await expect(page.locator('#header-count')).toHaveText('13 of 13 projects');
  });
});

test.describe('Search & Filter — Regression', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
  });

  test('service links count is 9', async ({ page }) => {
    await expect(page.locator('.pd-card-service-link')).toHaveCount(9);
  });

  test('no console errors', async ({ page }) => {
    const errors = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
    page.on('pageerror', err => errors.push(err.message));
    await page.reload({ waitUntil: 'networkidle' });
    expect(errors).toHaveLength(0);
  });

  test('no horizontal overflow', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
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
});
