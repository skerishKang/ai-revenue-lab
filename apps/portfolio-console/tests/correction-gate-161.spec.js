const { test, expect } = require('@playwright/test');

function getViewport(page) {
  return page.evaluate(() => ({ w: window.innerWidth, h: window.innerHeight }));
}

test.describe('Correction Gate 161 — Initial Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
  });

  test('header + 13 cards only on initial load', async ({ page }) => {
    await expect(page.locator('#topbar-title')).toBeVisible();
    await expect(page.locator('.pd-card')).toHaveCount(13);
    await expect(page.locator('.metric-grid')).toHaveCount(0);
    await expect(page.locator('.metric-card')).toHaveCount(0);
    await expect(page.locator('.priority-item')).toHaveCount(0);
    await expect(page.locator('#business-table-body')).toHaveCount(0);
    await expect(page.locator('.business-row')).toHaveCount(0);
    await expect(page.locator('.pd-detail')).toHaveCount(0);
    await expect(page.locator('#detail-panel')).toHaveCount(0);
    await expect(page.locator('.control-strip')).toHaveCount(0);
    await expect(page.locator('#project-directory-heading')).toHaveCount(0);
  });

  test('B01, B14 displayed in cards', async ({ page }) => {
    const cardB01 = page.locator('.pd-card-biznumber', { hasText: 'B01' });
    const cardB14 = page.locator('.pd-card-biznumber', { hasText: 'B14' });
    const cardB13 = page.locator('.pd-card-biznumber', { hasText: 'B13' });
    await expect(cardB01).toHaveCount(1);
    await expect(cardB14).toHaveCount(1);
    await expect(cardB13).toHaveCount(1);
  });

  test('null businessNumber shows PROJECT label, no random generation', async ({ page }) => {
    const projectsWithoutBiz = ['portfolio-console', 'lovebud', 'lovetree-3', 'ai-finder-bukgu', 'love-matchmaking', 'ai-finder-namgu', 'ai-finder-seogu'];
    for (const id of projectsWithoutBiz) {
      const card = page.locator(`.pd-card[data-project-id="${id}"]`);
      await expect(card.locator('.pd-card-biznumber')).toHaveText('PROJECT');
    }
  });

  test('exactly 4 sidebar menu buttons', async ({ page }) => {
    const buttons = page.locator('.view-nav-item');
    await expect(buttons).toHaveCount(4);
  });

  test('no decorative side-nav (business/deployments/github/models/registry)', async ({ page }) => {
    await expect(page.locator('.side-nav')).toHaveCount(0);
    await expect(page.locator('[data-view="deployments"]')).toHaveCount(0);
    await expect(page.locator('[data-view="github"]')).toHaveCount(0);
    await expect(page.locator('[data-view="models"]')).toHaveCount(0);
    await expect(page.locator('[data-view="registry"]')).toHaveCount(0);
  });

  test('search initially hidden', async ({ page }) => {
    await expect(page.locator('#view-search')).toBeHidden();
  });

  test('search visible only when search menu clicked', async ({ page }) => {
    await page.click('.view-nav-item[data-view="search"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#view-search')).toBeVisible();
    await expect(page.locator('#view-projects')).toBeHidden();
  });

  test('WIP shows 10 items with 4 review and 6 active', async ({ page }) => {
    await page.click('.view-nav-item[data-view="work"]');
    await page.waitForTimeout(200);
    const items = page.locator('.work-item');
    await expect(items).toHaveCount(10);
    const summaryText = await page.locator('#work-summary-text').textContent();
    expect(summaryText).toContain('10');
    expect(summaryText).toContain('4');
    expect(summaryText).toContain('6');
  });

  test('no metric-grid', async ({ page }) => {
    await expect(page.locator('.metric-grid')).toHaveCount(0);
  });

  test('no Priority Actions', async ({ page }) => {
    await expect(page.locator('.priority-item')).toHaveCount(0);
    await expect(page.locator('#activity-heading')).toHaveCount(0);
  });

  test('no duplicate project table', async ({ page }) => {
    await expect(page.locator('#business-table-body')).toHaveCount(0);
  });

  test('no fixed below-grid detail panel', async ({ page }) => {
    await expect(page.locator('#pd-detail')).toHaveCount(0);
    await expect(page.locator('.pd-detail')).toHaveCount(0);
  });

  test('Business Registry visible only in business-index view', async ({ page }) => {
    await expect(page.locator('#view-business')).toBeHidden();
    await page.click('.view-nav-item[data-view="business"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#view-business')).toBeVisible();
    await expect(page.locator('#biz-list')).toBeVisible();
    await expect(page.locator('.biz-item')).toHaveCount(15);
  });

  test('dark theme is default', async ({ page }) => {
    const theme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    expect(theme).toBe('dark');
  });

  test('light theme persists on reload', async ({ page }) => {
    await page.evaluate(() => localStorage.setItem('arl-portfolio-theme', 'light'));
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    const theme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    expect(theme).toBe('light');
  });

  test('invalid theme falls back to dark', async ({ page }) => {
    await page.evaluate(() => localStorage.setItem('arl-portfolio-theme', 'invalid'));
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    const theme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    expect(theme).toBe('dark');
  });

  test('theme toggle switches to light and back', async ({ page }) => {
    await page.click('#theme-toggle');
    await page.waitForTimeout(100);
    const theme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    expect(theme).toBe('light');
    await page.click('#theme-toggle');
    await page.waitForTimeout(100);
    const theme2 = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    expect(theme2).toBe('dark');
  });

  test('KO/EN toggles work', async ({ page }) => {
    await expect(page.locator('#topbar-title')).toContainText('내 비즈니스 관리');
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await expect(page.locator('#topbar-title')).toContainText('Business Operations');
    await page.click('#lang-ko');
    await page.waitForTimeout(200);
    await expect(page.locator('#topbar-title')).toContainText('내 비즈니스 관리');
  });

  test('no console errors', async ({ page }) => {
    const errors = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
    page.on('pageerror', err => errors.push(err.message));
    await page.reload({ waitUntil: 'networkidle' });
    expect(errors).toHaveLength(0);
  });

  test('no page errors', async ({ page }) => {
    const errors = [];
    page.on('pageerror', err => errors.push(err.message));
    await page.reload({ waitUntil: 'networkidle' });
    expect(errors).toHaveLength(0);
  });

  test('no failed requests', async ({ page }) => {
    const failed = [];
    page.on('requestfailed', req => {
      if (!req.url().startsWith('data:') && !req.url().startsWith('ws:')) failed.push(req.url());
    });
    await page.reload({ waitUntil: 'networkidle' });
    expect(failed).toHaveLength(0);
  });

  test('no horizontal overflow', async ({ page }) => {
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });
});

