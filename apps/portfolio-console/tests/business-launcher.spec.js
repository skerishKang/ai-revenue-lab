const { test, expect } = require('@playwright/test');

test.describe('Portfolio Console Business Launcher', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(150);
  });

  test('Business index is the default launcher view', async ({ page }) => {
    await expect(page.locator('#view-business')).toBeVisible();
    await expect(page.locator('.view-nav-item[data-view="business"]')).toHaveClass(/is-active/);
    await expect(page.locator('.biz-item')).toHaveCount(58);
  });

  test('launcher summarizes web, non-web and undeployed Businesses', async ({ page }) => {
    const summary = page.locator('#business-launcher-summary');
    await expect(summary).toBeVisible();
    await expect(summary).toContainText('바로 열기 48');
    await expect(summary).toContainText('비웹 1');
    await expect(summary).toContainText('미배포 9');
  });

  test('canonical numbered review surfaces are linked directly', async ({ page }) => {
    const expectations = [
      [6, 'https://06-world-feed.pages.dev/'],
      [32, 'https://32-ai-skill-studio.pages.dev/'],
      [35, 'https://35-ai-media-education-dx.pages.dev/'],
      [59, 'https://59-living-archive.pages.dev/'],
    ];

    for (const [number, href] of expectations) {
      const link = page.locator(`.biz-item[data-biz-number="${number}"] .biz-launch-open`);
      await expect(link).toHaveCount(1);
      await expect(link).toHaveAttribute('href', href);
      await expect(link).toHaveAttribute('target', '_blank');
      await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    }
  });

  test('Portfolio Console is represented as B44 even though its existing Pages project name is numberless', async ({ page }) => {
    const row = page.locator('.biz-item[data-biz-number="44"]');
    await expect(row).toContainText('Portfolio Console');
    await expect(row.locator('.biz-number')).toHaveText('44');
    await expect(row.locator('.biz-launch-open')).toHaveAttribute('href', 'https://ai-revenue-portfolio-console.pages.dev/');
  });

  test('B54 stays non-web and does not masquerade as a site', async ({ page }) => {
    const row = page.locator('.biz-item[data-biz-number="54"]');
    await expect(row.locator('.biz-launch-open')).toHaveCount(0);
    await expect(row.locator('.biz-launch-state')).toHaveText('CLI/TUI');
    await expect(row.locator('.biz-launch-detail')).toHaveCount(1);
  });

  test('clicking a web Business row opens its service directly', async ({ page }) => {
    await page.evaluate(() => {
      window.__launcherOpened = [];
      window.open = (...args) => {
        window.__launcherOpened.push(args);
        return null;
      };
    });

    await page.locator('.biz-item[data-biz-number="6"] .biz-title-group').click();
    const opened = await page.evaluate(() => window.__launcherOpened);
    expect(opened).toHaveLength(1);
    expect(opened[0][0]).toBe('https://06-world-feed.pages.dev/');
    expect(opened[0][1]).toBe('_blank');
  });

  test('상세 button still opens the Business status dialog', async ({ page }) => {
    await page.locator('.biz-item[data-biz-number="6"] .biz-launch-detail').click();
    const dialog = page.locator('#business-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('.dialog-name')).toHaveText('World Feed');
    await page.keyboard.press('Escape');
  });
});
