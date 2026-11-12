import { expect, test } from '@playwright/test';
import { assertTheme, auditTheme, chooseTheme, saveThemeEvidence, waitThemeHydration } from './themeChecks.ts';
import { installThemeFixtures, openThemeTournament, themeTournamentId } from './themeFixtures.ts';

test.use({ storageState: { cookies: [], origins: [] }, reducedMotion: 'reduce', trace: 'off', video: 'off' });
test.beforeEach(async ({ page, context, baseURL }) => {
  await context.addCookies([{ name: 'bc_locale', value: 'es', url: baseURL! }]);
  await installThemeFixtures(page);
});
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'ignoreErrors' }); });

for (const width of [1440, 390, 800]) test.describe(`tema público ${width}`, () => {
  test.use({ viewport: { width, height: width === 390 ? 844 : 900 } });

  test('selector nativo, cookie anual, persistencia y conservación de formulario/foco/scroll', async ({ page, context, browser }) => {
    await page.emulateMedia({ colorScheme: 'light' }); await page.goto('/login'); await waitThemeHydration(page);
    await assertTheme(page, 'dark', 'dark');
    expect((await context.cookies()).filter(cookie => cookie.name === 'bc_theme')).toEqual([]);
    const email = page.locator('#auth-email'); await email.fill('tema-032@example.test');
    await page.waitForLoadState('networkidle');
    const requests: string[] = []; page.on('request', request => { if (request.url().includes('/api/v1/')) requests.push(request.method()); });
    const form = await page.locator('form').elementHandle();
    const select = page.locator('.theme-switcher select'); await select.focus();
    await select.press('Home'); const start = Date.now() / 1000; await select.press('ArrowDown');
    await assertTheme(page, 'light', 'light'); await expect(select).toBeFocused();
    await expect(email).toHaveValue('tema-032@example.test');
    expect(await form!.evaluate(node => node === document.querySelector('form'))).toBe(true);
    const cookie = (await context.cookies()).find(item => item.name === 'bc_theme')!;
    expect(cookie.value).toBe('light'); expect(cookie.path).toBe('/'); expect(cookie.sameSite).toBe('Lax');
    expect(cookie.expires).toBeGreaterThanOrEqual(start + 31536000 - 5);
    expect(cookie.expires).toBeLessThanOrEqual(Date.now() / 1000 + 31536000 + 5);
    expect(requests).toEqual([]);
    await page.reload(); await waitThemeHydration(page); await assertTheme(page, 'light', 'light');
    const reopened = await browser.newContext({ storageState: await context.storageState() });
    try { const tab = await reopened.newPage(); await tab.goto(new URL('/login', page.url()).href); await waitThemeHydration(tab); await assertTheme(tab, 'light', 'light'); }
    finally { await reopened.close(); }
    await page.locator('#language-select').selectOption('en');
    await expect(select.locator('option')).toHaveText(['Dark', 'Light', 'System']);
    await expect(select).toHaveAccessibleName('Theme');
    await openThemeTournament(page);
    const filter = page.locator('#public-stats-scope'); await filter.selectOption('03200000-0000-4000-8000-000000000001');
    await page.evaluate(() => scrollTo(0, 300)); const scroll = await page.evaluate(() => scrollY);
    await chooseTheme(page, 'dark'); await expect(filter).toHaveValue('03200000-0000-4000-8000-000000000001');
    expect(await page.evaluate(() => scrollY)).toBe(scroll);
  });

  test('Sistema mantiene el modal abierto, foco y segmento; el hueco flotante deja pasar clics', async ({ page }) => {
    await openThemeTournament(page);
    await chooseTheme(page, 'system');
    const trigger = page.locator('.lineup-trigger').first(); await trigger.click();
    const dialog = page.getByRole('dialog'); await expect(dialog).toBeVisible();
    const node = await dialog.elementHandle(); const scroll = await page.evaluate(() => scrollY);
    for (const scheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme: scheme }); await assertTheme(page, 'system', scheme);
      expect(await node!.evaluate(element => element === document.querySelector('dialog[open]') && element.contains(document.activeElement))).toBe(true);
      expect(await page.evaluate(() => scrollY)).toBe(scroll); await expect(dialog).toContainText(/Segmento 2|Segment 2/);
    }
    await page.keyboard.press('Escape'); await expect(dialog).not.toBeVisible(); await expect(trigger).toBeFocused();
    const gap = await page.locator('.public-preferences').evaluate(group => {
      const a = group.querySelector('.theme-switcher')!.getBoundingClientRect(); const b = group.querySelector('.language-switcher')!.getBoundingClientRect();
      if (b.top <= a.bottom) return null;
      const x = (Math.max(a.left, b.left) + Math.min(a.right, b.right)) / 2; const y = (a.bottom + b.top) / 2;
      return { blocked: group.contains(document.elementFromPoint(x, y)), gap: b.top - a.bottom };
    });
    if (gap) expect(gap.blocked).toBe(false);
  });

  test('axe sin exclusiones en portada, detalle, estadísticas y campo en ambos temas', async ({ page }, info) => {
    for (const theme of ['dark', 'light'] as const) {
      for (const route of ['/', `/tournaments/${themeTournamentId}`]) {
        if (route === '/') await page.goto('/'); else await openThemeTournament(page);
        await waitThemeHydration(page); await page.waitForLoadState('networkidle'); await chooseTheme(page, theme);
        await auditTheme(page, info, `${width}-${theme}-${route === '/' ? 'portada' : 'detalle'}`);
        if (route !== '/') {
          await page.getByRole('tab', { name: 'Estadísticas de equipos', exact: true }).click();
          await auditTheme(page, info, `${width}-${theme}-equipos`);
          await page.locator('.lineup-trigger').first().click(); await expect(page.getByRole('dialog')).toBeVisible();
          await auditTheme(page, info, `${width}-${theme}-campo`); await page.keyboard.press('Escape');
        }
      }
    }
  });
});

