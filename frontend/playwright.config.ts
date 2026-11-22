import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  use: {
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
  },
  projects: [
    {
      name: 'h5',
      grep: /H5/,
      use: {
        ...devices['iPhone 13'],
        defaultBrowserType: 'chromium',
        baseURL: 'http://127.0.0.1:4301',
      },
    },
    {
      name: 'pc',
      grepInvert: /H5/,
      use: { ...devices['Desktop Chrome'], baseURL: 'http://127.0.0.1:4300' },
    },
  ],
  webServer: [
    {
      command: 'npm run preview -- --host 127.0.0.1 --port 4300 --strictPort',
      url: 'http://127.0.0.1:4300/ai-eido/',
      reuseExistingServer: !process.env.CI,
    },
    {
      command:
        'npm run preview:mobile -- --host 127.0.0.1 --port 4301 --strictPort',
      url: 'http://127.0.0.1:4301/ai-eido/',
      reuseExistingServer: !process.env.CI,
    },
  ],
});
