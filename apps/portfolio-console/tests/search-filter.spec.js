const { test, expect } = require('@playwright/test');

async function openSearchPanel(page) {
  await page.click('[data-project-view="search"]');
  await page.waitForSelector('#project-search-panel:not([hidden])', { state: 'visible' });
}

test.describe('Sidebar Search & Filter - Basic State', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
  });

  test('search panel is closed on initial load', async ({ page }) => {
    const hidden = await page.locator('#project-search-panel').getAttribute('hidden');
    expect(hidden).not.toBeNull();
  });

  test('search input is not focusable when panel is closed', async ({ page }) => {
    const isFocused = await page.evaluate(() => {
      const input = document.querySelector('#pd-search-input');
      input.focus();
      return input === document.activeElement;
    });
    expect(isFocused).toBeFalsy();
  });

  test('renders 13 project cards', async ({ page }) => {
    await expect(page.locator('.pd-card')).toHaveCount(13);
  });

  test('project status menu is active with aria-current', async ({ page }) => {
    const btn = page.locator('[data-project-view="projects"]');
    await expect(btn).toHaveClass(/is-active/);
    await expect(btn).toHaveAttribute('aria-current', 'page');
  });

  test('search filter button has aria-expanded=false', async ({ page }) => {
    const btn = page.locator('[data-project-view="search"]');
    await expect(btn).toHaveAttribute('aria-expanded', 'false');
  });

  test('search filter button has aria-controls', async ({ page }) => {
    const btn = page.locator('[data-project-view="search"]');
    await expect(btn).toHaveAttribute('aria-controls', 'project-search-panel');
  });

  test('result count shows 13 of 13', async ({ page }) => {
    await expect(page.locator('#project-count')).toHaveText('13개 중 13개');
  });
});

test.describe('Sidebar Search & Filter - Panel Open/Close', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
  });

  test('clicking search filter opens panel', async ({ page }) => {
    await openSearchPanel(page);
    const hidden = await page.locator('#project-search-panel').getAttribute('hidden');
    expect(hidden).toBeNull();
  });

  test('search filter button has aria-expanded=true when open', async ({ page }) => {
    await openSearchPanel(page);
    const btn = page.locator('[data-project-view="search"]');
    await expect(btn).toHaveAttribute('aria-expanded', 'true');
  });

  test('search filter menu is active when panel is open', async ({ page }) => {
    await openSearchPanel(page);
    const btn = page.locator('[data-project-view="search"]');
    await expect(btn).toHaveClass(/is-active/);
    const projectsBtn = page.locator('[data-project-view="projects"]');
    await expect(projectsBtn).not.toHaveClass(/is-active/);
  });

  test('close button closes panel and keeps filters', async ({ page }) => {
    await openSearchPanel(page);
    await page.fill('#pd-search-input', 'love');
    await page.waitForTimeout(200);
    await page.click('#project-search-close');
    await page.waitForTimeout(200);
    const hidden = await page.locator('#project-search-panel').getAttribute('hidden');
    expect(hidden).not.toBeNull();
    await expect(page.locator('.pd-card')).toHaveCount(3);
  });

  test('Escape closes panel and returns focus to trigger', async ({ page }) => {
    await openSearchPanel(page);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);
    const hidden = await page.locator('#project-search-panel').getAttribute('hidden');
    expect(hidden).not.toBeNull();
    const btn = page.locator('[data-project-view="search"]');
    const isFocused = await btn.evaluate(el => el === document.activeElement);
    expect(isFocused).toBeTruthy();
  });

  test('clicking project status closes panel and resets filters', async ({ page }) => {
    await openSearchPanel(page);
    await page.fill('#pd-search-input', 'love');
    await page.selectOption('#pd-stage-filter', 'live');
    await page.waitForTimeout(200);
    await page.click('[data-project-view="projects"]');
    await page.waitForTimeout(200);
    const hidden = await page.locator('#project-search-panel').getAttribute('hidden');
    expect(hidden).not.toBeNull();
    await expect(page.locator('.pd-card')).toHaveCount(13);
    await expect(page.locator('#project-count')).toHaveText('13개 중 13개');
  });

  test('close button has accessible name', async ({ page }) => {
    await openSearchPanel(page);
    const closeBtn = page.locator('#project-search-close');
    const ariaLabel = await closeBtn.getAttribute('aria-label');
    expect(ariaLabel).toBeTruthy();
    expect(ariaLabel.length).toBeGreaterThan(0);
  });
});

