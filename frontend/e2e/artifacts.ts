/**
 * Artefactos de diagnóstico del arnés E2E (RF-005, RNF-006).
 *
 * Se publica una traza **propia** (`trace-<vista>.jsonl`, una por vista) en
 * lugar de la de Playwright: `trace.zip` incrusta cabeceras con cookies y no
 * admite saneado soportado. Por construcción aquí solo hay método, ruta sin
 * consulta, estado e instante; ni cabeceras, ni cuerpos, ni credenciales. Las
 * capturas son de la interfaz y el registro del servidor pasa por `redactLog`.
 *
 * Todo lo que depende del tiempo recibe el instante por parámetro: la lógica es
 * pura y las funciones que escriben no leen el reloj.
 */

import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import type { Page } from '@playwright/test';

import type { VisibleRealtimeStatus } from './labels.ts';
import type {
  ConnectionCount,
  CycleMarks,
  ReloadClassification,
  ScenarioMarks,
  ViewId,
} from './observations.ts';

/* -------------------------------------------------------------------------- */
/* Saneado                                                                    */
/* -------------------------------------------------------------------------- */

/** Marca que sustituye cualquier valor sensible. */
export const REDACTED = '[REDACTED]';

const HEADER_NAMES =
  'set-cookie|cookie|authorization|proxy-authorization|x-csrf-token|x-xsrf-token';
const SENSITIVE_NAMES =
  'password|passwd|token|access_token|refresh_token|bc_csrf_token|csrf_token';

/**
 * `Cookie`, `Set-Cookie`, `Authorization` y las cabeceras CSRF: se retira el
 * nombre, los dos puntos y el valor hasta el final de la línea, de modo que ni
 * siquiera la palabra `Cookie` llegue a un artefacto publicado. El delimitador
 * anterior (espacio, paréntesis, coma…) se conserva.
 */
const HEADER_VALUE = new RegExp(
  `((?:^|[\\s\\[{(,;"']))["']?(?:${HEADER_NAMES})["']?\\s*:\\s*(?:"[^"]*"|'[^']*'|[^\\r\\n]+)`,
  'gi',
);

/** Pares JSON `"password": "..."`, `"bc_csrf_token": "..."`, etc. */
const SENSITIVE_JSON_PAIR = new RegExp(
  `((?:^|[{,;\\[\\s]))["'](?:${SENSITIVE_NAMES})["']\\s*:\\s*(?:"[^"]*"|'[^']*'|[^\\s,;}]+)`,
  'gi',
);

/** Asignaciones de consulta o formulario `token=...`, `password=...`, etc. */
const SENSITIVE_ASSIGNMENT = new RegExp(
  `((?:^|[\\s?&;,"'{]))(?:${SENSITIVE_NAMES})\\s*=\\s*(?:"[^"]*"|'[^']*'|[^\\s&;,"'}]+)`,
  'gi',
);

/**
 * Elimina de una línea el nombre y el valor de cookie, `Set-Cookie`,
 * `Authorization`, `token`, `bc_csrf_token` y `password`, y deja intacto el
 * resto de la línea. No consulta ninguna fuente externa ni el entorno.
 */
export function redactLine(line: string): string {
  return line
    .replace(HEADER_VALUE, `$1${REDACTED}`)
    .replace(SENSITIVE_JSON_PAIR, `$1${REDACTED}`)
    .replace(SENSITIVE_ASSIGNMENT, `$1${REDACTED}`);
}

/** Aplica `redactLine` a cada línea del registro del servidor, sin quitarlas. */
export function redactLog(text: string): string {
  return text.split('\n').map(redactLine).join('\n');
}

/**
 * Ruta sin consulta ni fragmento. Las URLs absolutas se reducen a su `pathname`,
 * de modo que ni el host ni un token en la consulta llegan al artefacto.
 */
export function redactPath(path: string): string {
  const withoutHash = path.split('#')[0] ?? '';
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(withoutHash)) {
    try {
      return new URL(withoutHash).pathname;
    } catch {
      // Una URL inválida cae al tratamiento por ruta.
    }
  }
  const queryStart = withoutHash.indexOf('?');
  const pathname = queryStart >= 0 ? withoutHash.slice(0, queryStart) : withoutHash;
  if (pathname === '') return '/';
  return pathname.startsWith('/') ? pathname : `/${pathname}`;
}

/* -------------------------------------------------------------------------- */
/* Estados observados                                                         */
/* -------------------------------------------------------------------------- */

/** Un estado visible con el instante en que se observó (reloj del arnés). */
export interface StateSample {
  readonly status: VisibleRealtimeStatus;
  readonly at: number;
}

