/**
 * Observaciones puras del arnés E2E del reintento manual del tiempo real.
 *
 * Sin dependencias de Playwright, sin DOM y **sin leer el reloj**: todos los
 * instantes, ventanas y duraciones llegan por parámetro desde el borde del
 * arnés (`channel.ts`, `realtimeScenario.ts` y `artifacts.ts`). Así el orden del
 * escenario, la clasificación de recargas y los recuentos de conexión se
 * verifican con `node --test`, sin navegador (RNF-001, RF-002).
 */

import type { RealtimeLabelNamespace } from '../app/utils/realtimeStatusLabel.ts';

/** Vistas que ejecutan el escenario (RF-003). El orden es el de la corrida. */
export const EXPECTED_VIEWS = ['public', 'workspace', 'operation'] as const;

export type ViewId = (typeof EXPECTED_VIEWS)[number];

/** Identificadores descubiertos por la API pública en la preparación. */
export interface DemoIdentifiers {
  readonly tournamentId: string;
  readonly matchId: string;
}

/**
 * Definición de una vista: su URL real, el namespace de sus etiquetas visibles
 * y el endpoint del consumidor cuya recarga se mide (RNF-005, RF-002).
 */
export interface ViewDefinition {
  readonly id: ViewId;
  readonly namespace: RealtimeLabelNamespace;
  readonly url: (ids: DemoIdentifiers) => string;
  readonly endpoint: (ids: DemoIdentifiers) => string;
  readonly timeoutMs: number;
}

export const VIEWS: Readonly<Record<ViewId, ViewDefinition>> = {
  public: {
    id: 'public',
    namespace: 'public',
    url: (ids) => `/tournaments/${encodeURIComponent(ids.tournamentId)}`,
    endpoint: (ids) => `/api/v1/tournaments/public/${encodeURIComponent(ids.tournamentId)}`,
    timeoutMs: 240_000,
  },
  workspace: {
    id: 'workspace',
    namespace: 'workspace',
    url: () => '/workspace',
    endpoint: () => '/api/v1/tournaments',
    timeoutMs: 240_000,
  },
  operation: {
    id: 'operation',
    namespace: 'match',
    url: (ids) => `/workspace/matches/${encodeURIComponent(ids.matchId)}`,
    endpoint: (ids) => `/api/v1/matches/${encodeURIComponent(ids.matchId)}/operation`,
    timeoutMs: 240_000,
  },
};

/**
 * Tiempos máximos declarados por condición (plan, «Tiempos máximos»). Cada
 * espera del escenario nombra su condición; ninguna es una espera fija.
 */
export const MAX_MS = {
  warmup: 120_000,
  initialConnected: 45_000,
  errorVisible: 15_000,
  manualVisible: 3_000,
  attemptFailed: 15_000,
  reconnect: 30_000,
  settle: 3_000,
  reloadWindow: 6_000,
  view: 240_000,
  run: 15 * 60_000,
  stackStart: 5 * 60_000,
  job: 25 * 60_000,
} as const satisfies Record<string, number>;

export type ScenarioCondition = keyof typeof MAX_MS;

/**
 * Tope en milisegundos de una condición. La condición `view` admite la vista
 * para leer su propio tope de `test`; el resto son iguales en las tres vistas.
 */
export function maxMillis(condition: ScenarioCondition, view?: ViewId): number {
  if (condition === 'view' && view) return VIEWS[view].timeoutMs;
  return MAX_MS[condition];
}

/* -------------------------------------------------------------------------- */
/* Recargas                                                                   */
/* -------------------------------------------------------------------------- */

/** Una petición observada por el navegador: ruta sin consulta y su instante. */
export interface ReloadRequest {
  readonly path: string;
  readonly at: number;
}

export interface ReloadClassificationInput {
  readonly requests: readonly ReloadRequest[];
  readonly endpoints: readonly string[];
  readonly connectedAt: number;
  readonly windowMs: number;
  readonly pollingIntervalMs: number;
  /** Navegaciones del frame principal (`framenavigated`); su valor esperado es 0. */
  readonly documentNavigations?: readonly number[];
}

export interface EndpointReloads {
  /** Si el consumidor recargó dentro de la ventana posterior a `connected`. */
  readonly attributable: boolean;
  /** Peticiones del consumidor dentro de la ventana (más de una es duplicado). */
  readonly inWindow: number;
  /** Peticiones fuera de la ventana y con cadencia de sondeo (informativas). */
  readonly polling: number;
}

