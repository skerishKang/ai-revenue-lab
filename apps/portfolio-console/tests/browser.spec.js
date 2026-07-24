const { test, expect } = require('@playwright/test');

test.describe('Portfolio Console Browser Tests', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle' });
  });

  test('renders 15 business rows', async ({ page }) => {
    const rows = page.locator('#business-table-body .business-row');
    await expect(rows).toHaveCount(15);
  });

  test('exposes business number and title in each row', async ({ page }) => {
    const firstRow = page.locator('#business-table-body .business-row').first();
    await expect(firstRow.locator('.business-number')).toHaveText('01');
    await expect(firstRow.locator('.business-title strong')).toHaveText('Personal Edition');

    const lastAssigned = page.locator('#business-table-body .business-row').nth(12);
    await expect(lastAssigned.locator('.business-number')).toHaveText('13');
    await expect(lastAssigned.locator('.business-title strong')).toHaveText('Personal Video Archive');
  });

  test('search filters rows by number and title', async ({ page }) => {
    await page.fill('#search-input', 'fiction');
    await page.waitForTimeout(200);

    const rows = page.locator('#business-table-body .business-row');
    await expect(rows).toHaveCount(1);
    await expect(rows.first().locator('.business-title strong')).toHaveText('Living Fiction');

    await page.fill('#search-input', '14');
    await page.waitForTimeout(200);
    await expect(rows).toHaveCount(1);
    await expect(rows.first().locator('.business-number')).toHaveText('14');
  });

  test('state filter limits visible rows', async ({ page }) => {
    await page.selectOption('#state-filter', 'reserved');
    await page.waitForTimeout(200);

    const rows = page.locator('#business-table-body .business-row');
    await expect(rows).toHaveCount(7);

    await page.selectOption('#state-filter', 'running');
    await page.waitForTimeout(200);
    await expect(rows).toHaveCount(4);

    await page.selectOption('#state-filter', 'all');
    await page.waitForTimeout(200);
    await expect(rows).toHaveCount(15);
  });

  test('sort control changes row order', async ({ page }) => {
    await page.selectOption('#sort-control', 'number-desc');
    await page.waitForTimeout(200);

    const firstNumber = await page.locator('#business-table-body .business-row').first().locator('.business-number').textContent();
    expect(firstNumber).toBe('15');

    await page.selectOption('#sort-control', 'number-asc');
    await page.waitForTimeout(200);

    const firstNumberAsc = await page.locator('#business-table-body .business-row').first().locator('.business-number').textContent();
    expect(firstNumberAsc).toBe('01');
  });

  test('priority sort orders by priority descending', async ({ page }) => {
    await page.selectOption('#sort-control', 'priority');
    await page.waitForTimeout(200);

    const firstNumber = await page.locator('#business-table-body .business-row').first().locator('.business-number').textContent();
    expect(firstNumber).toBe('01');
  });

  test('clicking a row selects it and updates detail panel', async ({ page }) => {
    await page.click('#business-table-body tr[data-business-number="14"]');
    await page.waitForTimeout(200);

    await expect(page.locator('#detail-number')).toHaveText('BUSINESS 14');
    await expect(page.locator('#detail-title')).toHaveText('Korean AI Platform');
    await expect(page.locator('#detail-status')).toHaveText('REVIEW');
    await expect(page.locator('#detail-progress-value')).toHaveText('78%');
  });

  test('detail panel shows next action and lifecycle', async ({ page }) => {
    await page.click('#business-table-body tr[data-business-number="1"]');
    await page.waitForTimeout(200);

    await expect(page.locator('#detail-next-action')).toContainText('PR #111');
    await expect(page.locator('#detail-lifecycle')).toHaveText('private_preview');
  });

  test('priority queue displays actionable businesses', async ({ page }) => {
    const priorityItems = page.locator('.priority-item');
    await expect(priorityItems).toHaveCount(6);

    const firstItem = priorityItems.first();
    await expect(firstItem.locator('.priority-number')).toHaveText('BIZ 01');
    await expect(firstItem.locator('.priority-title')).toHaveText('Personal Edition');
  });

  test('clicking a priority item selects the business', async ({ page }) => {
    const firstPriority = page.locator('.priority-item').first();
    await firstPriority.click();
    await page.waitForTimeout(200);

    await expect(page.locator('#detail-number')).toHaveText('BUSINESS 01');
  });

  test('disabled links have no href, tabindex=-1, and are keyboard-inert', async ({ page }) => {
    await page.click('#business-table-body tr[data-business-number="5"]');
    await page.waitForTimeout(200);

    const surfaceLink = page.locator('#surface-link');
    await expect(surfaceLink).toHaveClass(/is-disabled/);
    await expect(surfaceLink).toHaveAttribute('aria-disabled', 'true');
    await expect(surfaceLink).toHaveAttribute('tabindex', '-1');
    await expect(surfaceLink).not.toHaveAttribute('href');
    await expect(surfaceLink).not.toHaveAttribute('target');
    await expect(surfaceLink).not.toHaveAttribute('rel');

    const computedStyle = await surfaceLink.evaluate(el => window.getComputedStyle(el).pointerEvents);
    expect(computedStyle).toBe('none');
  });

  test('disabled link Enter key does not change URL or selection', async ({ page }) => {
    await page.click('#business-table-body tr[data-business-number="5"]');
    await page.waitForTimeout(200);

    const surfaceLink = page.locator('#surface-link');
    await surfaceLink.focus();
    await page.keyboard.press('Enter');
    await page.waitForTimeout(200);

    expect(page.url()).not.toContain('#');
    await expect(page.locator('#detail-number')).toHaveText('BUSINESS 05');
  });

  test('active external links have target=_blank and rel=noopener noreferrer', async ({ page }) => {
    await page.click('#business-table-body tr[data-business-number="2"]');
    await page.waitForTimeout(200);

    const links = [
      page.locator('#surface-link'),
      page.locator('#github-link'),
      page.locator('#issue-link'),
    ];

    for (const link of links) {
      await expect(link).not.toHaveClass(/is-disabled/);
      await expect(link).toHaveAttribute('target', '_blank');
      await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
      await expect(link).toHaveAttribute('tabindex', '0');
    }
  });

  test('no console errors on initial load', async ({ page }) => {
    const errors = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    page.on('pageerror', err => errors.push(err.message));

    await page.reload({ waitUntil: 'networkidle' });
    expect(errors).toHaveLength(0);
  });

  test('no failed local asset requests', async ({ page }) => {
    const failed = [];
    page.on('requestfailed', req => {
      if (!req.url().startsWith('data:') && !req.url().startsWith('ws:')) {
        failed.push(req.url());
      }
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

  test('mobile layout shows all essential columns', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(200);

    const rows = page.locator('#business-table-body .business-row');
    await expect(rows).toHaveCount(15);

    const firstRow = rows.first();
    await expect(firstRow.locator('.business-number')).toBeVisible();
    await expect(firstRow.locator('.business-title strong')).toBeVisible();
    await expect(firstRow.locator('.status-badge')).toBeVisible();
    await expect(firstRow.locator('.progress-cell')).toBeVisible();
    await expect(firstRow.locator('.action-cell')).toBeVisible();
  });

  test('Business 16 registry expansion updates all derived surfaces', async ({ page }) => {
    await page.route('**/app.js', async route => {
      const response = await route.fetch();
      const body = await response.text();
      const insert = `window.ARL_BUSINESSES.push({
  number: 16,
  slug: "test-business-16",
  title: "Test Business 16",
  koreanTitle: "테스트 사업 16",
  state: "review",
  lifecycle: "concept",
  progress: 50,
  workspace: "apps/test-business-16/",
  surfaceType: "Static demo",
  surfaceUrl: null,
  deployment: "Test deployment",
  githubLabel: "Issue #999",
  githubUrl: "https://github.com/skerishKang/ai-revenue-lab/issues/999",
  issueUrl: "https://github.com/skerishKang/ai-revenue-lab/issues/999",
  nextAction: "Add canonical data",
  lastVerified: "2026-07-24",
  priority: 50
});
`;
      await route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        body: insert + body,
      });
    });

    await page.goto('/', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);

    const rows = page.locator('#business-table-body .business-row');
    await expect(rows).toHaveCount(16);

    await expect(page.locator('#sidebar-range')).toHaveText('01–16');

    await page.fill('#search-input', '16');
    await page.waitForTimeout(200);
    await expect(rows).toHaveCount(1);
    await expect(rows.first().locator('.business-number')).toHaveText('16');
    await expect(rows.first().locator('.business-title strong')).toHaveText('Test Business 16');

    await page.fill('#search-input', '');
    await page.waitForTimeout(200);

    await page.click('#business-table-body tr[data-business-number="16"]');
    await page.waitForTimeout(200);

    await expect(page.locator('#detail-number')).toHaveText('BUSINESS 16');
    await expect(page.locator('#detail-title')).toHaveText('Test Business 16');
    await expect(page.locator('#detail-progress-value')).toHaveText('50%');

    const trackedText = await page.locator('#metric-tracked').textContent();
    expect(parseInt(trackedText)).toBe(9);

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('Korean and English titles do not overflow their cells', async ({ page }) => {
    const overflowCheck = await page.evaluate(() => {
      const cells = document.querySelectorAll('.business-title');
      const results = [];
      for (const cell of cells) {
        const rect = cell.getBoundingClientRect();
        const parentRect = cell.parentElement.getBoundingClientRect();
        results.push({
          scrollWidth: cell.scrollWidth,
          clientWidth: cell.clientWidth,
          overflows: cell.scrollWidth > cell.clientWidth,
          rectRight: Math.round(rect.right),
          parentRight: Math.round(parentRect.right)
        });
      }
      return results;
    });

    for (const result of overflowCheck) {
      expect(result.overflows).toBeFalsy();
    }
  });

  test('reserved rows are visually de-emphasized', async ({ page }) => {
    const reservedRow = page.locator('#business-table-body tr[data-business-number="7"]');
    await expect(reservedRow).toHaveClass(/is-reserved/);

    const opacity = await reservedRow.evaluate(el => window.getComputedStyle(el).opacity);
    expect(parseFloat(opacity)).toBeLessThan(1);
  });

  test('refresh button reloads the page', async ({ page }) => {
    await page.click('#refresh-button');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#business-table-body .business-row')).toHaveCount(15);
  });
});
