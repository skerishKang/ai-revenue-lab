const { test, expect } = require('@playwright/test');

async function openSearchPanel(page) {
  await page.click('[data-project-view="search"]');
  await page.waitForSelector('#project-search-panel:not([hidden])', { state: 'visible' });
}

test.describe('Work In Progress Queue', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
  });

  test('initial state shows projects active and work view hidden', async ({ page }) => {
    const projectsBtn = page.locator('[data-project-view="projects"]');
    await expect(projectsBtn).toHaveClass(/is-active/);
    await expect(projectsBtn).toHaveAttribute('aria-current', 'page');
    await expect(page.locator('#project-work-view')).toBeHidden();
    await expect(page.locator('.pd-card')).toHaveCount(13);
  });

  test('clicking work shows work view and hides project grid', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#project-work-view')).toBeVisible();
    const grid = page.locator('#pd-grid');
    await expect(grid).toBeHidden();
    const workBtn = page.locator('[data-project-view="work"]');
    await expect(workBtn).toHaveClass(/is-active/);
    await expect(workBtn).toHaveAttribute('aria-current', 'page');
    const projectsBtn = page.locator('[data-project-view="projects"]');
    await expect(projectsBtn).not.toHaveClass(/is-active/);
    await expect(projectsBtn).not.toHaveAttribute('aria-current');
    const searchBtn = page.locator('[data-project-view="search"]');
    await expect(searchBtn).toHaveAttribute('aria-expanded', 'false');
  });

  test('shows exactly 10 work items', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const items = page.locator('.work-item');
    await expect(items).toHaveCount(10);
  });

  test('shows review group count 4 and active group count 6', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const reviewHeading = page.locator('.work-group-heading').first();
    const activeHeading = page.locator('.work-group-heading').nth(1);
    await expect(reviewHeading).toContainText('4');
    await expect(activeHeading).toContainText('6');
  });

  test('no duplicate project IDs in work queue', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const ids = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('.work-item')).map(el => el.getAttribute('data-project-id'));
    });
    const uniqueIds = new Set(ids);
    expect(ids.length).toBe(uniqueIds.size);
  });

  test('source order preserved in each group', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const ids = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('.work-item')).map(el => el.getAttribute('data-project-id'));
    });
    const expectedReviewOrder = ['personal-edition', 'living-fiction', 'personal-video-archive', 'korean-ai-platform'];
    const expectedActiveOrder = ['portfolio-console', 'lovebud', 'living-travel', 'living-learning', 'lovetree-3', 'ai-finder-bukgu'];
    const reviewIds = ids.slice(0, 4);
    const activeIds = ids.slice(4, 10);
    expect(reviewIds).toEqual(expectedReviewOrder);
    expect(activeIds).toEqual(expectedActiveOrder);
  });

  test('Portfolio Console shows 60% progress', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const pcItem = page.locator('.work-item[data-project-id="portfolio-console"]');
    await expect(pcItem).toContainText('60%');
    await expect(pcItem).toContainText('완료');
  });

  test('LoveBud shows 50% progress', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const lbItem = page.locator('.work-item[data-project-id="lovebud"]');
    await expect(lbItem).toContainText('50%');
  });

  test('Living Travel shows 33% progress', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const ltItem = page.locator('.work-item[data-project-id="living-travel"]');
    await expect(ltItem).toContainText('33%');
  });

  test('Living Fiction shows 0% progress and blocker', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const lfItem = page.locator('.work-item[data-project-id="living-fiction"]');
    await expect(lfItem).toContainText('0%');
    await expect(lfItem).toContainText('배포 주소 404');
  });

  test('Korean AI Platform shows undefined progress and Provider registry blocker', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const kapItem = page.locator('.work-item[data-project-id="korean-ai-platform"]');
    await expect(kapItem).toContainText('진척도 미정');
    await expect(kapItem).toContainText('Provider registry');
  });

  test('LoveTree 3.0 shows undefined progress', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const ltItem = page.locator('.work-item[data-project-id="lovetree-3"]');
    await expect(ltItem).toContainText('진척도 미정');
  });

  test('work items have stage badge', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const items = page.locator('.work-item');
    const count = await items.count();
    for (let i = 0; i < count; i++) {
      await expect(items.nth(i).locator('.status-badge')).not.toBeEmpty();
    }
  });

  test('work items have developmentMode badge', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const items = page.locator('.work-item');
    const count = await items.count();
    for (let i = 0; i < count; i++) {
      await expect(items.nth(i).locator('.pd-mode-badge')).not.toBeEmpty();
    }
  });

  test('work items show currentWork', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const items = page.locator('.work-item');
    const count = await items.count();
    for (let i = 0; i < count; i++) {
      const currentWork = await items.nth(i).locator('.work-item-value').first().textContent();
      expect(currentWork.length).toBeGreaterThan(0);
    }
  });

  test('work items show nextAction', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const items = page.locator('.work-item');
    const count = await items.count();
    for (let i = 0; i < count; i++) {
      const nextAction = await items.nth(i).locator('.work-item-value').nth(1).textContent();
      expect(nextAction.length).toBeGreaterThan(0);
    }
  });

  test('service link exists for deployed projects', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const serviceLinks = page.locator('.work-item-service-link');
    const count = await serviceLinks.count();
    expect(count).toBeGreaterThan(0);
  });

  test('service links have security attributes', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const links = page.locator('.work-item-service-link');
    const count = await links.count();
    for (let i = 0; i < count; i++) {
      await expect(links.nth(i)).toHaveAttribute('target', '_blank');
      await expect(links.nth(i)).toHaveAttribute('rel', 'noopener noreferrer');
      await expect(links.nth(i)).toHaveAttribute('href', /^https:\/\//);
    }
  });

  test('Living Fiction has no service link', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const lfItem = page.locator('.work-item[data-project-id="living-fiction"]');
    const serviceLinkCount = await lfItem.locator('.work-item-service-link').count();
    const repoLinkCount = await lfItem.locator('.work-item-repo-link').count();
    const detailBtnCount = await lfItem.locator('.work-item-detail-btn').count();
    expect(serviceLinkCount).toBe(0);
    expect(repoLinkCount).toBe(1);
    expect(detailBtnCount).toBe(1);
  });

  test('view detail button opens project detail and switches to projects view', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    await page.click('.work-item[data-project-id="lovebud"] .work-item-detail-btn');
    await page.waitForTimeout(400);
    const projectsBtn = page.locator('[data-project-view="projects"]');
    await expect(projectsBtn).toHaveClass(/is-active/);
    await expect(projectsBtn).toHaveAttribute('aria-current', 'page');
    await expect(page.locator('#pd-detail-title')).toHaveText('LoveBud');
    await expect(page.locator('#pd-detail-badge')).toHaveText('운영 중');
  });

  test('no nested interactive elements in work items', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const nested = page.locator('.work-item a button');
    await expect(nested).toHaveCount(0);
  });

  test('work to search transitions correctly', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    await page.click('[data-project-view="search"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#project-work-view')).toBeHidden();
    await expect(page.locator('#pd-grid')).not.toBeHidden();
    await expect(page.locator('#project-search-panel')).toBeVisible();
    const searchBtn = page.locator('[data-project-view="search"]');
    await expect(searchBtn).toHaveAttribute('aria-expanded', 'true');
  });

  test('work to projects transitions and resets filters', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    await page.click('[data-project-view="projects"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#project-work-view')).toBeHidden();
    await expect(page.locator('#pd-grid')).not.toBeHidden();
    await expect(page.locator('.pd-card')).toHaveCount(13);
    const projectsBtn = page.locator('[data-project-view="projects"]');
    await expect(projectsBtn).toHaveAttribute('aria-current', 'page');
  });

  test('language switch preserves work view', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await expect(page.locator('#project-work-view')).toBeVisible();
    await expect(page.locator('#work-view-heading')).toHaveText('IN PROGRESS');
    await expect(page.locator('#nav-work-in-progress')).toHaveText('IN PROGRESS');
    await page.click('#lang-ko');
    await page.waitForTimeout(200);
    await expect(page.locator('#work-view-heading')).toHaveText('작업 중');
    await expect(page.locator('#nav-work-in-progress')).toHaveText('작업 중');
  });

  test('no console errors', async ({ page }) => {
    const errors = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
    page.on('pageerror', err => errors.push(err.message));
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
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
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    await page.reload({ waitUntil: 'networkidle' });
    expect(failed).toHaveLength(0);
  });

  test('no horizontal overflow at desktop', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('no horizontal overflow at tablet', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('no horizontal overflow at mobile', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('aria-current: only projects on initial load', async ({ page }) => {
    const count = await page.evaluate(() => document.querySelectorAll(".project-nav-item[aria-current='page']").length);
    expect(count).toBe(1);
    const projectsBtn = page.locator('[data-project-view="projects"]');
    await expect(projectsBtn).toHaveAttribute('aria-current', 'page');
    const workBtn = page.locator('[data-project-view="work"]');
    await expect(workBtn).not.toHaveAttribute('aria-current');
    const searchBtn = page.locator('[data-project-view="search"]');
    await expect(searchBtn).not.toHaveAttribute('aria-current');
  });

  test('aria-current: only work after clicking work', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const count = await page.evaluate(() => document.querySelectorAll(".project-nav-item[aria-current='page']").length);
    expect(count).toBe(1);
    const workBtn = page.locator('[data-project-view="work"]');
    await expect(workBtn).toHaveAttribute('aria-current', 'page');
  });

  test('aria-current: search only and aria-expanded true after work to search', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    await page.click('[data-project-view="search"]');
    await page.waitForTimeout(200);
    const count = await page.evaluate(() => document.querySelectorAll(".project-nav-item[aria-current='page']").length);
    expect(count).toBe(1);
    const searchBtn = page.locator('[data-project-view="search"]');
    await expect(searchBtn).toHaveAttribute('aria-current', 'page');
    await expect(searchBtn).toHaveAttribute('aria-expanded', 'true');
  });

  test('aria-current: only projects after search close', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    await page.click('[data-project-view="search"]');
    await page.waitForTimeout(200);
    await page.click('#project-search-close');
    await page.waitForTimeout(200);
    const count = await page.evaluate(() => document.querySelectorAll(".project-nav-item[aria-current='page']").length);
    expect(count).toBe(1);
    const projectsBtn = page.locator('[data-project-view="projects"]');
    await expect(projectsBtn).toHaveAttribute('aria-current', 'page');
  });

  test('work view heading focused after click and has tabindex=-1', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const headingId = await page.evaluate(() => document.activeElement.id);
    expect(headingId).toBe('work-view-heading');
    const tabindex = await page.locator('#work-view-heading').getAttribute('tabindex');
    expect(tabindex).toBe('-1');
  });

  test('EN work view shows translated labels and count', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await expect(page.locator('#work-view-heading')).toHaveText('IN PROGRESS');
    const workSection = page.locator('#project-work-view');
    await expect(workSection).toHaveAttribute('aria-labelledby', 'work-view-heading');
    await expect(page.locator('#work-view-count')).toHaveText('10 projects');
    const countText = await page.locator('#work-view-count').textContent();
    expect(countText).not.toContain('개');
    await expect(page.locator('#nav-work-in-progress')).toHaveText('IN PROGRESS');
    await expect(page.locator('.work-group-heading').first()).toContainText('REVIEW & IMPROVEMENT');
    await expect(page.locator('.work-group-heading').nth(1)).toContainText('ACTIVE DEVELOPMENT');
    const reviewGroupItems = page.locator('.work-group').first().locator('.work-item');
    await expect(reviewGroupItems).toHaveCount(4);
    const activeGroupItems = page.locator('.work-group').nth(1).locator('.work-item');
    await expect(activeGroupItems).toHaveCount(6);
  });

  test('EN work view service and repo links have correct labels', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    const serviceLinks = page.locator('.work-item-service-link');
    const count = await serviceLinks.count();
    for (let i = 0; i < count; i++) {
      await expect(serviceLinks.nth(i)).toHaveText('OPEN SERVICE');
    }
    const repoLinks = page.locator('.work-item-repo-link');
    const repoCount = await repoLinks.count();
    for (let i = 0; i < repoCount; i++) {
      await expect(repoLinks.nth(i)).toHaveText('OPEN REPOSITORY');
    }
  });

  test('KO restored after EN work view', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await expect(page.locator('#work-view-heading')).toHaveText('IN PROGRESS');
    await page.click('#lang-ko');
    await page.waitForTimeout(200);
    await expect(page.locator('#work-view-heading')).toHaveText('작업 중');
    await expect(page.locator('#work-view-count')).toHaveText('10개');
  });

  test('each work item article has accessible name with project name', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const items = page.locator('.work-item');
    const count = await items.count();
    expect(count).toBe(10);
    for (let i = 0; i < count; i++) {
      const labelledBy = await items.nth(i).getAttribute('aria-labelledby');
      expect(labelledBy).toBeTruthy();
      expect(labelledBy).toMatch(/^work-item-name-/);
      const nameText = await page.evaluate((id) => {
        const el = document.getElementById(id);
        return el ? el.textContent : '';
      }, labelledBy);
      expect(nameText.length).toBeGreaterThan(0);
    }
  });

  test('work item accessible names match expected project names', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const expectedNames = [
      'Personal Edition',
      'Living Fiction',
      'Personal Video Archive',
      'Korean AI Platform',
      'Portfolio Console',
      'LoveBud',
      'Living Travel',
      'Living Learning',
      'LoveTree 3.0',
      'AI Finder / 광주 북구청'
    ];
    const items = page.locator('.work-item');
    const count = await items.count();
    expect(count).toBe(10);
    for (let i = 0; i < count; i++) {
      const labelledBy = await items.nth(i).getAttribute('aria-labelledby');
      expect(labelledBy).toBeTruthy();
      const nameText = await page.evaluate((id) => {
        const el = document.getElementById(id);
        return el ? el.textContent : '';
      }, labelledBy);
      expect(nameText).toBe(expectedNames[i]);
    }
  });

  test('aria-current: exactly one after work click', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    const count = await page.evaluate(() => document.querySelectorAll(".project-nav-item[aria-current='page']").length);
    expect(count).toBe(1);
  });

  test('aria-current: exactly one after work to projects', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    await page.click('[data-project-view="projects"]');
    await page.waitForTimeout(200);
    const count = await page.evaluate(() => document.querySelectorAll(".project-nav-item[aria-current='page']").length);
    expect(count).toBe(1);
  });

  test('aria-current: exactly one after Escape', async ({ page }) => {
    await page.click('[data-project-view="work"]');
    await page.waitForTimeout(200);
    await page.click('[data-project-view="search"]');
    await page.waitForTimeout(200);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);
    const count = await page.evaluate(() => document.querySelectorAll(".project-nav-item[aria-current='page']").length);
    expect(count).toBe(1);
  });
});
