import { expect, type Page } from '@playwright/test';
import { demoCredentials, type DemoCredentials } from './demo.ts';
import { E2E_LABELS, labelText } from './labels.ts';

const SETUP_TIMEOUT_MS = 120_000;

export async function waitForHydration(page: Page): Promise<void> {
  await page.waitForFunction(() => {
    const container = document.querySelector('#__nuxt');
    return container !== null && '__vue_app__' in container;
  }, undefined, { timeout: SETUP_TIMEOUT_MS });
}

export async function signIn(page: Page, credentials: DemoCredentials = demoCredentials()): Promise<void> {
  page.setDefaultNavigationTimeout(SETUP_TIMEOUT_MS);
  await page.goto('/login', { waitUntil: 'load' });
  await waitForHydration(page);
  await page.getByLabel(labelText(E2E_LABELS.loginEmail), { exact: true }).fill(credentials.email);
  await page.getByLabel(labelText(E2E_LABELS.loginPassword), { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: labelText(E2E_LABELS.loginSubmit), exact: true }).click();
  await expect(page).toHaveURL(/\/workspace(?:\?|$)/, { timeout: SETUP_TIMEOUT_MS });
}

export async function ensureWorkspaceSession(page: Page, credentials: DemoCredentials = demoCredentials()): Promise<void> {
  page.setDefaultNavigationTimeout(SETUP_TIMEOUT_MS);
  await page.goto('/workspace', { waitUntil: 'load' });
  if (new URL(page.url()).pathname.replace(/\/+$/, '') === '/login') await signIn(page, credentials);
  await waitForHydration(page);
  await expect(page.getByText(labelText(E2E_LABELS.workspaceReady), { exact: true })).toBeVisible({ timeout: 30_000 });
}
