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

    await expect(page.locator('#detail-number')).toHaveText('비즈니스 14');
    await expect(page.locator('#detail-title')).toHaveText('Korean AI Platform');
    await expect(page.locator('#detail-status')).toHaveText('검토 중');
    await expect(page.locator('#detail-progress-value')).toHaveText('50%');
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

    await expect(page.locator('#detail-number')).toHaveText('비즈니스 01');
  });

  test('disabled links have no href, tabindex=-1, and are keyboard-inert', async ({ page }) => {
    await page.click('#business-table-body tr[data-business-number="5"]');
    await page.waitForTimeout(200);

    const surfaceLink = page.locator('#surface-link');
    await expect(surfaceLink).toHaveClass(/is-disabled/);
    await expect(surfaceLink).toHaveAttribute('aria-disabled', 'true');
    await expect(surfaceLink).toHaveAttribute('tabindex', '-1');
    await expect(surfaceLink).not.toHaveAttribute('href');
    await expect(surfaceLink).not.toHaveAttribute('target');
    await expect(surfaceLink).not.toHaveAttribute('rel');

    const computedStyle = await surfaceLink.evaluate(el => window.getComputedStyle(el).pointerEvents);
    expect(computedStyle).toBe('none');
  });

  test('disabled link Enter key does not change URL or selection', async ({ page }) => {
    await page.click('#business-table-body tr[data-business-number="5"]');
    await page.waitForTimeout(200);

    const surfaceLink = page.locator('#surface-link');
    await surfaceLink.focus();
    await page.keyboard.press('Enter');
    await page.waitForTimeout(200);

    expect(page.url()).not.toContain('#');
    await expect(page.locator('#detail-number')).toHaveText('비즈니스 05');
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
      await expect(link).toHaveAttribute('tabindex', '0');
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

  test('mobile layout shows all essential columns', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(200);

    const rows = page.locator('#business-table-body .business-row');
    await expect(rows).toHaveCount(15);

    const firstRow = rows.first();
    await expect(firstRow.locator('.business-number')).toBeVisible();
    await expect(firstRow.locator('.business-title strong')).toBeVisible();
    await expect(firstRow.locator('.status-badge')).toBeVisible();
    await expect(firstRow.locator('.progress-cell')).toBeVisible();
    await expect(firstRow.locator('.action-cell')).toBeVisible();
  });

  test('Business 16 registry expansion updates all derived surfaces', async ({ page }) => {
    await page.route('**/app.js', async route => {
      const response = await route.fetch();
      const body = await response.text();
      const insert = `window.ARL_BUSINESSES.push({
  number: 16,
  slug: "test-business-16",
  title: "Test Business 16",
  koreanTitle: "테스트 사업 16",
  state: "review",
  lifecycle: "concept",
  progress: 50,
  workspace: "apps/test-business-16/",
  surfaceType: "Static demo",
  surfaceUrl: null,
  deployment: "Test deployment",
  githubLabel: "Issue #999",
  githubUrl: "https://github.com/skerishKang/ai-revenue-lab/issues/999",
  issueUrl: "https://github.com/skerishKang/ai-revenue-lab/issues/999",
  nextAction: "Add canonical data",
  lastVerified: "2026-07-24",
  priority: 50
});
`;
      await route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        body: insert + body,
      });
    });

    await page.goto('/', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);

    const rows = page.locator('#business-table-body .business-row');
    await expect(rows).toHaveCount(16);

    await expect(page.locator('#sidebar-range')).toHaveText('01–16');

    await page.fill('#search-input', '16');
    await page.waitForTimeout(200);
    await expect(rows).toHaveCount(1);
    await expect(rows.first().locator('.business-number')).toHaveText('16');
    await expect(rows.first().locator('.business-title strong')).toHaveText('Test Business 16');

    await page.fill('#search-input', '');
    await page.waitForTimeout(200);

    await page.click('#business-table-body tr[data-business-number="16"]');
    await page.waitForTimeout(200);

    await expect(page.locator('#detail-number')).toHaveText('비즈니스 16');
    await expect(page.locator('#detail-title')).toHaveText('Test Business 16');
    await expect(page.locator('#detail-progress-value')).toHaveText('50%');

    const trackedText = await page.locator('#metric-tracked').textContent();
    expect(parseInt(trackedText)).toBe(9);

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('Korean and English titles do not overflow their cells', async ({ page }) => {
    const overflowCheck = await page.evaluate(() => {
      const cells = document.querySelectorAll('.business-title');
      const results = [];
      for (const cell of cells) {
        const rect = cell.getBoundingClientRect();
        const parentRect = cell.parentElement.getBoundingClientRect();
        results.push({
          scrollWidth: cell.scrollWidth,
          clientWidth: cell.clientWidth,
          overflows: cell.scrollWidth > cell.clientWidth,
          rectRight: Math.round(rect.right),
          parentRight: Math.round(parentRect.right)
        });
      }
      return results;
    });

    for (const result of overflowCheck) {
      expect(result.overflows).toBeFalsy();
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

test.describe('Quick Launch Removal Browser Tests', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(500);
  });

  test('Quick Launch section is not rendered', async ({ page }) => {
    await expect(page.locator('.quick-launch')).toHaveCount(0);
    await expect(page.locator('.ql-heading')).toHaveCount(0);
    await expect(page.locator('.ql-list')).toHaveCount(0);
    await expect(page.locator('.ql-item')).toHaveCount(0);
  });

  test('quick-launch.js script is not loaded', async ({ page }) => {
    const scripts = await page.evaluate(() =>
      Array.from(document.querySelectorAll('script')).map(s => s.src)
    );
    expect(scripts).not.toContain(expect.stringContaining('quick-launch'));
  });

  test('no Quick Launch related elements in DOM', async ({ page }) => {
    await expect(page.locator('#quick-launch-list')).toHaveCount(0);
    await expect(page.locator('#quick-launch-heading')).toHaveCount(0);
  });
});

test.describe('Project Directory Browser Tests', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
  });

  test('renders 13 project cards', async ({ page }) => {
    await expect(page.locator('.pd-card')).toHaveCount(13);
  });

  test('all project cards have name, stage badge, and repository', async ({ page }) => {
    const cards = page.locator('.pd-card');
    const count = await cards.count();
    for (let i = 0; i < count; i++) {
      const card = cards.nth(i);
      await expect(card.locator('.pd-card-name')).not.toBeEmpty();
      await expect(card.locator('.status-badge')).not.toBeEmpty();
      await expect(card.locator('.pd-card-meta')).not.toBeEmpty();
    }
  });

  test('project search filters by English name', async ({ page }) => {
    await page.fill('#pd-search-input', 'lovetree');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(1);
    await expect(page.locator('.pd-card-name').first()).toHaveText('LoveTree 3.0');
  });

  test('project search filters by Korean name', async ({ page }) => {
    await page.fill('#pd-search-input', '러브버드');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(1);
    await expect(page.locator('.pd-card-name').first()).toHaveText('LoveBud');
  });

  test('project search filters by repository', async ({ page }) => {
    await page.fill('#pd-search-input', '400-ai-finder');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(1);
    await expect(page.locator('.pd-card-name').first()).toHaveText('AI Finder / 광주 북구청');
  });

  test('project search filters by workspace', async ({ page }) => {
    await page.fill('#pd-search-input', 'apps/living-travel');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(1);
    await expect(page.locator('.pd-card-name').first()).toHaveText('Living Travel');
  });

  test('project search filters by purpose', async ({ page }) => {
    await page.fill('#pd-search-input', '가계도');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(1);
    await expect(page.locator('.pd-card-name').first()).toHaveText('LoveTree 3.0');
  });

  test('project search filters by business number', async ({ page }) => {
    await page.fill('#pd-search-input', '14');
    await page.waitForTimeout(200);
    const cards = page.locator('.pd-card');
    const count = await cards.count();
    expect(count).toBeGreaterThanOrEqual(1);
    const hasKoreanAI = await page.locator('.pd-card-name:has-text("Korean AI Platform")').count();
    expect(hasKoreanAI).toBe(1);
  });

  test('stage filter limits visible projects', async ({ page }) => {
    await page.selectOption('#pd-stage-filter', 'live');
    await page.waitForTimeout(200);
    const liveCount = await page.locator('.pd-card').count();
    expect(liveCount).toBeGreaterThan(0);

    await page.selectOption('#pd-stage-filter', 'planned');
    await page.waitForTimeout(200);
    const plannedCount = await page.locator('.pd-card').count();
    expect(plannedCount).toBeGreaterThan(0);

    await page.selectOption('#pd-stage-filter', 'all');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(13);
  });

  test('clicking a project card selects it and updates detail panel', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovetree-3"] .pd-card-detail-btn');
    await page.waitForTimeout(200);

    await expect(page.locator('#pd-detail-title')).toHaveText('LoveTree 3.0');
    await expect(page.locator('#pd-detail-badge')).toHaveText('운영 중');
    await expect(page.locator('#pd-detail-repo')).toHaveText('skerishKang/lovetree3.0');
    await expect(page.locator('#pd-detail-workspace')).toHaveText('/');
  });

  test('project detail shows purpose and progress note', async ({ page }) => {
    await page.click('.pd-card[data-project-id="korean-ai-platform"]');
    await page.waitForTimeout(200);

    await expect(page.locator('#pd-detail-purpose')).toContainText('한국어');
    await expect(page.locator('#pd-detail-progress')).toContainText('PR #142');
    await expect(page.locator('#pd-detail-progress')).toContainText('Provider registry');
  });

  test('project detail shows business number when assigned', async ({ page }) => {
    await page.click('.pd-card[data-project-id="personal-edition"] .pd-card-detail-btn');
    await page.waitForTimeout(200);

    await expect(page.locator('#pd-detail-biz')).toHaveText('비즈니스 01');
  });

  test('active page links have target=_blank and rel=noopener noreferrer', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn');
    await page.waitForTimeout(200);

    const pageLink = page.locator('#pd-page-link');
    await expect(pageLink).toHaveAttribute('target', '_blank');
    await expect(pageLink).toHaveAttribute('rel', 'noopener noreferrer');
    await expect(pageLink).toHaveAttribute('href', /^https:\/\//);
  });

  test('inactive page links are disabled', async ({ page }) => {
    await page.click('.pd-card[data-project-id="korean-ai-platform"]');
    await page.waitForTimeout(200);

    const pageLink = page.locator('#pd-page-link');
    await expect(pageLink).toHaveClass(/is-disabled/);
    await expect(pageLink).toHaveAttribute('aria-disabled', 'true');
    await expect(pageLink).toHaveAttribute('tabindex', '-1');
    await expect(pageLink).not.toHaveAttribute('href');
  });

  test('active repository links have security attributes', async ({ page }) => {
    await page.click('.pd-card[data-project-id="ai-finder-bukgu"] .pd-card-detail-btn');
    await page.waitForTimeout(200);

    const repoLink = page.locator('#pd-repo-link');
    await expect(repoLink).toHaveAttribute('target', '_blank');
    await expect(repoLink).toHaveAttribute('rel', 'noopener noreferrer');
  });

  test('inactive repository links are disabled', async ({ page }) => {
    await page.click('.pd-card[data-project-id="ai-finder-namgu"]');
    await page.waitForTimeout(200);

    const repoLink = page.locator('#pd-repo-link');
    await expect(repoLink).toHaveClass(/is-disabled/);
    await expect(repoLink).not.toHaveAttribute('href');
  });

  test('copy workspace button copies exact relative path', async ({ page }) => {
    await page.click('.pd-card[data-project-id="living-travel"] .pd-card-detail-btn');
    await page.waitForTimeout(200);

    const copyButton = page.locator('#pd-copy-workspace');
    await expect(copyButton).toBeVisible();
    await expect(copyButton).toHaveText('폴더 경로 복사');

    await page.evaluate(() => {
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: async (text) => { window.__copiedText = text; } },
        writable: true,
        configurable: true
      });
    });

    await copyButton.click();
    await page.waitForTimeout(100);

    const copiedValue = await page.evaluate(() => window.__copiedText);
    expect(copiedValue).toBe('apps/living-travel/');

    const note = page.locator('#pd-copy-note');
    await expect(note).toContainText('apps/living-travel/');
    await expect(note).not.toContainText('G:\\');
    await expect(note).not.toContainText('C:\\');
  });

  test('copy workspace handles clipboard API missing', async ({ page }) => {
    await page.click('.pd-card[data-project-id="living-travel"] .pd-card-detail-btn');
    await page.waitForTimeout(200);

    await page.evaluate(() => {
      Object.defineProperty(navigator, 'clipboard', {
        value: undefined,
        writable: true,
        configurable: true
      });
    });

    const copyButton = page.locator('#pd-copy-workspace');
    await copyButton.click();
    await page.waitForTimeout(100);

    const note = page.locator('#pd-copy-note');
    await expect(note).toContainText('복사하지 못했습니다');
  });

  test('copy workspace handles clipboard rejection', async ({ page }) => {
    await page.click('.pd-card[data-project-id="living-travel"] .pd-card-detail-btn');
    await page.waitForTimeout(200);

    await page.evaluate(() => {
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: async () => { throw new Error('Permission denied'); } },
        writable: true,
        configurable: true
      });
    });

    const copyButton = page.locator('#pd-copy-workspace');
    await copyButton.click();
    await page.waitForTimeout(100);

    const note = page.locator('#pd-copy-note');
    await expect(note).toContainText('복사하지 못했습니다');
  });

  test('copy workspace root path handled correctly', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovetree-3"] .pd-card-detail-btn');
    await page.waitForTimeout(200);

    await page.evaluate(() => {
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: async (text) => { window.__copiedText = text; } },
        writable: true,
        configurable: true
      });
    });

    const copyButton = page.locator('#pd-copy-workspace');
    await copyButton.click();
    await page.waitForTimeout(100);

    const copiedValue = await page.evaluate(() => window.__copiedText);
    expect(copiedValue).toBe('/');
  });

  test('copy workspace disabled for unconfirmed workspace', async ({ page }) => {
    await page.click('.pd-card[data-project-id="ai-finder-namgu"]');
    await page.waitForTimeout(200);

    const copyButton = page.locator('#pd-copy-workspace');
    await expect(copyButton).toBeDisabled();
  });

  test('Quick Launch is not present on the page', async ({ page }) => {
    await expect(page.locator('.quick-launch')).toHaveCount(0);
    await expect(page.locator('.ql-item')).toHaveCount(0);
  });

  test('project cards have a 자세히 보기 button', async ({ page }) => {
    const cards = page.locator('.pd-card');
    const count = await cards.count();
    for (let i = 0; i < count; i++) {
      await expect(cards.nth(i).locator('.pd-card-detail-btn')).toBeVisible();
    }
  });

  test('pageUrl cards have real anchor links with security attributes', async ({ page }) => {
    const links = page.locator('.pd-card-service-link');
    const count = await links.count();
    expect(count).toBe(8);

    for (let i = 0; i < count; i++) {
      const link = links.nth(i);
      await expect(link).toHaveAttribute('href', /^https:\/\//);
      await expect(link).toHaveAttribute('target', '_blank');
      await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    }
  });

  test('LoveBud service link has correct href', async ({ page }) => {
    const link = page.locator('.pd-card[data-project-id="lovebud"] .pd-card-service-link');
    await expect(link).toHaveAttribute('href', 'https://lovebud.pages.dev/');
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  test('LoveTree 3.0 service link has correct href', async ({ page }) => {
    const link = page.locator('.pd-card[data-project-id="lovetree-3"] .pd-card-service-link');
    await expect(link).toHaveAttribute('href', 'https://lovetree3.pages.dev/');
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  test('AI Finder / 광주 북구청 service link has correct href', async ({ page }) => {
    const link = page.locator('.pd-card[data-project-id="ai-finder-bukgu"] .pd-card-service-link');
    await expect(link).toHaveAttribute('href', 'https://cgbukku.pages.dev/');
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  test('Korean AI Platform has no service link', async ({ page }) => {
    await expect(page.locator('.pd-card[data-project-id="korean-ai-platform"] .pd-card-service-link')).toHaveCount(0);
    await expect(page.locator('.pd-card[data-project-id="korean-ai-platform"] .pd-card-main')).toHaveCount(1);
  });

  test('Living Fiction has no service link (404 URL removed)', async ({ page }) => {
    await expect(page.locator('.pd-card[data-project-id="living-fiction"] .pd-card-service-link')).toHaveCount(0);
    await expect(page.locator('.pd-card[data-project-id="living-fiction"] .pd-card-main')).toHaveCount(1);
  });

  test('no role=button or role=link on project cards', async ({ page }) => {
    const cards = page.locator('.pd-card');
    const count = await cards.count();
    for (let i = 0; i < count; i++) {
      const card = cards.nth(i);
      await expect(card).not.toHaveAttribute('role');
    }
  });

  test('no button nested inside anchor link', async ({ page }) => {
    const nested = page.locator('.pd-card a button');
    await expect(nested).toHaveCount(0);
  });

  test('no window.open usage in app.js', async ({ page }) => {
    const hasWindowOpen = await page.evaluate(() => typeof window.open === 'function' && window.open.toString().includes('[native code]'));
    expect(hasWindowOpen).toBeTruthy();
  });

  test('Korean AI Platform card does not navigate externally', async ({ page }) => {
    const [popup] = await Promise.all([
      page.waitForEvent('popup', { timeout: 1000 }).catch(() => null),
      page.click('.pd-card[data-project-id="korean-ai-platform"]'),
    ]);
    expect(popup).toBeNull();

    await expect(page.locator('#pd-detail-title')).toHaveText('Korean AI Platform');
  });

  test('자세히 보기 button opens detail panel', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn');
    await page.waitForTimeout(200);

    await expect(page.locator('#pd-detail-title')).toHaveText('LoveBud');
    await expect(page.locator('#pd-detail-badge')).toHaveText('운영 중');
  });

  test('자세히 보기 button does not open new tab', async ({ page }) => {
    const [popup] = await Promise.all([
      page.waitForEvent('popup', { timeout: 1000 }).catch(() => null),
      page.click('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn'),
    ]);
    expect(popup).toBeNull();
  });

  test('Enter key on service link opens new tab', async ({ page }) => {
    const link = page.locator('.pd-card[data-project-id="lovebud"] .pd-card-service-link');
    await link.focus();

    const [popup] = await Promise.all([
      page.waitForEvent('popup'),
      page.keyboard.press('Enter'),
    ]);
    expect(popup).toBeTruthy();
    expect(popup.url()).toBe('https://lovebud.pages.dev/');
  });

  test('Enter key on 자세히 보기 button opens detail panel', async ({ page }) => {
    const button = page.locator('.pd-card[data-project-id="korean-ai-platform"] .pd-card-detail-btn');
    await button.focus();
    await page.keyboard.press('Enter');
    await page.waitForTimeout(200);

    await expect(page.locator('#pd-detail-title')).toHaveText('Korean AI Platform');
  });

  test('undeployed projects show 미배포 indicator', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="korean-ai-platform"]');
    await expect(card.locator('.pd-card-undeployed')).toBeVisible();
    await expect(card.locator('.pd-card-undeployed')).toContainText('미배포');
  });

  test('deployed projects do not show 미배포 indicator', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="lovebud"]');
    await expect(card.locator('.pd-card-undeployed')).toHaveCount(0);
  });

  test('Living Fiction shows 미배포 indicator', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="living-fiction"]');
    await expect(card.locator('.pd-card-undeployed')).toBeVisible();
    await expect(card.locator('.pd-card-undeployed')).toContainText('미배포');
  });

  test('existing business registry still works', async ({ page }) => {
    await expect(page.locator('#business-table-body .business-row')).toHaveCount(15);
    await page.fill('#search-input', 'fiction');
    await page.waitForTimeout(200);
    await expect(page.locator('#business-table-body .business-row')).toHaveCount(1);
  });

  test('no horizontal overflow on desktop with project directory', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('no horizontal overflow on tablet with project directory', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('no horizontal overflow on mobile with project directory', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('no console errors with project directory', async ({ page }) => {
    const errors = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    page.on('pageerror', err => errors.push(err.message));

    await page.reload({ waitUntil: 'networkidle' });
    expect(errors).toHaveLength(0);
  });

  test('no failed local asset requests with project directory', async ({ page }) => {
    const failed = [];
    page.on('requestfailed', req => {
      if (!req.url().startsWith('data:') && !req.url().startsWith('ws:')) {
        failed.push(req.url());
      }
    });

    await page.reload({ waitUntil: 'networkidle' });
    expect(failed).toHaveLength(0);
  });
});

test.describe('Language Toggle Browser Tests', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(1000);
  });

  test('initial load is Korean', async ({ page }) => {
    await expect(page.locator('#topbar-title')).toHaveText('내 비즈니스 관리');
    await expect(page.locator('#project-directory-heading')).toHaveText('프로젝트 모아보기');
    await expect(page.locator('#registry-heading')).toHaveText('비즈니스 목록');
    await expect(page.locator('#activity-heading')).toHaveText('우선 작업');
  });

  test('Project Directory heading is Korean', async ({ page }) => {
    await expect(page.locator('#project-directory-heading')).toHaveText('프로젝트 모아보기');
    await expect(page.locator('#all-projects-label')).toHaveText('전체 프로젝트');
  });

  test('Project Directory buttons show Korean labels', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn');
    await page.waitForTimeout(200);

    await expect(page.locator('#pd-page-link')).toHaveText('페이지 열기');
    await expect(page.locator('#pd-repo-link')).toHaveText('저장소 열기');
    await expect(page.locator('#pd-copy-workspace')).toHaveText('폴더 경로 복사');
  });

  test('stage badges show Korean labels', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovetree-3"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-badge')).toHaveText('운영 중');

    await page.click('.pd-card[data-project-id="korean-ai-platform"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-badge')).toHaveText('검토 중');

    await page.click('.pd-card[data-project-id="ai-finder-namgu"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-badge')).toHaveText('계획');
  });

  test('business state badges show Korean labels', async ({ page }) => {
    await page.click('#business-table-body tr[data-business-number="2"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#detail-status')).toHaveText('운영 중');

    await page.click('#business-table-body tr[data-business-number="14"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#detail-status')).toHaveText('검토 중');
  });

  test('EN click switches to English', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(200);

    await expect(page.locator('#topbar-title')).toHaveText('Business Operations');
    await expect(page.locator('#project-directory-heading')).toHaveText('Project Directory');
    await expect(page.locator('#registry-heading')).toHaveText('Business Registry');
    await expect(page.locator('#activity-heading')).toHaveText('Priority Actions');
    await expect(page.locator('#pd-page-link')).toHaveText('OPEN PAGE');
    await expect(page.locator('#pd-repo-link')).toHaveText('OPEN REPOSITORY');
    await expect(page.locator('#pd-copy-workspace')).toHaveText('COPY WORKSPACE');
  });

  test('Korean click restores Korean', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await expect(page.locator('#topbar-title')).toHaveText('Business Operations');

    await page.click('#lang-ko');
    await page.waitForTimeout(200);
    await expect(page.locator('#topbar-title')).toHaveText('내 비즈니스 관리');
    await expect(page.locator('#project-directory-heading')).toHaveText('프로젝트 모아보기');
  });

  test('refresh resets to Korean', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await expect(page.locator('#topbar-title')).toHaveText('Business Operations');

    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    await expect(page.locator('#topbar-title')).toHaveText('내 비즈니스 관리');
  });

  test('technical identifiers unchanged after language switch', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovetree-3"] .pd-card-detail-btn');
    await page.waitForTimeout(200);

    const repoBefore = await page.locator('#pd-detail-repo').textContent();
    const workspaceBefore = await page.locator('#pd-detail-workspace').textContent();

    await page.click('#lang-en');
    await page.waitForTimeout(200);

    await expect(page.locator('#pd-detail-repo')).toHaveText(repoBefore);
    await expect(page.locator('#pd-detail-workspace')).toHaveText(workspaceBefore);
    await expect(page.locator('#pd-detail-title')).toHaveText('LoveTree 3.0');
  });

  test('project names unchanged after language switch', async ({ page }) => {
    const projectName = await page.locator('.pd-card-name').first().textContent();

    await page.click('#lang-en');
    await page.waitForTimeout(200);

    await expect(page.locator('.pd-card-name').first()).toHaveText(projectName);
  });

  test('search works after language switch', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(200);

    await page.fill('#pd-search-input', 'lovetree');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(1);

    await page.click('#lang-ko');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(1);
  });

  test('filter works after language switch', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(200);

    await page.selectOption('#pd-stage-filter', 'live');
    await page.waitForTimeout(200);
    const liveCount = await page.locator('.pd-card').count();
    expect(liveCount).toBeGreaterThan(0);

    await page.click('#lang-ko');
    await page.waitForTimeout(200);
    await expect(page.locator('.pd-card')).toHaveCount(liveCount);
  });

  test('selection maintained after language switch', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovetree-3"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-title')).toHaveText('LoveTree 3.0');

    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-title')).toHaveText('LoveTree 3.0');

    await page.click('#lang-ko');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-title')).toHaveText('LoveTree 3.0');
  });

  test('language toggle buttons show active state', async ({ page }) => {
    await expect(page.locator('#lang-ko')).toHaveClass(/is-active/);
    await expect(page.locator('#lang-en')).not.toHaveClass(/is-active/);

    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await expect(page.locator('#lang-en')).toHaveClass(/is-active/);
    await expect(page.locator('#lang-ko')).not.toHaveClass(/is-active/);
  });

  test('metric labels switch language', async ({ page }) => {
    await expect(page.locator('#metric-tracked-label')).toHaveText('추적 중');

    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await expect(page.locator('#metric-tracked-label')).toHaveText('TRACKED');
  });

  test('table headers switch language', async ({ page }) => {
    await expect(page.locator('#th-business')).toHaveText('비즈니스');

    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await expect(page.locator('#th-business')).toHaveText('BUSINESS');
  });

  test('no console errors after language switch', async ({ page }) => {
    const errors = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    page.on('pageerror', err => errors.push(err.message));

    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await page.click('#lang-ko');
    await page.waitForTimeout(200);

    expect(errors).toHaveLength(0);
  });

  test('no horizontal overflow after language switch', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(200);

    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBeFalsy();
  });

  test('initial html lang is ko', async ({ page }) => {
    const lang = await page.evaluate(() => document.documentElement.lang);
    expect(lang).toBe('ko');
  });

  test('EN click sets html lang to en', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    const lang = await page.evaluate(() => document.documentElement.lang);
    expect(lang).toBe('en');
  });

  test('Korean click restores html lang to ko', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await page.click('#lang-ko');
    await page.waitForTimeout(200);
    const lang = await page.evaluate(() => document.documentElement.lang);
    expect(lang).toBe('ko');
  });

  test('refresh resets html lang to ko', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    const lang = await page.evaluate(() => document.documentElement.lang);
    expect(lang).toBe('ko');
  });

  test('static HTML defaults are Korean before JS', async ({ page }) => {
    await page.goto('/', { waitUntil: 'commit' });
    const title = await page.locator('#topbar-title').textContent();
    expect(title).toContain('내 비즈니스 관리');
  });

  test('Korean AI Platform shows PR #142 merged and #138 closed', async ({ page }) => {
    await page.click('.pd-card[data-project-id="korean-ai-platform"]');
    await page.waitForTimeout(200);

    const progress = await page.locator('#pd-detail-progress').textContent();
    expect(progress).toContain('PR #142');
    expect(progress).toContain('Provider registry');

    const nextAction = await page.locator('#pd-detail-next').textContent();
    expect(nextAction).toContain('Provider registry');
  });

  test('Korean AI Platform does not show outdated PR #79 or PR #133', async ({ page }) => {
    await page.click('.pd-card[data-project-id="korean-ai-platform"]');
    await page.waitForTimeout(200);

    const progress = await page.locator('#pd-detail-progress').textContent();
    expect(progress).not.toContain('PR #79');
    expect(progress).not.toContain('PR #133');

    const current = await page.locator('#pd-detail-current').textContent();
    expect(current).not.toContain('PR #79');

    const nextAction = await page.locator('#pd-detail-next').textContent();
    expect(nextAction).not.toContain('PR #79');
  });

  test('business row progress label shows Korean 데모 initially', async ({ page }) => {
    const label = page.locator('#business-table-body .business-row').first().locator('.progress-label span').first();
    await expect(label).toHaveText('데모');
  });

  test('business row progress label shows DEMO after EN click', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    const label = page.locator('#business-table-body .business-row').first().locator('.progress-label span').first();
    await expect(label).toHaveText('DEMO');
  });

  test('business row progress label restores 데모 after Korean click', async ({ page }) => {
    await page.click('#lang-en');
    await page.waitForTimeout(200);
    await page.click('#lang-ko');
    await page.waitForTimeout(200);
    const label = page.locator('#business-table-body .business-row').first().locator('.progress-label span').first();
    await expect(label).toHaveText('데모');
  });
});