test.describe('Sidebar Search & Filter - Text Search', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
    await openSearchPanel(page);
  });

  test('search by English name: Portfolio Console', async ({ page }) => {
    await page.fill('#pd-search-input', 'Portfolio Console');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(1);
    await expect(page.locator('.pd-card-name').first()).toHaveText('Portfolio Console');
  });

  test('search by Korean name: 러브버드', async ({ page }) => {
    await page.fill('#pd-search-input', '러브버드');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(1);
    await expect(page.locator('.pd-card-name').first()).toHaveText('LoveBud');
  });

  test('search by business number: 14', async ({ page }) => {
    await page.fill('#pd-search-input', '14');
    await page.waitForTimeout(200);
    const count = await page.locator('.pd-card').count();
    expect(count).toBeGreaterThanOrEqual(1);
    const hasKoreanAI = await page.locator('.pd-card-name:has-text("Korean AI Platform")').count();
    expect(hasKoreanAI).toBe(1);
  });

  test('search by repository label: 400-ai-finder', async ({ page }) => {
    await page.fill('#pd-search-input', '400-ai-finder');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(1);
    await expect(page.locator('.pd-card-name').first()).toHaveText('AI Finder / 광주 북구청');
  });

  test('search by workspace: apps/living-travel', async ({ page }) => {
    await page.fill('#pd-search-input', 'apps/living-travel');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(1);
    await expect(page.locator('.pd-card-name').first()).toHaveText('Living Travel');
  });

  test('search by purpose string: 가계도', async ({ page }) => {
    await page.fill('#pd-search-input', '가계도');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(1);
    await expect(page.locator('.pd-card-name').first()).toHaveText('LoveTree 3.0');
  });

  test('search by currentWork string: #1150', async ({ page }) => {
    await page.fill('#pd-search-input', '#1150');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(1);
    await expect(page.locator('.pd-card-name').first()).toHaveText('AI Finder / 광주 북구청');
  });

  test('search by nextAction string: Provider registry', async ({ page }) => {
    await page.fill('#pd-search-input', 'Provider registry');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(1);
    await expect(page.locator('.pd-card-name').first()).toHaveText('Korean AI Platform');
  });

  test('search is case-insensitive', async ({ page }) => {
    await page.fill('#pd-search-input', 'LOVEBUD');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(1);
    await expect(page.locator('.pd-card-name').first()).toHaveText('LoveBud');
  });

  test('search ignores leading/trailing whitespace', async ({ page }) => {
    await page.fill('#pd-search-input', '  lovebud  ');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(1);
    await expect(page.locator('.pd-card-name').first()).toHaveText('LoveBud');
  });
});

test.describe('Sidebar Search & Filter - Stage Filter', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
    await openSearchPanel(page);
  });

  test('filter by live stage shows 7 cards', async ({ page }) => {
    await page.selectOption('#pd-stage-filter', 'live');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(7);
  });

  test('filter by review stage shows 3 cards', async ({ page }) => {
    await page.selectOption('#pd-stage-filter', 'review');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(3);
  });

  test('filter by planned stage shows 3 cards', async ({ page }) => {
    await page.selectOption('#pd-stage-filter', 'planned');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(3);
  });

  test('paused stage shows empty state (0 results)', async ({ page }) => {
    await page.selectOption('#pd-stage-filter', 'paused');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(0);
    await expect(page.locator('.empty-state')).toBeVisible();
    await expect(page.locator('.empty-state')).toContainText('조건에 맞는 프로젝트가 없습니다');
  });

  test('building stage shows empty state (0 results)', async ({ page }) => {
    await page.selectOption('#pd-stage-filter', 'building');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(0);
    await expect(page.locator('.empty-state')).toBeVisible();
  });

  test('reset to all shows 13 cards', async ({ page }) => {
    await page.selectOption('#pd-stage-filter', 'live');
    await page.waitForTimeout(200);
    await page.selectOption('#pd-stage-filter', 'all');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(13);
  });
});

