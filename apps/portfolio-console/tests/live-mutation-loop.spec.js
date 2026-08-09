const { test, expect } = require('@playwright/test');

const LIVE_PAYLOAD = {
  ok: true,
  schemaVersion: 2,
  syncedAt: '2026-08-09T08:45:00Z',
  stale: false,
  repository: {
    fullName: 'skerishKang/ai-revenue-lab',
    url: 'https://github.com/skerishKang/ai-revenue-lab',
    latestSha: '07ab5fddd59e886f530fe39c441c372c34c14d8c',
  },
  businesses: [
    {
      number: 6,
      connectionState: 'connected',
      repository: 'skerishKang/ai-revenue-lab',
      productDecisionIssue: null,
      phaseIssues: { ui: null, ux: null, backend: null },
      currentPullRequests: { ui: null, ux: null, backend: null },
      phaseDiscovery: {
        ui: { status: 'discovered', method: 'refs' },
        ux: null,
        backend: null,
      },
      phaseVerdicts: null,
      activityAt: '2026-08-09T08:40:00Z',
    },
  ],
};

test('live GitHub discovery decoration settles and the console remains responsive', async ({ page }) => {
  await page.route('**/api/github-status', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(LIVE_PAYLOAD),
    });
  });

  await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 15000 });

  const discovery = page.locator('.biz-item[data-biz-number="6"] [data-live-discovery]');
  await expect(discovery).toHaveText('UI:Refs', { timeout: 5000 });

  const settled = await page.evaluate(async () => {
    const target = document.querySelector('.biz-item[data-biz-number="6"] [data-live-discovery]');
    if (!target) return { missing: true };

    let mutations = 0;
    let ticks = 0;
    const observer = new MutationObserver((records) => { mutations += records.length; });
    observer.observe(target, { childList: true, characterData: true, subtree: true });

    const interval = setInterval(() => { ticks += 1; }, 20);
    await new Promise((resolve) => setTimeout(resolve, 300));
    clearInterval(interval);
    observer.disconnect();

    return { missing: false, mutations, ticks, text: target.textContent };
  });

  expect(settled.missing).toBe(false);
  expect(settled.text).toBe('UI:Refs');
  expect(settled.mutations).toBe(0);
  expect(settled.ticks).toBeGreaterThan(5);

  const beforeTheme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
  await page.click('#theme-toggle');
  const afterTheme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
  expect(afterTheme).not.toBe(beforeTheme);
});
