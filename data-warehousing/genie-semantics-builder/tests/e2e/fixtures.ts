import os from 'node:os';
import path from 'node:path';
import { chromium, test as base } from '@playwright/test';
import type { BrowserContext } from '@playwright/test';

/**
 * The app sign-in needs a Chrome profile with the work account, which a fresh test browser lacks. The
 * scenarios run in installed Google Chrome on a persistent profile of their own, set up once with
 * `pnpm e2e:profile`. Chrome does not allow automating the default profile, so this is a separate one.
 */
export const profileDir =
  process.env.E2E_PROFILE_DIR ?? path.join(os.homedir(), '.cache', 'semantics-builder-e2e', 'chrome-profile');

export const test = base.extend<object, { persistent: BrowserContext }>({
  persistent: [
    // Playwright reads the fixture's parameter list, so the empty pattern is required.
    // eslint-disable-next-line no-empty-pattern
    async ({}, use) => {
      const ctx = await chromium.launchPersistentContext(profileDir, {
        channel: 'chrome',
        headless: process.env.E2E_HEADLESS === '1',
        baseURL: process.env.E2E_BASE_URL,
        viewport: { width: 1440, height: 900 },
      });
      await use(ctx);
      await ctx.close();
    },
    { scope: 'worker' },
  ],
  context: async ({ persistent }, use) => use(persistent),
  page: async ({ persistent }, use) => {
    const page = await persistent.newPage();
    await use(page);
    await page.close();
  },
});

export { expect } from '@playwright/test';
