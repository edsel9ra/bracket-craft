/**
 * Proyecto de preparación del arnés E2E (decisión 12, caso límite 13).
 *
 * La sesión del Workspace se crea **por la interfaz** una sola vez: no se
 * inyectan cookies a mano, porque `bc_user_id` y `bc_organization_id` las
 * escribe el cliente y una cookie fabricada dejaría de valer si la aplicación
 * cambia de nombre o de forma. El estado resultante se guarda en
 * `frontend/.auth/state.json`, **fuera** de `e2e-report/` y fuera de git, para
 * que las cookies de sesión nunca se publiquen como artefacto.
 *
 * `ensureWorkspaceSession` es también el punto de reautenticación declarada: si
 * una vista pierde la sesión, inicia sesión de nuevo en lugar de confundir la
 * redirección con un fallo del reintento.
 */

import { mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test as setup, type Page } from '@playwright/test';

import { demoCredentials, type DemoCredentials } from './demo.ts';
import {
  E2E_LABELS,
  E2E_LOCALE,
  labelText,
  localeCookie,
} from './labels.ts';

/** Estado de sesión reutilizado por las tres vistas (ignorado por git). */
export const STORAGE_STATE_PATH = fileURLToPath(new URL('../.auth/state.json', import.meta.url));

/** La preparación no se mide como escenario, pero comparte pila con él. */
const SETUP_TIMEOUT_MS = 120_000;
const READY_TIMEOUT_MS = 30_000;

function isLoginPath(url: string): boolean {
  try {
    return new URL(url).pathname.replace(/\/+$/, '') === '/login';
  } catch {
    return url.includes('/login');
  }
}

/**
 * Espera a que la aplicación esté hidratada antes de interactuar: con `nuxt
 * dev` el HTML llega del servidor antes de que los manejadores del cliente
 * existan y un clic prematuro dispararía el envío nativo del formulario. La
 * señal es el montaje de Vue en el contenedor de la aplicación, no una espera
 * fija; se usa solo en la preparación, nunca para decidir el veredicto.
 */
export async function waitForHydration(page: Page): Promise<void> {
  await page.waitForFunction(
    () => {
      const container = document.querySelector('#__nuxt');
      return container !== null && '__vue_app__' in container;
    },
    undefined,
    { timeout: SETUP_TIMEOUT_MS },
  );
}

/** Inicia sesión por la interfaz con la cuenta ficticia de desarrollo. */
export async function signIn(page: Page, credentials: DemoCredentials = demoCredentials()): Promise<void> {
  page.setDefaultNavigationTimeout(SETUP_TIMEOUT_MS);
  await page.goto('/login', { waitUntil: 'load' });
  await waitForHydration(page);
  await page.getByLabel(labelText(E2E_LABELS.loginEmail), { exact: true }).fill(credentials.email);
  await page
    .getByLabel(labelText(E2E_LABELS.loginPassword), { exact: true })
    .fill(credentials.password);
  await page
    .getByRole('button', { name: labelText(E2E_LABELS.loginSubmit), exact: true })
    .click();
  await expect(page).toHaveURL(/\/workspace(?:\?|$)/, { timeout: SETUP_TIMEOUT_MS });
}

/**
 * Abre el Workspace y, si la sesión ya no vale, se reautentica de forma
 * declarada. Termina cuando el panel privado está visible en el idioma fijado.
 */
export async function ensureWorkspaceSession(
  page: Page,
  credentials: DemoCredentials = demoCredentials(),
): Promise<void> {
  page.setDefaultNavigationTimeout(SETUP_TIMEOUT_MS);
  await page.goto('/workspace', { waitUntil: 'load' });
  if (isLoginPath(page.url())) {
    await signIn(page, credentials);
  }
  await waitForHydration(page);
  await expect(page.getByText(labelText(E2E_LABELS.workspaceReady), { exact: true })).toBeVisible({
    timeout: READY_TIMEOUT_MS,
  });
}

setup('prepara el idioma y la sesión del Workspace', async ({ page, context, baseURL }) => {
  const origin = baseURL ?? 'http://localhost:3000';
  // Playwright admite `url` o `domain`+`path`, nunca ambos en la misma cookie.
  const locale = localeCookie();
  await context.addCookies([
    { name: locale.name, value: locale.value, url: new URL('/', origin).toString() },
  ]);

  await ensureWorkspaceSession(page);

  const state = await context.storageState();
  const sessionCookie = state.cookies.find((cookie) => cookie.name === 'bc_user_id');
  const localeCookieState = state.cookies.find((cookie) => cookie.name === 'bc_locale');
  expect(sessionCookie?.value, 'the Workspace session must be present in the storage state').toBeTruthy();
  expect(localeCookieState?.value, 'the run must keep the fixed locale').toBe(E2E_LOCALE);

  await mkdir(dirname(STORAGE_STATE_PATH), { recursive: true });
  await context.storageState({ path: STORAGE_STATE_PATH });
});
