import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

/**
 * Opens a normal Google Chrome window, not through Playwright, on the scenario profile with a local
 * debugging port. Sign in to the app there and leave the window open: the scenarios attach to it.
 */
// Same folder as fixtures.ts. Node runs this file without a bundler, so it cannot import fixtures.ts.
const profileDir =
  process.env.E2E_PROFILE_DIR ?? path.join(os.homedir(), '.cache', 'semantics-builder-e2e', 'chrome-profile');
const url = process.env.E2E_BASE_URL;
if (!url) throw new Error('Set E2E_BASE_URL to the app URL.');

const port = new URL(process.env.E2E_CDP_URL ?? 'http://127.0.0.1:9333').port;
const args = [`--user-data-dir=${profileDir}`, `--remote-debugging-port=${port}`, '--no-first-run', url];
const [cmd, cmdArgs] =
  process.platform === 'darwin'
    ? ['open', ['-na', 'Google Chrome', '--args', ...args]]
    : process.platform === 'win32'
      ? ['cmd', ['/c', 'start', 'chrome', ...args]]
      : ['google-chrome', args];
spawn(cmd, cmdArgs, { stdio: 'ignore', detached: true }).unref();
console.log(
  `Opened Google Chrome on ${profileDir}, debugging port ${port}.\nSign in to the app and leave the window open. Then run: pnpm e2e`
);
