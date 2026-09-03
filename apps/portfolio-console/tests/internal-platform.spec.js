const { test, expect } = require('@playwright/test');

test.describe('Internal Platform view', () => {
  test('keeps platform components separate from Business numbering and exposes current Engine work', async ({ page }) => {
    const consoleErrors = [];
    const pageErrors = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });
    page.on('pageerror', (error) => pageErrors.push(String(error)));

    await page.goto('/');

    const platformNav = page.locator('.view-nav-item[data-view="platform"]');
    await expect(platformNav).toBeVisible();
    await expect(platformNav).toContainText('내부 플랫폼');

    await platformNav.click();
    await expect(page.locator('#view-platform')).toBeVisible();
    await expect(page.locator('#header-prefix')).toHaveText('내부 플랫폼 관리');
    await expect(page.locator('#header-count')).toHaveText('IP 3');

    const cards = page.locator('.ip-item');
    await expect(cards).toHaveCount(3);
    await expect(page.locator('.ip-id')).toHaveText(['IP-CORE', 'IP-ENGINE', 'IP-CONTROL']);
    await expect(page.locator('.ip-source')).toHaveText([
      'packages/padiem-ai-core/',
      'apps/padiem-ai-engine/',
      'packages/padiem-control-plane/'
    ]);

    // The Business index remains a separate authority surface.
    const businessNav = page.locator('.view-nav-item[data-view="business"]');
    await businessNav.click();
    await expect(page.locator('#view-business')).toBeVisible();
    await expect(page.locator('#biz-list .biz-item').first()).toBeVisible();
    await expect(page.locator('#biz-list')).not.toContainText('IP-CORE');
    await expect(page.locator('#biz-list')).not.toContainText('IP-ENGINE');
    await expect(page.locator('#biz-list')).not.toContainText('IP-CONTROL');

    // Return to Internal Platform and prove current Engine work is directly discoverable.
    await platformNav.click();
    const engineCard = page.locator('.ip-item[data-platform-id="IP-ENGINE"]');
    await expect(engineCard).toContainText('Padiem AI Engine');
    await engineCard.click();

    const dialog = page.locator('#internal-platform-dialog');
    await expect(dialog).toBeVisible();
    await expect(page.locator('#ip-dialog-title')).toHaveText('IP-ENGINE · Padiem AI Engine');
    await expect(page.locator('#ip-dialog-body')).toContainText('Business 번호 없음');
    await expect(page.locator('#ip-dialog-body')).toContainText('apps/padiem-ai-engine/');
    await expect(page.locator('#ip-dialog-body')).toContainText('#1698');
    await expect(page.locator('#ip-dialog-body a[href="https://github.com/skerishKang/ai-revenue-lab/issues/1698"]')).toBeVisible();

    await page.locator('#ip-dialog-close-btn').click();
    await expect(dialog).not.toBeVisible();

    // Search is bounded to the Internal Platform registry.
    await page.locator('#ip-search-input').fill('Control Plane');
    await expect(cards).toHaveCount(1);
    await expect(page.locator('.ip-id')).toHaveText('IP-CONTROL');
    await expect(page.locator('#header-count')).toHaveText('IP 1');

    // English translation keeps the platform view active and searchable.
    await page.locator('#lang-en').click();
    await expect(page.locator('#view-platform')).toBeVisible();
    await expect(page.locator('#header-prefix')).toHaveText('Internal Platform');
    await expect(page.locator('.view-nav-item[data-view="platform"]')).toContainText('INTERNAL PLATFORM');

    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
});
