import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

/**
 * Opens the scenario profile in a normal Google Chrome window, not through Playwright: Google refuses
 * account sign-in in a browser under automation. Add the work account to Chrome, sign in to the app, then
 * quit that Chrome window. The scenarios reuse the saved sign-in.
 */
// Same folder as fixtures.ts. Node runs this file without a bundler, so it cannot import fixtures.ts.
const profileDir =
  process.env.E2E_PROFILE_DIR ?? path.join(os.homedir(), '.cache', 'semantics-builder-e2e', 'chrome-profile');
const url = process.env.E2E_BASE_URL;
if (!url) throw new Error('Set E2E_BASE_URL to the app URL.');

const args = [`--user-data-dir=${profileDir}`, '--no-first-run', url];
const [cmd, cmdArgs] =
  process.platform === 'darwin'
    ? ['open', ['-na', 'Google Chrome', '--args', ...args]]
    : process.platform === 'win32'
      ? ['cmd', ['/c', 'start', 'chrome', ...args]]
      : ['google-chrome', args];
spawn(cmd, cmdArgs, { stdio: 'ignore', detached: true }).unref();
console.log(`Opened Google Chrome on ${profileDir}.\nAdd your work account, sign in to the app, then quit that Chrome window.`);
