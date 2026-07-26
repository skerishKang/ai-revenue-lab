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

  test('renders 13 project cards', async ({ page }) => {
    await expect(page.locator('.pd-card')).toHaveCount(13);
  });

  test('all cards have stage badge', async ({ page }) => {
    const cards = page.locator('.pd-card');
    const count = await cards.count();
    for (let i = 0; i < count; i++) {
      await expect(cards.nth(i).locator('.status-badge')).not.toBeEmpty();
    }
  });

  test('all cards have developmentMode badge', async ({ page }) => {
    const cards = page.locator('.pd-card');
    const count = await cards.count();
    for (let i = 0; i < count; i++) {
      await expect(cards.nth(i).locator('.pd-mode-badge')).not.toBeEmpty();
    }
  });

  test('defined milestone cards show currentMilestone', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="portfolio-console"]');
    await expect(card.locator('.pd-card-milestone-name')).toContainText('#137');
  });

  test('defined milestone cards show progress percent', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="portfolio-console"]');
    await expect(card.locator('.pd-card-pct').first()).toContainText('완료');
    await expect(card.locator('.pd-card-pct').nth(1)).toContainText('남음');
  });

  test('defined milestone cards show progress bar', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="portfolio-console"]');
    await expect(card.locator('.pd-card-bar')).toBeVisible();
    await expect(card.locator('.pd-card-bar i')).toBeVisible();
  });

  test('undefined milestone cards show 진척도 미정', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="lovetree-3"]');
    await expect(card.locator('.pd-card-milestone-undefined')).toContainText('진척도 미정');
  });

  test('undefined milestone cards show 목표 정의 필요', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="lovetree-3"]');
    await expect(card.locator('.pd-card-milestone-undefined')).toContainText('목표 정의 필요');
  });

  test('undefined milestone cards have no progress bar', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="lovetree-3"]');
    await expect(card.locator('.pd-card-bar')).toHaveCount(0);
  });

  test('undefined milestone cards have no percent numbers', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="lovetree-3"]');
    await expect(card.locator('.pd-card-pct')).toHaveCount(0);
  });

  test('detail panel shows developmentMode', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-mode')).not.toBeEmpty();
  });

  test('detail panel shows currentMilestone', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-milestone')).toContainText('#3425');
  });

  test('detail panel shows progressBasis in Korean', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-basis')).toHaveText('완료 작업 수 / 전체 마일스톤 작업 수');
  });

  test('detail panel shows progress percent for defined milestone', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    const progress = await page.locator('#pd-detail-progress').textContent();
    expect(progress).toContain('완료');
    expect(progress).toContain('남음');
  });

  test('detail panel shows done tasks list', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    const doneTasks = page.locator('#pd-detail-done-tasks li');
    const count = await doneTasks.count();
    expect(count).toBeGreaterThan(0);
  });

  test('detail panel shows remaining tasks list', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    const remainingTasks = page.locator('#pd-detail-remaining-tasks li');
    const count = await remainingTasks.count();
    expect(count).toBeGreaterThan(0);
  });

  test('detail panel shows blockers', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-blockers')).toContainText('#3425');
  });

  test('detail panel undefined milestone shows 진척도 미정', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovetree-3"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-progress')).toContainText('진척도 미정');
  });

  test('Korean AI Platform shows PR #142 in progressNote area', async ({ page }) => {
    await page.click('.pd-card[data-project-id="korean-ai-platform"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-milestone')).toContainText('진척도 미정');
  });

  test('Korean AI Platform does not show outdated PR #79', async ({ page }) => {
    await page.click('.pd-card[data-project-id="korean-ai-platform"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    const next = await page.locator('#pd-detail-next').textContent();
    expect(next).not.toContain('PR #79');
  });

  test('LoveTree 3.0 shows undefined milestone in detail', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovetree-3"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-badge')).toHaveText('운영 중');
    await expect(page.locator('#pd-detail-milestone')).toContainText('진척도 미정');
  });

  test('LoveMatchmaking shows planned stage', async ({ page }) => {
    await page.click('.pd-card[data-project-id="love-matchmaking"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-badge')).toHaveText('계획');
  });

  test('Living Fiction shows review stage not live', async ({ page }) => {
    await page.click('.pd-card[data-project-id="living-fiction"]');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-badge')).toHaveText('검토 중');
  });

  test('Personal Video Archive shows review stage', async ({ page }) => {
    await page.click('.pd-card[data-project-id="personal-video-archive"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-badge')).toHaveText('검토 중');
  });

  test('Personal Edition shows CTO review pending', async ({ page }) => {
    await page.click('.pd-card[data-project-id="personal-edition"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    const next = await page.locator('#pd-detail-next').textContent();
    expect(next).toContain('PR #111');
  });

  test('Korean AI Platform has service link with Worker URL', async ({ page }) => {
    const link = page.locator('.pd-card[data-project-id="korean-ai-platform"] .pd-card-service-link');
    await expect(link).toHaveCount(1);
    await expect(link).toHaveAttribute('href', 'https://ai-revenue-korean-ai-platform.charliekant.workers.dev/workspace');
  });

  test('Living Fiction has no service link (404)', async ({ page }) => {
    await expect(page.locator('.pd-card[data-project-id="living-fiction"] .pd-card-service-link')).toHaveCount(0);
    await expect(page.locator('.pd-card[data-project-id="living-fiction"] .pd-card-undeployed')).toBeVisible();
  });

  test('service link count matches expected 9', async ({ page }) => {
    await expect(page.locator('.pd-card-service-link')).toHaveCount(9);
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

  test('LoveBud detail shows PostgreSQL migration evidence', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    const doneTasks = await page.locator('#pd-detail-done-tasks').textContent();
    expect(doneTasks).toContain('PR #3531');
    expect(doneTasks).toContain('e0ff1b2a');
  });

  test('Portfolio Console detail shows #137 milestone', async ({ page }) => {
    await page.click('.pd-card[data-project-id="portfolio-console"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-milestone')).toContainText('#137');
  });

  test('Portfolio Console does not reference PR #140 as evidence', async ({ page }) => {
    await page.click('.pd-card[data-project-id="portfolio-console"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    const doneTasks = await page.locator('#pd-detail-done-tasks').textContent();
    expect(doneTasks).not.toContain('PR #140 작업 현재 브랜치');
  });

  test('Portfolio Console done tasks show PR #147 merged evidence', async ({ page }) => {
    await page.click('.pd-card[data-project-id="portfolio-console"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    const doneTasks = await page.locator('#pd-detail-done-tasks').textContent();
    expect(doneTasks).toContain('PR #147 merged');
    expect(doneTasks).toContain('9f4c812a');
  });

  test('Portfolio Console done tasks do not reference Draft or CTO 검토 대기', async ({ page }) => {
    await page.click('.pd-card[data-project-id="portfolio-console"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    const doneTasks = await page.locator('#pd-detail-done-tasks').textContent();
    expect(doneTasks).not.toContain('Draft');
    expect(doneTasks).not.toContain('CTO 검토 대기');
  });

  test('Portfolio Console done tasks show PR #153 merged evidence', async ({ page }) => {
    await page.click('.pd-card[data-project-id="portfolio-console"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    const doneTasks = await page.locator('#pd-detail-done-tasks').textContent();
    expect(doneTasks).toContain('PR #153 merged');
    expect(doneTasks).toContain('3fb95ea5');
  });

  test('Portfolio Console done tasks do not contain 미구현 for search filter', async ({ page }) => {
    await page.click('.pd-card[data-project-id="portfolio-console"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    const doneTasks = await page.locator('#pd-detail-done-tasks').textContent();
    expect(doneTasks).not.toContain('미구현');
  });

  test('Portfolio Console currentWork shows Production 배포 검증 준비', async ({ page }) => {
    await page.click('.pd-card[data-project-id="portfolio-console"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-current')).toContainText('Production 배포 검증 준비');
  });

  test('Portfolio Console nextAction shows Cloudflare Access 검증', async ({ page }) => {
    await page.click('.pd-card[data-project-id="portfolio-console"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-next')).toContainText('Cloudflare Access 검증');
  });

  test('Portfolio Console card shows exact 60% progress', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="portfolio-console"]');
    await expect(card.locator('.pd-card-pct').first()).toHaveText('완료 60%');
    await expect(card.locator('.pd-card-pct').nth(1)).toHaveText('남음 40%');
    const barWidth = await card.locator('.pd-card-bar i').evaluate(el => el.style.width);
    expect(barWidth).toBe('60%');
  });

  test('Portfolio Console detail shows 3/5 tasks', async ({ page }) => {
    await page.click('.pd-card[data-project-id="portfolio-console"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-progress')).toContainText('3/5');
    const barWidth = await page.locator('#pd-detail-progress-bar').evaluate(el => el.style.width);
    expect(barWidth).toBe('60%');
  });

  test('LoveBud card shows exact 50% progress', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="lovebud"]');
    await expect(card.locator('.pd-card-pct').first()).toHaveText('완료 50%');
    await expect(card.locator('.pd-card-pct').nth(1)).toHaveText('남음 50%');
    const barWidth = await card.locator('.pd-card-bar i').evaluate(el => el.style.width);
    expect(barWidth).toBe('50%');
  });

  test('LoveBud detail shows 3/6 tasks', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovebud"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-progress')).toContainText('3/6');
    const barWidth = await page.locator('#pd-detail-progress-bar').evaluate(el => el.style.width);
    expect(barWidth).toBe('50%');
  });

  test('Personal Edition card shows exact 25% progress', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="personal-edition"]');
    await expect(card.locator('.pd-card-pct').first()).toHaveText('완료 25%');
    await expect(card.locator('.pd-card-pct').nth(1)).toHaveText('남음 75%');
    const barWidth = await card.locator('.pd-card-bar i').evaluate(el => el.style.width);
    expect(barWidth).toBe('25%');
  });

  test('Personal Edition detail shows 1/4 tasks', async ({ page }) => {
    await page.click('.pd-card[data-project-id="personal-edition"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-progress')).toContainText('1/4');
    const barWidth = await page.locator('#pd-detail-progress-bar').evaluate(el => el.style.width);
    expect(barWidth).toBe('25%');
  });

  test('Living Fiction card shows exact 0% progress', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="living-fiction"]');
    await expect(card.locator('.pd-card-pct').first()).toHaveText('완료 0%');
    await expect(card.locator('.pd-card-pct').nth(1)).toHaveText('남음 100%');
    const barWidth = await card.locator('.pd-card-bar i').evaluate(el => el.style.width);
    expect(barWidth).toBe('0%');
  });

  test('Living Fiction detail shows 0/1 tasks', async ({ page }) => {
    await page.click('.pd-card[data-project-id="living-fiction"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-progress')).toContainText('0/1');
    const barWidth = await page.locator('#pd-detail-progress-bar').evaluate(el => el.style.width);
    expect(barWidth).toBe('0%');
  });

  test('LoveTree card has no percent and no progress bar', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="lovetree-3"]');
    await expect(card.locator('.pd-card-pct')).toHaveCount(0);
    await expect(card.locator('.pd-card-bar')).toHaveCount(0);
    await expect(card.locator('.pd-card-milestone-undefined')).toContainText('진척도 미정');
    await expect(card.locator('.pd-card-milestone-undefined')).toContainText('목표 정의 필요');
  });

  test('Korean AI Platform card has no percent and no progress bar', async ({ page }) => {
    const card = page.locator('.pd-card[data-project-id="korean-ai-platform"]');
    await expect(card.locator('.pd-card-pct')).toHaveCount(0);
    await expect(card.locator('.pd-card-bar')).toHaveCount(0);
    await expect(card.locator('.pd-card-milestone-undefined')).toContainText('진척도 미정');
    await expect(card.locator('.pd-card-milestone-undefined')).toContainText('목표 정의 필요');
  });

  test('LoveTree detail shows 진척도 미정 and no progress track', async ({ page }) => {
    await page.click('.pd-card[data-project-id="lovetree-3"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-progress')).toContainText('진척도 미정');
    await expect(page.locator('#pd-detail-progress')).toContainText('목표 정의 필요');
    const trackDisplay = await page.locator('#pd-detail-progress-track').evaluate(el => el.style.display);
    expect(trackDisplay).toBe('none');
  });

  test('Korean AI Platform detail shows 진척도 미정 and no progress track', async ({ page }) => {
    await page.click('.pd-card[data-project-id="korean-ai-platform"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-progress')).toContainText('진척도 미정');
    await expect(page.locator('#pd-detail-progress')).toContainText('목표 정의 필요');
    const trackDisplay = await page.locator('#pd-detail-progress-track').evaluate(el => el.style.display);
    expect(trackDisplay).toBe('none');
  });

  test('AI Finder 북구청 shows actual currentWork with #1150 and #1080', async ({ page }) => {
    await page.click('.pd-card[data-project-id="ai-finder-bukgu"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-current')).toContainText('#1150');
    await expect(page.locator('#pd-detail-current')).toContainText('#1080');
  });

  test('AI Finder 북구청 nextAction references #1150 and #1080', async ({ page }) => {
    await page.click('.pd-card[data-project-id="ai-finder-bukgu"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    await expect(page.locator('#pd-detail-next')).toContainText('#1150');
    await expect(page.locator('#pd-detail-next')).toContainText('#1080');
  });

  test('AI Finder 북구청 does not show 현재 작업 없음', async ({ page }) => {
    await page.click('.pd-card[data-project-id="ai-finder-bukgu"] .pd-card-detail-btn');
    await page.waitForTimeout(200);
    const current = await page.locator('#pd-detail-current').textContent();
    expect(current).not.toContain('현재 작업 없음');
  });
});
