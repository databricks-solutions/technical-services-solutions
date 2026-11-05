import { expect } from '@playwright/test';
import type { Page } from '@playwright/test';

/** A name the scenarios can find and delete later. */
export const e2eName = (what: string) => `E2E ${what} ${new Date().toISOString().slice(0, 16).replace('T', ' ')}`;

/** Approves the SQL modal that every write shows, after checking it lists SQL. */
export async function approveSql(page: Page, okText: RegExp | string) {
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(/SQL to run/).first()).toBeVisible();
  await dialog.getByRole('button', { name: okText }).click();
  await expect(dialog).toBeHidden({ timeout: 120_000 });
}

export async function createProject(page: Page, name: string, goal: string) {
  await page.goto('/');
  await page.getByRole('button', { name: 'New project' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel(/Name/).fill(name);
  await dialog.getByLabel('Business goal').fill(goal);
  await dialog.getByRole('button', { name: 'Create project' }).click();
  await expect(page.getByRole('heading', { name })).toBeVisible();
}

export async function createSubProject(page: Page, name: string) {
  await page.getByRole('button', { name: 'New sub-project' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel(/Name/).fill(name);
  await dialog.getByRole('button', { name: 'Create sub-project' }).click();
  // A new sub-project opens on Sources & Readiness.
  await expect(page.getByRole('heading', { name: 'Sources & Readiness' })).toBeVisible();
}

/** Ticks tables in the Unity Catalog tree: catalog, then schema, then each table. */
export async function pickTables(page: Page, catalog: string, schema: string, tables: string[]) {
  const tree = page.getByRole('list', { name: 'Unity Catalog' });
  await tree.getByRole('button', { name: catalog, exact: true }).click();
  await tree.getByRole('button', { name: schema, exact: true }).click();
  const group = page.getByRole('group', { name: `Tables in ${catalog}.${schema}` });
  for (const t of tables) await group.getByRole('checkbox', { name: t, exact: true }).check();
}

export async function openModule(page: Page, label: string) {
  await page.getByRole('navigation', { name: 'Semantics Builder' }).getByRole('link', { name: label }).click();
  await expect(page.getByRole('heading', { name: label, level: 2 })).toBeVisible();
}

/** Deletes a project through its page, with the sandbox cleanup ticked. */
export async function deleteProject(page: Page, name: string) {
  await page.goto('/');
  await page.getByRole('heading', { name }).click();
  await page.getByRole('button', { name: 'Delete project' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('textbox').fill(name);
  const cleanup = dialog.getByRole('checkbox');
  if (await cleanup.count()) await cleanup.first().check();
  await dialog.getByRole('button', { name: /Delete project/ }).click();
  await expect(page.getByRole('heading', { name })).toBeHidden();
}
