/**
 * Runner local del E2E del reintento manual (T7, RF-004, RF-005, RF-006).
 *
 * `pnpm run e2e` arranca la pila, siembra los datos demo, ejecuta Playwright
 * (setup + tres vistas, Chromium headless, `workers: 1`, `retries: 0`), agrega
 * los artefactos en `summary.json`, imprime la tabla de las tres vistas y
 * traduce el resultado a los códigos 0/1/2/3:
 *
 *   0 verde · 1 fallo de comportamiento · 2 fallo de infraestructura ·
 *   3 corrida inválida (vista omitida o escenario inválido).
 *
 * `pnpm run e2e:test` es el mismo runner con `--no-stack`: no arranca, no
 * siembra ni baja nada; es lo que usa la integración continua. Los argumentos
 * que no son del runner se reenvían a `playwright test` (`--grep`, `--project`).
 *
 * En un entorno sin Docker pero con la pila ya sana (por ejemplo, un contenedor
 * de Playwright con la pila en la red del host), el runner lo declara y ejecuta
 * contra la pila existente. Sin pila alcanzable sale 2: no se declara verde.
 * En ese mismo entorno el registro del servidor no se puede recoger y
 * `server.log` lo declara con una línea explícita (RF-006): el artefacto nunca
 * falta en silencio.
 */

import { spawn } from 'node:child_process';
import { readFile, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

import {
  REPORT_DIR,
  redactLine,
  reportPath,
  writeJsonReport,
  writeTextReport,
  type ArtifactVerdict,
  type ViewArtifact,
} from './artifacts.ts';
import { EXPECTED_VIEWS, MAX_MS, type ViewId } from './observations.ts';
import {
  buildRunSummary,
  buildServerLog,
  formatSummaryTable,
  parseRunnerArgs,
  type PlaywrightProjectOutcome,
  type PlaywrightStatus,
  type RunStackInfo,
  type ServerLogCapture,
} from './runModel.ts';

const FRONTEND_ROOT = fileURLToPath(new URL('..', import.meta.url));
const REPO_ROOT = fileURLToPath(new URL('../..', import.meta.url));

const BASE_URL = (process.env.E2E_BASE_URL ?? 'http://localhost:3000').replace(/\/+$/, '');
const API_BASE = (process.env.E2E_API_BASE ?? 'http://localhost:8000/api/v1').replace(/\/+$/, '');
const WEB_HEALTH_URL = `${BASE_URL}/health.txt`;
const API_HEALTH_URL =
  process.env.E2E_API_HEALTH_URL ?? new URL('/health/ready', `${API_BASE}/`).toString();

const PLAYWRIGHT_TIMEOUT_MS = MAX_MS.run + 60_000;
const COMMAND_TIMEOUT_MS = 120_000;

/* -------------------------------------------------------------------------- */
/* Procesos                                                                   */
/* -------------------------------------------------------------------------- */

interface CommandResult {
  readonly code: number | null;
  readonly output: string;
  readonly timedOut: boolean;
}

function describeError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function runCommand(
  command: string,
  args: readonly string[],
  options: { readonly cwd: string; readonly timeoutMs: number; readonly inherit?: boolean },
): Promise<CommandResult> {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn(command, [...args], {
        cwd: options.cwd,
        env: process.env,
        stdio: options.inherit ? 'inherit' : ['ignore', 'pipe', 'pipe'],
      });
    } catch (error) {
      resolve({ code: 127, output: describeError(error), timedOut: false });
      return;
    }

    let output = '';
    let timedOut = false;
    const append = (chunk: Buffer | string): void => {
      output += chunk.toString();
      // Solo se conserva la cola: el mensaje de error es lo que se publica.
      if (output.length > 20_000) output = output.slice(-20_000);
    };
    if (!options.inherit) {
      child.stdout?.on('data', append);
      child.stderr?.on('data', append);
    }

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
    }, options.timeoutMs);

    child.on('error', (error) => {
      clearTimeout(timer);
      resolve({ code: 127, output: describeError(error), timedOut });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ code, output, timedOut });
    });
  });
}

/** Causa legible de un comando fallido, saneada y acotada a la primera línea. */
function commandCause(prefix: string, result: CommandResult): string {
  if (result.timedOut) return `${prefix}: tiempo agotado`;
  const first = redactLine(result.output.trim().split('\n').find((line) => line.trim()) ?? '');
  const detail = first.length > 0 ? `: ${first}` : '';
  return `${prefix}${detail}`;
}

