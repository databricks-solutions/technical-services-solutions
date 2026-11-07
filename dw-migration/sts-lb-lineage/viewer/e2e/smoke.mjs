// UI smoke test: opens a generated lineage.html in headless Chrome, in light and dark mode, and
// checks that every page renders with readable contrast, that graphs appear without extra clicks,
// that the process map toggles keep a graph on screen, and that graphs work from the keyboard.
// Usage: CHROME_PATH=/path/to/chrome node e2e/smoke.mjs <lineage.html> [object-id] [process]
import { pathToFileURL } from 'node:url';
import puppeteer from 'puppeteer-core';

const [file, objectId, processName] = process.argv.slice(2);
const chrome = process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
if (!file) throw new Error('usage: node e2e/smoke.mjs <lineage.html> [object-id] [process]');

const browser = await puppeteer.launch({ executablePath: chrome, headless: true });
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 1000 });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
const url = pathToFileURL(file).href;
const failures = [];
const check = (ok, what) => (ok ? console.log(`ok   ${what}`) : (failures.push(what), console.log(`FAIL ${what}`)));

async function open(hash) {
  await page.goto(`${url}#${hash}`);
  await page.reload();
  await page.waitForSelector('.lbl-main', { timeout: 10_000 });
}
const graphNodes = (scope = '') =>
  page
    .waitForSelector(`${scope} .react-flow__node`, { timeout: 3_000 })
    .then(() => page.$$eval(`${scope} .react-flow__node`, (n) => n.length))
    .catch(() => 0);
const toggle = (id) => page.$eval(`[data-component-id="${id}"]`, (s) => s.click()).then(() => new Promise((r) => setTimeout(r, 400)));

// WCAG relative-luminance contrast between the page title and the page background
const contrast = () =>
  page.evaluate(() => {
    const rgb = (c) => (c.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
    const lum = ([r, g, b]) =>
      [r, g, b].map((v) => ((v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)).reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0);
    let bgEl = document.querySelector('.lbl-main');
    let bg = getComputedStyle(bgEl).backgroundColor;
    while (bgEl && /rgba\(0, 0, 0, 0\)|transparent/.test(bg)) {
      bgEl = bgEl.parentElement;
      bg = bgEl ? getComputedStyle(bgEl).backgroundColor : 'rgb(255, 255, 255)';
    }
    const fg = getComputedStyle(document.querySelector('.lbl-main h1, .lbl-main h2') ?? document.body).color;
    const [a, b] = [lum(rgb(fg)), lum(rgb(bg))].sort((x, y) => y - x);
    return { ratio: (a + 0.05) / (b + 0.05), background: lum(rgb(bg)) };
  });

for (const scheme of ['light', 'dark']) {
  await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: scheme }]);
  await open('tab=overview');
  const c = await contrast();
  check(scheme === 'light' ? c.background > 0.5 : c.background < 0.5, `${scheme} mode applies (background luminance ${c.background.toFixed(2)})`);
  check(c.ratio >= 4.5, `${scheme} mode title contrast ${c.ratio.toFixed(1)}:1 (needs 4.5:1)`);
  await open('tab=processes');
  check((await graphNodes()) > 0, `${scheme} mode process map shows a graph`);
}
await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'light' }]);

for (const tab of ['overview', 'statistics', 'processes', 'objects', 'impact']) {
  await open(`tab=${tab}`);
  check(await page.$('.lbl-main h1, .lbl-main h2, .lbl-main header'), `${tab} page renders`);
}

await open('tab=overview');
check((await graphNodes('.lbl-canvas.is-preview')) > 0, 'overview shows a lineage map without a click');

await open('tab=processes');
check((await graphNodes()) > 0, 'process map shows a graph on open');
for (const id of ['sts-lb-lineage.map.hubs', 'sts-lb-lineage.map.connected']) {
  const enabled = await page.$eval(`[data-component-id="${id}"]`, (s) => !s.disabled).catch(() => false);
  if (!enabled) continue;
  await toggle(id);
  check((await graphNodes()) > 0, `process map keeps a graph after toggling ${id.split('.').pop()} off`);
}

// keyboard: focus a node, move with an arrow key, open with Enter
await open('tab=processes');
await graphNodes();
await page.$eval('.react-flow__node[tabindex="0"]', (n) => n.focus());
const first = await page.evaluate(() => document.activeElement?.getAttribute('data-id'));
for (const key of ['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp']) {
  await page.keyboard.press(key);
  if ((await page.evaluate(() => document.activeElement?.getAttribute('data-id'))) !== first) break;
}
const moved = await page.evaluate(() => document.activeElement?.getAttribute('data-id'));
check(moved && moved !== first, 'arrow keys move the focus to another graph node');
check(await page.evaluate(() => !!document.activeElement?.getAttribute('aria-label')), 'focused graph node has an accessible name');
await page.keyboard.press('Enter');
await new Promise((r) => setTimeout(r, 400));
check(/[#&](proc|obj)=/.test(page.url()), 'Enter opens the focused node');

await open('tab=objects');
const objectGraph = (await graphNodes()) > 0;
const chooser = await page.$('[data-component-id="sts-lb-lineage.objects.too-many"]');
check(objectGraph || chooser, 'objects page opens on the graph, or asks for a narrower scope');

if (objectId) {
  await open(`tab=objects&obj=${encodeURIComponent(objectId)}`);
  check((await graphNodes('.lbl-details')) > 0, 'object details show the lineage graph on open');
}
if (processName) {
  await open(`tab=processes&proc=${encodeURIComponent(processName)}`);
  check((await graphNodes('.lbl-details')) > 0, 'process details show the lineage graph on open');
}

check(errors.length === 0, `no console errors${errors.length ? `: ${errors.slice(0, 3).join(' | ')}` : ''}`);
await browser.close();
if (failures.length) process.exit(1);
