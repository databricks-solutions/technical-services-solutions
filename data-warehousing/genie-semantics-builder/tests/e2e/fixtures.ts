import { chromium, test as base } from '@playwright/test';
import type { Browser, BrowserContext } from '@playwright/test';

/**
 * The scenarios attach to a Google Chrome window you opened and signed in to yourself (`pnpm e2e:profile`).
 * A browser started by Playwright cannot pass the work sign-in, and Chrome refuses DevTools connections on
 * its default profile, so the window uses a profile of its own with a local debugging port.
 */
export const cdpUrl = process.env.E2E_CDP_URL ?? 'http://127.0.0.1:9333';

export const test = base.extend<object, { attached: { browser: Browser; context: BrowserContext } }>({
  attached: [
    // Playwright reads the fixture's parameter list, so the empty pattern is required.
    // eslint-disable-next-line no-empty-pattern
    async ({}, use) => {
      const browser = await chromium.connectOverCDP(cdpUrl).catch((err: unknown) => {
        throw new Error(
          `No Chrome at ${cdpUrl}. Run \`pnpm e2e:profile\`, sign in, and leave the window open. (${(err as Error).message})`
        );
      });
      await use({ browser, context: browser.contexts()[0] });
      // Disconnects only; the window and its sign-in stay open for the next run.
      await browser.close();
    },
    { scope: 'worker' },
  ],
  context: async ({ attached }, use) => use(attached.context),
  page: async ({ attached }, use) => {
    const page = await attached.context.newPage();
    const base = process.env.E2E_BASE_URL ?? '';
    // An attached context has no baseURL, so relative paths are resolved here.
    const goto = page.goto.bind(page);
    page.goto = (url, options) => goto(url.startsWith('/') ? new URL(url, base).toString() : url, options);
    await use(page);
    await page.close();
  },
});

export { expect } from '@playwright/test';
