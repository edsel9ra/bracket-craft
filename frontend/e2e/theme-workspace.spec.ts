import { expect, test } from '@playwright/test';
import { assertTheme, auditTheme, chooseTheme, waitThemeHydration } from './themeChecks.ts';
import { installThemeFixtures, openThemeWorkspace } from './themeFixtures.ts';

test.use({ reducedMotion: 'reduce', trace: 'off', video: 'off' });
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'ignoreErrors' }); });

for (const width of [1440, 390, 800]) test(`Workspace ${width}: selector, cookie, sesión, IDs únicos y axe en ambos temas`, async ({ page, context }, info) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
  await context.clearCookies({ name: 'bc_theme' }); await installThemeFixtures(page);
  await openThemeWorkspace(page); await waitThemeHydration(page); await expect(page).toHaveURL(/\/workspace$/);
  await page.waitForLoadState('networkidle');
  const ids = await page.locator('select[id]').evaluateAll(elements => elements.map(element => element.id));
  expect(new Set(ids).size).toBe(ids.length);
  const user = (await context.cookies()).find(cookie => cookie.name === 'bc_user_id')?.value;
  expect(user).toBeTruthy();
  const requests: string[] = []; page.on('request', request => { if (request.url().includes('/api/v1/')) requests.push(request.method()); });
  for (const theme of ['light', 'dark'] as const) {
    await chooseTheme(page, theme); await assertTheme(page, theme, theme);
    expect((await context.cookies()).find(cookie => cookie.name === 'bc_theme')?.value).toBe(theme);
    expect((await context.cookies()).find(cookie => cookie.name === 'bc_user_id')?.value).toBe(user);
    await auditTheme(page, info, `workspace-${width}-${theme}`);
  }
  expect(requests).toEqual([]);
  await chooseTheme(page, 'light'); await page.reload(); await waitThemeHydration(page); await assertTheme(page, 'light', 'light');
  await expect(page).toHaveURL(/\/workspace$/);
  expect((await context.cookies()).find(cookie => cookie.name === 'bc_user_id')?.value).toBe(user);
  await chooseTheme(page, 'system');
  for (const colorScheme of ['dark', 'light'] as const) { await page.emulateMedia({ colorScheme }); await assertTheme(page, 'system', colorScheme); }
  if (width === 390) await page.locator('.workspace-menu-toggle').click();
});
