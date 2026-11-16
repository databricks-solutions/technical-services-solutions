import { expect, test } from './fixtures';
import { createProject, deleteProjectByApi, e2eName } from './helpers';

const project = e2eName('Discover');

test('discover the same KPIs in two schemas, then certify one in a dictionary', async ({ page }) => {
  await createProject(page, project, 'Consolidate the KPIs of the sandbox views.');
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

  await panel.getByRole('button', { name: 'Add to a dictionary' }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.locator('#certify-project').click();
  await page.getByRole('option', { name: project, exact: true }).click();
  await dialog.getByRole('button', { name: 'Add as certified' }).click();
  await expect(dialog.getByText('Added as certified.')).toBeVisible({ timeout: 30_000 });
  await dialog.getByRole('button', { name: 'Close' }).first().click();
  await deleteProjectByApi(page, project);
});

test('check on open runs the stale drift checks as the user', async ({ page }) => {
  await page.goto('/metric-views');
  const res = await page.evaluate(async () => {
    const r = await fetch('/api/drift/stale', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: '{}',
    });
    return { status: r.status, body: (await r.json()) as { checked: number; failed: number } };
  });
  expect(res.status).toBe(200);
  expect(res.body.failed).toBe(0);
});