/** Estado con su ciclo de pulsación y su distancia a la pulsación y al intento. */
export interface StateObservation extends StateSample {
  readonly cycle: number | null;
  readonly relativeToClickMs: number | null;
  readonly relativeToAttemptMs: number | null;
}

/**
 * Sitúa cada estado respecto al último clic anterior: es lo que permite
 * reconstruir que el estado manual aparece **después** de la pulsación y que
 * desaparece al volver a error o al conectar (RF-005).
 */
export function observeStates(
  states: readonly StateSample[],
  cycles: readonly CycleMarks[],
): readonly StateObservation[] {
  return states.map((state) => {
    let index = -1;
    for (let position = 0; position < cycles.length; position += 1) {
      const cycle = cycles[position];
      if (cycle && state.at >= cycle.clickedAt) index = position;
    }

    const cycle = index >= 0 ? cycles[index] : undefined;
    if (!cycle) {
      return { ...state, cycle: null, relativeToClickMs: null, relativeToAttemptMs: null };
    }
    return {
      ...state,
      cycle: index,
      relativeToClickMs: state.at - cycle.clickedAt,
      relativeToAttemptMs: state.at - cycle.attemptStartedAt,
    };
  });
}

/* -------------------------------------------------------------------------- */
/* Artefacto por vista                                                        */
/* -------------------------------------------------------------------------- */

export type ArtifactVerdict = 'passed' | 'behavioral' | 'infrastructure' | 'invalid';

export type ReloadOrigin = 'reconnect' | 'polling' | 'none';

export interface ConsumerReloads {
  readonly attributable: boolean;
  readonly inWindow: number;
  readonly polling: number;
  readonly origin: ReloadOrigin;
}

/** Recargas clasificadas por consumidor, con su origen (RF-002, RF-005). */
export interface ArtifactReloads {
  readonly attributable: number;
  readonly duplicates: number;
  readonly polling: number;
  readonly beforeConnected: number;
  readonly unclassified: number;
  readonly documentReloads: number;
  readonly byEndpoint: Readonly<Record<string, ConsumerReloads>>;
}

export interface ViewArtifact {
  readonly schemaVersion: 1;
  readonly view: ViewId;
  readonly verdict: ArtifactVerdict;
  readonly cause: string | null;
  readonly durationMs: number;
  readonly states: readonly StateObservation[];
  readonly marks: ScenarioMarks;
  readonly connections: ConnectionCount;
  readonly attempts: number;
  readonly reloads: ArtifactReloads;
}

export interface ViewArtifactInput {
  readonly view: ViewId;
  readonly verdict: ArtifactVerdict;
  readonly cause?: string | null;
  readonly durationMs: number;
  readonly states: readonly StateSample[];
  readonly marks: ScenarioMarks;
  readonly connections: ConnectionCount;
  readonly attempts: number;
  readonly reloads: ReloadClassification;
}

function toArtifactReloads(reloads: ReloadClassification): ArtifactReloads {
  const byEndpoint: Record<string, ConsumerReloads> = {};
  for (const [endpoint, entry] of Object.entries(reloads.byEndpoint)) {
    byEndpoint[endpoint] = {
      attributable: entry.attributable,
      inWindow: entry.inWindow,
      polling: entry.polling,
      origin: entry.attributable ? 'reconnect' : entry.polling > 0 ? 'polling' : 'none',
    };
  }
  return {
    attributable: reloads.attributable,
    duplicates: reloads.duplicates,
    polling: reloads.polling,
    beforeConnected: reloads.beforeConnected,
    unclassified: reloads.unclassified,
    documentReloads: reloads.documentReloads,
    byEndpoint,
  };
}

/**
 * Construye el JSON de una vista: estados con su instante respecto a la
 * pulsación y al inicio del intento, marcas, conexiones, recargas por origen,
 * documento y veredicto con su causa. Sin cabeceras por construcción y con la
 * causa saneada.
 */
export function buildViewArtifact(input: ViewArtifactInput): ViewArtifact {
  return {
    schemaVersion: 1,
    view: input.view,
    verdict: input.verdict,
    cause: input.cause ? redactLine(input.cause) : null,
    durationMs: input.durationMs,
    states: observeStates(input.states, input.marks.cycles),
    marks: input.marks,
    connections: input.connections,
    attempts: input.attempts,
    reloads: toArtifactReloads(input.reloads),
  };
}

/* -------------------------------------------------------------------------- */
/* Traza propia sin cabeceras                                                 */
/* -------------------------------------------------------------------------- */

export interface TraceRequestEntry {
  readonly type: 'request';
  readonly at: number;
  readonly method: string;
  readonly path: string;
  readonly status: number | null;
}

