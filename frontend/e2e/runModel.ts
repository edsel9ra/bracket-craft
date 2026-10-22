/**
 * Modelo puro del runner E2E (T7, RF-004, RF-005, RF-006).
 *
 * Aquí viven las decisiones que no necesitan navegador, pila ni disco:
 * reenvío de argumentos, agregación de los artefactos por vista, veredicto
 * global, traducción a los códigos de salida 0/1/2/3, comprobación de los
 * tiempos máximos declarados y la tabla legible del resumen.
 *
 * **No lee el reloj**: los instantes y las duraciones llegan por parámetro desde
 * el borde (`run.ts`), igual que en `observations.ts`. Tampoco depende de
 * Playwright: la única entrada del veredicto es el artefacto de cada vista y el
 * resultado que el reporter volcó en `results.json`.
 */

import { redactLine, redactLog, type ArtifactVerdict, type ViewArtifact } from './artifacts.ts';
import {
  EXPECTED_VIEWS,
  MAX_MS,
  countSamples,
  countTransitions,
  type ViewId,
} from './observations.ts';

/* -------------------------------------------------------------------------- */
/* Argumentos                                                                 */
/* -------------------------------------------------------------------------- */

export interface RunnerArgs {
  /** Omite el arranque, la siembra y la parada de la pila (`e2e:test`). */
  readonly noStack: boolean;
  /** Argumentos que se reenvían a `playwright test`. */
  readonly forwarded: readonly string[];
}

/**
 * Separa las opciones propias del runner de las que pertenecen a Playwright.
 *
 * Admite las dos formas reales: `run.ts --no-stack -- --grep x` y la que
 * produce `pnpm run e2e:test -- --grep x`, que llega **sin** el separador
 * (`run.ts --no-stack --grep x`). Todo lo que no sea una opción propia se
 * reenvía, de modo que el gate de vistas omitidas se puede demostrar con
 * `--grep`.
 */
export function parseRunnerArgs(argv: readonly string[]): RunnerArgs {
  const separator = argv.indexOf('--');
  const own = separator >= 0 ? argv.slice(0, separator) : argv;
  const after = separator >= 0 ? argv.slice(separator + 1) : [];

  let noStack = false;
  const forwarded: string[] = [];
  for (const argument of own) {
    if (argument === '--no-stack') noStack = true;
    else forwarded.push(argument);
  }

  return { noStack, forwarded: [...forwarded, ...after] };
}

/* -------------------------------------------------------------------------- */
/* Códigos de salida y resultados                                             */
/* -------------------------------------------------------------------------- */

/** Los cuatro veredictos de la corrida (decisión 10 del plan). */
export const EXIT_CODES = {
  green: 0,
  behavioral: 1,
  infrastructure: 2,
  invalid: 3,
} as const;

export type ExitCode = (typeof EXIT_CODES)[keyof typeof EXIT_CODES];

export type RunStatus = 'green' | 'behavioral' | 'infrastructure' | 'invalid';

/** Veredicto de una vista: el del artefacto o `missing` si no llegó a informar. */
export type ViewVerdict = ArtifactVerdict | 'missing';

/** Estado con el que Playwright cerró el test de una vista o la preparación. */
export type PlaywrightStatus =
  | 'passed'
  | 'failed'
  | 'timedOut'
  | 'skipped'
  | 'interrupted'
  | 'missing';

export interface PlaywrightProjectOutcome {
  readonly project: string;
  readonly status: PlaywrightStatus;
  readonly durationMs: number;
}

/* -------------------------------------------------------------------------- */
/* Resumen                                                                    */
/* -------------------------------------------------------------------------- */

export interface RunLimits {
  /** Máximo declarado de una vista (4 min por defecto). */
  readonly viewMs: number;
  /** Máximo declarado de la corrida completa (15 min por defecto). */
  readonly runMs: number;
}

export type StackMode = 'started' | 'external' | 'skipped';

export interface RunStackInfo {
  readonly mode: StackMode;
  /** Duración de arranque y siembra; `null` cuando no se arrancó. */
  readonly durationMs: number | null;
}

