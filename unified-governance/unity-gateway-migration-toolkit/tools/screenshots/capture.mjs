#!/usr/bin/env node
/**
 * Capture the documentation screenshots of the Unity Gateway Migration Toolkit.
 *
 * Drives headless Google Chrome (puppeteer-core) against the mock backend (mock_server.py), which serves the built
 * frontend (app/frontend/static). Every image starts from a fresh seeded state (POST /__mock/reset), so the clicks
 * in one image don't change what the next one shows.
 *
 * Environment (all optional):
 *   OUT_DIR      output folder (default: docs/screenshots in this repo)
 *   SHOTS_DIR    folder with node_modules/puppeteer-core (default: /tmp/shots)
 *   CHROME_PATH  Chrome executable (default: /Applications/Google Chrome.app, macOS)
 *   MOCK_URL     use a mock server that is already running (default: start mock_server.py on MOCK_PORT)
 *   MOCK_PORT    port for the mock this script starts (default: 8765)
 *   ONLY         comma-separated image names to capture (default: all)
 *
 * Usage: node tools/screenshots/capture.mjs
 */
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { mkdirSync, statSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "../..");
const OUT = process.env.OUT_DIR || path.join(REPO, "docs", "screenshots");
const SHOTS = process.env.SHOTS_DIR || "/tmp/shots";
const CHROME = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = Number(process.env.MOCK_PORT || 8765);
const BASE = process.env.MOCK_URL || `http://127.0.0.1:${PORT}`;
const ONLY = process.env.ONLY ? new Set(process.env.ONLY.split(",").map((s) => s.trim())) : null;
const WIDTH = 1280;
const HEIGHT = 800;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function loadPuppeteer() {
  try {
    return (await import("puppeteer-core")).default;
  } catch {
    const req = createRequire(path.join(SHOTS, "package.json"));
    return req("puppeteer-core");
  }
}

async function startMock() {
  if (process.env.MOCK_URL) return null;
  try {
    await fetch(`${BASE}/api/whoami`);
    throw new Error(`port ${PORT} is already in use: stop that server or set MOCK_URL to use it`);
  } catch (e) {
    if (String(e.message).startsWith("port ")) throw e;
  }
  const child = spawn("python3", [path.join(HERE, "mock_server.py"), "--port", String(PORT)], { stdio: "ignore" });
  for (let i = 0; i < 80; i++) {
    await sleep(100);
    try {
      await fetch(`${BASE}/api/whoami`);
      return child;
    } catch {
      /* not up yet */
    }
  }
  child.kill();
  throw new Error("the mock server didn't start");
}

async function reset(state) {
  const res = await fetch(`${BASE}/__mock/reset`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state }),
  });
  if (!res.ok) throw new Error(`mock reset failed: ${res.status}`);
}

/** A fresh page on the app, seeded state, light theme, 1280x800 at scale 1. */
async function open(browser, state) {
  await reset(state);
  const page = await browser.newPage();
  await page.setViewport({ width: WIDTH, height: HEIGHT, deviceScaleFactor: 1 });
  await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: "light" }]);
  await page.goto(`${BASE}/`, { waitUntil: "networkidle0" });
  // The top bar is sticky; in a tall crop it would sit over the content, so the capture lays it out statically.
  await page.addStyleTag({
    content: "header.top{position:static!important}"
      + "*,*::before,*::after{transition:none!important;animation:none!important;caret-color:transparent!important}",
  });
  await page.waitForFunction(() => document.querySelector("header.top")?.innerText.includes("Operator"), { timeout: 15000 });
  await page.evaluate(() => document.fonts.ready);
  return page;
}

/** Wait until the page text contains `text`. */
async function waitText(page, text, timeout = 20000) {
  await page.waitForFunction((t) => document.body.innerText.includes(t), { timeout }, text);
  await sleep(150);
}

/** Click the first element matching `selector` (inside `root` when given) whose trimmed text starts with `text`. */
async function clickText(page, selector, text, root = null) {
  const ok = await page.evaluate((sel, t, rootEl) => {
    const scope = rootEl || document;
    const el = [...scope.querySelectorAll(sel)].find((b) => b.textContent.trim().startsWith(t));
    if (!el) return false;
    el.scrollIntoView({ block: "center" });
    el.click();
    return true;
  }, selector, text, root);
  if (!ok) throw new Error(`no ${selector} with text "${text}"`);
  await sleep(200);
}

