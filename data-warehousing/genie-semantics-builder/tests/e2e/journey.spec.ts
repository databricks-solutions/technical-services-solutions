import { expect, test } from '@playwright/test';
import { approveSql, createProject, createSubProject, deleteProject, e2eName, openModule, pickTables } from './helpers';

/**
 * The whole journey on bakehouse, the smallest real dataset: sources, readiness, discovery, brief,
 * design, validation, stress test, delete. Model output varies, so the checks look at structure.
 */
test.describe.configure({ mode: 'serial' });

const project = e2eName('Bakehouse');
const sub = 'Franchise revenue';

test.afterAll(async ({ browser }) => {
  const page = await browser.newPage();
  await deleteProject(page, project).catch(() => undefined);
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
  await page.getByRole('button', { name: /^Add/ }).first().click();
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
  await page.getByRole('button', { name: 'Build this' }).first().click({ timeout: 180_000 });
  await expect(page.getByRole('heading', { name: 'Untitled brief' })).toBeHidden({ timeout: 180_000 });
  await page.getByRole('button', { name: 'Save brief draft' }).click();
  await page.getByRole('button', { name: 'Confirm brief' }).click({ timeout: 120_000 });
  await expect(page.getByText('Brief confirmed')).toBeVisible({ timeout: 60_000 });
});

test('generate and validate a design', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('heading', { name: project }).click();
  await page.getByRole('link', { name: sub }).first().click();
  await openModule(page, 'Metric Designer');
  await page.getByRole('button', { name: 'Generate design' }).click();
  await expect(page.getByRole('tab', { name: 'YAML' })).toBeVisible({ timeout: 300_000 });
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
  await expect(page.getByRole('table', { name: 'Stress test results' }).getByRole('row')).toHaveCount(3);
  await expect(page.getByRole('heading', { name: 'Materialization suggestions' })).toBeVisible();
});