export interface ViewSummary {
  readonly view: ViewId;
  readonly verdict: ViewVerdict;
  readonly cause: string | null;
  readonly durationMs: number;
  /** Recuento de **muestras** por estado visible (retrying, connected, error…). */
  readonly states: Readonly<Record<string, number>>;
  /**
   * Número de cambios de estado consecutivos distintos; `null` si la vista no
   * dejó artefacto. Campo aditivo y opcional: `schemaVersion` sigue en 1.
   */
  readonly transitions: number | null;
  /** Recargas observadas por consumidor: 0 o 1 atribuible, nunca el documento. */
  readonly reloads: {
    readonly attributable: number;
    readonly polling: number;
    readonly documentReloads: number;
  } | null;
}

export interface RunSummary {
  readonly schemaVersion: 1;
  readonly status: RunStatus;
  readonly exitCode: ExitCode;
  /** Causa legible y saneada; `null` solo en verde. */
  readonly cause: string | null;
  readonly reasons: readonly string[];
  readonly totalDurationMs: number;
  readonly stack: RunStackInfo;
  readonly limits: RunLimits;
  readonly views: readonly ViewSummary[];
  readonly missing: readonly ViewId[];
}

export interface RunSummaryInput {
  /** Artefactos `view-<vista>.json` que sí se escribieron. */
  readonly artifacts: readonly ViewArtifact[];
  /** Resultado bruto de Playwright por proyecto (`setup`, `public`…). */
  readonly projects: readonly PlaywrightProjectOutcome[];
  /** Duración de la fase de Playwright; la del arranque se informa aparte. */
  readonly totalDurationMs: number;
  readonly stack?: RunStackInfo | undefined;
  /** Fallo previo al informe (arranque, siembra o `results.json` ausente). */
  readonly infrastructureCause?: string | null | undefined;
  readonly limits?: RunLimits | undefined;
  readonly expectedViews?: readonly ViewId[] | undefined;
}

const DEFAULT_LIMITS: RunLimits = { viewMs: MAX_MS.view, runMs: MAX_MS.run };

function sanitizeCause(cause: string | null | undefined): string | null {
  if (cause === null || cause === undefined || cause.trim().length === 0) return null;
  return redactLine(cause.trim());
}

function hasStatus(
  projects: readonly PlaywrightProjectOutcome[],
  project: string,
): PlaywrightProjectOutcome | undefined {
  return projects.find((entry) => entry.project === project);
}

/**
 * Decide el resultado de una vista combinando lo que Playwright informó con el
 * artefacto que dejó el escenario. El artefacto explica **por qué** falló; el
 * estado del test impide declarar verde un spec que falló después de escribir
 * un artefacto correcto (p. ej. una aserción del propio spec).
 */
function evaluateView(input: {
  readonly view: ViewId;
  readonly artifact: ViewArtifact | undefined;
  readonly project: PlaywrightProjectOutcome | undefined;
  readonly limits: RunLimits;
}): ViewSummary {
  const { view, artifact, project, limits } = input;
  const baseDuration = project?.durationMs ?? artifact?.durationMs ?? 0;
  const states = artifact ? countSamples(artifact.states) : {};
  const transitions = artifact ? countTransitions(artifact.states) : null;
  const reloads = artifact
    ? {
        attributable: artifact.reloads.attributable,
        polling: artifact.reloads.polling,
        documentReloads: artifact.reloads.documentReloads,
      }
    : null;

  const summary = (
    verdict: ViewVerdict,
    cause: string | null,
    durationMs = baseDuration,
  ): ViewSummary => ({
    view,
    verdict,
    cause: sanitizeCause(cause),
    durationMs,
    states,
    transitions,
    reloads,
  });

  if (!project) return summary('missing', 'omitted-view');
  if (project.status === 'missing' || project.status === 'skipped') {
    return summary('missing', `omitted-view:${project.status}`);
  }
  if (project.status === 'interrupted') return summary('missing', 'omitted-view:interrupted');
  if (project.status === 'timedOut') return summary('behavioral', 'view-timeout');

  if (project.status === 'failed') {
    if (!artifact) return summary('infrastructure', 'view-failed-without-artifact');
    if (artifact.verdict === 'passed') return summary('behavioral', 'view-assertion-failed');
    return summary(artifact.verdict, artifact.cause ?? `view-${artifact.verdict}`);
  }

  // El test pasó: el veredicto lo da el artefacto. Ausente o ilegible es un
  // fallo del arnés, no una corrida válida.
  if (!artifact) return summary('infrastructure', 'view-artifact-missing');
  const verdict = artifact.verdict;
  const result = summary(verdict, artifact.cause);
  if (verdict === 'passed' && result.durationMs > limits.viewMs) {
    return summary('behavioral', 'view-time-exceeded');
  }
  return result;
}

