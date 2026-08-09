const { test, expect } = require('@playwright/test');

test.describe('Portfolio Console Business Launcher', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(180);
  });

  test('Business index is the default launcher view', async ({ page }) => {
    await expect(page.locator('#view-business')).toBeVisible();
    await expect(page.locator('.view-nav-item[data-view="business"]')).toHaveClass(/is-active/);
    await expect(page.locator('.biz-item')).toHaveCount(58);
  });

  test('launcher separates internal web, non-web and all external or successor Businesses', async ({ page }) => {
    const summary = page.locator('#business-launcher-summary');
    await expect(summary).toBeVisible();
    await expect(summary).toContainText('바로 열기 46');
    await expect(summary).toContainText('비웹 1');
    await expect(summary).toContainText('확장 11');
    await expect(summary).toContainText('미배포 0');
  });

  test('B1 owner rejection is rendered as redesign while technical phase truth remains available', async ({ page }) => {
    const row = page.locator('.biz-item[data-biz-number="1"]');
    const badges = row.locator('.biz-phase-badge');
    await expect(row).toHaveAttribute('data-owner-ui-status', 'OWNER_REJECTED');
    await expect(badges).toHaveCount(3);
    await expect(badges.nth(0)).toHaveText('UI · 재설계');
    await expect(badges.nth(1)).toHaveText('UX · UI 확정 대기');
    await expect(badges.nth(2)).toHaveText('BE · 동결');

    const identity = await page.evaluate(() => {
      const business = window.ARL_BUSINESSES.find((item) => item.number === 1);
      return {
        ownerUiStatus: business.ownerUiStatus,
        uiStatus: business.uiStatus,
        uxStatus: business.uxStatus,
        backendStatus: business.backendStatus,
      };
    });
    expect(identity).toEqual({
      ownerUiStatus: 'OWNER_REJECTED',
      uiStatus: 'UI_NOT_READY',
      uxStatus: 'BLOCKED_BY_UI',
      backendStatus: 'FROZEN',
    });
  });

  test('historical technical UI approval is not displayed as final owner approval', async ({ page }) => {
    for (const number of [2, 4, 6, 13, 14, 44]) {
      const row = page.locator(`.biz-item[data-biz-number="${number}"]`);
      await expect(row).toHaveAttribute('data-owner-ui-status', 'OWNER_REVIEW_REQUIRED');
      await expect(row.locator('.biz-phase-badge').nth(0)).toHaveText('UI · 검토 필요');
    }

    const technical = await page.evaluate(() => [2, 4, 6, 13, 14, 44].map((number) => {
      const business = window.ARL_BUSINESSES.find((item) => item.number === number);
      return [number, business.uiStatus, business.ownerUiStatus];
    }));
    expect(technical).toEqual([
      [2, 'UI_APPROVED', 'OWNER_REVIEW_REQUIRED'],
      [4, 'UI_APPROVED', 'OWNER_REVIEW_REQUIRED'],
      [6, 'UI_APPROVED', 'OWNER_REVIEW_REQUIRED'],
      [13, 'UI_APPROVED', 'OWNER_REVIEW_REQUIRED'],
      [14, 'UI_APPROVED', 'OWNER_REVIEW_REQUIRED'],
      [44, 'UI_APPROVED', 'OWNER_REVIEW_REQUIRED'],
    ]);
  });

  test('all #396 hard exclusions are list-only external or successor rows with no internal phase badges', async ({ page }) => {
    const excluded = [3, 5, 23, 24, 25, 26, 27, 28, 30, 31, 50];
    for (const number of excluded) {
      const row = page.locator(`.biz-item[data-biz-number="${number}"]`);
      await expect(row).toHaveAttribute('data-portfolio-class', 'expanded-successor');
      await expect(row).toHaveAttribute('data-owner-ui-status', 'NOT_APPLICABLE');
      await expect(row.locator('.biz-phase-badge')).toHaveCount(0);
      await expect(row.locator('.biz-auth')).toHaveText('외부/확장');
    }

    const states = await page.evaluate((numbers) => numbers.map((number) => {
      const business = window.ARL_BUSINESSES.find((item) => item.number === number);
      return [number, business.uiStatus, business.uxStatus, business.backendStatus, business.ownerUiStatus];
    }), excluded);
    states.forEach(([number, ui, ux, be, owner]) => {
      expect([ui, ux, be, owner], `B${number}`).toEqual(['NOT_APPLICABLE', 'NOT_APPLICABLE', 'NOT_APPLICABLE', 'NOT_APPLICABLE']);
    });
  });

  test('B5 is shown as expanded to DanjiOn with authoritative source link', async ({ page }) => {
    const row = page.locator('.biz-item[data-biz-number="5"]');
    await expect(row).toHaveAttribute('data-boundary-kind', 'expanded-successor');
    await expect(row.locator('.biz-expanded-lineage')).toHaveText('단지온으로 확장 · 외부 개발');
    await expect(row.locator('.biz-launch-external')).toHaveAttribute('href', 'https://github.com/skerishKang/02-danji-on');
  });

  test('B23 and B24 keep direct access to their existing external live sites', async ({ page }) => {
    await expect(page.locator('.biz-item[data-biz-number="23"] .biz-launch-external'))
      .toHaveAttribute('href', 'https://lovebud.pages.dev/');
    await expect(page.locator('.biz-item[data-biz-number="24"] .biz-launch-external'))
      .toHaveAttribute('href', 'https://lovetree3.pages.dev/');
    await expect(page.locator('.biz-item[data-biz-number="23"] .biz-launch-external')).toHaveText('사이트 열기 ↗');
    await expect(page.locator('.biz-item[data-biz-number="24"] .biz-launch-external')).toHaveText('사이트 열기 ↗');
  });

  test('integrated successor lineages are explicit and do not invent repository links', async ({ page }) => {
    for (const number of [26, 28, 50]) {
      const row = page.locator(`.biz-item[data-biz-number="${number}"]`);
      await expect(row).toHaveAttribute('data-boundary-kind', 'integrated-successor');
      await expect(row.locator('.biz-expanded-lineage')).toHaveText('이어온으로 통합 · 외부 개발');
      await expect(row.locator('.biz-launch-state')).toHaveText('외부 작업');
      await expect(row.locator('.biz-launch-external')).toHaveCount(0);
    }
    for (const number of [27, 31]) {
      const row = page.locator(`.biz-item[data-biz-number="${number}"]`);
      await expect(row).toHaveAttribute('data-boundary-kind', 'integrated-successor');
      await expect(row.locator('.biz-expanded-lineage')).toHaveText('사실로으로 통합 · 외부 개발');
      await expect(row.locator('.biz-launch-state')).toHaveText('외부 작업');
      await expect(row.locator('.biz-launch-external')).toHaveCount(0);
    }
  });

  test('B30 points to 400-ai-finder instead of an internal placeholder', async ({ page }) => {
    const row = page.locator('.biz-item[data-biz-number="30"]');
    await expect(row).toHaveAttribute('data-boundary-kind', 'expanded-successor');
    await expect(row.locator('.biz-expanded-lineage')).toHaveText('400-ai-finder으로 확장 · 외부 개발');
    await expect(row.locator('.biz-launch-external')).toHaveAttribute('href', 'https://github.com/skerishKang/400-ai-finder');
  });

  test('B3 is conservatively excluded as external parallel work without invented source URL', async ({ page }) => {
    const row = page.locator('.biz-item[data-biz-number="3"]');
    await expect(row).toHaveAttribute('data-boundary-kind', 'external-parallel');
    await expect(row.locator('.biz-expanded-lineage')).toHaveText('외부·병렬 확장 · 내부 개발 제외');
    await expect(row.locator('.biz-launch-state')).toHaveText('외부 작업');
    await expect(row.locator('.biz-launch-external')).toHaveCount(0);
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

  test('clicking an internal web Business row opens its service directly', async ({ page }) => {
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
