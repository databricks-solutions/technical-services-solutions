import { expect, test } from './fixtures';

test('discover the same KPIs in two schemas and propose one definition', async ({ page }) => {
  await page.goto('/metric-views');
  await page.getByRole('button', { name: 'Discover and consolidate KPIs' }).click();
  const panel = page.getByRole('region', { name: 'Discover KPIs' });
  await panel.locator('#discover-catalog').click();
  await page.getByRole('option', { name: 'sandbox', exact: true }).click();
  await panel.getByRole('checkbox', { name: 'semantics_builder', exact: true }).check();
  await panel.getByRole('checkbox', { name: 'semantics_builder_promoted', exact: true }).check();
  await panel.getByRole('button', { name: 'Find KPIs' }).click();
  await expect(panel.getByText(/views? with KPIs/)).toBeVisible({ timeout: 60_000 });
  // The promoted view and its sandbox copies share their measures.
  await expect(panel.getByLabel('Duplicate KPIs')).toBeVisible();
  await expect(panel.getByRole('button', { name: /^Import / }).first()).toBeVisible();
});