function setupFailure(
  projects: readonly PlaywrightProjectOutcome[],
  infrastructureCause: string | null,
): string | null {
  if (infrastructureCause) return infrastructureCause;
  const setup = hasStatus(projects, 'setup');
  if (!setup) return 'setup-missing';
  if (setup.status !== 'passed') return `setup-${setup.status}`;
  return null;
}

/**
 * Agrega artefactos y resultados de Playwright en el resumen de la corrida y
 * decide el código de salida:
 *
 * - `2` infraestructura: arranque/siembra fallidos, `results.json` ausente, la
 *   preparación no pasó o una vista no dejó artefacto habiendo ejecutado.
 * - `3` inválida: falta una vista, se saltó o un artefacto se declaró inválido.
 * - `1` comportamiento: clic sin efecto, estado manual ausente, recargas
 *   duplicadas, documento recargado, tiempo máximo superado.
 * - `0` verde: las tres vistas presentes, ejecutadas y `passed`.
 */
export function buildRunSummary(input: RunSummaryInput): RunSummary {
  const expectedViews = input.expectedViews ?? EXPECTED_VIEWS;
  const limits = input.limits ?? DEFAULT_LIMITS;
  const reasons: string[] = [];

  const infrastructure = setupFailure(input.projects, sanitizeCause(input.infrastructureCause));
  if (infrastructure) reasons.push(infrastructure);

  const views = expectedViews.map((view) =>
    evaluateView({
      view,
      artifact: input.artifacts.find((artifact) => artifact.view === view),
      project: hasStatus(input.projects, view),
      limits,
    }),
  );

  for (const view of views) {
    // Con un fallo de arranque o de preparación, las vistas ni siquiera se
    // ejecutaron: la causa raíz es la infraestructura, no una omisión.
    if (!infrastructure && view.verdict !== 'passed' && view.cause) {
      reasons.push(`${view.view}: ${view.cause}`);
    }
  }

  const missing = views.filter((view) => view.verdict === 'missing').map((view) => view.view);

  let status: RunStatus;
  if (infrastructure) status = 'infrastructure';
  else if (missing.length > 0) status = 'invalid';
  else if (views.some((view) => view.verdict === 'invalid')) status = 'invalid';
  else if (views.some((view) => view.verdict === 'infrastructure')) status = 'infrastructure';
  else if (views.some((view) => view.verdict === 'behavioral')) status = 'behavioral';
  else if (input.totalDurationMs > limits.runMs) {
    status = 'behavioral';
    reasons.push('run-time-exceeded');
  } else status = 'green';

  const cause = status === 'green' ? null : sanitizeCause([...new Set(reasons)].join('; '));

  return {
    schemaVersion: 1,
    status,
    exitCode: EXIT_CODES[status],
    cause,
    reasons: [...new Set(reasons)],
    totalDurationMs: input.totalDurationMs,
    stack: input.stack ?? { mode: 'skipped', durationMs: null },
    limits,
    views,
    missing,
  };
}

/* -------------------------------------------------------------------------- */
/* Registro del servidor                                                      */
/* -------------------------------------------------------------------------- */

