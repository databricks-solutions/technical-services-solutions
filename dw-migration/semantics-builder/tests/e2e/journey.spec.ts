import { expect, test } from './fixtures';
import {
  approveSql,
  createProject,
  createSubProject,
  deleteProject,
  deleteProjectByApi,
  e2eName,
  openModule,
  pickTables,
} from './helpers';

/**
 * The whole journey on bakehouse, the smallest real dataset: sources, readiness, discovery, brief,
 * design, validation, stress test, delete. Model output varies, so the checks look at structure.
 */
test.describe.configure({ mode: 'serial' });

const project = e2eName('Bakehouse');
const sub = 'Franchise revenue';

// Cleanup through the API, so a failed step never leaves the project behind.
test.afterAll(async ({ attached }) => {
  const page = await attached.context.newPage();
  await deleteProjectByApi(page, project);
  await page.close();
});

test('create the project and sub-project', async ({ page }) => {
  await createProject(page, project, 'Revenue and transactions of the bakehouse franchises.');
  await createSubProject(page, sub);
});

test('pick sources, check how they relate, and assess them', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('heading', { name: project }).click();
  await page.getByRole('link', { name: sub }).first().click();
  await pickTables(page, 'sandbox_source', 'bakehouse', ['sales_transactions', 'sales_franchises', 'sales_customers']);
  await page.getByRole('button', { name: 'Check how they relate' }).click();
  // Wait for the check result, then keep all three even if a rule does not join one of them.
  const add = page.getByRole('button', { name: /^Add (all \d+ anyway|\d+ tables?)/ }).first();
  await add.waitFor({ timeout: 120_000 });
  const addAll = page.getByRole('button', { name: /^Add all \d+ anyway/ });
  await ((await addAll.count()) ? addAll : add).click();
  // The assessment runs on add and ends with a score.
  await expect(page.getByRole('region', { name: 'Semantic readiness' })).toBeVisible({ timeout: 180_000 });
  await expect(page.getByRole('tab', { name: /Improvement plan/ })).toBeVisible();
  await page.getByRole('tab', { name: 'Lineage' }).click();
  await expect(page.getByRole('img', { name: /Lineage of 3 tables/ })).toBeVisible();
  await page.getByRole('tab', { name: 'Permissions' }).click();
  await expect(page.getByRole('table')).toContainText('Read sandbox_source.bakehouse.sales_transactions');
});

test('discover metrics and confirm a brief', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('heading', { name: project }).click();
  await page.getByRole('link', { name: sub }).first().click();
  await openModule(page, 'Intent & Context');
  // Discovery starts when the user asks what can be built; the AI then proposes idea cards.
  await page.getByRole('button', { name: 'What can I build from these tables?' }).click();
  await page.getByRole('button', { name: 'Build this' }).first().click({ timeout: 180_000 });
  await expect(page.getByRole('heading', { name: 'Untitled brief' })).toBeHidden({ timeout: 180_000 });
  await page.getByRole('button', { name: 'Save brief draft' }).click();
  await page.getByRole('button', { name: 'Confirm brief' }).click({ timeout: 120_000 });
  await expect(page.getByText('Brief confirmed')).toBeVisible({ timeout: 60_000 });
});

test('build a design by hand, with no AI', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('heading', { name: project }).click();
  await page.getByRole('link', { name: sub }).first().click();
  await openModule(page, 'Metric Designer');
  await page.getByRole('button', { name: 'Start from a template' }).click();
  await expect(page.getByText('From the template')).toBeVisible({ timeout: 120_000 });
  await page.getByRole('button', { name: 'Edit fields' }).click();
  await page.locator('#fb-name').fill('Hand Count');
  await page.locator('#fb-expr').fill('COUNT(1)');
  await page.getByRole('button', { name: 'Add the measure' }).click();
  await page.getByRole('button', { name: 'Save as a new version' }).click();
  // Scrollable Du Bois tables carry the label on a wrapper, so they are found by label.
  await expect(page.getByLabel('Measures')).toContainText('Hand Count', { timeout: 120_000 });
  await expect(page.getByRole('button', { name: 'Edit fields' })).toBeEnabled();
  await page.getByRole('tab', { name: /^Tests/ }).click();
  await page.getByRole('button', { name: 'Edit tests by hand' }).click();
  await page.getByRole('button', { name: 'Add a test' }).click();
  await page.getByRole('button', { name: 'Save the tests' }).click();
  await expect(page.getByRole('button', { name: 'Edit tests by hand' })).toBeVisible({ timeout: 120_000 });
  await expect(page.getByRole('listitem').filter({ hasText: /^Test \d+:/ })).toHaveCount(1);
});

test('generate and validate a design', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('heading', { name: project }).click();
  await page.getByRole('link', { name: sub }).first().click();
  await openModule(page, 'Metric Designer');
  await page.getByRole('button', { name: /^Generate (a new )?design$/ }).click();
  await expect(page.getByText('Generated by AI', { exact: true })).toBeVisible({ timeout: 300_000 });
  await page.getByRole('button', { name: 'Validate in sandbox' }).first().click();
  await approveSql(page, 'Run SQL');
  await expect(page.getByText('Validated', { exact: true }).first()).toBeVisible({ timeout: 300_000 });
});

test('stress test two queries', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('heading', { name: project }).click();
  await page.getByRole('link', { name: sub }).first().click();
  await openModule(page, 'Optimize');
  const runs = page.getByRole('table', { name: 'Workload' }).getByRole('checkbox');
  const n = await runs.count();
  for (let i = 2; i < n; i++) await runs.nth(i).uncheck();
  await page.getByLabel('Runs per query').fill('2');
  await page.getByRole('button', { name: 'Review and run' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Run' }).click();
  await expect(page.getByText('Finished', { exact: true })).toBeVisible({ timeout: 600_000 });
  // Scrollable Du Bois tables carry the label on a wrapper, so they are found by label; the check reads the times.
  await expect(page.getByLabel('Stress test results')).toContainText(/\d+(\.\d)? (s|ms)/);
  await page.getByRole('tab', { name: /^Materialization/ }).click();
  await expect(page.getByRole('heading', { name: 'Materialization suggestions' })).toBeVisible();
  await page.getByRole('tab', { name: 'Cost' }).click();
  await expect(page.getByLabel('Runs and their cost')).toContainText('Stress test');

  // Roll back: restore version 1 (the template, the oldest row) as a new version; then the Unity Catalog tab asks for a target.
  await openModule(page, 'Metric Designer');
  await page.getByRole('tab', { name: /^History/ }).click();
  await page.getByRole('button', { name: 'Open' }).last().click();
  await page.getByRole('button', { name: 'Restore as a new version' }).click();
  await expect(page.getByText('Restored', { exact: true }).first()).toBeVisible({ timeout: 60_000 });
  await page.getByRole('tab', { name: 'Unity Catalog' }).click();
  await expect(page.getByText('Set the Unity Catalog view to promote to.')).toBeVisible({ timeout: 60_000 });
});

test('delete the project from its page, with the sandbox cleanup', async ({ page }) => {
  await deleteProject(page, project);
});
