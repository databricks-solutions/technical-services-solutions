import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end scenarios against a deployed app. Sign in once with `pnpm e2e:login`, which saves the
 * session to tests/e2e/.auth/user.json (git-ignored). The scenarios use real data, the real model
 * endpoint and the sandbox schema, so they are slow: run them on demand, not in CI.
 */
const baseURL = process.env.E2E_BASE_URL;
if (!baseURL) throw new Error('Set E2E_BASE_URL to the app URL, for example https://<app>.databricksapps.com');

export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 20 * 60_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    storageState: 'tests/e2e/.auth/user.json',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    actionTimeout: 30_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