/**
 * Frase explícita para el `server.log` cuando el entorno no tiene Docker (por
 * ejemplo, el contenedor del arnés de Playwright). RF-006 exige los mismos
 * artefactos en local que en la integración continua: si no se pueden recoger,
 * el propio fichero **declara** la diferencia; nunca se omite en silencio.
 */
export const SERVER_LOG_UNAVAILABLE = 'no disponible: docker CLI ausente';

export interface ServerLogCommandResult {
  readonly code: number | null;
  readonly timedOut: boolean;
  readonly output: string;
}

export interface ServerLogCapture {
  /** `true` solo si el artefacto compuesto contiene evidencia utilizable. */
  readonly available: boolean;
  /** Contenido final del artefacto, saneado y con la cabecera. */
  readonly content: string;
  /** Motivo declarado en el artefacto; `null` cuando sí se recogió. */
  readonly note: string | null;
}

/** Entrada del fallback de integración continua (RF-008). */
export interface ServerLogFallbackInput {
  /** Contenido actual de `server.log`, o `null` si el arnés no lo dejó. */
  readonly existing: string | null;
  /** Salida cruda de `docker compose logs` en este proceso. */
  readonly rawOutput: string;
}

/** Decisión del fallback: conservar el artefacto o escribir uno nuevo. */
export interface ServerLogFallback {
  /** `true` solo si hay que escribir `content`. */
  readonly write: boolean;
  /** Contenido a escribir; `null` cuando se conserva el existente. */
  readonly content: string | null;
}

/** Cabecera exacta del artefacto, escrita por el arnés y por el fallback de CI. */
export const SERVER_LOG_HEADER = '# server.log — docker compose logs --no-color api worker web';

function serverLogBody(lines: readonly string[]): string {
  return `${[SERVER_LOG_HEADER, ...lines].join('\n')}\n`;
}

function withoutTrailingBlankLines(text: string): string {
  return text.replace(/\n+$/, '');
}

/**
 * Decide si un `server.log` **ya contiene evidencia utilizable** (RF-008): la
 * cabecera exacta más al menos una línea de contenido distinta de las
 * declaraciones `# no disponible:`. Ausente, vacío o solo con cabecera no
 * cuenta; la decisión se toma sobre el fichero y nunca sobre el flag ni el
 * código de salida del comando.
 */
export function serverLogIsAvailable(content: string | null | undefined): boolean {
  if (content === null || content === undefined || content.trim().length === 0) return false;

  const [header = '', ...rest] = content.split(/\r?\n/);
  if (header.trimEnd() !== SERVER_LOG_HEADER) return false;
  if (rest.some((line) => line.trimStart().startsWith('# no disponible:'))) return false;

  return rest.some((line) => line.trim().length > 0);
}

function composeServerLogContent(rawOutput: string): string {
  const body = withoutTrailingBlankLines(redactLog(rawOutput));
  return body.trim().length === 0 ? `${SERVER_LOG_HEADER}\n` : `${SERVER_LOG_HEADER}\n${body}\n`;
}

/**
 * Compone el `server.log` del fallback de CI (RF-008).
 *
 * - Con la salida cruda devuelve el artefacto saneado y encabezado.
 * - Con `{ existing, rawOutput }` decide si hay que escribir: un artefacto ya
 *   disponible se conserva (`write: false`) y solo se reescribe cuando falta o
 *   declara no estar disponible.
 */
export function composeServerLog(rawOutput: string): string;
export function composeServerLog(input: ServerLogFallbackInput): ServerLogFallback;
export function composeServerLog(
  input: string | ServerLogFallbackInput,
): string | ServerLogFallback {
  if (typeof input === 'string') return composeServerLogContent(input);
  if (serverLogIsAvailable(input.existing)) return { write: false, content: null };
  return { write: true, content: composeServerLogContent(input.rawOutput) };
}

/**
 * Decide y sanea el registro del servidor local. Función pura: la
 * disponibilidad de Docker y el resultado del comando llegan por parámetro, y el
 * saneado es el mismo `redactLog` que protege al resto de artefactos.
 */
