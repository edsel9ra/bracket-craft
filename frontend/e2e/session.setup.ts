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

import { expect, test as setup } from '@playwright/test';

import { ensureWorkspaceSession } from './workspaceSession.ts';
import {
  E2E_LOCALE,
  localeCookie,
} from './labels.ts';

/** Estado de sesión reutilizado por las tres vistas (ignorado por git). */
export const STORAGE_STATE_PATH = fileURLToPath(new URL('../.auth/state.json', import.meta.url));

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
