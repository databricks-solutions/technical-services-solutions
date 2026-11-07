import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end scenarios against a deployed app, in installed Google Chrome on a persistent profile (see
 * tests/e2e/fixtures.ts). Set it up once with `pnpm e2e:profile`. The scenarios use real data, the model
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
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    actionTimeout: 30_000,
  },
  // The installed Google Chrome, not the bundled Chrome for Testing: managed Chrome passes the sign-in policy.
  projects: [{ name: 'chrome', use: { ...devices['Desktop Chrome'], channel: 'chrome' } }],
});
