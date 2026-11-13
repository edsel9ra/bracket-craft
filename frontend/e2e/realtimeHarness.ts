import { randomUUID } from 'node:crypto';
import { chmod, mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { expect, type Browser, type BrowserContext } from '@playwright/test';
import { demoApiBase } from './demo.ts';

const directory = fileURLToPath(new URL('../.auth/realtime/', import.meta.url));
const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:3000';

export interface Tenant {
  organization_id: string; tournament_id: string; match_id: string; open_match_id: string;
  owner_email: string; reader_email: string; password: string;
}

export async function login(browser: Browser, tenant: Tenant, reader = false) {
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  await context.request.get(`${demoApiBase()}/auth/csrf`);
  const csrf = (await context.cookies()).find(row => row.name === 'bc_csrf_token');
  expect(csrf).toBeDefined();
  const response = await context.request.post(`${demoApiBase()}/auth/login`, {
    headers: { 'X-CSRF-Token': decodeURIComponent(csrf!.value), Origin: baseURL },
    data: { email: reader ? tenant.reader_email : tenant.owner_email, password: tenant.password },
  });
  expect(response.status(), 'real session login').toBe(200);
  const identity = await response.json() as { user_id: string };
  await context.addCookies([
    { name: 'bc_organization_id', value: tenant.organization_id, url: baseURL },
    { name: 'bc_user_id', value: identity.user_id, url: baseURL },
  ]);
  await context.addInitScript(organizationId => localStorage.setItem('bc_last_organization_id', organizationId), tenant.organization_id);
  return context;
}

export async function control<T>(body: Record<string, unknown>): Promise<T> {
  await mkdir(directory, { recursive: true });
  await chmod(directory, 0o777);
  const id = randomUUID();
  const temporary = `${directory}pending-${id}`;
  const response = `${directory}response-${id}.json`;
  await writeFile(temporary, JSON.stringify(body));
  await rename(temporary, `${directory}request-${id}.json`);
  let result: { result?: T; error?: string } | undefined;
  await expect.poll(async () => {
    try { result = JSON.parse(await readFile(response, 'utf8')) as typeof result; return true; }
    catch (cause) { if ((cause as NodeJS.ErrnoException).code === 'ENOENT') return false; throw cause; }
  }, { timeout: 90_000, message: `test-only control ${body.action}` }).toBe(true);
  await unlink(response);
  expect(result?.error, 'fixture command must succeed').toBeUndefined();
  return result!.result!;
}

export async function http<T>(context: BrowserContext, tenant: Tenant, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'X-Organization-ID': tenant.organization_id };
  if (body !== undefined) {
    await context.request.get(`${demoApiBase()}/auth/csrf`);
    const cookie = (await context.cookies()).find(row => row.name === 'bc_csrf_token');
    expect(cookie).toBeDefined();
    headers['X-CSRF-Token'] = decodeURIComponent(cookie!.value);
    headers.Origin = baseURL;
  }
  const response = body === undefined
    ? await context.request.get(`${demoApiBase()}${path}`, { headers })
    : await context.request.post(`${demoApiBase()}${path}`, { headers, data: body });
  expect(response.ok(), `${path}: HTTP ${response.status()}`).toBe(true);
  return await response.json() as T;
}

export async function rectify(owner: BrowserContext, reviewer: BrowserContext, tenant: Tenant) {
  const versions = await http<Array<{ version_number: number; report: Record<string, unknown> }>>(owner, tenant, `/matches/${tenant.match_id}/report-versions`);
  const current = versions.reduce((a, b) => a.version_number > b.version_number ? a : b);
  const report = current.report;
  const events = (report.events as Array<Record<string, unknown>>).filter(row => !row.is_voided);
  const goal = events.find(row => row.event_type === 'goal');
  expect(goal).toBeDefined();
  const eventKeys = ['client_event_id', 'event_type', 'team_id', 'beneficiary_team_id', 'player_id', 'minute', 'added_minute', 'segment_id', 'assist_player_id', 'player_out_id', 'player_in_id', 'metadata'];
  const proposed = { ...Object.fromEntries(['resolution_type', 'winner_team_id', 'home_penalties', 'away_penalties', 'away_score_regular', 'away_score'].map(key => [key, report[key] ?? null])),
    home_score_regular: Number(report.home_score_regular) + 1, home_score: Number(report.home_score) + 1,
    events: [...events, { ...goal!, client_event_id: randomUUID() }].map(row => Object.fromEntries(eventKeys.map(key => [key, row[key] ?? (key === 'metadata' ? {} : null)]))) };
  const request = await http<{ id: string; base_version_number: number }>(owner, tenant, `/matches/${tenant.match_id}/rectifications`, {
    proposed_report: proposed, reason: `F8 ${randomUUID()}`, evidence: 'Isolated realtime fixture',
  });
  await http(reviewer, tenant, `/rectifications/${request.id}/preview`);
  await http(reviewer, tenant, `/rectifications/${request.id}/decision`, {
    decision: 'approve', reason: 'F8 fixture approval', expected_base_version: request.base_version_number,
  });
}