export function buildServerLog(input: {
  readonly dockerAvailable: boolean;
  readonly command: ServerLogCommandResult | null;
}): ServerLogCapture {
  if (!input.dockerAvailable) {
    return {
      available: false,
      content: serverLogBody([`# ${SERVER_LOG_UNAVAILABLE}`]),
      note: SERVER_LOG_UNAVAILABLE,
    };
  }

  const command = input.command;
  if (command === null || command.timedOut || command.code !== 0) {
    const reason =
      command === null
        ? 'no se ejecutó'
        : command.timedOut
          ? 'tiempo agotado'
          : `código ${command.code ?? 'desconocido'}`;
    const note = `no disponible: docker compose logs ${reason}`;
    const output = command === null ? '' : withoutTrailingBlankLines(redactLog(command.output));
    return {
      available: false,
      content: serverLogBody([`# ${note}`, ...(output.length > 0 ? [output] : [])]),
      note,
    };
  }

  const output = withoutTrailingBlankLines(redactLog(command.output));
  const empty = output.trim().length === 0;
  const note = empty ? 'no disponible: docker compose logs sin salida' : null;
  const content = serverLogBody([note === null ? output : `# ${note}`]);
  const available = serverLogIsAvailable(content);

  return { available, content, note: available ? null : note };
}

/* -------------------------------------------------------------------------- */
/* Presentación                                                               */
/* -------------------------------------------------------------------------- */

const EXIT_LABELS: Readonly<Record<RunStatus, string>> = {
  green: 'VERDE',
  behavioral: 'FALLO DE COMPORTAMIENTO',
  infrastructure: 'FALLO DE INFRAESTRUCTURA',
  invalid: 'CORRIDA INVÁLIDA',
};

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function formatSamples(states: Readonly<Record<string, number>>): string {
  const entries = Object.entries(states);
  if (entries.length === 0) return '-';
  return entries.map(([status, count]) => `${status}=${count}`).join(' ');
}

function formatTransitions(transitions: number | null): string {
  return transitions === null ? '-' : String(transitions);
}

function formatReloads(reloads: ViewSummary['reloads']): string {
  if (!reloads) return '-';
  return `attr=${reloads.attributable} poll=${reloads.polling} doc=${reloads.documentReloads}`;
}

/**
 * Tabla legible para la salida del runner: vista, veredicto, duración,
 * **muestras**, **transiciones** y recargas. La causa de cada vista no verde va
 * debajo. Las cabeceras separan explícitamente ambas cifras (RF-006).
 */
export function formatSummaryTable(summary: RunSummary): readonly string[] {
  const header = ['VISTA', 'RESULTADO', 'DURACIÓN', 'MUESTRAS', 'TRANSICIONES', 'RECARGAS'];
  const rows = summary.views.map((view) => [
    view.view,
    view.verdict,
    formatDuration(view.durationMs),
    formatSamples(view.states),
    formatTransitions(view.transitions),
    formatReloads(view.reloads),
  ]);

  const widths = header.map((title, column) =>
    Math.max(title.length, ...rows.map((row) => row[column]?.length ?? 0)),
  );
  const render = (row: readonly string[]): string =>
    row
      .map((cell, column) => cell.padEnd(widths[column] ?? cell.length))
      .join('  ')
      .trimEnd();

  const lines = [render(header), render(widths.map((width) => '-'.repeat(width)))];
  for (const row of rows) lines.push(render(row));

  lines.push('');
  const stack =
    summary.stack.mode === 'started'
      ? `arranque ${formatDuration(summary.stack.durationMs ?? 0)}`
      : summary.stack.mode === 'external'
        ? 'pila externa ya levantada'
        : 'sin arranque (--no-stack)';
  lines.push(`TOTAL ${formatDuration(summary.totalDurationMs)} · ${stack}`);
  lines.push(`RESULTADO: ${EXIT_LABELS[summary.status]} (${summary.exitCode})`);
  if (summary.cause) lines.push(`CAUSA: ${summary.cause}`);

  return lines;
}
