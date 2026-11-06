import { expect, test } from './fixtures';
import { deleteProjectByApi, e2eName } from './helpers';

const project = e2eName('Import');

test('import a metric view made outside the app, then find it in the library', async ({ page }) => {
  await page.goto('/metric-views');
  await page.getByRole('button', { name: 'Import a metric view' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.locator('#catalog').click();
  await page.getByRole('option', { name: 'sandbox', exact: true }).click();
  await dialog.locator('#schema').click();
  await page.getByRole('option', { name: 'semantics_builder', exact: true }).click();
  await dialog.locator('#view').click();
  await page.getByRole('option', { name: /^wholesale_order_revenue_metrics__gsb_/ }).click();
  await dialog.locator('#import-project').fill(project);
  await dialog.getByRole('button', { name: 'Import' }).click();
  await expect(page.getByText('Built from a metric view imported from Unity Catalog.')).toBeVisible({ timeout: 60_000 });
  await page.goto('/metric-views');
  await expect(page.getByLabel('Metric views')).toContainText(project, { timeout: 30_000 });
  await deleteProjectByApi(page, project);
});
