const { test, expect } = require('@playwright/test');

test('B1 owner review routes to canonical Production and remains unapproved', async ({ page }) => {
  await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
  await page.waitForTimeout(180);

  const row = page.locator('.biz-item[data-biz-number="1"]');
  await expect(row).toHaveAttribute('data-owner-ui-status', 'OWNER_REJECTED');
  await expect(row.locator('.biz-phase-badge').nth(0)).toHaveText('UI · 재설계');

  const link = row.locator('.biz-launch-open');
  await expect(link).toHaveCount(1);
  await expect(link).toHaveAttribute('href', 'https://ai-revenue-final-review-b01.pages.dev/');
  await expect(link).toHaveAttribute('target', '_blank');
  await expect(link).toHaveAttribute('rel', 'noopener noreferrer');

  const identity = await page.evaluate(() => {
    const business = window.ARL_BUSINESSES.find((item) => item.number === 1);
    return {
      surfaceUrl: business.surfaceUrl,
      ownerUiStatus: business.ownerUiStatus,
    };
  });

  expect(identity).toEqual({
    surfaceUrl: 'https://ai-revenue-final-review-b01.pages.dev/',
    ownerUiStatus: 'OWNER_REJECTED',
  });
});