/** The section.card whose heading starts with `title`. */
async function card(page, title) {
  const handle = await page.evaluateHandle((t) => [...document.querySelectorAll("section.card")]
    .find((s) => s.querySelector("h3")?.textContent.trim().startsWith(t)) || null, title);
  if (!(await handle.asElement())) throw new Error(`no card "${title}"`);
  return handle.asElement();
}

async function rectOf(page, handle) {
  return page.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: r.left + window.scrollX, y: r.top + window.scrollY, width: r.width, height: r.height };
  }, handle);
}

/** Crop from the top of `from` (document coordinates) to the bottom of `to`, full width. */
async function region(page, file, fromHandle, toHandle, { pad = 0 } = {}) {
  // The app moves focus to a new scan's heading; the focus ring isn't part of the picture.
  await page.evaluate(() => document.activeElement?.blur?.());
  const a = await rectOf(page, fromHandle);
  const b = await rectOf(page, toHandle);
  const top = Math.max(0, a.y - pad);
  const bottom = b.y + b.height + pad;
  await page.screenshot({ path: path.join(OUT, file), clip: { x: 0, y: top, width: WIDTH, height: bottom - top }, captureBeyondViewport: true });
  return { file, height: Math.round(bottom - top) };
}

async function headerHandle(page) {
  return page.$("header.top");
}

async function mainHandle(page) {
  return page.$("main");
}

/** Chooses the scan rows' detail, Apply's dry run, and so on. Each entry is one image. */
const SHOTS_LIST = [
  ["overview-first-run.png", async (browser, out) => {
    const page = await open(browser, "empty");
    await waitText(page, "No snapshot yet");
    return region(page, out, await headerHandle(page), await mainHandle(page));
  }],

  ["overview.png", async (browser, out) => {
    const page = await open(browser, "full");
    await waitText(page, "Workspaces by migration wave");
    return region(page, out, await headerHandle(page), await card(page, "Workspaces by migration wave"));
  }],

  ["scans-new.png", async (browser, out) => {
    const page = await open(browser, "full");
    await clickText(page, "[role=tab]", "Scans");
    await waitText(page, "Scan history");
    return region(page, out, await headerHandle(page), await card(page, "Scan history"));
  }],

  ["scan-readiness.png", async (browser, out) => {
    const page = await open(browser, "full");
    await clickText(page, "[role=tab]", "Scans");
    await waitText(page, "Scan history");
    await clickText(page, "button", "2026-");
    await waitText(page, "Next:");
    const scan = await card(page, "Scan of");
    return region(page, out, scan, await card(page, "Warnings"));
  }],

  ["scan-code-fixes.png", async (browser, out) => {
    const page = await open(browser, "full");
    await clickText(page, "[role=tab]", "Scans");
    await waitText(page, "Scan history");
    await clickText(page, "button", "2026-");
    await waitText(page, "Next:");
    await clickText(page, "[role=tab]", "Code fixes");
    await page.waitForSelector("details.diff");
    await sleep(200);
    const scan = await card(page, "Scan of");
    return region(page, out, scan, scan);
  }],

  ["apply-planner.png", async (browser, out) => {
    const page = await planner(browser);
    return region(page, out, await headerHandle(page), await card(page, "2. Choose endpoints and options"));
  }],

  ["apply-confirm.png", async (browser, out) => {
    const page = await planner(browser);
    await clickText(page, "button", "Execute");
    await page.waitForSelector(".modal");
    await page.type("#confirm-word", "EXECUTE");
    await sleep(200);
    // The dialog is fixed to the viewport, so the plain viewport capture shows it over the dimmed page.
    await page.evaluate(() => document.activeElement?.blur?.());
    await page.screenshot({ path: path.join(OUT, out), captureBeyondViewport: false });
    return { file: out, height: HEIGHT };
  }],

  ["cutover-traffic.png", async (browser, out) => {
    const page = await open(browser, "full");
    await clickText(page, "[role=tab]", "Verify");
    await openStep(page, "traffic");
    await waitText(page, "Legacy traffic by endpoint");
    return region(page, out, await headerHandle(page), await card(page, "1. Legacy traffic"));
  }],

  ["cutover-pause-test.png", async (browser, out) => {
    const page = await open(browser, "full");
    await clickText(page, "[role=tab]", "Verify");
    await openStep(page, "pause");
    await waitText(page, "3. Pause a legacy endpoint");
    const pause = await card(page, "3. Pause a legacy endpoint");
    // Pause the endpoint with no traffic in the window (the traffic check shows it quiet).
    const endpointSelect = await pause.$("select");
    await endpointSelect.select("legacy-summarizer-openai");
    await waitText(page, "No legacy requests since");
    await dryThenExecute(page, pause, "Pause legacy-summarizer-openai", "PAUSE");
    await waitText(page, "Pause: succeeded");
    await openStep(page, "test");
    const test = await card(page, "4. Test a Unity Gateway service");
    await page.evaluate((c) => {
      const label = [...c.querySelectorAll("label.choice")].find((l) => l.textContent.includes("ai_gateway.migrated.legacy-summarizer-openai"));
      label?.querySelector("input")?.click();
    }, test);
    await sleep(200);
    await dryThenExecute(page, test, "Send 1 request", "TEST");
    await waitText(page, "Test call: succeeded");
    // The strip shows the pause as done; the step below is the test call that answered.
    return region(page, out, await card(page, "Cut-over status"), test);
  }],

  ["cutover-usage-enforce.png", async (browser, out) => {
    const page = await open(browser, "full");
    await clickText(page, "[role=tab]", "Verify");
    await openStep(page, "enforce");
    await waitText(page, "6. Enforce Unity Gateway");
    await waitText(page, "Ready to enforce").catch(() => {});
    return region(page, out, await card(page, "Cut-over status"), await card(page, "6. Enforce Unity Gateway"));
  }],
];