test.describe('Correction Gate 161 — Dialog', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
  });

  test('native dialog opens on detail button click', async ({ page }) => {
    await page.locator('.pd-card-detail-btn').first().click();
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();
    const isOpen = await dialog.evaluate(el => el.open);
    expect(isOpen).toBe(true);
  });

  test('dialog closes on Escape', async ({ page }) => {
    await page.locator('.pd-card-detail-btn').first().click();
    await page.waitForTimeout(300);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeHidden();
  });

  test('dialog closes on close button', async ({ page }) => {
    await page.locator('.pd-card-detail-btn').first().click();
    await page.waitForTimeout(300);
    await page.locator('#dialog-close-btn').click();
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeHidden();
  });

  test('focus returns to calling card after dialog close', async ({ page }) => {
    const firstBtn = page.locator('.pd-card-detail-btn').first();
    const btnId = await firstBtn.evaluate(el => el.dataset.projectId);
    await firstBtn.click();
    await page.waitForTimeout(300);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    const activeId = await page.evaluate(() => {
      const el = document.activeElement;
      return el ? el.dataset.projectId : null;
    });
    expect(activeId).toBe(btnId);
  });

  test('work queue detail button opens same dialog', async ({ page }) => {
    await page.click('.view-nav-item[data-view="work"]');
    await page.waitForTimeout(200);
    await page.locator('.work-detail-btn').first().click();
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();
    await page.keyboard.press('Escape');
  });
});

