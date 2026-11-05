import { expect, test } from '@playwright/test';

// Fast checks that need no model calls or warehouse time.
test('the projects page loads with the shell and the theme switch', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Semantics Builder' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Projects', level: 2 })).toBeVisible();
  await page.getByLabel('Theme').click();
  await page.getByRole('option', { name: 'Light' }).click();
  await expect(page.getByLabel('Theme')).toContainText('Light');
});

test('a new project needs a name', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'New project' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'Create project' }).click();
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(dialog).toBeHidden();
});

test('an unknown project shows an error, not a blank page', async ({ page }) => {
  await page.goto('/projects/00000000-0000-0000-0000-000000000000');
  await expect(page.getByText(/not found|cannot|could not/i).first()).toBeVisible();
});