async function dockerAvailable(): Promise<boolean> {
  const result = await runCommand('docker', ['compose', 'version', '--short'], {
    cwd: REPO_ROOT,
    timeoutMs: 10_000,
  });
  return result.code === 0 && !result.timedOut;
}

/** Comprueba que la pila ya levantada responde por HTTP (web y API). */
async function probeStack(): Promise<{ readonly ok: boolean; readonly cause: string | null }> {
  const targets: ReadonlyArray<readonly [string, string]> = [
    ['web', WEB_HEALTH_URL],
    ['api', API_HEALTH_URL],
  ];
  for (const [name, url] of targets) {
    try {
      const response = await fetch(url, {
        headers: { accept: '*/*' },
        signal: AbortSignal.timeout(5_000),
      });
      if (!response.ok) {
        return { ok: false, cause: `${name} respondió ${response.status}` };
      }
    } catch (error) {
      return { ok: false, cause: `${name}: ${describeError(error)}` };
    }
  }
  return { ok: true, cause: null };
}

/* -------------------------------------------------------------------------- */
/* Lectura del informe                                                        */
/* -------------------------------------------------------------------------- */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

const PLAYWRIGHT_STATUSES: ReadonlySet<PlaywrightStatus> = new Set([
  'passed',
  'failed',
  'timedOut',
  'skipped',
  'interrupted',
  'missing',
]);

const ARTIFACT_VERDICTS: ReadonlySet<ArtifactVerdict> = new Set([
  'passed',
  'behavioral',
  'infrastructure',
  'invalid',
]);

/** Valida lo mínimo que el resumen consume; un artefacto corrupto se ignora. */
function isViewArtifact(value: unknown): value is ViewArtifact {
  if (!isRecord(value)) return false;
  const view = value['view'];
  const verdict = value['verdict'];
  return (
    typeof view === 'string' &&
    (EXPECTED_VIEWS as readonly string[]).includes(view) &&
    typeof verdict === 'string' &&
    (ARTIFACT_VERDICTS as ReadonlySet<string>).has(verdict) &&
    typeof value['durationMs'] === 'number' &&
    Array.isArray(value['states']) &&
    isRecord(value['reloads'])
  );
}

async function readArtifacts(): Promise<ViewArtifact[]> {
  const artifacts: ViewArtifact[] = [];
  for (const view of EXPECTED_VIEWS) {
    try {
      const raw = JSON.parse(await readFile(reportPath(`view-${view}.json`), 'utf8')) as unknown;
      if (isViewArtifact(raw)) artifacts.push(raw);
    } catch {
      // Ausente o ilegible: el resultado de Playwright decide si fue omitida.
    }
  }
  return artifacts;
}

function parseProjects(raw: unknown): PlaywrightProjectOutcome[] | null {
  if (!isRecord(raw)) return null;
  const projects = raw['projects'];
  if (!Array.isArray(projects)) return null;

  const parsed: PlaywrightProjectOutcome[] = [];
  for (const entry of projects) {
    if (!isRecord(entry)) continue;
    const project = entry['project'];
    const status = entry['status'];
    const durationMs = entry['durationMs'];
    if (typeof project !== 'string' || typeof status !== 'string') continue;
    if (!PLAYWRIGHT_STATUSES.has(status as PlaywrightStatus)) continue;
    if (typeof durationMs !== 'number') continue;
    parsed.push({ project, status: status as PlaywrightStatus, durationMs });
  }
  return parsed;
}

/* -------------------------------------------------------------------------- */
/* Ejecución                                                                  */
/* -------------------------------------------------------------------------- */

interface StackPreparation {
  readonly stack: RunStackInfo;
  readonly started: boolean;
  readonly cause: string | null;
}

async function prepareStack(noStack: boolean): Promise<StackPreparation> {
  if (noStack) {
    return { stack: { mode: 'skipped', durationMs: null }, started: false, cause: null };
  }

  if (!(await dockerAvailable())) {
    const probe = await probeStack();
    if (probe.ok) {
      console.log(
        '[e2e] docker no disponible en este entorno: se ejecuta contra la pila ya levantada.',
      );
      return { stack: { mode: 'external', durationMs: null }, started: false, cause: null };
    }
    return {
      stack: { mode: 'external', durationMs: null },
      started: false,
      cause: `docker-unavailable: ${probe.cause ?? 'sin pila alcanzable'}`,
    };
  }

  const startedAt = Date.now();
  const up = await runCommand(
    'docker',
    ['compose', 'up', '-d', '--build', '--wait', '--wait-timeout', '300'],
    { cwd: REPO_ROOT, timeoutMs: MAX_MS.stackStart },
  );
  if (up.code !== 0 || up.timedOut) {
    return {
      stack: { mode: 'started', durationMs: Date.now() - startedAt },
      started: true,
      cause: commandCause('stack-start-failed', up),
    };
  }

  const seed = await runCommand(
    'docker',
    ['compose', 'exec', '-T', 'api', 'python', '-m', 'scripts.seed_demo'],
    { cwd: REPO_ROOT, timeoutMs: MAX_MS.stackStart },
  );
  if (seed.code !== 0 || seed.timedOut) {
    return {
      stack: { mode: 'started', durationMs: Date.now() - startedAt },
      started: true,
      cause: commandCause('seed-failed', seed),
    };
  }

  return {
    stack: { mode: 'started', durationMs: Date.now() - startedAt },
    started: true,
    cause: null,
  };
}

