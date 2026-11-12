import { mkdir, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { expect, test } from '@playwright/test';
import { installThemeFixtures, openThemeTournament, openThemeWorkspace, themeTournamentId } from './themeFixtures.ts';
import { waitThemeHydration } from './themeChecks.ts';

test('@capture deterministic theme surfaces and register R before comparison', async ({ playwright }, info) => {
  const origin = process.env.THEME_CAPTURE_URL;
  const output = process.env.THEME_CAPTURE_OUTPUT;
  const operation = process.env.THEME_OPERATION_PATH;
  expect(origin).toBeTruthy(); expect(output).toBeTruthy();
  expect(operation).toMatch(/^\/workspace\/matches\/[0-9a-f-]+$/);
  const rows = [];
  for (const locale of ['es', 'en']) for (const width of [1440, 390, 800]) {
    for (const [surface, route] of [['portada', '/'], ['detalle', `/tournaments/${themeTournamentId}`], ['workspace', '/workspace'], ['operacion', operation!]] as const) {
      const workspace = surface === 'workspace' || surface === 'operacion';
      const browser = await playwright.chromium.launch({ headless: true, args: ['--disable-gpu', '--disable-gpu-rasterization', '--disable-partial-raster', '--force-color-profile=srgb', '--force-device-scale-factor=2'] });
      const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 900 }, deviceScaleFactor: 1, reducedMotion: 'reduce', timezoneId: 'UTC', storageState: workspace ? '.auth/state.json' : { cookies: [], origins: [] } });
      try {
        await context.clearCookies({ name: 'bc_theme' });
        await context.addCookies([{ name: 'bc_locale', value: locale, url: origin! }]);
        const page = await context.newPage(); await installThemeFixtures(page);
        if (surface === 'detalle') await openThemeTournament(page, origin!);
        else if (surface === 'workspace') await openThemeWorkspace(page, origin!);
        else await page.goto(new URL(route, origin!).href);
        await waitThemeHydration(page);
        if (workspace) await expect(page).toHaveURL(new RegExp(`${route}$`));
        if (surface === 'operacion') await expect(page.locator('.operation-grid')).toBeVisible();
        await page.waitForLoadState('networkidle'); await page.evaluate(() => document.fonts.ready); await page.mouse.move(0, 0);
        await page.addStyleTag({ content: '#nuxt-devtools-container,#nuxt-devtools-anchor{display:none!important}*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}' });
        await page.waitForFunction(() => !document.querySelector('[class*="-leave-active"],[class*="-enter-active"]'));
        for (const open of workspace && width === 390 ? [false, true] : [false]) {
          if (open) await page.locator('.workspace-menu-toggle').click();
          await page.evaluate(() => { scrollTo(0, 0); return new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))); });
          const control = workspace ? page.locator(open ? '.workspace-mobile-menu' : '.workspace-desktop-controls') : page.locator('.public-preferences');
          const region = workspace && width === 390 && !open ? null : await control.boundingBox();
          const key = `${surface}-${locale}-${width}${open ? '-menu' : ''}`; const path = `${output}/${key}.png`;
          await mkdir(dirname(path), { recursive: true });
          rows.push({ key, region, route, width, locale, browser: browser.version() });
          await writeFile(`${output}/manifest.json`, JSON.stringify(rows, null, 2));
          await page.screenshot({ path, animations: 'disabled' });
        }
      } finally { await context.close(); await browser.close(); }
    }
  }
  await info.attach('capture-metadata', { body: JSON.stringify(rows), contentType: 'application/json' });
});