test.describe('Sidebar Search & Filter - DevelopmentMode Filter', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
    await openSearchPanel(page);
  });

  test('filter by active-development shows 6 cards', async ({ page }) => {
    await page.selectOption('#pd-dev-mode-filter', 'active-development');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(6);
  });

  test('filter by needs-improvement shows 4 cards', async ({ page }) => {
    await page.selectOption('#pd-dev-mode-filter', 'needs-improvement');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(4);
  });

  test('filter by not-started shows 3 cards', async ({ page }) => {
    await page.selectOption('#pd-dev-mode-filter', 'not-started');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(3);
  });

  test('maintenance mode shows empty state', async ({ page }) => {
    await page.selectOption('#pd-dev-mode-filter', 'maintenance');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(0);
    await expect(page.locator('.empty-state')).toBeVisible();
  });

  test('complete mode shows empty state', async ({ page }) => {
    await page.selectOption('#pd-dev-mode-filter', 'complete');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(0);
    await expect(page.locator('.empty-state')).toBeVisible();
  });
});

test.describe('Sidebar Search & Filter - Combination Search', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
    await openSearchPanel(page);
  });

  test('text + stage: love + live shows 2 cards', async ({ page }) => {
    await page.fill('#pd-search-input', 'love');
    await page.selectOption('#pd-stage-filter', 'live');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(2);
    const names = await page.locator('.pd-card-name').allTextContents();
    expect(names).toContain('LoveBud');
    expect(names).toContain('LoveTree 3.0');
  });

  test('stage + developmentMode: live + active-development shows 6 cards', async ({ page }) => {
    await page.selectOption('#pd-stage-filter', 'live');
    await page.selectOption('#pd-dev-mode-filter', 'active-development');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(6);
  });

  test('text + stage + developmentMode: love + live + active-development shows 2 cards', async ({ page }) => {
    await page.fill('#pd-search-input', 'love');
    await page.selectOption('#pd-stage-filter', 'live');
    await page.selectOption('#pd-dev-mode-filter', 'active-development');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(2);
    const names = await page.locator('.pd-card-name').allTextContents();
    expect(names).toContain('LoveBud');
    expect(names).toContain('LoveTree 3.0');
  });
});