test.describe('Correction Gate 161 — Viewport Variants', () => {
  test('Desktop 1440x1100: dashboard renders correctly', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(500);
    await expect(page.locator('.pd-card')).toHaveCount(13);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('Tablet 768x1024: dashboard renders correctly', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(500);
    await expect(page.locator('.pd-card')).toHaveCount(13);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('Mobile 390x844: dashboard renders correctly', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(500);
    await expect(page.locator('.pd-card')).toHaveCount(13);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('Mobile 390x844: menu toggle and drawer work', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(500);
    await page.click('#menu-toggle');
    await page.waitForTimeout(300);
    await expect(page.locator('#sidebar')).toHaveClass(/is-open/);
    await page.locator('#drawer-close').click({ force: true });
    await page.waitForTimeout(400);
    await expect(page.locator('#sidebar')).not.toHaveClass(/is-open/);
  });

  test('Mobile 390x844: drawer closes on overlay click', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(500);
    await page.click('#menu-toggle');
    await page.waitForTimeout(300);
    await page.click('#drawer-overlay');
    await page.waitForTimeout(300);
    await expect(page.locator('#sidebar')).not.toHaveClass(/is-open/);
  });

  test('Mobile 390x844: full-screen dialog', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(500);
    await page.locator('.pd-card-detail-btn').first().click();
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();
    const box = await dialog.boundingBox();
    expect(box.width).toBeCloseTo(390, -1);
    await page.keyboard.press('Escape');
  });
});

test.describe('Correction Gate 161 — Desktop Grid 3/2/1', () => {
  test('Desktop 1440x1100: first 3 cards same row, 4th card wraps', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(500);
    await expect(page.locator('.pd-card')).toHaveCount(13);
    const boxes = await page.locator('.pd-card').evaluateAll(cards =>
      cards.map(c => {
        const r = c.getBoundingClientRect();
        return { y: r.y, top: r.top };
      })
    );
    expect(boxes[0].y).toBe(boxes[1].y);
    expect(boxes[1].y).toBe(boxes[2].y);
    expect(boxes[3].y).toBeGreaterThan(boxes[0].y);
  });

  test('Desktop 1440x1100: grid computed 3 columns', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(500);
    const gridTemplate = await page.locator('#pd-grid').evaluate(el =>
      getComputedStyle(el).getPropertyValue('grid-template-columns')
    );
    const colCount = gridTemplate.split(/\s+/).filter(s => s.trim() && s !== 'repeat').length;
    expect(colCount).toBe(3);
  });

  test('Tablet ~900px: 2 columns', async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 1024 });
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(500);
    await expect(page.locator('.pd-card')).toHaveCount(13);
    const boxes = await page.locator('.pd-card').evaluateAll(cards =>
      cards.map(c => {
        const r = c.getBoundingClientRect();
        return { y: r.y, top: r.top };
      })
    );
    expect(boxes[0].y).toBe(boxes[1].y);
    expect(boxes[2].y).toBeGreaterThan(boxes[0].y);
  });

  test('Mobile 390x844: 1 column', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(500);
    await expect(page.locator('.pd-card')).toHaveCount(13);
    const boxes = await page.locator('.pd-card').evaluateAll(cards =>
      cards.map(c => c.getBoundingClientRect())
    );
    for (let i = 1; i < boxes.length; i++) {
      expect(boxes[i].y).toBeGreaterThanOrEqual(boxes[i - 1].y + boxes[i - 1].height - 1);
    }
  });
});

