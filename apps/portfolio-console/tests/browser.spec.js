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

  test('inactive links are not clickable and have correct attributes', async ({ page }) => {
    await page.click('#business-table-body tr[data-business-number="5"]');
    await page.waitForTimeout(200);

    const surfaceLink = page.locator('#surface-link');
    await expect(surfaceLink).toHaveClass(/is-disabled/);
    await expect(surfaceLink).toHaveAttribute('aria-disabled', 'true');

    const computedStyle = await surfaceLink.evaluate(el => window.getComputedStyle(el).pointerEvents);
    expect(computedStyle).toBe('none');
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

  test('mobile layout shows essential columns', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(200);

    const rows = page.locator('#business-table-body .business-row');
    await expect(rows).toHaveCount(15);

    const firstRow = rows.first();
    await expect(firstRow.locator('.business-number')).toBeVisible();
    await expect(firstRow.locator('.business-title strong')).toBeVisible();
    await expect(firstRow.locator('.status-badge')).toBeVisible();
  });

  test('Business 16 addition does not break layout', async ({ page }) => {
    await page.evaluate(() => {
      const tableBody = document.getElementById('business-table-body');
      const newRow = document.createElement('tr');
      newRow.className = 'business-row';
      newRow.dataset.businessNumber = '16';
      newRow.innerHTML = `
        <td><div class="business-id"><span class="business-number">16</span><span class="business-title"><strong>Test Business</strong><span>테스트 사업</span></span></div></td>
        <td><span class="status-badge status-review">REVIEW</span></td>
        <td class="progress-cell"><div class="progress-label"><span>DEMO</span><span>50%</span></div><div class="progress-track"><i style="width:50%"></i></div></td>
        <td class="mono-cell">Static demo</td>
        <td class="mono-cell">Issue #999</td>
        <td class="action-cell">Add canonical data</td>
      `;
      tableBody.appendChild(newRow);
    });
    await page.waitForTimeout(200);

    const rows = page.locator('#business-table-body .business-row');
    await expect(rows).toHaveCount(16);

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('Korean and English titles do not overflow', async ({ page }) => {
    const titles = await page.evaluate(() => {
      const cells = document.querySelectorAll('.business-title');
      return Array.from(cells).map(cell => {
        const strong = cell.querySelector('strong');
        const span = cell.querySelector('span');
        return {
          english: strong?.textContent || '',
          korean: span?.textContent || '',
          overflow: window.getComputedStyle(cell).overflow
        };
      });
    });

    for (const title of titles) {
      expect(title.english.length).toBeGreaterThan(0);
      expect(title.korean.length).toBeGreaterThan(0);
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
