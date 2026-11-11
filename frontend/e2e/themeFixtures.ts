import { expect, type Page } from '@playwright/test';
import { publicContract } from './publicPolishFixtures.ts';

export const themeTournamentId = '03200000-0000-4000-8000-000000000000';

async function openThemePage(page: Page, path: string, origin?: string) {
  await page.goto(origin ? new URL('/', origin).href : '/');
  await page.waitForFunction(() => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__?: { config: { globalProperties: { $nuxt: { isHydrating: boolean } } } } };
    return root?.__vue_app__?.config.globalProperties.$nuxt.isHydrating === false;
  });
  await page.evaluate(async path => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__: { config: { globalProperties: { $router: { push: (path: string) => Promise<unknown> } } } } };
    await root.__vue_app__.config.globalProperties.$router.push(path);
  }, path);
}

export async function openThemeWorkspace(page: Page, origin?: string) {
  await openThemePage(page, '/workspace', origin);
  await expect(page.locator('.empty-state')).toBeVisible();
  await expect(page.locator('.tournament-card')).toHaveCount(0);
}

export async function openThemeTournament(page: Page, origin?: string) {
  await openThemePage(page, `/tournaments/${themeTournamentId}`, origin);
  await expect(page.getByRole('heading', { name: 'Torneo de aceptación 032', exact: true })).toBeVisible();
  await expect(page.locator('.player-stats-panel tbody tr')).toHaveCount(50);
  await page.locator('.player-stats-panel tbody tr').first().scrollIntoViewIfNeeded();
  await expect(page.locator('img.player-photo')).toHaveCount(0);
  await page.evaluate(() => scrollTo(0, 0));
}

export async function installThemeFixtures(page: Page) {
  const data = JSON.parse(JSON.stringify(publicContract(4)).replaceAll('03100000', '03200000')) as ReturnType<typeof publicContract>;
  data.tournament.name = 'Torneo de aceptación 032';
  data.players[0]!.photo_url = '/032-missing-photo.png';
  await page.route('**/032-missing-photo.png', route => route.fulfill({ status: 404 }));
  await page.route('**/api/v1/tournaments/public**', async route => {
    const request = route.request();
    if (request.method() !== 'GET') return route.continue();
    const url = new URL(request.url()); const endpoint = url.pathname.split('/').at(-1)!;
    const offset = Number(url.searchParams.get('offset') ?? 0);
    const body = endpoint === 'public' ? [data.tournament]
      : endpoint === 'standings' ? data.standings : endpoint === 'matches' ? data.matches
        : endpoint === 'player-stats' ? data.players.slice(offset, offset + 50)
          : endpoint === 'team-stats' ? data.teams.slice(offset, offset + 50) : data.tournament;
    await route.fulfill({ json: body, headers: { 'Access-Control-Allow-Origin': request.headers()['origin'] ?? '*', 'Access-Control-Allow-Credentials': 'true' } });
  });
  await page.route(/\/api\/v1\/tournaments(?:\?.*)?$/, async route => {
    if (route.request().method() === 'GET') await route.fulfill({ json: [], headers: { 'Access-Control-Allow-Origin': route.request().headers()['origin'] ?? '*', 'Access-Control-Allow-Credentials': 'true' } });
    else await route.continue();
  });
}