test.describe('Sidebar Search & Filter - Progress Sort', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
    await openSearchPanel(page);
  });

  test('progress-desc orders by progress descending', async ({ page }) => {
    await page.selectOption('#pd-sort-filter', 'progress-desc');
    await page.waitForTimeout(200);
    const ids = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('.pd-card')).map(card => card.getAttribute('data-project-id'));
    });
    expect(ids).toEqual([
      'portfolio-console',
      'lovebud',
      'living-learning',
      'personal-video-archive',
      'living-travel',
      'personal-edition',
      'living-fiction',
      'ai-finder-bukgu',
      'lovetree-3',
      'korean-ai-platform',
      'love-matchmaking',
      'ai-finder-namgu',
      'ai-finder-seogu'
    ]);
  });

  test('progress-asc orders by progress ascending', async ({ page }) => {
    await page.selectOption('#pd-sort-filter', 'progress-asc');
    await page.waitForTimeout(200);
    const ids = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('.pd-card')).map(card => card.getAttribute('data-project-id'));
    });
    expect(ids).toEqual([
      'living-fiction',
      'ai-finder-bukgu',
      'personal-edition',
      'living-travel',
      'lovebud',
      'living-learning',
      'personal-video-archive',
      'portfolio-console',
      'lovetree-3',
      'korean-ai-platform',
      'love-matchmaking',
      'ai-finder-namgu',
      'ai-finder-seogu'
    ]);
  });

  test('undefined milestone projects are last in progress-desc', async ({ page }) => {
    await page.selectOption('#pd-sort-filter', 'progress-desc');
    await page.waitForTimeout(200);
    const ids = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('.pd-card')).map(card => card.getAttribute('data-project-id'));
    });
    const undefinedIds = ['lovetree-3', 'korean-ai-platform', 'love-matchmaking', 'ai-finder-namgu', 'ai-finder-seogu'];
    const lastFive = ids.slice(-5);
    expect(lastFive).toEqual(undefinedIds);
  });

  test('undefined milestone projects are last in progress-asc', async ({ page }) => {
    await page.selectOption('#pd-sort-filter', 'progress-asc');
    await page.waitForTimeout(200);
    const ids = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('.pd-card')).map(card => card.getAttribute('data-project-id'));
    });
    const undefinedIds = ['lovetree-3', 'korean-ai-platform', 'love-matchmaking', 'ai-finder-namgu', 'ai-finder-seogu'];
    const lastFive = ids.slice(-5);
    expect(lastFive).toEqual(undefinedIds);
  });

  test('same progress maintains original order in progress-desc', async ({ page }) => {
    await page.selectOption('#pd-sort-filter', 'progress-desc');
    await page.waitForTimeout(200);
    const ids = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('.pd-card')).map(card => card.getAttribute('data-project-id'));
    });
    const lovebudIdx = ids.indexOf('lovebud');
    const livingLearningIdx = ids.indexOf('living-learning');
    const personalVideoIdx = ids.indexOf('personal-video-archive');
    expect(lovebudIdx).toBeLessThan(livingLearningIdx);
    expect(livingLearningIdx).toBeLessThan(personalVideoIdx);
    const livingFictionIdx = ids.indexOf('living-fiction');
    const aiFinderBukguIdx = ids.indexOf('ai-finder-bukgu');
    expect(livingFictionIdx).toBeLessThan(aiFinderBukguIdx);
  });

  test('LoveBud shows 50% progress in card', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="lovebud"]');
    await expect(card.locator('.pd-card-pct').first()).toHaveText('완료 50%');
    const barWidth = await card.locator('.pd-card-bar i').evaluate(el => el.style.width);
    expect(barWidth).toBe('50%');
  });

  test('Portfolio Console shows 80% progress in card', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="portfolio-console"]');
    await expect(card.locator('.pd-card-pct').first()).toHaveText('완료 80%');
    const barWidth = await card.locator('.pd-card-bar i').evaluate(el => el.style.width);
    expect(barWidth).toBe('80%');
  });
});

test.describe('Sidebar Search & Filter - Reset & Result Count', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
    await openSearchPanel(page);
  });

  test('default shows 13 of 13', async ({ page }) => {
    await expect(page.locator('#project-count')).toHaveText('13개 중 13개');
  });

  test('filter shows correct count', async ({ page }) => {
    await page.selectOption('#pd-stage-filter', 'live');
    await page.waitForTimeout(200);
    await expect(page.locator('#project-count')).toHaveText('13개 중 7개');
  });

  test('reset restores 13 of 13', async ({ page }) => {
    await page.fill('#pd-search-input', 'love');
    await page.selectOption('#pd-stage-filter', 'live');
    await page.selectOption('#pd-dev-mode-filter', 'active-development');
    await page.selectOption('#pd-sort-filter', 'progress-desc');
    await page.waitForTimeout(200);
    await page.click('#pd-reset-filter');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(13);
    await expect(page.locator('#project-count')).toHaveText('13개 중 13개');
    await expect(page.locator('#pd-search-input')).toHaveValue('');
    await expect(page.locator('#pd-stage-filter')).toHaveValue('all');
    await expect(page.locator('#pd-dev-mode-filter')).toHaveValue('all');
    await expect(page.locator('#pd-sort-filter')).toHaveValue('default');
  });

  test('zero results show empty state', async ({ page }) => {
    await page.selectOption('#pd-stage-filter', 'paused');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(0);
    await expect(page.locator('.empty-state')).toBeVisible();
    await expect(page.locator('#project-count')).toHaveText('13개 중 0개');
  });
});