export interface TraceNavigationEntry {
  readonly type: 'navigation';
  readonly at: number;
  readonly path: string;
}

export interface TraceWebSocketEntry {
  readonly type: 'websocket';
  readonly at: number;
  readonly action: 'open' | 'close';
  readonly path: string;
}

export interface TraceConsoleEntry {
  readonly type: 'console';
  readonly at: number;
  readonly level: string;
  readonly text: string;
}

export interface TracePageErrorEntry {
  readonly type: 'pageerror';
  readonly at: number;
  readonly text: string;
}

export type TraceEntry =
  | TraceRequestEntry
  | TraceNavigationEntry
  | TraceWebSocketEntry
  | TraceConsoleEntry
  | TracePageErrorEntry;

/** Petición registrada solo con método, ruta sin consulta y estado. */
export function traceRequest(input: {
  readonly at: number;
  readonly method: string;
  readonly url: string;
  readonly status: number | null;
}): TraceRequestEntry {
  return {
    type: 'request',
    at: input.at,
    method: input.method.toUpperCase(),
    path: redactPath(input.url),
    status: input.status,
  };
}

export function traceNavigation(input: {
  readonly at: number;
  readonly url: string;
}): TraceNavigationEntry {
  return { type: 'navigation', at: input.at, path: redactPath(input.url) };
}

export function traceWebSocket(input: {
  readonly at: number;
  readonly action: 'open' | 'close';
  readonly url: string;
}): TraceWebSocketEntry {
  return { type: 'websocket', at: input.at, action: input.action, path: redactPath(input.url) };
}

export function traceConsole(input: {
  readonly at: number;
  readonly level: string;
  readonly text: string;
}): TraceConsoleEntry {
  return { type: 'console', at: input.at, level: input.level, text: redactLine(input.text) };
}

export function tracePageError(input: { readonly at: number; readonly text: string }): TracePageErrorEntry {
  return { type: 'pageerror', at: input.at, text: redactLine(input.text) };
}

/** Una entrada por línea, en JSON, sin cabeceras ni cuerpos. */
export function traceLine(entry: TraceEntry): string {
  return JSON.stringify(entry);
}

/* -------------------------------------------------------------------------- */
/* Escritura (siempre fuera de lo versionado: `e2e-report/`)                   */
/* -------------------------------------------------------------------------- */

/** Directorio de artefactos de la corrida, ignorado por git. */
export const REPORT_DIR = fileURLToPath(new URL('../e2e-report', import.meta.url));

export function reportPath(...segments: readonly string[]): string {
  return join(REPORT_DIR, ...segments);
}

async function writeReportFile(file: string, content: string): Promise<string> {
  await mkdir(dirname(file), { recursive: true });
  await writeFile(file, content, 'utf8');
  return file;
}

/** Escritor JSON genérico (`view-<vista>.json`, `summary.json`). */
export function writeJsonReport(fileName: string, value: unknown): Promise<string> {
  return writeReportFile(reportPath(fileName), `${JSON.stringify(value, null, 2)}\n`);
}

export function writeViewArtifact(artifact: ViewArtifact): Promise<string> {
  return writeJsonReport(`view-${artifact.view}.json`, artifact);
}

/**
 * Nombre de la traza de una vista. Un fichero **por vista**: la corrida ejecuta
 * las tres en serie y un único `trace.jsonl` haría que la última pisara a las
 * anteriores, de modo que en un fallo se perdería la traza de la vista que falló
 * (B2 de la validación). La consola del navegador viaja en este mismo JSONL con
 * `type: 'console'`, así que tampoco se comparte entre vistas.
 */
export function traceFileName(view: ViewId | string): string {
  return `trace-${view}.jsonl`;
}

/** Vuelca la traza propia de una vista; una entrada JSON por línea. */
export function writeTrace(entries: readonly TraceEntry[], fileName: string): Promise<string> {
  const body = entries.length > 0 ? `${entries.map(traceLine).join('\n')}\n` : '';
  return writeReportFile(reportPath(fileName), body);
}

/** Escritura de un artefacto de texto ya saneado (`server.log`, por ejemplo). */
export function writeTextReport(fileName: string, content: string): Promise<string> {
  const body = content.endsWith('\n') ? content : `${content}\n`;
  return writeReportFile(reportPath(fileName), body);
}

/** Captura de la interfaz (viewport, no la página completa ni herramientas). */
export async function captureScreenshot(page: Page, view: ViewId | string): Promise<string> {
  const file = reportPath('screenshots', `${view}.png`);
  await mkdir(dirname(file), { recursive: true });
  await page.screenshot({ path: file, fullPage: false });
  return file;
}
