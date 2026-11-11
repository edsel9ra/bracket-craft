import { writeFile } from 'node:fs/promises';
import { expect, type Locator, type Page, type TestInfo } from '@playwright/test';
import type { PublicMatch } from '../app/utils/publicTournament.ts';

export async function saveMeasurements(info: TestInfo, name: string, measurements: unknown) {
  const path = info.outputPath(`${name}.json`);
  await writeFile(path, JSON.stringify(measurements, null, 2));
  await info.attach(name, { path, contentType: 'application/json' });
}

export async function openPublicContract(page: Page) {
  await page.goto('/');
  await page.waitForFunction(() => '__vue_app__' in document.querySelector('#__nuxt')!);
  await page.locator('#language-select').selectOption('es');
  await page.locator('.tournament-card').first().click();
  await expect(page.getByRole('heading', { name: 'Torneo público 031', exact: true })).toBeVisible();
  await expect(page.locator('.player-stats-panel tbody tr')).toHaveCount(50);
}

export async function measureColumns(panel: Locator) {
  const region = panel.locator('.scroll-content');
  await region.evaluate(e => { e.scrollLeft = 0; });
  return region.evaluate(e => {
    const r = e.getBoundingClientRect();
    return [...e.querySelectorAll('thead th')].map(th => {
      const box = th.getBoundingClientRect();
      return { label: th.textContent!.trim(), complete: box.left >= r.left - 1 && box.right <= r.right + 1 };
    });
  });
}

export async function measureSticky(region: Locator) {
  await region.focus();
  await expect(region).toBeFocused();
  const overflow = await region.evaluate(e => e.scrollWidth > e.clientWidth);
  const hint = region.locator('..').locator('.scroll-hint');
  if (overflow) {
    await expect(hint).toBeVisible();
    await region.press('ArrowRight');
    await expect.poll(() => region.evaluate(e => e.scrollLeft)).toBeGreaterThan(0);
    await region.evaluate(e => { e.scrollLeft = e.scrollWidth; });
    await expect.poll(() => region.evaluate(e => Math.abs(e.querySelector('tbody td:nth-child(2)')!.getBoundingClientRect().left - e.getBoundingClientRect().left))).toBeLessThanOrEqual(1);
  } else await expect(hint).toBeHidden();
  return { overflow, client: await region.evaluate(e => e.clientWidth), scroll: await region.evaluate(e => e.scrollWidth) };
}

export async function measureBracket(page: Page, rows: PublicMatch[]) {
  const expected: string[] = [];
  for (const source of rows) {
    if (!source.winner_team_id || source.matchday === null) continue;
    const destinations = rows.filter(target => target.matchday === source.matchday! + 1 && target.stage_id === source.stage_id && target.group_id === source.group_id && [target.home_team_id, target.away_team_id].includes(source.winner_team_id));
    const sources = rows.filter(other => other.matchday === source.matchday && other.stage_id === source.stage_id && other.group_id === source.group_id && other.winner_team_id === source.winner_team_id);
    if (destinations.length === 1 && sources.length === 1) expected.push(`${source.id}:${destinations[0]!.id}`);
  }
  const paths = page.locator('.bracket-connections path');
  await expect(paths).toHaveCount(expected.length);
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  const actual = await paths.evaluateAll(elements => elements.map(e => `${e.getAttribute('data-source-id')}:${e.getAttribute('data-target-id')}`).sort());
  expect(actual).toEqual(expected.sort());
  await expect(page.locator('.bracket-match')).toHaveCount(rows.length);
  const boxes = await page.locator('.bracket-match').evaluateAll(elements => elements.map(e => {
    const r = e.getBoundingClientRect();
    return { id: e.getAttribute('data-match-id')!, collision: e.getAttribute('data-collision') === 'true', x: r.x, y: r.y, width: r.width, height: r.height, center: r.y + r.height / 2 };
  }));
  const centers = [];
  for (const target of boxes) {
    const sources = expected.filter(edge => edge.endsWith(`:${target.id}`)).map(edge => boxes.find(box => box.id === edge.split(':')[0])!);
    if (!sources.length) continue;
    const delta = Math.abs(target.center - sources.reduce((sum, box) => sum + box.center, 0) / sources.length);
    if (!target.collision) expect(delta).toBeLessThanOrEqual(2);
    centers.push({ id: target.id, delta, collision: target.collision });
  }
  for (let i = 0; i < boxes.length; i++) for (const other of boxes.slice(i + 1)) {
    const box = boxes[i]!;
    expect(Math.min(box.x + box.width, other.x + other.width) <= Math.max(box.x, other.x) + 1 || Math.min(box.y + box.height, other.y + other.height) <= Math.max(box.y, other.y) + 1).toBe(true);
  }
  expect(await page.locator('.bracket-match').evaluateAll(elements => elements.map(e => e.getAttribute('data-match-id')))).toEqual(rows.map(row => row.id));
  return { drawn: actual.length, deducible: expected.length, falseLines: actual.filter(edge => !expected.includes(edge)), centers };
}

export async function assertNoDocumentOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
}