for (const slowdown of [1, 4]) test(`SSR claro y primer pintado con hidratación retenida, CPU ×${slowdown}`, async ({ page, context }, info) => {
  await page.goto('/login'); await waitThemeHydration(page); await chooseTheme(page, 'light');
  const session = await context.newCDPSession(page); await session.send('Emulation.setCPUThrottlingRate', { rate: slowdown });
  await page.addInitScript(() => {
    const state = window as unknown as { themeFrames: { theme: string | undefined; scheme: string; canvas: string; hydrated: boolean }[]; themePaints: { name: string; theme: string | undefined; scheme: string }[]; themeSamplingStopped: boolean };
    state.themeFrames = [];
    state.themePaints = [];
    state.themeSamplingStopped = false;
    new PerformanceObserver(list => {
      for (const entry of list.getEntries()) state.themePaints.push({ name: entry.name, theme: document.documentElement.dataset.theme, scheme: getComputedStyle(document.documentElement).colorScheme });
    }).observe({ type: 'paint', buffered: true });
    function sample() {
      const element = document.documentElement;
      if (element?.dataset.theme) {
        const nuxt = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__?: unknown };
        const style = getComputedStyle(element);
        state.themeFrames.push({ theme: element.dataset.theme, scheme: style.colorScheme, canvas: style.getPropertyValue('--color-canvas').trim(), hydrated: !!nuxt?.__vue_app__ });
      }
      if (!state.themeSamplingStopped) requestAnimationFrame(sample);
    }
    requestAnimationFrame(sample);
  });
  let release!: () => void; const held = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/*', async route => { if (route.request().resourceType() === 'script') await held; await route.continue(); });
  const warnings: string[] = []; page.on('console', message => { if (/hydration|mismatch/i.test(message.text()) && ['error', 'warning'].includes(message.type())) warnings.push(message.type()); });
  try {
    const response = await page.reload({ waitUntil: 'commit' });
    const html = await response!.text();
    expect(/<html[^>]+data-theme="light"/.test(html)).toBe(true);
    expect(/<meta[^>]+name="theme-color"[^>]+content="#f5f7ef"/.test(html)).toBe(true);
    expect((await response!.headersArray()).filter(header => header.name.toLowerCase() === 'set-cookie' && header.value.startsWith('bc_theme='))).toEqual([]);
    await page.waitForFunction(() => (window as unknown as { themeFrames: { scheme: string }[] }).themeFrames.filter(frame => frame.scheme === 'light').length >= 30);
    await page.waitForFunction(() => (window as unknown as { themePaints: { name: string }[] }).themePaints.some(paint => paint.name === 'first-contentful-paint'));
    await assertTheme(page, 'light', 'light');
    const frames = await page.evaluate(() => (window as unknown as { themeFrames: { theme: string; scheme: string; canvas: string; hydrated: boolean }[] }).themeFrames);
    expect(frames.length).toBeGreaterThanOrEqual(30); expect(frames.every(frame => frame.theme === 'light' && frame.scheme !== 'dark' && !frame.hydrated)).toBe(true);
    expect(frames.filter(frame => frame.scheme === 'light').every(frame => frame.canvas === '#f5f7ef')).toBe(true);
    const paints = await page.evaluate(() => (window as unknown as { themePaints: { name: string; theme: string; scheme: string }[] }).themePaints);
    expect(paints.every(paint => paint.theme === 'light' && paint.scheme === 'light')).toBe(true);
    release(); await waitThemeHydration(page);
    await assertTheme(page, 'light', 'light'); expect(warnings).toEqual([]);
    const allFrames = await page.evaluate(() => new Promise<typeof frames>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => {
      const state = window as unknown as { themeFrames: typeof frames; themeSamplingStopped: boolean };
      state.themeSamplingStopped = true; resolve(state.themeFrames);
    }))));
    expect(allFrames.some(frame => frame.hydrated)).toBe(true);
    expect(allFrames.every(frame => frame.theme === 'light' && frame.scheme !== 'dark')).toBe(true);
    expect(allFrames.filter(frame => frame.scheme === 'light').every(frame => frame.canvas === '#f5f7ef')).toBe(true);
    await saveThemeEvidence(info, `initial-frames-cpu-${slowdown}`, allFrames);
    await saveThemeEvidence(info, `initial-paints-cpu-${slowdown}`, paints);
  } finally { release(); await page.unrouteAll({ behavior: 'ignoreErrors' }); await session.detach(); }
});

test('SSR concurrente aislado, cookie inválida no reparada y persistencia bloqueada', async ({ page, context, browser, baseURL }) => {
  const responses = await Promise.all(['light', 'dark', 'unknown'].map(value => context.request.get('/login', { headers: { Cookie: `bc_locale=es; bc_theme=${value}` } })));
  for (const [index, response] of responses.entries()) {
    const html = await response.text(); const theme = /<html[^>]+data-theme="([^"]+)"/.exec(html)?.[1];
    expect(theme).toBe(index === 0 ? 'light' : 'dark');
    expect(response.headersArray().filter(header => header.name.toLowerCase() === 'set-cookie' && header.value.startsWith('bc_theme='))).toEqual([]);
  }
  await context.addCookies([{ name: 'bc_theme', value: 'unknown', url: baseURL! }]);
  await page.goto('/login'); await waitThemeHydration(page); await assertTheme(page, 'dark', 'dark');
  expect((await context.cookies()).find(cookie => cookie.name === 'bc_theme')?.value).toBe('unknown');
  const blocked = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  try {
    await blocked.addInitScript(() => {
      const cookie = Object.getOwnPropertyDescriptor(Document.prototype, 'cookie')!;
      Object.defineProperty(document, 'cookie', { get() { return cookie.get!.call(document); }, set(value: string) { if (value.startsWith('bc_theme=')) throw new DOMException('Blocked', 'SecurityError'); cookie.set!.call(document, value); } });
    });
    const tab = await blocked.newPage(); await tab.goto(new URL('/login', baseURL!).href); await waitThemeHydration(tab);
    await chooseTheme(tab, 'light'); await assertTheme(tab, 'light', 'light');
    expect((await blocked.cookies()).filter(cookie => cookie.name === 'bc_theme')).toEqual([]);
    await tab.reload(); await waitThemeHydration(tab); await assertTheme(tab, 'dark', 'dark');
  } finally { await blocked.close(); }
});
