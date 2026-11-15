// T78: verificación visual de la sección live en desktop (1440px) y móvil
// (390px): estados live/paused/suspended/desactualizado y revisión con teclado.
// Escribe PNG saneados + manifiesto SHA-256 en e2e-report/live-visual/.
import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium, expect, type BrowserContext, type Page } from '@playwright/test';
import { control, http, login, type Tenant } from './realtimeHarness.ts';
import { waitForHydration } from './workspaceSession.ts';

const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:3000';
const outDir = fileURLToPath(new URL('../e2e-report/live-visual/', import.meta.url));
const SIZES = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
];

interface Operation {
  match: { home_team_id: string; away_team_id: string };
  segments: Array<{ id: string; status: string }>;
  rosters: Array<{ player_id: string; team_id: string }>;
}

interface Shot { name: string; path: string; sha256: string; bytes: number; }

async function shot(page: Page, name: string, shots: Shot[]) {
  const path = `${outDir}${name}.png`;
  await page.screenshot({ path, fullPage: true });
  const bytes = await readFile(path);
  shots.push({ name, path: `e2e-report/live-visual/${name}.png`, sha256: createHash('sha256').update(bytes).digest('hex'), bytes: bytes.length });
}

async function live(context: BrowserContext, tenant: Tenant, matchId: string, body: Record<string, unknown>) {
  return await http<{ revision: number }>(context, tenant, `/matches/${matchId}/live/commands`, body);
}

async function run() {
  await mkdir(outDir, { recursive: true });
  const shots: Shot[] = [];
  const browser = await chromium.launch();
  const [tenant] = await control<[Tenant, Tenant]>({ action: 'bootstrap' });
  const owner = await login(browser, tenant);
  try {
  try {
    await control({ action: 'prepare_open', organization_id: tenant.organization_id });
    const matchId = tenant.open_match_id;
    const operation = await http<Operation>(owner, tenant, `/matches/${matchId}/operation`);
    const segment = operation.segments.find(row => row.status === 'active');
    const home = operation.match.home_team_id;
    const player = operation.rosters.find(row => row.team_id === home)!;
    let revision = 0;
    for (const size of SIZES) {
      {
        const page = await owner.newPage();
        await page.setViewportSize({ width: size.width, height: size.height });
        await page.goto(`${baseURL}/workspace/matches/${matchId}`);
        await waitForHydration(page);
        await expect(page.getByRole('heading', { name: 'Partido en vivo', exact: true })).toBeVisible();
        await shot(page, `${size.name}-provisioned`, shots);

        if (size.name === 'desktop') {
          // Teclado: foco sobre «Iniciar en vivo» y activación con Enter.
          const startButton = page.getByRole('button', { name: 'Iniciar en vivo', exact: true });
          await startButton.focus();
          const focused = await page.evaluate(() => document.activeElement?.textContent?.trim());
          expect(focused).toBe('Iniciar en vivo');
          await page.keyboard.press('Enter');
          // Confirmación expresa «Iniciar el partido en vivo»: aceptar por teclado.
          const dialog = page.getByRole('dialog');
          await expect(dialog.getByRole('heading', { name: 'Iniciar el partido en vivo', exact: true })).toBeVisible();
          await dialog.getByRole('button', { name: 'Iniciar en vivo', exact: true }).focus();
          await page.keyboard.press('Enter');
        }
        // En móvil el partido ya está live desde desktop; ejercita el resto.
        await expect(page.getByText('En vivo', { exact: true }).first()).toBeVisible();
        await shot(page, `${size.name}-live`, shots);
        if (size.name === 'desktop') {
          revision = 1;
          revision = (await live(owner, tenant, matchId, {
            command_id: randomUUID(), type: 'start_clock', expected_revision: revision, segment_id: segment!.id,
          })).revision;
        }
        await expect(page.getByText(/Reloj.*corriendo/).first()).toBeVisible();
        await shot(page, `${size.name}-clock-running`, shots);

        revision = (await live(owner, tenant, matchId, {
          command_id: randomUUID(), type: 'pause_clock', expected_revision: revision,
        })).revision;
        await expect(page.getByText(/Reloj.*en pausa/).first()).toBeVisible({ timeout: 15_000 });
        await shot(page, `${size.name}-clock-paused`, shots);

        revision = (await live(owner, tenant, matchId, {
          command_id: randomUUID(), type: 'add_event', expected_revision: revision,
          event: {
            client_event_id: randomUUID(), event_type: 'goal', team_id: home,
            player_id: player.player_id, minute: 5, added_minute: 0,
            segment_id: segment!.id, metadata: null,
          },
        })).revision;
        await expect(page.locator('.live-events li').getByText("Gol · 5'").first()).toBeVisible();

        revision = (await live(owner, tenant, matchId, {
          command_id: randomUUID(), type: 'suspend', expected_revision: revision,
        })).revision;
        await expect(page.getByText('Suspendido', { exact: true }).first()).toBeVisible();
        await shot(page, `${size.name}-suspended`, shots);

        revision = (await live(owner, tenant, matchId, {
          command_id: randomUUID(), type: 'resume', expected_revision: revision,
        })).revision;
        await expect(page.getByText('En vivo', { exact: true }).first()).toBeVisible();
        revision = (await live(owner, tenant, matchId, {
          command_id: randomUUID(), type: 'resume_clock', expected_revision: revision,
        })).revision;
        await expect(page.getByText(/Reloj.*corriendo/).first()).toBeVisible();

        // Desactualizado: abortar el canal socket y recargar → reloj estimado.
        let blockSocket = true;
        await page.context().routeWebSocket(/socket\.io/, async ws => {
          if (blockSocket) { ws.close(); return; }
          const server = await ws.connectToServer();
          ws.onMessage(message => server.send(message));
          server.onMessage(message => ws.send(message));
        });
        await page.reload();
        await waitForHydration(page);
        await expect(page.getByText('sin conexión (estimado)').first()).toBeVisible();
        await shot(page, `${size.name}-stale`, shots);
        blockSocket = false;
        await page.reload();
        await waitForHydration(page);
        await expect(page.getByText('En vivo', { exact: true }).first()).toBeVisible();

        // Revisión con teclado: el bloque está siempre visible; navegar por Tab
        // hasta el selector de resolución y continuar.
        await expect(page.getByText('Revisión y cierre', { exact: true }).first()).toBeVisible();
        await page.locator('#live-review-resolution').focus();
        await page.keyboard.press('Tab');
        const reviewFocused = await page.evaluate(() => document.activeElement?.id);
        expect(reviewFocused).not.toBe('live-review-resolution');
        await shot(page, `${size.name}-review`, shots);
        await page.close();
      }
    }
  } finally { await owner.close(); }
  } finally {
    await browser.close();
    const manifest = {
      generated_at: new Date().toISOString(),
      sizes: SIZES.map(row => row.name),
      checks: ['provisioned', 'live', 'clock-running', 'clock-paused', 'suspended', 'review'],
      screenshots: shots,
    };
    await writeFile(`${outDir}manifest.json`, JSON.stringify(manifest, null, 2) + '\n');
    console.log(`MANIFEST ${outDir}manifest.json`);
    for (const item of shots) console.log(`SHOT ${item.name} ${item.bytes}B ${item.sha256.slice(0, 12)}`);
  }
}

await run();