/** Apply tab with two endpoints selected and a successful dry run (Execute is then available). */
async function planner(browser) {
  const page = await open(browser, "full");
  await clickText(page, "[role=tab]", "Apply");
  await waitText(page, "Endpoints apply can migrate");
  await page.click('input[aria-label="Select claims-summary-pt"]');
  await page.click('input[aria-label="Select support-bot-openai"]');
  await sleep(200);
  const planCard = await card(page, "2. Choose endpoints and options");
  await clickInCard(page, planCard, "Dry run");
  await waitText(page, "Dry run checked");
  return page;
}

/** Verify & cut over shows one step at a time: click its tile in the status strip. */
async function openStep(page, key) {
  await page.waitForSelector(`button.tile[data-step="${key}"]`);
  await page.click(`button.tile[data-step="${key}"]`);
  await sleep(250);
}

/** Clicks a button in a card by its text (exact match on the trimmed text). */
async function clickInCard(page, cardHandle, text) {
  const ok = await page.evaluate((c, t) => {
    const b = [...c.querySelectorAll("button")].find((x) => x.textContent.trim() === t);
    if (!b) return false;
    b.scrollIntoView({ block: "center" });
    b.click();
    return true;
  }, cardHandle, text);
  if (!ok) throw new Error(`no button "${text}" in the card`);
  await sleep(250);
}

/** Dry run in a card, wait for the check inside that card, open Execute, type the word, confirm with the labelled button. */
async function dryThenExecute(page, cardHandle, confirmLabel, word) {
  await clickInCard(page, cardHandle, "Dry run");
  await page.waitForFunction((c) => c.innerText.includes("Dry run checked"), { timeout: 20000 }, cardHandle);
  await sleep(150);
  await clickInCard(page, cardHandle, "Execute…");
  await page.waitForSelector(".modal");
  await page.type("#confirm-word", word);
  await sleep(200);
  await page.evaluate((label) => {
    const b = [...document.querySelectorAll(".modal button[type=submit]")].find((x) => x.textContent.trim().startsWith(label));
    b?.click();
  }, confirmLabel);
  await sleep(400);
}

async function main() {
  const puppeteer = await loadPuppeteer();
  mkdirSync(OUT, { recursive: true });
  if (!existsSync(path.join(REPO, "app", "frontend", "static", "index.html"))) {
    throw new Error("app/frontend/static/index.html is missing: run npm run build in app/frontend first");
  }
  const mock = await startMock();
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: true,
    args: ["--no-sandbox", "--hide-scrollbars", "--font-render-hinting=none"],
    defaultViewport: { width: WIDTH, height: HEIGHT, deviceScaleFactor: 1 },
  });
  try {
    for (const [name, run] of SHOTS_LIST) {
      if (ONLY && !ONLY.has(name.replace(/\.png$/, ""))) continue;
      const info = await run(browser, name);
      const size = statSync(path.join(OUT, name)).size;
      console.log(`${name}: ${info.height}px tall, ${(size / 1024).toFixed(0)} KB`);
      // Close the page the shot opened, so the next one starts from a clean page.
      for (const p of await browser.pages()) await p.close().catch(() => {});
    }
  } finally {
    await browser.close();
    if (mock) mock.kill();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