test.describe('Sidebar Search & Filter - Regression', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
  });

  test('service links count is 9', async ({ page }) => {
    await expect(page.locator('.pd-card-service-link')).toHaveCount(9);
  });

  test('no service links count is 4', async ({ page }) => {
    const noLinkCards = page.locator('.pd-card[data-has-page-url="false"]');
    await expect(noLinkCards).toHaveCount(4);
  });

  test('Portfolio Console shows 80% progress', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="portfolio-console"]');
    await expect(card.locator('.pd-card-pct').first()).toHaveText('완료 80%');
  });

  test('자세히 보기 button exists on all cards', async ({ page }) => {
    await expect(page.locator('.pd-card-detail-btn')).toHaveCount(13);
  });

  test('Korean AI Platform has Worker service link', async ({ page }) => {
    const link = page.locator('.pd-card[data-project-id="korean-ai-platform"] .pd-card-service-link');
    await expect(link).toHaveCount(1);
    await expect(link).toHaveAttribute('href', 'https://ai-revenue-korean-ai-platform.charliekant.workers.dev/workspace');
  });

  test('Living Fiction has no service link', async ({ page }) => {
    await expect(page.locator('.pd-card[data-project-id="living-fiction"] .pd-card-service-link')).toHaveCount(0);
  });

  test('Quick Launch is not present', async ({ page }) => {
    await expect(page.locator('.quick-launch')).toHaveCount(0);
    await expect(page.locator('.ql-item')).toHaveCount(0);
  });

  test('Korean is default language', async ({ page }) => {
    await expect(page.locator('#topbar-title')).toHaveText('내 비즈니스 관리');
  });

  test('EN switch works', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await expect(page.locator('#topbar-title')).toHaveText('Business Operations');
  });

  test('Business Registry shows 15 rows', async ({ page }) => {
    await expect(page.locator('#business-table-body .business-row')).toHaveCount(15);
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

  test('no horizontal overflow', async ({ page }) => {
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('sidebar has project menu buttons', async ({ page }) => {
    await expect(page.locator('[data-project-view="projects"]')).toHaveCount(1);
    await expect(page.locator('[data-project-view="search"]')).toHaveCount(1);
  });

  test('search panel exists in DOM', async ({ page }) => {
    await expect(page.locator('#project-search-panel')).toHaveCount(1);
  });
});

test.describe('Sidebar Search & Filter - Accessibility Contracts', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
  });

  test('close button returns focus to search trigger', async ({ page }) => {
    await openSearchPanel(page);
    await page.fill('#pd-search-input', 'love');
    await page.waitForTimeout(200);
    await page.click('#project-search-close');
    await page.waitForTimeout(200);
    const btn = page.locator('[data-project-view="search"]');
    const isFocused = await btn.evaluate(el => el === document.activeElement);
    expect(isFocused).toBeTruthy();
  });

  test('Escape returns focus to search trigger', async ({ page }) => {
    await openSearchPanel(page);
    await page.fill('#pd-search-input', 'love');
    await page.waitForTimeout(200);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);
    const btn = page.locator('[data-project-view="search"]');
    const isFocused = await btn.evaluate(el => el === document.activeElement);
    expect(isFocused).toBeTruthy();
  });

  test('Escape maintains filter state', async ({ page }) => {
    await openSearchPanel(page);
    await page.fill('#pd-search-input', 'love');
    await page.selectOption('#pd-stage-filter', 'live');
    await page.waitForTimeout(200);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(2);
    await expect(page.locator('#project-count')).toHaveText('13개 중 2개');
  });

  test('close button maintains filter state', async ({ page }) => {
    await openSearchPanel(page);
    await page.fill('#pd-search-input', 'love');
    await page.selectOption('#pd-stage-filter', 'live');
    await page.waitForTimeout(200);
    await page.click('#project-search-close');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(2);
    await expect(page.locator('#project-count')).toHaveText('13개 중 2개');
  });

  test('closed panel input is not programmatically focusable', async ({ page }) => {
    const isFocused = await page.evaluate(() => {
      const input = document.querySelector('#pd-search-input');
      input.focus();
      return input === document.activeElement;
    });
    expect(isFocused).toBeFalsy();
  });

  test('closed panel input is not keyboard focusable', async ({ page }) => {
    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');
    const activeTag = await page.evaluate(() => document.activeElement.tagName);
    const activeId = await page.evaluate(() => document.activeElement.id);
    expect(activeId).not.toBe('pd-search-input');
  });

  test('opening panel focuses search input', async ({ page }) => {
    await openSearchPanel(page);
    const isFocused = await page.evaluate(() => {
      const input = document.querySelector('#pd-search-input');
      return input === document.activeElement;
    });
    expect(isFocused).toBeTruthy();
  });

  test('aria-expanded is false when panel closed', async ({ page }) => {
    const btn = page.locator('[data-project-view="search"]');
    await expect(btn).toHaveAttribute('aria-expanded', 'false');
  });

  test('aria-expanded is true when panel open', async ({ page }) => {
    await openSearchPanel(page);
    const btn = page.locator('[data-project-view="search"]');
    await expect(btn).toHaveAttribute('aria-expanded', 'true');
  });

  test('aria-expanded syncs back to false after close', async ({ page }) => {
    await openSearchPanel(page);
    await page.click('#project-search-close');
    await page.waitForTimeout(200);
    const btn = page.locator('[data-project-view="search"]');
    await expect(btn).toHaveAttribute('aria-expanded', 'false');
  });

  test('aria-expanded syncs back to false after Escape', async ({ page }) => {
    await openSearchPanel(page);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);
    const btn = page.locator('[data-project-view="search"]');
    await expect(btn).toHaveAttribute('aria-expanded', 'false');
  });

  test('project status is active and search is inactive when closed', async ({ page }) => {
    const projectsBtn = page.locator('[data-project-view="projects"]');
    const searchBtn = page.locator('[data-project-view="search"]');
    await expect(projectsBtn).toHaveClass(/is-active/);
    await expect(projectsBtn).toHaveAttribute('aria-current', 'page');
    await expect(searchBtn).not.toHaveClass(/is-active/);
  });

  test('search is active and project status is inactive when open', async ({ page }) => {
    await openSearchPanel(page);
    const projectsBtn = page.locator('[data-project-view="projects"]');
    const searchBtn = page.locator('[data-project-view="search"]');
    await expect(searchBtn).toHaveClass(/is-active/);
    await expect(projectsBtn).not.toHaveClass(/is-active/);
    await expect(projectsBtn).not.toHaveAttribute('aria-current');
  });

  test('project status button resets filters and shows 13 cards', async ({ page }) => {
    await openSearchPanel(page);
    await page.fill('#pd-search-input', 'love');
    await page.selectOption('#pd-stage-filter', 'live');
    await page.selectOption('#pd-dev-mode-filter', 'active-development');
    await page.selectOption('#pd-sort-filter', 'progress-desc');
    await page.waitForTimeout(200);
    await page.click('[data-project-view="projects"]');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(13);
    await expect(page.locator('#project-count')).toHaveText('13개 중 13개');
    await expect(page.locator('#pd-search-input')).toHaveValue('');
    await expect(page.locator('#pd-stage-filter')).toHaveValue('all');
    await expect(page.locator('#pd-dev-mode-filter')).toHaveValue('all');
    await expect(page.locator('#pd-sort-filter')).toHaveValue('default');
  });

  test('close button has accessible name', async ({ page }) => {
    await openSearchPanel(page);
    const closeBtn = page.locator('#project-search-close');
    const ariaLabel = await closeBtn.getAttribute('aria-label');
    expect(ariaLabel).toBeTruthy();
    expect(ariaLabel.length).toBeGreaterThan(0);
  });
});

