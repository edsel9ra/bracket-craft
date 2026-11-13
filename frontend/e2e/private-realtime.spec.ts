import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test';
import { demoApiBase } from './demo.ts';
import { waitForHydration } from './workspaceSession.ts';
import { control, http, login, rectify, type Tenant } from './realtimeHarness.ts';

const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:3000';
interface Probe { paused: string | null; delivered: string[]; connections: number; suspended: number }
interface Wire { event: string; payload: Record<string, unknown> }

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

function signal() {
  let release!: () => void;
  const promise = new Promise<void>(resolve => { release = resolve; });
  return { promise, release: () => release() };
}

for (const change of ['organization', 'identity'] as const) {
  test(`in-flight accepted HTTP cannot restore a previous ${change} context`, async ({ browser }) => {
    const [tenant, other] = await control<[Tenant, Tenant]>({ action: 'bootstrap' });
    await control({ action: 'link_owner', organization_id: other.organization_id, other_organization_id: tenant.organization_id });
    const owner = await login(browser, tenant);
    const held = signal();
    const reached = signal();
    try {
      const view = await receiver(owner, tenant);
      await expect(view.page.locator('.operation-shell')).toBeVisible();
      await view.page.route(`**/matches/${tenant.match_id}/operation`, async route => {
        const response = await route.fetch();
        reached.release();
        await held.promise;
        if (change === 'identity') await route.fulfill({ status: 403, json: { detail: 'Forbidden' } });
        else await route.fulfill({ response });
      });
      await publish(tenant);
      await reached.promise;
      if (change === 'organization') {
        await view.page.locator('.workspace-organization-select').selectOption(other.organization_id);
        await expect(view.page).toHaveURL(/\/workspace$/);
      } else {
        await view.page.locator('.workspace-account-button').click();
        await view.page.getByRole('menuitem', { name: 'Salir', exact: true }).click();
        await expect(view.page).toHaveURL(baseURL + '/');
      }
      held.release();
      await flush([view.page]);
      await expect(view.page.locator('.operation-shell')).toHaveCount(0);
      if (change === 'organization') await expect(view.page.locator('.workspace-organization-select')).toHaveValue(other.organization_id);
      else await expect(view.page).toHaveURL(baseURL + '/');
    } finally { held.release(); await owner.close(); }
  });
}

test('busy action consolidates invalidations into one trailing reload without losing the action', async ({ browser }) => {
  const [tenant] = await control<[Tenant, Tenant]>({ action: 'bootstrap' });
  await control({ action: 'prepare_open', organization_id: tenant.organization_id });
  const owner = await login(browser, tenant);
  const held = signal();
  const reached = signal();
  try {
    const view = await receiver(owner, { ...tenant, match_id: tenant.open_match_id });
    await expect(view.page.locator('.operation-shell')).toBeVisible();
    let reads = 0;
    view.page.on('request', request => { if (request.url().endsWith(`/matches/${tenant.open_match_id}/operation`)) reads++; });
    await view.page.route(`**/matches/${tenant.open_match_id}/segments/*/interrupt`, async route => {
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      reached.release();
      await held.promise;
      await route.fulfill({ response });
    });
    await view.page.locator('#interrupt-minute').fill('5');
    await view.page.getByRole('button', { name: 'Registrar interrupción', exact: true }).click();
    await reached.promise;
    const before = reads;
    for (let n = 0; n < 3; n++) {
      const event = await publish(tenant, { open: true });
      await expect.poll(() => view.ids().includes(event.event_id)).toBe(true);
    }
    await flush([view.page]);
    expect(reads).toBe(before);
    held.release();
    await expect(view.page.getByText('Interrupción registrada', { exact: true })).toBeVisible();
    await expect.poll(() => reads).toBe(before + 2); // action refresh plus one consolidated trailing read
    await flush([view.page]);
    expect(reads).toBe(before + 2);
  } finally { held.release(); await owner.close(); }
});

