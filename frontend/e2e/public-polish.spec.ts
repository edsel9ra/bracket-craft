import { expect, test } from '@playwright/test';
import { bracketId, installPublicContract, leagueId } from './publicPolishFixtures.ts';
import { chooseTheme } from './themeChecks.ts';
import { assertNoDocumentOverflow, measureBracket, measureColumns, measureSticky, openPublicContract, saveMeasurements } from './publicPolishChecks.ts';

test.use({ storageState: { cookies: [], origins: [] }, reducedMotion: 'reduce', trace: 'off' });

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }, { width: 800, height: 900 }]) {
  test.describe(`público anónimo ${viewport.width}`, () => {
    test.use({ viewport });

    test('prioridades, filtros, continuación, estados y campos públicos', async ({ page, context }, info) => {
      expect((await context.cookies()).length).toBe(0);
      const contract = await installPublicContract(page);
      await openPublicContract(page);
      const measurements: unknown[] = [];
      for (const [tab, selector, labels] of [
        ['Estadísticas de jugadores', '.player-stats-panel', ['Posición', 'Jugador', 'Goles']],
        ['Estadísticas de equipos', '.team-stats-panel', ['Posición', 'Equipos', 'GF']],
      ] as const) {
        await page.getByRole('tab', { name: tab, exact: true }).click();
        const panel = page.locator(selector);
        await expect(panel.locator('tbody tr')).toHaveCount(50);
        await expect(panel).toContainText('50 filas mostradas');
        const columns = await measureColumns(panel);
        expect(columns.slice(0, 3)).toEqual(labels.map(label => ({ label, complete: true })));
        measurements.push({ tab, columns, sticky: await measureSticky(panel.locator('.scroll-content')) });
        expect(await panel.locator('tbody tr td:first-child').allTextContents()).toEqual(contract.data[selector.includes('player') ? 'players' : 'teams'].slice(0, 50).map(row => String(row.rank)));
        contract.state.hold = true;
        const more = panel.locator('button.load-more');
        await more.click();
        await expect(more).toBeDisabled();
        await expect.poll(() => contract.requests.some(row => row.offset === 50 && row.path.endsWith(selector.includes('player') ? 'player-stats' : 'team-stats'))).toBe(true);
        contract.state.hold = false; contract.state.release();
        await expect(panel.locator('tbody tr')).toHaveCount(53);
        await expect(panel).toContainText('53 filas mostradas');
        await expect(more).toHaveCount(0);
        expect(await panel.locator('tbody tr td:first-child').allTextContents()).toEqual(contract.data[selector.includes('player') ? 'players' : 'teams'].map(row => String(row.rank)));
      }
      const scope = page.locator('#public-stats-scope');
      await expect(scope).toHaveValue('');
      await scope.selectOption(leagueId);
      for (const tab of ['Estadísticas de jugadores', 'Estadísticas de equipos']) {
        await page.getByRole('tab', { name: tab, exact: true }).click();
        await expect(page.locator('.public-stats tbody tr')).toHaveCount(3);
      }
      await scope.selectOption('');
      await expect(page.locator('.team-stats-panel tbody tr')).toHaveCount(50);
      expect(contract.requests.filter(row => row.path.endsWith('team-stats')).some(row => row.scope === leagueId)).toBe(true);
      contract.state.mode = 'empty';
      await scope.selectOption(bracketId);
      for (const tab of ['Estadísticas de jugadores', 'Estadísticas de equipos']) {
        await page.getByRole('tab', { name: tab, exact: true }).click();
        await expect(page.locator('.public-stats tbody tr')).toHaveCount(0);
        await expect(page.locator('.public-stats')).toContainText('0 filas mostradas');
      }
      contract.state.mode = 'error';
      await scope.selectOption('');
      await expect(page.getByRole('alert').first()).toBeVisible();
      await expect(page.locator('.public-stats tbody tr')).toHaveCount(0);
      contract.state.mode = 'normal';
      await scope.selectOption(leagueId);
      await expect(page.locator('.team-stats-panel tbody tr')).toHaveCount(3);
      await page.getByRole('tab', { name: 'Estadísticas de jugadores', exact: true }).click();
      await expect(page.locator('.player-photo--initials').first()).toBeVisible();
      expect(contract.requests.every(row => row.method === 'GET' && row.path.startsWith('/api/v1/tournaments/public/'))).toBe(true);
      await assertNoDocumentOverflow(page);
      await saveMeasurements(info, 'public-measurements', measurements);
    });

    test('anclas, clasificación, nombres largos y formación publicada con foco', async ({ page }, info) => {
      await installPublicContract(page);
      await page.goto('/');
      await page.waitForFunction(() => '__vue_app__' in document.querySelector('#__nuxt')!);
      const browse = page.locator('a[href="#public-tournaments"]');
      expect((await browse.boundingBox())!.y).toBeLessThan(viewport.height);
      await expect(page.locator('.example-score')).toHaveText('Marcador de ejemplo');
      await browse.click();
      await expect(page.locator('#public-tournaments')).toBeFocused();
      await page.locator('.tournament-card').first().click();
      await expect(page.locator('.player-stats-panel tbody tr')).toHaveCount(50);
      const nav = page.locator('.public-section-nav');
      expect((await nav.boundingBox())!.y).toBeLessThan(viewport.height);
      for (const target of ['public-results', 'public-stats', 'public-teams']) {
        await page.locator(`a[href="#${target}"]`).click();
        await expect(page.locator(`#${target}`)).toBeFocused();
        expect((await page.locator(`#${target}`).boundingBox())!.y).toBeLessThan(viewport.height);
      }
      await expect(page.locator('.public-team-list li')).toHaveCount(53);
      const region = page.locator('.phase-selected .scroll-content').first();
      const sticky = await measureSticky(region);
      const trigger = page.locator('.lineup-trigger').first();
      await trigger.click();
      const dialog = page.getByRole('dialog');
      await expect(dialog).toBeVisible();
      const box = (await dialog.boundingBox())!;
      expect(box.width).toBeLessThanOrEqual(viewport.width); expect(box.height).toBeLessThanOrEqual(viewport.height);
      await expect(dialog.locator('.team-pitch')).toHaveCount(1);
      await dialog.locator('.textual-equivalent summary').click();
      await expect(dialog.locator('.textual-equivalent-list')).toBeVisible();
      await expect(dialog).toContainText('Segmento 2');
      await page.keyboard.press('Escape');
      await expect(dialog).not.toBeVisible();
      await expect(trigger).toBeFocused();
      expect(await page.locator('.phase-selected .match-card').count()).toBeGreaterThan(0);
      await assertNoDocumentOverflow(page);
      await saveMeasurements(info, 'navigation-measurements', { sticky, dialog: box });
    });

    for (const theme of ['dark', 'light'] as const) test(`cronología pública ${theme}: orden, segmentos, foco y sin desbordamiento`, async ({ page }, info) => {
      const contract = await installPublicContract(page);
      await openPublicContract(page);
      await chooseTheme(page, theme);
      const trigger = page.locator('.timeline-trigger').first();
      await trigger.click();
      const dialog = page.getByRole('dialog');
      await expect(dialog).toBeVisible();
      await expect(dialog.locator('.timeline-close')).toBeFocused();
      await expect(dialog.locator('.timeline-event')).toHaveCount(5);
      await expect(dialog.locator('.timeline-separator')).toHaveText(['Segmento 1', 'Segmento 2']);
      expect(await dialog.locator('.timeline-minute').allTextContents()).toEqual(["23'", "45+2'", "52'", "60'", "88'"]);
      await expect(dialog).toContainText('Gol en propia meta');
  await expect(dialog.locator('.timeline-event').nth(2)).toContainText('A favor de: ');
      await expect(dialog).toContainText('Roja por doble amarilla');
      await expect(dialog).toContainText('Sale: Nombre Apellido Extremadamente Largo Que Sale Del Campo');
      await expect(dialog).toContainText('Entra: Nombre Apellido Extremadamente Largo Que Entra Al Campo');
      await expect(dialog).not.toContainText('#');
      const box = (await dialog.boundingBox())!;
      expect(box.width).toBeLessThanOrEqual(viewport.width); expect(box.height).toBeLessThanOrEqual(viewport.height);
      expect(await dialog.locator('.timeline-dialog-content').evaluate(e => e.scrollWidth <= e.clientWidth)).toBe(true);
      expect(contract.requests.filter(row => row.path.endsWith('/timeline'))).toHaveLength(1);
      await page.keyboard.press('Escape');
      await expect(dialog).not.toBeVisible();
      await expect(trigger).toBeFocused();
      await assertNoDocumentOverflow(page);
      await saveMeasurements(info, `timeline-measurements-${theme}`, { theme, dialog: box });
    });

    for (const theme of ['dark', 'light'] as const) test(`ficha pública ${theme}: enlace desde estadísticas, cabecera, totales, trayectoria y foco`, async ({ page }, info) => {
      const contract = await installPublicContract(page);
      await openPublicContract(page);
      await chooseTheme(page, theme);
      const links = page.locator('.player-stats-panel .stats-player-link');
      await expect(links).toHaveCount(1);
      await links.click();
      await expect(page).toHaveURL(/\/players\/03100000-0000-4000-8000-000000002001$/);
      await expect(page.getByRole('heading', { level: 1, name: 'Global Apellido Extenso 1' })).toBeVisible();
      await expect(page.locator('.profile-photo--initials')).toHaveText('GA');
      await expect(page.locator('.profile-total dd')).toHaveText(['6', '12', '3', '0', '0']);
      await expect(page.locator('.profile-content tbody tr')).toHaveCount(3);
      await expect(page.locator('.profile-content')).not.toContainText('#');
      const tournamentLink = page.locator('.profile-content tbody .profile-link').first();
      await tournamentLink.focus();
      await page.keyboard.press('Tab');
      await page.keyboard.press('Shift+Tab');
      await expect(tournamentLink).toBeFocused();
      expect(await tournamentLink.evaluate(e => getComputedStyle(e).outlineStyle)).toBe('solid');
      const hero = (await page.locator('.profile-hero').boundingBox())!;
      expect(hero.width).toBeLessThanOrEqual(viewport.width);
      await assertNoDocumentOverflow(page);
      expect(contract.requests.filter(row => row.path.includes('/public/players/'))).toHaveLength(1);
      await saveMeasurements(info, `profile-measurements-${theme}`, { theme, hero });
    });

    test('ficha pública desde la cronología: navegar cierra el diálogo', async ({ page }) => {
      await installPublicContract(page);
      await openPublicContract(page);
      await page.locator('.timeline-trigger').first().click();
      const dialog = page.getByRole('dialog');
      await expect(dialog).toBeVisible();
      await expect(dialog.locator('.timeline-player-link')).toHaveCount(1);
      await dialog.locator('.timeline-player-link').click();
      await expect(page).toHaveURL(/\/players\/03100000-0000-4000-8000-000000003023$/);
      await expect(dialog).not.toBeVisible();
      await expect(page.getByRole('heading', { level: 1, name: 'Nombre Publicado 23' })).toBeVisible();
      await assertNoDocumentOverflow(page);
    });

    test('plazas sin resolver muestran su origen y el equipo al llenarse (040)', async ({ page }, info) => {
      const { data } = await installPublicContract(page);
      const rows = data.matches.filter(row => row.stage_id === bracketId);
      Object.assign(rows[2]!, {
        home_team_id: null, home_team_name: null, home_team_short_code: null, status: 'scheduled', home_score: null, away_score: null,
        winner_team_id: null, resolution_type: null, away_team_id: null, away_team_name: null, away_team_short_code: null,
        home_origin: { kind: 'group_position', group_name: 'A', position: 1, ordinal: null },
        away_origin: { kind: 'best_of_position', group_name: null, position: 3, ordinal: 1 },
      });
      await openPublicContract(page);
      await page.locator('.phase-chip').filter({ hasText: 'Eliminatoria' }).click();
      await expect(page.locator('.bracket-grid.measured')).toBeVisible();
      const slot = page.locator('.bracket-match').nth(2);
      await expect(slot).toContainText('1.º del grupo A');
      await expect(slot).toContainText('Mejor 3.º n.º 1');
      await expect(page.locator('.bracket-match').first()).not.toContainText('del grupo');
      await assertNoDocumentOverflow(page);
      await saveMeasurements(info, 'bracket-origins', { width: viewport.width });
    });

    test('ganador repetido o destino ambiguo no inventa conectores', async ({ page }) => {
      const { data } = await installPublicContract(page);
      const rows = data.matches.filter(row => row.stage_id === bracketId);
      const source = rows[0]!;
      Object.assign(rows[1]!, { home_team_id: source.home_team_id, winner_team_id: source.winner_team_id, status: 'finished', home_score: 2, away_score: 0 });
      rows[5]!.away_team_id = source.winner_team_id;
      await openPublicContract(page);
      await page.locator('.phase-chip').filter({ hasText: 'Eliminatoria' }).click();
      await expect(page.locator('.bracket-grid.measured')).toBeVisible();
      await measureBracket(page, rows);
      await expect(page.locator(`path[data-source-id="${source.id}"]`)).toHaveCount(0);
      await expect(page.locator(`path[data-source-id="${rows[1]!.id}"]`)).toHaveCount(0);
    });

    for (const size of [4, 8, 16, 5]) test(`cuadro ${size}, relaciones únicas y geometría`, async ({ page }, info) => {
      const { data } = await installPublicContract(page, size);
      await openPublicContract(page);
      await page.locator('.phase-chip').filter({ hasText: 'Eliminatoria' }).click();
      await expect(page.locator('.bracket-grid.measured')).toBeVisible();
      const rows = data.matches.filter(row => row.stage_id === bracketId);
      const measured = await measureBracket(page, rows);
      const diagram = page.locator('.bracket-grid').locator('..');
      if (await diagram.evaluate(e => e.scrollWidth > e.clientWidth)) {
        await expect(diagram.locator('..').locator('.scroll-hint')).toBeVisible();
        await diagram.focus(); await diagram.press('ArrowRight');
        await expect.poll(() => diagram.evaluate(e => e.scrollLeft)).toBeGreaterThan(0);
        await diagram.evaluate(e => { e.scrollLeft = e.scrollWidth; });
      }
      await expect(page.locator('.bracket-round-heading').last()).toHaveText('Final');
      if (size !== 5) {
        await expect(page.locator('.bracket-match').filter({ hasText: 'Walkover' })).toHaveCount(1);
        await expect(page.locator('.bracket-team.winner').first()).toContainText('Ganador');
        await expect(page.locator('.bracket-match strong').filter({ hasText: /^-$/ }).first()).toBeVisible();
      }
      await assertNoDocumentOverflow(page);
      await saveMeasurements(info, 'bracket-measurements', { size, ...measured });
    });
  });
}
