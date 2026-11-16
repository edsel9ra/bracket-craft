import { expect, test, type Page } from '@playwright/test';
import { auditTheme, waitThemeHydration } from './themeChecks.ts';
import { assertNoDocumentOverflow } from './publicPolishChecks.ts';

// Spec 039 T9: las tres pantallas con un contrato ficticio, sin escribir en la API.
const TOKEN = 'T9_token-0123456789abcdefghijklmnopqrstuvw';
const USER_ID = '00000000-0000-4000-8000-000000000039';

type Call = { method: string; path: string; body: unknown };

async function installPasswordContract(page: Page, options: { hasPassword?: boolean } = {}) {
  const calls: Call[] = [];
  const state = { forgot: 202, reset: 204 as number, resetDetail: '', change: 204 as number, changeDetail: '' };
  await page.route('**/api/v1/auth/password**', async route => {
    const request = route.request();
    if (request.method() === 'OPTIONS') return route.continue();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    calls.push({ method: request.method(), path, body: request.postDataJSON() ?? null });
    if (path === '/auth/password') return route.fulfill({ json: { has_password: options.hasPassword !== false } });
    if (path === '/auth/password/forgot') return route.fulfill({ status: state.forgot, json: {} });
    if (path === '/auth/password/reset') {
      return state.reset === 204 ? route.fulfill({ status: 204 }) : route.fulfill({ status: state.reset, json: { detail: state.resetDetail } });
    }
    if (path === '/auth/password/change') {
      return state.change === 204 ? route.fulfill({ status: 204 }) : route.fulfill({ status: state.change, json: { detail: state.changeDetail } });
    }
    return route.fulfill({ status: 404, json: { detail: 'Not Found' } });
  });
  return { calls, state };
}

test.use({ storageState: { cookies: [], origins: [] }, reducedMotion: 'reduce', trace: 'off', video: 'off' });
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'ignoreErrors' }); });