test.describe('Sidebar Search & Filter - EN Label Switching', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await openSearchPanel(page);
  });

  test('search label switches to EN', async ({ page }) => {
    await expect(page.locator('#pd-search-label')).toHaveText('SEARCH');
  });

  test('stage label switches to EN', async ({ page }) => {
    await expect(page.locator('#pd-stage-label')).toHaveText('STAGE');
  });

  test('dev mode label switches to EN', async ({ page }) => {
    await expect(page.locator('#pd-dev-mode-label')).toHaveText('DEV MODE');
  });

  test('sort label switches to EN', async ({ page }) => {
    await expect(page.locator('#pd-sort-label')).toHaveText('SORT');
  });

  test('reset button switches to EN', async ({ page }) => {
    await expect(page.locator('#pd-reset-filter')).toHaveText('RESET');
  });

  test('panel title switches to EN', async ({ page }) => {
    await expect(page.locator('#project-search-title')).toHaveText('SEARCH & FILTER');
  });

  test('close button accessible name switches to EN', async ({ page }) => {
    const closeBtn = page.locator('#project-search-close');
    const ariaLabel = await closeBtn.getAttribute('aria-label');
    expect(ariaLabel).toBe('Close search panel');
  });

  test('result count shows EN format', async ({ page }) => {
    await expect(page.locator('#project-count')).toHaveText('13 of 13 projects');
  });

  test('stage options switch to EN', async ({ page }) => {
    await expect(page.locator('#pd-stage-filter option[value="all"]')).toHaveText('ALL');
    await expect(page.locator('#pd-stage-filter option[value="live"]')).toHaveText('LIVE');
    await expect(page.locator('#pd-stage-filter option[value="building"]')).toHaveText('BUILDING');
    await expect(page.locator('#pd-stage-filter option[value="review"]')).toHaveText('REVIEW');
    await expect(page.locator('#pd-stage-filter option[value="planned"]')).toHaveText('PLANNED');
    await expect(page.locator('#pd-stage-filter option[value="paused"]')).toHaveText('PAUSED');
  });

  test('development mode options switch to EN', async ({ page }) => {
    await expect(page.locator('#pd-dev-mode-filter option[value="all"]')).toHaveText('ALL');
    await expect(page.locator('#pd-dev-mode-filter option[value="not-started"]')).toHaveText('NOT STARTED');
    await expect(page.locator('#pd-dev-mode-filter option[value="active-development"]')).toHaveText('ACTIVE DEV');
    await expect(page.locator('#pd-dev-mode-filter option[value="needs-improvement"]')).toHaveText('NEEDS IMPROVEMENT');
    await expect(page.locator('#pd-dev-mode-filter option[value="maintenance"]')).toHaveText('MAINTENANCE');
    await expect(page.locator('#pd-dev-mode-filter option[value="complete"]')).toHaveText('COMPLETE');
    await expect(page.locator('#pd-dev-mode-filter option[value="paused"]')).toHaveText('PAUSED');
  });

  test('sort options switch to EN', async ({ page }) => {
    await expect(page.locator('#pd-sort-filter option[value="default"]')).toHaveText('DEFAULT');
    await expect(page.locator('#pd-sort-filter option[value="progress-desc"]')).toHaveText('PROGRESS DESC');
    await expect(page.locator('#pd-sort-filter option[value="progress-asc"]')).toHaveText('PROGRESS ASC');
  });

  test('empty state switches to EN', async ({ page }) => {
    await page.selectOption('#pd-stage-filter', 'paused');
    await page.waitForTimeout(200);
    await expect(page.locator('.empty-state')).toContainText('No projects match the criteria.');
  });

  test('search filter nav button switches to EN', async ({ page }) => {
    await expect(page.locator('#nav-search-filter')).toHaveText('SEARCH & FILTER');
  });

  test('project status nav button switches to EN', async ({ page }) => {
    await expect(page.locator('#nav-projects')).toHaveText('PROJECT STATUS');
  });

  test('search placeholder switches to EN', async ({ page }) => {
    await expect(page.locator('#pd-search-input')).toHaveAttribute('placeholder', 'Search by name, repo, folder, purpose, current work, next action');
  });

  test('Korean labels restored after switching back', async ({ page }) => {
    await page.click('#lang-ko');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-search-label')).toHaveText('검색');
    await expect(page.locator('#pd-stage-label')).toHaveText('단계');
    await expect(page.locator('#pd-dev-mode-label')).toHaveText('개발 모드');
    await expect(page.locator('#pd-sort-label')).toHaveText('정렬');
    await expect(page.locator('#pd-reset-filter')).toHaveText('초기화');
    await expect(page.locator('#project-search-title')).toHaveText('검색·필터');
  });
});
