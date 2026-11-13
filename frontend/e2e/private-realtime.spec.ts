import { randomUUID } from 'node:crypto';
import { chmod, mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test';
import { demoApiBase } from './demo.ts';
import { waitForHydration } from './workspaceSession.ts';

const directory = fileURLToPath(new URL('../.auth/realtime/', import.meta.url));
const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:3000';
interface Tenant {
  organization_id: string; tournament_id: string; match_id: string; open_match_id: string;
  owner_email: string; reader_email: string; password: string;
}
interface Probe { paused: string | null; delivered: string[]; connections: number; suspended: number }
interface Wire { event: string; payload: Record<string, unknown> }

async function control<T>(body: Record<string, unknown>): Promise<T> {
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

async function login(browser: Browser, tenant: Tenant, reader = false) {
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

async function http<T>(context: BrowserContext, tenant: Tenant, path: string, body?: unknown): Promise<T> {
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

async function rectify(owner: BrowserContext, reviewer: BrowserContext, tenant: Tenant) {
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

async function receiver(context: BrowserContext, tenant: Tenant, publicScope = false, transportOnly = false) {
  const page = await context.newPage();
  const wire: Wire[] = [];
  let opened = 0;
  let closed = 0;
  page.on('websocket', socket => {
    socket.on('close', () => { closed++; });
    socket.on('framereceived', frame => {
      const text = frame.payload.toString();
      if (text.startsWith('40')) opened++;
      if (!text.startsWith('42')) return;
      const [event, payload] = JSON.parse(text.slice(2)) as [string, Record<string, unknown>];
      wire.push({ event, payload });
    });
  });
  if (transportOnly) {
    await page.goto(`${baseURL}/health.txt`);
    await page.evaluate(({ apiBase, organizationId }) => {
      const url = new URL('/socket.io/?EIO=4&transport=websocket', apiBase);
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      const socket = new WebSocket(url);
      socket.onmessage = message => {
        const packet = String(message.data);
        if (packet.startsWith('0')) socket.send(`40${JSON.stringify({ organization_id: organizationId })}`);
        else if (packet === '2') socket.send('3');
      };
    }, { apiBase: demoApiBase(), organizationId: tenant.organization_id });
  } else {
    await page.goto(publicScope ? `/tournaments/${tenant.tournament_id}` : `/workspace/matches/${tenant.match_id}`);
    await waitForHydration(page);
  }
  await expect.poll(() => opened).toBe(1);
  await expect.poll(() => wire.some(row => row.event === 'RESYNC')).toBe(true);
  const ids = () => wire.filter(row => row.event !== 'RESYNC').map(row => row.payload.event_id);
  return { page, wire, ids, opened: () => opened, closed: () => closed };
}

async function publish(tenant: Tenant, options: Record<string, unknown> = {}) {
  return await control<{ event_id: string }>({ action: 'publish', organization_id: tenant.organization_id, ...options });
}
async function delivered(eventId: string) {
  await expect.poll(async () => (await control<Probe>({ action: 'probe' })).delivered.includes(eventId)).toBe(true);
}
async function flush(pages: Page[]) {
  await Promise.all(pages.map(page => page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))));
}

function versionsPanel(page: Page) {
  return page.getByRole('heading', { name: 'Versiones del acta', exact: true }).locator('..');
}

test('published rectification refreshes history without manual refresh and preserves an open editor', async ({ browser }) => {
  const [tenant] = await control<[Tenant, Tenant]>({ action: 'bootstrap' });
  const owner = await login(browser, tenant);
  const reader = await login(browser, tenant, true);
  try {
    const [editing, watching] = await Promise.all([receiver(owner, tenant), receiver(reader, tenant)]);
    const editorPanel = versionsPanel(editing.page);
    const receiverPanel = versionsPanel(watching.page);
    await expect(editorPanel.locator('select').first()).toHaveValue('1');
    await expect(receiverPanel.locator('select').first()).toHaveValue('1');
    const previousScore = await editing.page.locator('.match-score strong').innerText();
    await editorPanel.getByRole('button', { name: 'Solicitar rectificación', exact: true }).click();
    const draft = editorPanel.getByRole('textbox', { name: 'Motivo de la solicitud', exact: true });
    await draft.fill('Draft preserved during realtime publication');
    await rectify(owner, reader, tenant);
    await expect(receiverPanel.locator('select').first()).toHaveValue('2');
    await expect(editing.page.locator('.match-score strong')).not.toHaveText(previousScore);
    await expect(draft).toHaveValue('Draft preserved during realtime publication');
    await expect(editorPanel.locator('select').first()).toHaveValue('1');
    await editorPanel.getByRole('button', { name: 'Cancelar', exact: true }).click();
    await editing.page.getByRole('dialog').getByRole('button', { name: 'Descartar cambios', exact: true }).click();
    await expect(editorPanel.locator('select').first()).toHaveValue('2');
  } finally { await owner.close(); await reader.close(); }
});

test.afterEach(async () => {
  await control({ action: 'release' });
  await control({ action: 'mode', authorization_failure: false, revalidation_failure: false, pause_maintenance: false });
  await control({ action: 'archive' });
});

test('private transport: real sessions, two tenants, two tabs, minimal wire and HTTP-equivalent empty permissions/officials', async ({ browser }) => {
  const [a, b] = await control<[Tenant, Tenant]>({ action: 'bootstrap' });
  const owner = await login(browser, a);
  const reader = await login(browser, a, true);
  const foreign = await login(browser, b);
  const anonymous = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  try {
    await rectify(owner, reader, a);
    await control({ action: 'secondary_role', organization_id: a.organization_id });
    await control({ action: 'assign_official', organization_id: a.organization_id });
    for (const kind of ['permission', 'official']) await control({ action: 'withdraw', organization_id: a.organization_id, kind });
    await http(reader, a, `/matches/${a.match_id}/operation`);
    const receivers = await Promise.all([receiver(owner, a), receiver(reader, a), receiver(reader, a), receiver(foreign, b), receiver(anonymous, a, true)]);
    const event = await publish(a, { private: true });
    await delivered(event.event_id);
    for (const target of receivers.slice(0, 3)) {
      await expect.poll(() => target.ids().includes(event.event_id)).toBe(true);
      const payload = target.wire.find(row => row.payload.event_id === event.event_id)!.payload;
      expect(Object.keys(payload).sort()).toEqual(['event_id', 'match_id', 'tournament_id']);
    }
    await flush(receivers.map(row => row.page));
    for (const target of receivers.slice(3)) expect(target.ids()).not.toContain(event.event_id);
    const publicEvent = await publish(a);
    await expect.poll(() => receivers[4]!.ids().includes(publicEvent.event_id)).toBe(true);
    const probe = await publish(a, { event_type: 'VERIFICATION_OUTBOX_PROBE' });
    await delivered(probe.event_id);
    await flush(receivers.map(row => row.page));
    for (const target of receivers) expect(target.ids()).not.toContain(probe.event_id);
  } finally { await Promise.all([owner, reader, foreign, anonymous].map(context => context.close())); }
});

for (const kind of ['roles', 'membership', 'session']) {
  test(`commit/evaluation barriers: withdrawal of ${kind} with sockets open`, async ({ browser }) => {
    const [tenant] = await control<[Tenant, Tenant]>({ action: 'bootstrap' });
    const owner = await login(browser, tenant);
    const reader = await login(browser, tenant, true);
    try {
      await control({ action: 'mode', pause_maintenance: true });
      const [allowed, revoked] = await Promise.all([receiver(owner, tenant, false, true), receiver(reader, tenant, false, true)]);
      const before = await publish(tenant, { barrier: 'after' });
      await expect.poll(async () => (await control<Probe>({ action: 'probe' })).paused).toBe(before.event_id);
      await control({ action: 'withdraw', organization_id: tenant.organization_id, kind });
      await control({ action: 'release' });
      await expect.poll(() => revoked.ids().includes(before.event_id)).toBe(true);
      const after = await publish(tenant, { barrier: 'before' });
      await expect.poll(async () => (await control<Probe>({ action: 'probe' })).paused).toBe(after.event_id);
      await control({ action: 'release' });
      await delivered(after.event_id);
      await expect.poll(() => allowed.ids().includes(after.event_id)).toBe(true);
      await flush([allowed.page, revoked.page]);
      expect(revoked.ids()).not.toContain(after.event_id);
      expect(revoked.opened()).toBe(1);
      expect(revoked.closed()).toBe(0);
      const denied = await reader.request.get(`${demoApiBase()}/matches/${tenant.match_id}/operation`, { headers: { 'X-Organization-ID': tenant.organization_id } });
      expect([401, 403, 404]).toContain(denied.status());
      if (kind !== 'session') {
        await control({ action: 'restore', organization_id: tenant.organization_id, kind });
        await http(reader, tenant, `/matches/${tenant.match_id}/operation`);
        const restored = await publish(tenant);
        await expect.poll(() => revoked.ids().includes(restored.event_id)).toBe(true);
        expect(revoked.opened()).toBe(1);
      } else {
        const renewed = await login(browser, tenant, true);
        try {
          const newSession = await receiver(renewed, tenant, false, true);
          const fresh = await publish(tenant);
          await expect.poll(() => newSession.ids().includes(fresh.event_id)).toBe(true);
          await delivered(fresh.event_id);
          expect(revoked.ids()).not.toContain(fresh.event_id);
        } finally { await renewed.close(); }
      }
    } finally { await owner.close(); await reader.close(); }
  });
}

test('authorization-only failure: public continues; 032 retry recovers terminal HTTP without a new event, reconnect or replay', async ({ browser }) => {
  const [tenant, other] = await control<[Tenant, Tenant]>({ action: 'bootstrap' });
  await control({ action: 'link_owner', organization_id: other.organization_id, other_organization_id: tenant.organization_id });
  const owner = await login(browser, tenant);
  const reader = await login(browser, tenant, true);
  const changedContext = await login(browser, tenant);
  const anonymous = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  try {
    const [active, revoked, publicView] = await Promise.all([receiver(owner, tenant), receiver(reader, tenant), receiver(anonymous, tenant, true)]);
    const changed = await receiver(changedContext, tenant);
    const baseline = active.wire.length;
    const revokedBaseline = revoked.wire.length;
    const previousScore = await active.page.locator('.match-score strong').innerText();
    await expect(versionsPanel(active.page).locator('select').first()).toHaveValue('1');
    let reads = 0;
    active.page.on('response', response => { if (response.url().endsWith(`/matches/${tenant.match_id}/operation`) && response.status() === 200) reads++; });
    await control({ action: 'mode', authorization_failure: true, revalidation_failure: true });
    await changed.page.locator('.workspace-organization-select').selectOption(other.organization_id);
    await expect(changed.page).toHaveURL(/\/workspace$/);
    await expect(changed.page.locator('.workspace-organization-select')).toHaveValue(other.organization_id);
    const changedBaseline = changed.wire.length;
    await rectify(owner, reader, tenant);
    const missing = await publish(tenant, { private: true });
    await delivered(missing.event_id);
    await expect.poll(async () => (await control<Probe>({ action: 'probe' })).suspended).toBeGreaterThanOrEqual(2);
    const publicEvent = await publish(tenant);
    await expect.poll(() => publicView.ids().includes(publicEvent.event_id)).toBe(true);
    await control({ action: 'withdraw', organization_id: tenant.organization_id, kind: 'session' });
    await control({ action: 'mode', authorization_failure: false });
    await flush([active.page, revoked.page]);
    expect(active.ids()).not.toContain(missing.event_id);
    expect(changed.ids()).not.toContain(missing.event_id);
    await control({ action: 'mode', revalidation_failure: false });
    await expect.poll(() => active.wire.slice(baseline).some(row => row.event === 'RESYNC' && row.payload.reason === 'RELAY_START')).toBe(true);
    await expect.poll(() => reads).toBeGreaterThan(0);
    await expect.poll(() => changed.wire.slice(changedBaseline).some(row => row.event === 'RESYNC' && row.payload.reason === 'RELAY_START')).toBe(true);
    await expect(changed.page.locator('.workspace-organization-select')).toHaveValue(other.organization_id);
    await expect.poll(() => revoked.closed()).toBeGreaterThan(0);
    expect(revoked.wire.slice(revokedBaseline).some(row => row.event === 'RESYNC' && row.payload.reason === 'RELAY_START')).toBe(false);
    expect(active.ids()).not.toContain(missing.event_id);
    expect(active.opened()).toBe(1);
    expect(active.closed()).toBe(0);
    const resync = active.wire.slice(baseline).find(row => row.event === 'RESYNC' && row.payload.reason === 'RELAY_START')!;
    expect(Object.keys(resync.payload).sort()).toEqual(['event_id', 'reason']);
    await expect(active.page.locator('.operation-shell')).toBeVisible();
    await expect(active.page.locator('.match-score strong')).not.toHaveText(previousScore);
    await expect(versionsPanel(active.page).locator('select').first()).toHaveValue('2');
    await expect(active.page.locator('#close-home-regular')).toBeDisabled();
  } finally { await owner.close(); await reader.close(); await anonymous.close(); await changedContext.close(); }
});