for (const width of [1440, 390]) for (const theme of ['dark', 'light'] as const) test.describe(`contraseña ${width} ${theme}`, () => {
  test.use({ viewport: { width, height: width === 390 ? 844 : 900 } });
  test.beforeEach(async ({ context, baseURL }) => {
    await context.addCookies([
      { name: 'bc_locale', value: 'es', url: baseURL! },
      { name: 'bc_theme', value: theme, url: baseURL! },
      { name: 'bc_csrf_token', value: 'e2e-csrf-token-039', url: baseURL! },
    ]);
  });

  test('login enlaza a la recuperación y esta confirma siempre igual', async ({ page }, info) => {
    const contract = await installPasswordContract(page);
    await page.goto('/login');
    await waitThemeHydration(page);
    await page.getByRole('link', { name: '¿Olvidaste tu contraseña?' }).click();
    await expect(page).toHaveURL(/\/password\/forgot$/);
    await expect(page.getByRole('heading', { level: 1, name: 'Recuperar la contraseña' })).toBeVisible();
    await page.getByRole('button', { name: 'Enviar instrucciones' }).click();
    await expect(page.getByText('Este campo es obligatorio.')).toBeVisible();
    expect(contract.calls).toEqual([]);
    await page.getByLabel('Email').fill('  nadia@example.com ');
    await page.getByRole('button', { name: 'Enviar instrucciones' }).click();
    const sent = page.getByTestId('password-forgot-sent');
    await expect(sent).toContainText('Si el correo corresponde a una cuenta');
    await expect(sent).toBeFocused();
    expect(contract.calls).toEqual([{ method: 'POST', path: '/auth/password/forgot', body: { email: 'nadia@example.com' } }]);
    await assertNoDocumentOverflow(page);
    await auditTheme(page, info, `password-forgot-${width}-${theme}`);
  });

  test('el enlace lee el token del fragmento, lo retira y vuelve al login', async ({ page }, info) => {
    const contract = await installPasswordContract(page);
    await page.goto(`/password/reset#${TOKEN}`);
    await waitThemeHydration(page);
    await expect.poll(() => page.evaluate(() => location.hash)).toBe('');
    await expect(page).toHaveURL(/\/password\/reset$/);
    await page.locator('#password-reset-new').fill('corta');
    await page.getByLabel('Repite la contraseña nueva').fill('otra');
    await page.getByRole('button', { name: 'Guardar contraseña' }).click();
    await expect(page.getByText('Debe tener al menos 8 caracteres.')).toBeVisible();
    await expect(page.getByText('Las contraseñas no coinciden.')).toBeVisible();
    expect(contract.calls).toEqual([]);
    await auditTheme(page, info, `password-reset-${width}-${theme}`);

    contract.state.reset = 400;
    contract.state.resetDetail = 'PASSWORD_REUSED';
    await page.locator('#password-reset-new').fill('nueva-contraseña-039');
    await page.getByLabel('Repite la contraseña nueva').fill('nueva-contraseña-039');
    await page.getByRole('button', { name: 'Guardar contraseña' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'distinta de la actual' })).toBeFocused();

    contract.state.reset = 204;
    await page.getByRole('button', { name: 'Guardar contraseña' }).click();
    await expect(page).toHaveURL(/\/login\?notice=password-reset$/);
    await expect(page.getByRole('status').filter({ hasText: 'Tu contraseña se cambió' })).toBeVisible();
    expect(contract.calls.at(-1)).toEqual({ method: 'POST', path: '/auth/password/reset', body: { token: TOKEN, new_password: 'nueva-contraseña-039' } });
    await assertNoDocumentOverflow(page);
  });

  test('un enlace inválido o ausente ofrece pedir otro', async ({ page }) => {
    const contract = await installPasswordContract(page);
    await page.goto('/password/reset');
    await waitThemeHydration(page);
    await expect(page.getByTestId('password-reset-invalid')).toHaveText('El enlace no es válido o ha caducado.');
    await page.getByRole('link', { name: 'Pedir un enlace nuevo' }).click();
    await expect(page).toHaveURL(/\/password\/forgot$/);

    await page.goto(`/password/reset#${TOKEN}`);
    await waitThemeHydration(page);
    contract.state.reset = 400;
    contract.state.resetDetail = 'PASSWORD_RESET_INVALID';
    await page.locator('#password-reset-new').fill('nueva-contraseña-039');
    await page.getByLabel('Repite la contraseña nueva').fill('nueva-contraseña-039');
    await page.getByRole('button', { name: 'Guardar contraseña' }).click();
    await expect(page.getByTestId('password-reset-invalid')).toBeFocused();
    await assertNoDocumentOverflow(page);
  });

  test('cambio desde la cuenta: actual incorrecta, éxito y cuenta solo-Google', async ({ page, context, baseURL }, info) => {
    await context.addCookies([{ name: 'bc_user_id', value: USER_ID, url: baseURL! }]);
    const contract = await installPasswordContract(page);
    await page.goto('/account/password');
    await waitThemeHydration(page);
    await expect(page.getByRole('heading', { level: 1, name: 'Cambiar la contraseña' })).toBeVisible();
    await page.getByLabel('Contraseña actual').fill('antigua-039');
    await page.locator('#password-change-new').fill('nueva-contraseña-039');
    await page.getByLabel('Repite la contraseña nueva').fill('nueva-contraseña-039');
    contract.state.change = 400;
    contract.state.changeDetail = 'CURRENT_PASSWORD_INVALID';
    await page.getByRole('button', { name: 'Cambiar contraseña' }).click();
    await expect(page.getByLabel('Contraseña actual')).toBeFocused();
    await expect(page.getByText('La contraseña actual no es correcta.')).toBeVisible();

    contract.state.change = 204;
    await page.getByLabel('Contraseña actual').fill('antigua-0390');
    await page.getByRole('button', { name: 'Cambiar contraseña' }).click();
    await expect(page.getByTestId('password-changed')).toBeFocused();
    await expect(page.getByLabel('Contraseña actual')).toHaveValue('');
    expect(contract.calls.at(-1)).toEqual({
      method: 'POST', path: '/auth/password/change',
      body: { current_password: 'antigua-0390', new_password: 'nueva-contraseña-039' },
    });
    await assertNoDocumentOverflow(page);
    await auditTheme(page, info, `password-change-${width}-${theme}`);

    await page.unrouteAll({ behavior: 'ignoreErrors' });
    await installPasswordContract(page, { hasPassword: false });
    await page.reload();
    await waitThemeHydration(page);
    await expect(page.getByTestId('password-google-only')).toContainText('entra con Google');
    await expect(page.getByLabel('Contraseña actual')).toHaveCount(0);
  });
});
