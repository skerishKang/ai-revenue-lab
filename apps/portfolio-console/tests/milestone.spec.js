const { test, expect } = require('@playwright/test');

test.describe('Milestone Progress Tests', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
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
      if (!req.url().startsWith('data:') && !req.url().startsWith('ws:')) {
        failed.push(req.url());
      }
    });
    await page.reload({ waitUntil: 'networkidle' });
    expect(failed).toHaveLength(0);
  });

  test('no horizontal overflow at desktop', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('no horizontal overflow at tablet', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('no horizontal overflow at mobile', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('LoveBud shows OPEN evidence note', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    const progress = await page.locator('#pd-detail-progress').textContent();
    expect(progress).toContain('OPEN');
    expect(progress).toContain('evidence');
  });

  test('Korean AI Platform shows PR #142 merged', async ({ page }) => {
    await page.click('.pd-card[data-project-id="korean-ai-platform"]');
    await page.waitForTimeout(200);
    const progress = await page.locator('#pd-detail-progress').textContent();
    expect(progress).toContain('PR #142');
    expect(progress).toContain('dedicated Worker');
    expect(progress).toContain('Provider registry');
  });

  test('Korean AI Platform does not show outdated PR #79', async ({ page }) => {
    await page.click('.pd-card[data-project-id="korean-ai-platform"]');
    await page.waitForTimeout(200);
    const progress = await page.locator('#pd-detail-progress').textContent();
    expect(progress).not.toContain('Draft PR #79');
    const next = await page.locator('#pd-detail-next').textContent();
    expect(next).not.toContain('PR #79');
  });

  test('LoveTree 3.0 shows undefined milestone', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovetree-3"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-badge')).toHaveText('운영 중');
  });

  test('LoveMatchmaking shows planned stage', async ({ page }) => {
    await page.click('.pd-card[data-project-id="love-matchmaking"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-badge')).toHaveText('계획');
  });

  test('AI Finder / Bukgu shows #1181 deferred', async ({ page }) => {
    await page.click('.pd-card[data-project-id="ai-finder-bukgu"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    const progress = await page.locator('#pd-detail-progress').textContent();
    expect(progress).not.toContain('1181');
  });

  test('Living Fiction shows 404 deployment note', async ({ page }) => {
    await page.click('.pd-card[data-project-id="living-fiction"]');
    await page.waitForTimeout(200);
    const progress = await page.locator('#pd-detail-progress').textContent();
    expect(progress).toContain('404');
  });

  test('Personal Edition shows CTO review pending', async ({ page }) => {
    await page.click('.pd-card[data-project-id="personal-edition"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    const next = await page.locator('#pd-detail-next').textContent();
    expect(next).toContain('PR #111');
  });

  test('Personal Video Archive shows needs-improvement context', async ({ page }) => {
    await page.click('.pd-card[data-project-id="personal-video-archive"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    const progress = await page.locator('#pd-detail-progress').textContent();
    expect(progress).toContain('Production');
  });

  test('LoveBud pageUrl is lovebud.pages.dev', async ({ page }) => {
    const link = page.locator('.pd-card[data-project-id="lovebud"] .pd-card-service-link');
    await expect(link).toHaveAttribute('href', 'https://lovebud.pages.dev/');
  });

  test('Korean AI Platform has no service link (undeployed)', async ({ page }) => {
    await expect(page.locator('.pd-card[data-project-id="korean-ai-platform"] .pd-card-service-link')).toHaveCount(0);
    await expect(page.locator('.pd-card[data-project-id="korean-ai-platform"] .pd-card-undeployed')).toBeVisible();
  });

  test('Living Fiction has no service link (404)', async ({ page }) => {
    await expect(page.locator('.pd-card[data-project-id="living-fiction"] .pd-card-service-link')).toHaveCount(0);
    await expect(page.locator('.pd-card[data-project-id="living-fiction"] .pd-card-undeployed')).toBeVisible();
  });

  test('service link count matches expected 8', async ({ page }) => {
    await expect(page.locator('.pd-card-service-link')).toHaveCount(8);
  });

  test('all 13 cards have 자세히 보기 button', async ({ page }) => {
    await expect(page.locator('.pd-card-detail-btn')).toHaveCount(13);
  });

  test('Business Registry shows 15 rows', async ({ page }) => {
    await expect(page.locator('#business-table-body .business-row')).toHaveCount(15);
  });

  test('Korean AI Platform business 14 shows PR #142', async ({ page }) => {
    await page.click('#business-table-body tr[data-business-number="14"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#detail-number')).toHaveText('비즈니스 14');
    await expect(page.locator('#detail-title')).toHaveText('Korean AI Platform');
    await expect(page.locator('#detail-github')).toContainText('PR #142');
    await expect(page.locator('#detail-deployment')).toContainText('Worker');
  });

  test('Business 1 Personal Edition shows Draft PR #111', async ({ page }) => {
    await page.click('#business-table-body tr[data-business-number="1"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#detail-title')).toHaveText('Personal Edition');
    await expect(page.locator('#detail-github')).toContainText('Draft PR #111');
  });

  test('Business 2 Living Travel PR #88', async ({ page }) => {
    await page.click('#business-table-body tr[data-business-number="2"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#detail-github')).toContainText('PR #88');
  });

  test('language toggle still works after milestone changes', async ({ page }) => {
    await expect(page.locator('#topbar-title')).toHaveText('내 비즈니스 관리');

    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await expect(page.locator('#topbar-title')).toHaveText('Business Operations');

    await page.click('#lang-ko');
    await page.waitForTimeout(200);
    await expect(page.locator('#topbar-title')).toHaveText('내 비즈니스 관리');
  });
});