export interface ReloadClassification {
  /** Consumidores que recargaron dentro de la ventana: como máximo 1 por consumidor. */
  readonly attributable: number;
  /** Recargas sobrantes del mismo consumidor en la misma ventana (fallo). */
  readonly duplicates: number;
  /** Sondeo periódico fuera de la ventana (informativo, no es recarga). */
  readonly polling: number;
  /** Peticiones previas a `connected` (carga inicial, no atribuibles). */
  readonly beforeConnected: number;
  /** Peticiones fuera de la ventana pero antes del primer sondeo previsto. */
  readonly unclassified: number;
  /** Navegaciones del documento: ninguna es admisible (0 esperado). */
  readonly documentReloads: number;
  readonly byEndpoint: Readonly<Record<string, EndpointReloads>>;
}

function pathnameOf(path: string): string {
  const end = path.search(/[?#]/);
  return end >= 0 ? path.slice(0, end) : path;
}

/**
 * `endpoint` coincide con la ruta exacta o con un prefijo de segmento, nunca
 * con una ruta que solo comparta caracteres (`/tournaments` no captura
 * `/tournamentsX`). El consumidor se elige por el prefijo más largo.
 */
function matchEndpoint(pathname: string, endpoints: readonly string[]): string | null {
  let best: string | null = null;
  let bestLength = -1;
  for (const endpoint of endpoints) {
    const base = pathnameOf(endpoint).replace(/\/+$/, '');
    if (base.length <= bestLength) continue;
    if (pathname === base || pathname.startsWith(`${base}/`)) {
      best = endpoint;
      bestLength = base.length;
    }
  }
  return best;
}

function isInWindow(at: number, connectedAt: number, windowMs: number): boolean {
  return at >= connectedAt && at <= connectedAt + windowMs;
}

/** Grupo ya filtrado por consumidor: más de una petición en la ventana es duplicado. */
export interface ReloadGroup {
  readonly requests: readonly ReloadRequest[];
  readonly connectedAt: number;
  readonly windowMs: number;
}

export function isDuplicateReload(group: ReloadGroup): boolean {
  let inWindow = 0;
  for (const request of group.requests) {
    if (isInWindow(request.at, group.connectedAt, group.windowMs)) {
      inWindow += 1;
      if (inWindow > 1) return true;
    }
  }
  return false;
}

/**
 * Clasifica las recargas por consumidor y por instante respecto a `connected`:
 *
 * - `attributable`: primer consumo dentro de la ventana posterior a la reconexión.
 * - `duplicates`: segunda recarga del mismo consumidor en esa ventana (fallo).
 * - `polling`: fuera de la ventana y con al menos un intervalo de sondeo de
 *   separación (el sondeo periódico de la página pública, informativo).
 * - `beforeConnected`: anteriores a la reconexión (carga inicial).
 * - `unclassified`: fuera de la ventana pero antes del primer sondeo previsto.
 *
 * Ninguna navegación del documento es una recarga atribuible: se cuentan aparte
 * (`documentReloads`, desde `framenavigated` del frame principal) y su valor
 * esperado es 0 (RF-002).
 */
export function classifyReloads(input: ReloadClassificationInput): ReloadClassification {
  const counts = new Map<string, { inWindow: number; polling: number }>();
  for (const endpoint of input.endpoints) {
    counts.set(endpoint, { inWindow: 0, polling: 0 });
  }

  let duplicates = 0;
  let polling = 0;
  let beforeConnected = 0;
  let unclassified = 0;

  for (const request of input.requests) {
    const endpoint = matchEndpoint(pathnameOf(request.path), input.endpoints);
    if (endpoint === null) continue;

    const bucket = counts.get(endpoint);
    if (!bucket) continue;

    if (request.at < input.connectedAt) {
      beforeConnected += 1;
      continue;
    }

    if (isInWindow(request.at, input.connectedAt, input.windowMs)) {
      bucket.inWindow += 1;
      continue;
    }

    if (request.at - input.connectedAt >= input.pollingIntervalMs) {
      bucket.polling += 1;
      polling += 1;
      continue;
    }

    unclassified += 1;
  }

  for (const bucket of counts.values()) {
    if (bucket.inWindow > 1) duplicates += bucket.inWindow - 1;
  }

  const byEndpoint: Record<string, EndpointReloads> = {};
  let attributable = 0;
  for (const [endpoint, bucket] of counts) {
    byEndpoint[endpoint] = {
      attributable: bucket.inWindow > 0,
      inWindow: bucket.inWindow,
      polling: bucket.polling,
    };
    if (bucket.inWindow > 0) attributable += 1;
  }

  return {
    attributable,
    duplicates,
    polling,
    beforeConnected,
    unclassified,
    documentReloads: input.documentNavigations?.length ?? 0,
    byEndpoint,
  };
}

/* -------------------------------------------------------------------------- */
/* Orden del escenario                                                        */
/* -------------------------------------------------------------------------- */

/** Marcas de un ciclo de pulsación: clic, inicio del intento, manual y su fin. */
export interface CycleMarks {
  readonly clickedAt: number;
  readonly attemptStartedAt: number;
  readonly manualVisibleAt: number;
  readonly manualGoneAt: number;
}

/** Marcas del escenario completo, tomadas en el borde con el reloj del arnés. */
export interface ScenarioMarks {
  readonly connectedOnceAt: number;
  readonly blockedAt: number;
  readonly closedAt: number;
  readonly errorVisibleAt: number;
  readonly cycles: readonly CycleMarks[];
  readonly unblockedAt: number;
  readonly connectedAt: number;
  readonly settledAt: number;
  /** Primera recarga atribuible, si se observó alguna. */
  readonly firstReloadAt?: number;
}

export type ScenarioViolation =
  | 'blocked-without-connection'
  | 'close-before-block'
  | 'error-before-close'
  | 'click-before-error'
  | 'attempt-before-click'
  | 'manual-before-click'
  | 'manual-before-attempt'
  | 'manual-gone-before-visible'
  | 'manual-survived'
  | 'connected-without-manual'
  | 'connected-while-blocked'
  | 'settled-before-connected'
  | 'reload-before-reconnect';

/**
 * Violaciones del orden canónico. Una lista vacía es una corrida con la
 * secuencia completa: conexión aceptada antes del bloqueo, error antes del
 * clic, manual después del inicio del intento y antes de desbloquear, y
 * reconexión posterior al desbloqueo (RNF-001, RNF-007).
 */
export function assertScenarioOrder(marks: ScenarioMarks): readonly ScenarioViolation[] {
  const violations = new Set<ScenarioViolation>();

  if (marks.connectedOnceAt >= marks.blockedAt) violations.add('blocked-without-connection');
  if (marks.closedAt < marks.blockedAt) violations.add('close-before-block');
  if (marks.errorVisibleAt < marks.closedAt) violations.add('error-before-close');

  if (marks.cycles.length === 0) violations.add('connected-without-manual');

  for (const cycle of marks.cycles) {
    if (cycle.clickedAt < marks.errorVisibleAt) violations.add('click-before-error');
    if (cycle.attemptStartedAt < cycle.clickedAt) violations.add('attempt-before-click');
    if (cycle.manualVisibleAt < cycle.clickedAt) violations.add('manual-before-click');
    else if (cycle.manualVisibleAt < cycle.attemptStartedAt) {
      violations.add('manual-before-attempt');
    }
    if (cycle.manualGoneAt < cycle.manualVisibleAt) {
      violations.add('manual-gone-before-visible');
    }
    if (cycle.manualVisibleAt >= marks.unblockedAt || cycle.manualGoneAt > marks.unblockedAt) {
      violations.add('manual-survived');
    }
  }

  if (marks.connectedAt <= marks.unblockedAt) violations.add('connected-while-blocked');
  if (marks.settledAt < marks.connectedAt) violations.add('settled-before-connected');
  if (marks.firstReloadAt !== undefined && marks.firstReloadAt < marks.connectedAt) {
    violations.add('reload-before-reconnect');
  }

  return [...violations];
}

/* -------------------------------------------------------------------------- */
/* Conexiones                                                                 */
/* -------------------------------------------------------------------------- */

export interface ConnectionCount {
  /** Conexión inicial aceptada más la que queda tras la última pulsación. */
  readonly established: number;
  /** Ningún intento bloqueado llega a establecer transporte. */
  readonly establishedDuringBlock: number;
}

/**
 * Conexiones persistentes esperadas. Cada intento hecho con el canal bloqueado
 * cuenta como intento, nunca como conexión establecida: solo la inicial y la
 * que queda conectada al final son transporte real (Q3, punto 3 de QA).
 */
export function expectedConnectionCount(input: { readonly cycles: number }): ConnectionCount {
  return {
    established: input.cycles > 0 ? 2 : 1,
    establishedDuringBlock: 0,
  };
}
