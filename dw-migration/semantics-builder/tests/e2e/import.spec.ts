import { expect, test } from './fixtures';
import { deleteProjectByApi, e2eName } from './helpers';

const project = e2eName('Import');

test('list the metric views to adopt', async ({ page }) => {
  await page.goto('/metric-views?tab=adopt');
  await expect(page.getByRole('tab', { name: /^Adopt \(\d+\)/, selected: true })).toBeVisible({ timeout: 60_000 });
  // The app's own sandbox copies never show as views to adopt.
  await expect(page.getByLabel('Metric views to adopt', { exact: true }).or(page.getByText('Nothing to adopt'))).toBeVisible();
  await expect(page.getByText(/__gsb_/)).toHaveCount(0);
});

test('adopt a metric view made outside the app, then find it in the library', async ({ page }) => {
  await page.goto('/metric-views');
  await page.getByRole('button', { name: 'Adopt by name' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.locator('#catalog').click();
  await page.getByRole('option', { name: 'sandbox', exact: true }).click();
  await dialog.locator('#schema').click();
  await page.getByRole('option', { name: 'semantics_builder', exact: true }).click();
  await dialog.locator('#view').click();
  await page.getByRole('option', { name: /^wholesale_order_revenue_metrics__gsb_/ }).click();
  await dialog.locator('#import-project').fill(project);
  await dialog.getByRole('button', { name: 'Adopt' }).click();
  await expect(page.getByText('Built from a metric view imported from Unity Catalog.')).toBeVisible({ timeout: 60_000 });
  await page.goto('/metric-views');
  // The nav link has the same label as the table, so find the row by its project cell text.
  await expect(page.getByText(`${project} /`)).toBeVisible({ timeout: 30_000 });
  await deleteProjectByApi(page, project);
});
