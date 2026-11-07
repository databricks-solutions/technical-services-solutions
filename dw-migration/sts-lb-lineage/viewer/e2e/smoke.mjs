// UI smoke test: opens a generated lineage.html in headless Chrome and checks that every page
// renders, that graphs appear without extra clicks, and that the process map toggles keep a graph
// on screen. Usage: CHROME_PATH=/path/to/chrome node e2e/smoke.mjs <lineage.html> [object-id] [process]
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