test('duplicates, actual stream trim/reset and reconnect reconstruct HTTP without replay', async ({ browser }) => {
  const [tenant] = await control<[Tenant, Tenant]>({ action: 'bootstrap' });
  const owner = await login(browser, tenant);
  try {
    const view = await receiver(owner, tenant);
    await expect(view.page.locator('.operation-shell')).toBeVisible();
    let reads = 0;
    view.page.on('request', request => { if (request.url().endsWith(`/matches/${tenant.match_id}/operation`)) reads++; });
    const first = await publish(tenant);
    await expect.poll(() => reads).toBe(1);
    await control({ action: 'inject', organization_id: tenant.organization_id, event_id: first.event_id });
    const marker = await control<{ event_id: string }>({ action: 'inject', organization_id: tenant.organization_id, event_type: 'UNKNOWN' });
    await delivered(marker.event_id);
    await flush([view.page]);
    expect(view.ids().filter(id => id === first.event_id)).toHaveLength(2);
    expect(reads).toBe(1);
    for (const kind of ['trim', 'reset']) {
      const baseline = view.wire.length;
      const pending = await publish(tenant, { barrier: 'before' });
      await expect.poll(async () => (await control<Probe>({ action: 'probe' })).paused).toBe(pending.event_id);
      const lost = await control<{ event_id: string }>({ action: 'stream_gap', kind });
      const before = reads;
      await control({ action: 'release' });
      const reason = kind === 'trim' ? 'STREAM_TRIMMED' : 'REDIS_RESET';
      await expect.poll(() => view.wire.slice(baseline).some(row => row.event === 'RESYNC' && row.payload.reason === reason)).toBe(true);
      await expect.poll(() => reads).toBeGreaterThan(before);
      expect(view.ids()).not.toContain(lost.event_id);
      await expect(view.page.locator('.operation-shell')).toBeVisible();
    }
    const previous = view.opened();
    const dropped = await control<{ engine_sids: number }>({ action: 'drop_transport' });
    console.log(`drop_transport engine_sid count: ${dropped.engine_sids}`);
    expect(dropped.engine_sids).toBeGreaterThan(0);
    await expect.poll(() => view.closed()).toBeGreaterThan(0);
    const lost = await publish(tenant);
    await delivered(lost.event_id);
    const before = reads;
    await control({ action: 'release_connect' });
    await expect.poll(() => view.opened()).toBeGreaterThan(previous);
    await expect.poll(() => reads).toBeGreaterThan(before);
    expect(view.ids()).not.toContain(lost.event_id);
  } finally { await owner.close(); }
});

test('real JWT expiry cuts off an open socket and HTTP without expiring other sessions', async ({ browser }) => {
  const [tenant] = await control<[Tenant, Tenant]>({ action: 'bootstrap' });
  const reader = await login(browser, tenant, true);
  const owner = await login(browser, tenant);
  try {
    await control({ action: 'mode', pause_maintenance: true });
    const credential = await control<{ token: string; deadline: number }>({ action: 'short_token', organization_id: tenant.organization_id });
    await reader.addCookies([{ name: 'bc_access_token', value: credential.token, url: baseURL }]);
    const [expired, healthy] = await Promise.all([receiver(reader, tenant, false, true), receiver(owner, tenant, false, true)]);
    const first = await publish(tenant);
    await expect.poll(() => expired.ids().includes(first.event_id)).toBe(true);
    const pending = await publish(tenant, { barrier: 'before' });
    await expect.poll(async () => (await control<Probe>({ action: 'probe' })).paused).toBe(pending.event_id);
    await control({ action: 'wait_expiry', deadline: credential.deadline });
    const response = await reader.request.get(`${demoApiBase()}/matches/${tenant.match_id}/operation`,
      { headers: { 'X-Organization-ID': tenant.organization_id } });
    expect(response.status()).toBe(401);
    await control({ action: 'release' });
    await delivered(pending.event_id);
    await expect.poll(() => healthy.ids().includes(pending.event_id)).toBe(true);
    await flush([expired.page, healthy.page]);
    expect(expired.ids()).not.toContain(pending.event_id);
    expect(expired.closed()).toBe(0);
    expect(expired.opened()).toBe(1);
  } finally { await reader.close(); await owner.close(); }
});

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