/**
 * Recoge el registro del servidor (RF-005, RF-006) **antes** de bajar la pila y
 * lo deja saneado en `e2e-report/server.log`, igual que hace el job de CI. Si el
 * entorno no tiene Docker —el contenedor del arnés, por ejemplo— el artefacto
 * declara la diferencia con una línea explícita en lugar de faltar en silencio.
 */
async function writeServerLog(): Promise<void> {
  let capture: ServerLogCapture;
  try {
    const hasDocker = await dockerAvailable();
    if (!hasDocker) {
      capture = buildServerLog({ dockerAvailable: false, command: null });
    } else {
      const result = await runCommand(
        'docker',
        ['compose', 'logs', '--no-color', 'api', 'worker', 'web'],
        { cwd: REPO_ROOT, timeoutMs: COMMAND_TIMEOUT_MS },
      );
      capture = buildServerLog({
        dockerAvailable: true,
        command: { code: result.code, timedOut: result.timedOut, output: result.output },
      });
    }
  } catch (error) {
    capture = buildServerLog({
      dockerAvailable: true,
      command: { code: null, timedOut: false, output: describeError(error) },
    });
  }

  await writeTextReport('server.log', capture.content);
  console.log(
    capture.available
      ? '[e2e] server.log recogido y saneado en e2e-report/.'
      : `[e2e] server.log: ${capture.note ?? 'no disponible'}`,
  );
}

async function main(): Promise<number> {
  const args = parseRunnerArgs(process.argv.slice(2));

  await rm(REPORT_DIR, { recursive: true, force: true });

  let stack: RunStackInfo = { mode: 'skipped', durationMs: null };
  let stackStarted = false;
  let infrastructureCause: string | null = null;
  let projects: PlaywrightProjectOutcome[] = [];
  let totalDurationMs = 0;

  try {
    const preparation = await prepareStack(args.noStack);
    stack = preparation.stack;
    stackStarted = preparation.started;
    infrastructureCause = preparation.cause;

    if (!infrastructureCause) {
      const startedAt = Date.now();
      const playwright = await runCommand(
        'pnpm',
        ['exec', 'playwright', 'test', ...args.forwarded],
        { cwd: FRONTEND_ROOT, timeoutMs: PLAYWRIGHT_TIMEOUT_MS, inherit: true },
      );
      totalDurationMs = Date.now() - startedAt;

      try {
        const raw = JSON.parse(await readFile(reportPath('results.json'), 'utf8')) as unknown;
        const parsed = parseProjects(raw);
        if (parsed) projects = parsed;
        else infrastructureCause = 'results-invalid';
      } catch {
        infrastructureCause = playwright.timedOut ? 'run-time-exceeded' : 'results-missing';
      }
    }
  } catch (error) {
    infrastructureCause = `runner-error: ${describeError(error)}`;
  }

  await writeServerLog().catch((error: unknown) => {
    console.error(`[e2e] no se pudo escribir server.log: ${describeError(error)}`);
  });

  const artifacts = await readArtifacts();
  const summary = buildRunSummary({
    artifacts,
    projects,
    totalDurationMs,
    stack,
    infrastructureCause,
  });

  await writeJsonReport('summary.json', summary);
  console.log('');
  console.log(formatSummaryTable(summary).join('\n'));

  if (stackStarted) {
    const down = await runCommand('docker', ['compose', 'down'], {
      cwd: REPO_ROOT,
      timeoutMs: COMMAND_TIMEOUT_MS,
    });
    if (down.code !== 0) {
      console.error(`[e2e] no se pudo bajar la pila: ${commandCause('stack-stop-failed', down)}`);
    }
  }

  return summary.exitCode;
}

process.exitCode = await main();
