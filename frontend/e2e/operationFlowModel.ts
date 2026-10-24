/**
 * Modelo puro del escenario E2E de operación y cierre (spec 012, H4-T10;
 * RF-043, RF-045, RF-050, RF-051, RF-012, RNF-005, RNF-008).
 *
 * El escenario **no** reutiliza el artefacto del reintento: este módulo define
 * su propio artefacto con el mismo `schemaVersion`, el mismo contrato de
 * veredicto (`passed`, `behavioral`, `infrastructure`, `invalid`), sus muestras
 * de estado y el número de transiciones. `states` son **muestras** (cuántas
 * veces se observó cada hito) y `transitions` son los cambios consecutivos
 * distintos, con la misma semántica que el resumen del arnés de reintento.
 *
 * No lee el reloj, el entorno, el almacenamiento ni la red: los instantes y las
 * duraciones llegan por parámetro desde el borde del navegador. Tampoco depende
 * de Playwright, de modo que sus funciones se prueban con `node --test`.
 */

import { redactLine } from './artifacts.ts';

/** Nombre de la vista del escenario nuevo. No compite con `EXPECTED_VIEWS`. */
export const OPERATION_FLOW_VIEW = 'operation-flow' as const;

/** Proyecto de Playwright que ejecuta el escenario nuevo. */
export const OPERATION_FLOW_PROJECT = 'operation-flow' as const;

/**
 * Hitos verificados por el escenario, en el orden en que se registran. Cada uno
 * es una muestra de estado, no una transición: si un paso se repite, suma.
 */
export const OPERATION_FLOW_STATES = [
  'rules-read-only',
  'rules-format-default',
  'rules-format-warning',
  'rules-error-announced',
  'rules-error-cleared',
  'rules-saved',
  'summary-format-warning',
  'enrollment-blocked',
  'enrollment-rejected',
  'operation-format-warning',
  'opening-blocked',
  'version-published',
  'roster-players-added',
  'segment-opened',
  'lineup-saved',
  'event-at-limit',
  'segment-at-limit',
  'segment-limit-announced',
  'event-limit-announced',
  'report-closed',
  'roster-retired',
  'roster-reactivated',
  'roster-lock-absent',
  'roster-created-without-lock',
  'roster-lock-visible',
  'roster-create-locked',
  'wizard-keyboard-rules',
  'wizard-keyboard-phases',
  'wizard-keyboard-teams',
  'wizard-error-associated',
  'wizard-error-corrected',
  'wizard-back-navigation',
] as const;

export type OperationFlowState = (typeof OPERATION_FLOW_STATES)[number];

/** Veredictos del escenario; mismos cuatro valores que el arnés de reintento. */
export type OperationFlowVerdict = 'passed' | 'behavioral' | 'infrastructure' | 'invalid';

export interface OperationFlowSample {
  readonly status: OperationFlowState;
  readonly at: number;
}

export interface OperationFlowArtifact {
  readonly schemaVersion: 1;
  readonly view: typeof OPERATION_FLOW_VIEW;
  readonly verdict: OperationFlowVerdict;
  readonly cause: string | null;
  readonly durationMs: number;
  readonly states: readonly OperationFlowSample[];
  /** Cambios consecutivos distintos; se deriva de `states`. */
  readonly transitions: number;
}

export interface OperationFlowArtifactInput {
  readonly verdict: OperationFlowVerdict;
  readonly cause?: string | null;
  readonly durationMs: number;
  readonly states: readonly OperationFlowSample[];
}

const STATE_SET: ReadonlySet<string> = new Set(OPERATION_FLOW_STATES);
const VERDICTS: ReadonlySet<string> = new Set([
  'passed',
  'behavioral',
  'infrastructure',
  'invalid',
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/**
 * Recuento de muestras por estado. Una muestra repetida suma: describe cuántas
 * veces se verificó el hito, no cuántas veces cambió.
 */
export function countFlowSamples(
  states: readonly OperationFlowSample[],
): Readonly<Record<string, number>> {
  const counts: Record<string, number> = {};
  for (const sample of states) {
    counts[sample.status] = (counts[sample.status] ?? 0) + 1;
  }
  return counts;
}

/**
 * Transiciones de estado: pares consecutivos con estado distinto. El primer
 * elemento no cuenta y una muestra repetida tampoco. Misma regla que
 * `countTransitions` del arnés de reintento.
 */
export function countFlowTransitions(states: readonly OperationFlowSample[]): number {
  let transitions = 0;
  for (let index = 1; index < states.length; index += 1) {
    const previous = states[index - 1];
    const current = states[index];
    if (previous && current && previous.status !== current.status) transitions += 1;
  }
  return transitions;
}

/** Construye el artefacto saneado; no lee el reloj ni modifica las muestras. */
export function buildOperationFlowArtifact(
  input: OperationFlowArtifactInput,
): OperationFlowArtifact {
  const states = [...input.states].sort((left, right) => left.at - right.at);
  return {
    schemaVersion: 1,
    view: OPERATION_FLOW_VIEW,
    verdict: input.verdict,
    cause: input.cause ? redactLine(input.cause) : null,
    durationMs: Math.max(0, Math.round(input.durationMs)),
    states,
    transitions: countFlowTransitions(states),
  };
}

/**
 * Valida lo mínimo que consume el runner: esquema, vista, veredicto, muestras
 * conocidas y transiciones derivadas. Un artefacto corrupto se descarta.
 */
export function isOperationFlowArtifact(value: unknown): value is OperationFlowArtifact {
  if (!isRecord(value)) return false;
  if (value['schemaVersion'] !== 1) return false;
  if (value['view'] !== OPERATION_FLOW_VIEW) return false;
  if (typeof value['verdict'] !== 'string' || !VERDICTS.has(value['verdict'])) return false;
  if (!(value['cause'] === null || typeof value['cause'] === 'string')) return false;
  if (typeof value['durationMs'] !== 'number' || !Number.isFinite(value['durationMs'])) return false;
  if (typeof value['transitions'] !== 'number' || !Number.isInteger(value['transitions'])) {
    return false;
  }
  const states = value['states'];
  if (!Array.isArray(states)) return false;
  const samples: OperationFlowSample[] = [];
  for (const entry of states) {
    if (!isRecord(entry)) return false;
    const status = entry['status'];
    const at = entry['at'];
    if (typeof status !== 'string' || !STATE_SET.has(status)) return false;
    if (typeof at !== 'number' || !Number.isFinite(at)) return false;
    samples.push({ status: status as OperationFlowState, at });
  }
  return countFlowTransitions(samples) === value['transitions'];
}