test.describe('Correction Gate 161 — Card GitHub Status', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
  });

  test('all 13 cards show disconnected status in KO', async ({ page }) => {
    const states = page.locator('.pd-card-github-state');
    await expect(states).toHaveCount(13);
    const texts = await states.allTextContents();
    for (const text of texts) {
      expect(text.trim()).toBe('자동 동기화 미연결');
    }
  });

  test('EN switch updates all 13 cards to English', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(300);
    const states = page.locator('.pd-card-github-state');
    await expect(states).toHaveCount(13);
    const texts = await states.allTextContents();
    for (const text of texts) {
      expect(text.trim()).toBe('GITHUB LIVE SYNC NOT CONNECTED');
    }
  });

  test('KO switch restores Korean on all cards', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await page.click('#lang-ko');
    await page.waitForTimeout(200);
    const states = page.locator('.pd-card-github-state');
    const texts = await states.allTextContents();
    for (const text of texts) {
      expect(text.trim()).toBe('자동 동기화 미연결');
    }
  });

  test('no fake Issue/PR/CI numbers in GitHub status area', async ({ page }) => {
    const stateText = await page.locator('.pd-card-github-state').allTextContents();
    for (const text of stateText) {
      expect(text.trim()).not.toMatch(/#\d+/);
    }
  });
});

test.describe('Correction Gate 161 — Dialog Content', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
  });

  test('first project dialog shows progressBasis', async ({ page }) => {
    await page.locator('.pd-card-detail-btn').first().click();
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('.dialog-section-label', { hasText: '진척 기준' })).toBeVisible();
  });

  test('first project dialog shows completed tasks section', async ({ page }) => {
    await page.locator('.pd-card-detail-btn').first().click();
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('.dialog-section-label', { hasText: '완료 작업' })).toBeVisible();
    const items = dialog.locator('.dialog-task-list').first().locator('.dialog-task-item');
    const count = await items.count();
    expect(count).toBeGreaterThan(0);
  });

  test('first project dialog shows remaining tasks section', async ({ page }) => {
    await page.locator('.pd-card-detail-btn').first().click();
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('.dialog-section-label', { hasText: '남은 작업' })).toBeVisible();
  });

  test('first project dialog shows GitHub disconnected section', async ({ page }) => {
    await page.locator('.pd-card-detail-btn').first().click();
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('.dialog-section-label', { hasText: 'GitHub 상태' })).toBeVisible();
    await expect(dialog.locator('.dialog-section-value', { hasText: '자동 동기화 미연결' })).toBeVisible();
  });

  test('first project dialog shows repository', async ({ page }) => {
    await page.locator('.pd-card-detail-btn').first().click();
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('.dialog-section-label', { hasText: '저장소' })).toBeVisible();
  });

  test('first project dialog shows workspace', async ({ page }) => {
    await page.locator('.pd-card-detail-btn').first().click();
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('.dialog-section-label', { hasText: '폴더' })).toBeVisible();
  });

  test('first project dialog shows lastVerified', async ({ page }) => {
    await page.locator('.pd-card-detail-btn').first().click();
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('.dialog-section-label', { hasText: '마지막 확인' })).toBeVisible();
  });

  test('language switch updates open dialog content without closing', async ({ page }) => {
    await page.locator('.pd-card-detail-btn').first().click();
    await page.waitForTimeout(300);
    const dialog = page.locator('#project-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('.dialog-section-label', { hasText: 'GitHub 상태' })).toBeVisible();
    await page.evaluate(() => {
      const btn = document.querySelector('#lang-en');
      if (btn) btn.click();
    });
    await page.waitForTimeout(300);
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('.dialog-section-label', { hasText: 'GITHUB STATUS' })).toBeVisible();
    await expect(dialog.locator('.dialog-section-value', { hasText: 'GITHUB LIVE SYNC NOT CONNECTED' })).toBeVisible();
    await page.keyboard.press('Escape');
  });
});

test.describe('Correction Gate 161 — Evidence Viewport', () => {
  test('Desktop 1440x1100 viewport is correctly set for screenshot generation', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(500);
    const vp = await page.evaluate(() => ({ w: window.innerWidth, h: window.innerHeight }));
    expect(vp.w).toBe(1440);
    expect(vp.h).toBe(1100);
    await expect(page.locator('.pd-card')).toHaveCount(13);
  });

  test('Desktop 1440x1100 shows 3-column grid', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(500);
    const colCount = await page.evaluate(() => {
      const grid = document.querySelector('.pd-grid');
      const cols = getComputedStyle(grid).getPropertyValue('grid-template-columns');
      return cols.split(/\s+/).filter(s => s.trim() && s !== 'repeat').length;
    });
    expect(colCount).toBe(3);
  });
});
