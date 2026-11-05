import os from 'node:os';
import path from 'node:path';
import { chromium } from '@playwright/test';

// Same folder as fixtures.ts. Node runs this file without a bundler, so it cannot import fixtures.ts.
const profileDir =
  process.env.E2E_PROFILE_DIR ?? path.join(os.homedir(), '.cache', 'semantics-builder-e2e', 'chrome-profile');

// Opens the scenario profile in Google Chrome. Sign in to Chrome with the work account and to the app, then close it.
const url = process.env.E2E_BASE_URL;
if (!url) throw new Error('Set E2E_BASE_URL to the app URL.');
const ctx = await chromium.launchPersistentContext(profileDir, { channel: 'chrome', headless: false, viewport: null });
const page = ctx.pages()[0] ?? (await ctx.newPage());
await page.goto(url);
console.log(`Profile: ${profileDir}\nSign in, wait for the projects page, then close the window.`);
await new Promise<void>((resolve) => ctx.on('close', () => resolve()));
