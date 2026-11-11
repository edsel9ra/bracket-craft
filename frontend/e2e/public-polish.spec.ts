import { expect, test } from '@playwright/test';
import { bracketId, installPublicContract, leagueId } from './publicPolishFixtures.ts';
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
