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

  test('launcher summarizes web, non-web, expanded and undeployed Businesses', async ({ page }) => {
    const summary = page.locator('#business-launcher-summary');
    await expect(summary).toBeVisible();
    await expect(summary).toContainText('바로 열기 48');
    await expect(summary).toContainText('비웹 1');
    await expect(summary).toContainText('확장 1');
    await expect(summary).toContainText('미배포 8');
  });

  test('B1 phase badges explicitly identify UI UX and BE semantics', async ({ page }) => {
    const badges = page.locator('.biz-item[data-biz-number="1"] .biz-phase-badge');
    await expect(badges).toHaveCount(3);
    await expect(badges.nth(0)).toHaveText('UI · 진행 중');
    await expect(badges.nth(1)).toHaveText('UX · UI 확정 대기');
    await expect(badges.nth(2)).toHaveText('BE · 동결');
  });

  test('B5 is shown as expanded to DanjiOn instead of an internal phase-gated Business', async ({ page }) => {
    const row = page.locator('.biz-item[data-biz-number="5"]');
    await expect(row).toHaveAttribute('data-portfolio-class', 'expanded-successor');
    await expect(row.locator('.biz-auth')).toHaveText('확장');
    await expect(row.locator('.biz-expanded-lineage')).toHaveText('단지온으로 확장 · 외부 개발');
    await expect(row.locator('.biz-phase-badge')).toHaveCount(0);
    await expect(row.locator('.biz-launch-state')).toHaveCount(0);
    await expect(row.locator('.biz-launch-external')).toHaveAttribute('href', 'https://github.com/skerishKang/02-danji-on');

    const identity = await page.evaluate(() => {
      const business = window.ARL_BUSINESSES.find((item) => item.number === 5);
      return {
        portfolioClass: business.portfolioClass,
        lifecycle: business.lifecycle,
        state: business.state,
        workspace: business.workspace,
        uiStatus: business.uiStatus,
        uxStatus: business.uxStatus,
        backendStatus: business.backendStatus,
      };
    });
    expect(identity).toEqual({
      portfolioClass: 'expanded-successor',
      lifecycle: 'expanded_successor',
      state: 'external',
      workspace: 'skerishKang/02-danji-on',
      uiStatus: 'NOT_APPLICABLE',
      uxStatus: 'NOT_APPLICABLE',
      backendStatus: 'NOT_APPLICABLE',
    });
  });

  test('B5 detail dialog explains that internal phases no longer apply', async ({ page }) => {
    const row = page.locator('.biz-item[data-biz-number="5"]');
    await row.locator('.biz-launch-detail').click();
    const dialog = page.locator('#business-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('.dialog-name')).toHaveText('Neighbor Market');
    await expect(dialog.locator('.dialog-section').nth(0).locator('.dialog-section-value')).toContainText('확장');
    await expect(dialog.locator('.dialog-section').nth(1).locator('.dialog-section-value')).toHaveText('단지온으로 확장 · 내부 UI/UX/BE 단계 미적용');
    await expect(dialog.locator('.expanded-successor-link')).toHaveAttribute('href', 'https://github.com/skerishKang/02-danji-on');
    await page.keyboard.press('Escape');
  });

  test('desktop launcher authority, phase and action columns share fixed axes', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });

    const rows = [1, 5, 6].map((number) => page.locator(`.biz-item[data-biz-number="${number}"]`));
    const boxes = [];
    for (const row of rows) {
      boxes.push({
        auth: await row.locator('.biz-auth').boundingBox(),
        phases: await row.locator('.biz-phase-group').boundingBox(),
        actions: await row.locator('.biz-launch-actions').boundingBox(),
      });
    }

    for (const key of ['auth', 'phases', 'actions']) {
      expect(boxes[0][key]).not.toBeNull();
      for (const box of boxes.slice(1)) {
        expect(Math.abs(box[key].x - boxes[0][key].x)).toBeLessThanOrEqual(1);
        expect(Math.abs(box[key].width - boxes[0][key].width)).toBeLessThanOrEqual(1);
      }
    }

    expect(boxes[0].auth.width).toBeGreaterThanOrEqual(115);
    expect(boxes[0].phases.width).toBeGreaterThanOrEqual(359);
    expect(boxes[0].actions.width).toBeGreaterThanOrEqual(155);
  });

  test('desktop phase badges align internally across normal rows', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });

    const first = page.locator('.biz-item[data-biz-number="1"] .biz-phase-badge');
    const sixth = page.locator('.biz-item[data-biz-number="6"] .biz-phase-badge');
    await expect(first).toHaveCount(3);
    await expect(sixth).toHaveCount(3);

    for (let index = 0; index < 3; index += 1) {
      const a = await first.nth(index).boundingBox();
      const b = await sixth.nth(index).boundingBox();
      expect(a).not.toBeNull();
      expect(b).not.toBeNull();
      expect(Math.abs(a.x - b.x)).toBeLessThanOrEqual(1);
      expect(Math.abs(a.width - b.width)).toBeLessThanOrEqual(1);
    }
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
