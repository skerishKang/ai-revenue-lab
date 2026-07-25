const { defineConfig, devices } = require('@playwright/test');

module.exports = defineConfig({
  testDir: 'tests',
  timeout: 15000,
  expect: { timeout: 5000 },
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 3,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'on-first-retry',
    screenshot: 'only-if-assertion-failed',
    actionTimeout: 5000,
  },
  projects: [
    {
      name: 'chromium-desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1100 } },
    },
    {
      name: 'chromium-tablet',
      use: { ...devices['Desktop Chrome'], viewport: { width: 768, height: 1024 } },
    },
    {
      name: 'chromium-mobile',
      use: { ...devices['Pixel 5'], viewport: { width: 390, height: 844 } },
    },
  ],
  webServer: {
    command: process.platform === 'win32'
      ? 'python -m http.server 4173'
      : 'python3 -m http.server 4173',
    port: 4173,
    timeout: 15000,
    reuseExistingServer: true,
  },
});
