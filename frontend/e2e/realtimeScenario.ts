/**
 * Escenario determinista del reintento manual del tiempo real (RF-001,
 * RF-002, RF-006, RNF-001).
 *
 * Orden fijo, sin esperas fijas arbitrarias: cada paso espera una condición
 * observable con su tope declarado en `observations.ts`:
 *
 *   conectar → bloquear el canal → cerrar el transporte interceptado → error
 *   visible → [clic con el canal bloqueado → intento nuevo → estado manual →
 *   liberar → error] × 2 → desbloquear → conectado → asentamiento → recuentos
 *   y recargas.
 *
 * El estado manual es **producto**: se observa por el texto y el rol de la
 * interfaz, nunca por estado interno, ganchos ni variables globales. Si no
 * aparece después del clic es un **fallo de comportamiento**; si antes del clic
 * no hay error, el canal no estaba bloqueado o no hubo conexión aceptada antes
 * del bloqueo, la corrida es **inválida** con su causa en el artefacto.
 */

import { expect, type BrowserContext, type Page } from '@playwright/test';

import {
  buildViewArtifact,
  captureScreenshot,
  reportPath,
  traceConsole,
  traceFileName,
  tracePageError,
  writeTrace,
  writeViewArtifact,
  type ArtifactVerdict,
  type TraceEntry,
  type ViewArtifact,
} from './artifacts.ts';
import { createChannelGate, type ChannelGate } from './channel.ts';
import {
  E2E_LABELS,
  REALTIME_STATUS_TEXT,
  labelText,
  localeCookie,
  type VisibleRealtimeStatus,
} from './labels.ts';
import {
  MAX_MS,
  VIEWS,
  assertScenarioOrder,
  classifyReloads,
  expectedConnectionCount,
  type ConnectionCount,
  type CycleMarks,
  type DemoIdentifiers,
  type ReloadClassification,
  type ScenarioMarks,
  type ScenarioViolation,
  type ViewDefinition,
  type ViewId,
} from './observations.ts';
import type { StateObservation, StateSample } from './artifacts.ts';
import { createStatusModel } from './statusObserver.ts';
import { readRealtimeStatusTexts, realtimeRetryControl } from './viewLocators.ts';

/** Dos ciclos de pulsación: la doble pulsación se prueba con dos errores. */
export const SCENARIO_CYCLES = 2;

/** Sondeo periódico de la página pública (política de la 004). */
const PUBLIC_POLL_INTERVAL_MS = 30_000;

/** Cadencia de muestreo del texto visible; solo afecta a la marca temporal. */
const STATUS_POLL_INTERVAL_MS = 40;

const DEFAULT_BASE_URL = 'http://localhost:3000';

export type ScenarioVerdict = Exclude<ArtifactVerdict, 'passed'>;

/** Fallo con la clasificación que el runner traducirá a verde/inválida/fallo. */
export class ScenarioFailure extends Error {
  readonly verdict: ScenarioVerdict;
  readonly cause: string;

  constructor(verdict: ScenarioVerdict, cause: string, detail: string) {
    super(`${cause}: ${detail}`);
    this.name = 'ScenarioFailure';
    this.verdict = verdict;
    this.cause = cause;
  }
}

export interface ScenarioInput {
  readonly page: Page;
  readonly context: BrowserContext;
  readonly view: ViewDefinition;
  readonly ids: DemoIdentifiers;
  readonly baseURL?: string | undefined;
  /** Estado propio de la vista que el reintento no debe alterar (por vista). */
  readonly pageState?: ViewPageState | undefined;
}

/**
 * Trabajo en curso propio de una vista. `prepare` deja la página en ese estado
 * antes de bloquear el canal y `assertPreserved` comprueba, tras reconectar,
 * que el reintento no lo descartó ni disparó una acción de la página. Cada
 * spec declara el suyo; el escenario solo decide cuándo se ejecutan.
 */
export interface ViewPageState {
  prepare(page: Page): Promise<void>;
  /** Se ejecuta con el estado manual visible, en cada ciclo de pulsación. */
  assertDuringManual?(page: Page): Promise<void>;
  assertPreserved(page: Page, gate: ChannelGate): Promise<void>;
}

export interface ScenarioResult {
  readonly view: ViewId;
  readonly artifact: ViewArtifact;
  readonly marks: ScenarioMarks;
  readonly states: readonly StateObservation[];
  readonly connections: ConnectionCount;
  readonly attempts: number;
  readonly reloads: ReloadClassification;
  readonly orderViolations: readonly ScenarioViolation[];
  readonly manualText: string;
  /** Ruta del artefacto escrito en `e2e-report/`. */
  readonly artifactPath: string;
}

interface MutableCycle {
  clickedAt: number;
  attemptStartedAt: number;
  manualVisibleAt: number;
  manualGoneAt: number;
}

interface MutableMarks {
  connectedOnceAt: number;
  blockedAt: number;
  closedAt: number;
  errorVisibleAt: number;
  cycles: MutableCycle[];
  unblockedAt: number;
  connectedAt: number;
  settledAt: number;
}

function normalize(text: string): string {
  return text.replace(/\s+/g, ' ').trim().toLocaleLowerCase();
}

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Marca estrictamente posterior a la anterior para las marcas **sintéticas**
 * (bloqueo, cierre, clic y desbloqueo): el reloj del borde tiene resolución de
 * milisegundos y dos pasos seguidos pueden compartir marca. Solo se usa en
 * instantes que no son una observación; **nunca** desplaza una marca observada
 * (`manualVisibleAt`, `manualGoneAt`…), que se registran con el instante real de
 * la observación (B1 de la validación).
 */
function stampAfter(previous: number, at: number = Date.now()): number {
  return at > previous ? at : previous + 1;
}

/* -------------------------------------------------------------------------- */
/* Estado visible (solo interfaz)                                             */
/* -------------------------------------------------------------------------- */

function statusFromTexts(texts: readonly string[], view: ViewDefinition): VisibleRealtimeStatus | null {
  const entries = REALTIME_STATUS_TEXT[view.namespace];
  const wanted: VisibleRealtimeStatus[] = ['error', 'retrying', 'reconnecting', 'connected'];
  for (const status of wanted) {
    const expected = normalize(labelText(entries[status]));
    if (texts.some((text) => normalize(text) === expected)) return status;
  }
  return null;
}

interface StatusObserver {
  start(): void;
  stop(): Promise<void>;
  states(): readonly StateSample[];
  lastTexts(): readonly string[];
  current(): VisibleRealtimeStatus | null;
  read(): Promise<{ texts: readonly string[]; status: VisibleRealtimeStatus | null }>;
  /** Registra una observación real hecha fuera de una espera. */
  observe(status: VisibleRealtimeStatus, at: number): void;
  waitFor(
    status: VisibleRealtimeStatus,
    timeoutMs: number,
    condition: string,
    verdict?: ScenarioVerdict,
  ): Promise<number>;
  /** Espera a que el estado deje de ser `status` y devuelve el instante real. */
  waitForOtherThan(
    status: VisibleRealtimeStatus,
    timeoutMs: number,
    condition: string,
  ): Promise<number>;
  /** Primera transición registrada desde `after` con un estado distinto. */
  firstChangeAfter(status: VisibleRealtimeStatus, after: number): StateSample | null;
}

/**
 * Muestrea el contenido de los elementos con `role="status"` (la interfaz) y lo
 * combina con las observaciones directas del escenario en el modelo puro
 * `createStatusModel`. Nunca inyecta código en la página ni lee estado interno de
 * la aplicación (RNF-010). Los textos se comparan sin distinguir mayúsculas: el
 * CSS de la vista transforma el texto a mayúsculas, pero `textContent` conserva
 * el original.
 *
 * Dos fuentes, a propósito: el bucle registra solo **cambios** cada 40 ms; cada
 * espera registra **siempre** la observación con su instante real, porque el
 * estado puede durar menos que un ciclo de muestreo (entre los dos ciclos de
 * pulsación el error pasa fugazmente y `latest` se queda en `retrying`). Sin la
 * segunda fuente, el segundo ciclo se declararía `manual-not-sampled` aunque el
 * producto sí mostró el estado (B1 de la validación).
 */
function createStatusObserver(page: Page, view: ViewDefinition): StatusObserver {
  const model = createStatusModel();
  let lastTexts: readonly string[] = [];
  let running = false;
  let loop: Promise<void> | null = null;

  async function read(): Promise<{ texts: readonly string[]; status: VisibleRealtimeStatus | null }> {
    try {
      const texts = await readRealtimeStatusTexts(page, view);
      return { texts, status: statusFromTexts(texts, view) };
    } catch {
      // Contexto destruido por una navegación: no hay texto que observar.
      return { texts: [], status: null };
    }
  }

  async function tick(): Promise<void> {
    const observed = await read();
    lastTexts = observed.texts;
    model.sample(observed.status, Date.now());
  }

  async function runLoop(): Promise<void> {
    while (running) {
      await tick();
      if (!running) break;
      await delay(STATUS_POLL_INTERVAL_MS);
    }
  }

  return {
    start(): void {
      if (running) return;
      running = true;
      loop = runLoop();
    },
    async stop(): Promise<void> {
      running = false;
      await loop?.catch(() => undefined);
      loop = null;
    },
    states(): readonly StateSample[] {
      return model.samples();
    },
    lastTexts(): readonly string[] {
      return lastTexts;
    },
    current(): VisibleRealtimeStatus | null {
      return model.current();
    },
    read,
    observe(status, at): void {
      model.observe(status, at);
    },
    async waitFor(status, timeoutMs, condition, verdict = 'behavioral'): Promise<number> {
      const deadline = Date.now() + timeoutMs;
      for (;;) {
        const observed = await read();
        lastTexts = observed.texts;
        if (observed.status === status) {
          const at = Date.now();
          // Observación real de una espera: se registra siempre, aunque coincida
          // con el último estado, y con el instante tal cual (sin desplazarlo).
          model.observe(status, at);
          return at;
        }
        if (Date.now() > deadline) {
          throw new ScenarioFailure(
            verdict,
            condition,
            `no se observó el estado «${status}» en ${timeoutMs} ms; último texto visible: ${JSON.stringify(
              observed.texts,
            )}`,
          );
        }
        await delay(STATUS_POLL_INTERVAL_MS);
      }
    },
    async waitForOtherThan(status, timeoutMs, condition): Promise<number> {
      const deadline = Date.now() + timeoutMs;
      for (;;) {
        const observed = await read();
        lastTexts = observed.texts;
        if (observed.status !== null && observed.status !== status) {
          const at = Date.now();
          model.observe(observed.status, at);
          return at;
        }
        if (Date.now() > deadline) {
          throw new ScenarioFailure(
            'behavioral',
            'manual-survived',
            `el estado «${status}» siguió visible ${timeoutMs} ms después (${condition})`,
          );
        }
        await delay(STATUS_POLL_INTERVAL_MS);
      }
    },
    firstChangeAfter(status, after): StateSample | null {
      return model.firstChangeAfter(status, after);
    },
  };
}

/* -------------------------------------------------------------------------- */
/* Escenario                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Peticiones canónicas del consumidor: la ruta exacta de su endpoint, sin
 * subproyecciones. Una recarga de la página pública pide torneo, clasificación
 * y partidos en paralelo, y las tres son **una** recarga; contar cada
 * proyección como una recarga daría duplicados falsos y, a la vez, ocultaría
 * dos recargas simultáneas por suscripción duplicada. El endpoint del
 * consumidor (tabla del plan) es siempre la petición canónica de su recarga.
 */
function canonicalReloadRequests(
  gate: ChannelGate,
  endpoint: string,
): ReadonlyArray<{ path: string; at: number }> {
  const canonical = endpoint.replace(/\/+$/, '');
  return gate
    .requests()
    .filter((record) => record.path === canonical)
    .map((record) => ({ path: record.path, at: record.at }));
}

function reloadsFor(
  gate: ChannelGate,
  view: ViewDefinition,
  ids: DemoIdentifiers,
  connectedAt: number,
): ReloadClassification {
  const endpoint = view.endpoint(ids);
  return classifyReloads({
    requests: canonicalReloadRequests(gate, endpoint),
    endpoints: [endpoint],
    connectedAt: connectedAt >= 0 ? connectedAt : Number.POSITIVE_INFINITY,
    windowMs: MAX_MS.reloadWindow,
    pollingIntervalMs: PUBLIC_POLL_INTERVAL_MS,
    documentNavigations: gate.documentNavigations().map((record) => record.at),
  });
}

function freezeMarks(marks: MutableMarks): ScenarioMarks {
  const cycles: CycleMarks[] = marks.cycles.map((cycle) => ({
    clickedAt: cycle.clickedAt,
    attemptStartedAt: cycle.attemptStartedAt,
    manualVisibleAt: cycle.manualVisibleAt,
    manualGoneAt: cycle.manualGoneAt,
  }));
  return {
    connectedOnceAt: marks.connectedOnceAt,
    blockedAt: marks.blockedAt,
    closedAt: marks.closedAt,
    errorVisibleAt: marks.errorVisibleAt,
    cycles,
    unblockedAt: marks.unblockedAt,
    connectedAt: marks.connectedAt,
    settledAt: marks.settledAt,
  };
}

export async function runRealtimeScenario(input: ScenarioInput): Promise<ScenarioResult> {
  const { page, context, view, ids } = input;
  const startedAt = Date.now();
  const gate = createChannelGate(page);
  const observer = createStatusObserver(page, view);
  const origin = input.baseURL ?? DEFAULT_BASE_URL;

  const marks: MutableMarks = {
    connectedOnceAt: -1,
    blockedAt: -1,
    closedAt: -1,
    errorVisibleAt: -1,
    cycles: [],
    unblockedAt: -1,
    connectedAt: -1,
    settledAt: -1,
  };

  const trace: TraceEntry[] = [];
  const onConsole = (message: { type(): string; text(): string }): void => {
    trace.push(traceConsole({ at: Date.now(), level: message.type(), text: message.text() }));
  };
  const onPageError = (error: Error): void => {
    trace.push(tracePageError({ at: Date.now(), text: error.message }));
  };

  let manualText = labelText(REALTIME_STATUS_TEXT[view.namespace].retrying);
  let failure: ScenarioFailure | null = null;

  const finalize = async (
    verdict: ArtifactVerdict,
    cause: string | null,
  ): Promise<ScenarioResult> => {
    const counts = gate.counts();
    const connections: ConnectionCount = { established: counts.established };
    const reloads = reloadsFor(gate, view, ids, marks.connectedAt);
    const artifactMarks = freezeMarks(marks);
    const artifact = buildViewArtifact({
      view: view.id,
      verdict,
      cause,
      durationMs: Date.now() - startedAt,
      states: observer.states(),
      marks: artifactMarks,
      connections,
      attempts: counts.attempts,
      reloads,
    });
    const artifactPath = await writeViewArtifact(artifact);
    // Una traza por vista: la corrida ejecuta las tres en serie y un fichero
    // compartido haría que la última pisara la traza de la vista que falló.
    await writeTrace(
      [...gate.trace(), ...trace].sort((left, right) => left.at - right.at),
      traceFileName(view.id),
    );
    if (verdict !== 'passed') {
      await captureScreenshot(page, view.id).catch(() => '');
    }
    return {
      view: view.id,
      artifact,
      marks: artifact.marks,
      states: artifact.states,
      connections,
      attempts: counts.attempts,
      reloads,
      orderViolations: assertScenarioOrder(artifact.marks),
      manualText,
      artifactPath,
    };
  };

  const fail = (verdict: ScenarioVerdict, cause: string, detail: string): never => {
    throw new ScenarioFailure(verdict, cause, detail);
  };

  try {
    // 1. Interceptores en modo `pass` ANTES de navegar: la conexión inicial es
    //    real y queda establecida antes del bloqueo (caso límite 1).
    await gate.install();

    const locale = localeCookie();
    await context.addCookies([
      { name: locale.name, value: locale.value, url: new URL('/', origin).toString() },
    ]);

    page.on('console', onConsole);
    page.on('pageerror', onPageError);
    observer.start();

    // 2. Carga inicial y primera conexión aceptada.
    await page.goto(view.url(ids), { waitUntil: 'load', timeout: MAX_MS.initialConnected });
    marks.connectedOnceAt = await observer.waitFor(
      'connected',
      MAX_MS.initialConnected,
      'initial-connected',
      'infrastructure',
    );
    try {
      await gate.waitForEstablished(1, MAX_MS.initialConnected);
    } catch (error) {
      fail(
        'invalid',
        'no-accepted-connection-before-block',
        `no hubo una conexión persistente aceptada antes del bloqueo: ${describeError(error)}`,
      );
    }
    gate.markDocumentBaseline();

    // 2b. Trabajo en curso propio de la vista, antes de tocar el canal: es el
    //     estado que el reintento no debe alterar (RF-002).
    if (input.pageState) {
      try {
        await input.pageState.prepare(page);
      } catch (error) {
        fail(
          'infrastructure',
          'page-state-unavailable',
          `la vista ${view.id} no ofreció su estado propio: ${describeError(error)}`,
        );
      }
    }

    // 3. Bloqueo del canal y caída real del transporte interceptado.
    marks.blockedAt = stampAfter(marks.connectedOnceAt);
    gate.setMode('abort');
    await gate.closeEstablishedTransport();
    marks.closedAt = stampAfter(marks.blockedAt);

    // 4. El error se hace visible: el control solo existe en `error`, así que su
    //    aparición **es** la observación del estado, con su instante real (no se
    //    desplaza para forzar el orden). El localizador se acota al contenedor
    //    del estado del tiempo real, así que no compite con otros «Reintentar»
    //    ni con otros `role="status"`.
    const retryButton = realtimeRetryControl(page, view);
    try {
      await retryButton.waitFor({ state: 'visible', timeout: MAX_MS.errorVisible });
    } catch (error) {
      fail(
        'invalid',
        'no-error-before-click',
        `el control «${labelText(E2E_LABELS.retry)}» no apareció: ${describeError(
          error,
        )}; último texto visible: ${JSON.stringify(observer.lastTexts())}`,
      );
    }
    marks.errorVisibleAt = Date.now();
    observer.observe('error', marks.errorVisibleAt);

    if (!gate.isBlocked() || gate.counts().blocked === 0) {
      fail(
        'invalid',
        'channel-not-blocked',
        `antes del clic el canal no estaba bloqueado (modo ${gate.mode()}, peticiones bloqueadas ${gate.counts().blocked})`,
      );
    }

    const reconnectingText = labelText(REALTIME_STATUS_TEXT[view.namespace].reconnecting);
    if (normalize(manualText) === normalize(reconnectingText)) {
      fail(
        'behavioral',
        'manual-label-not-distinct',
        `el estado manual y el automático comparten texto: «${manualText}»`,
      );
    }

    // 5. Dos ciclos: pulsar con el canal bloqueado, observar el estado manual,
    //    liberar el intento y volver a error.
    for (let index = 0; index < SCENARIO_CYCLES; index += 1) {
      if (!gate.isBlocked()) {
        fail('invalid', 'channel-not-blocked', `el canal se desbloqueó antes del ciclo ${index + 1}`);
      }
      gate.setMode('hold');

      const previousMark =
        index === 0
          ? marks.errorVisibleAt
          : (marks.cycles[index - 1]?.manualGoneAt ?? marks.errorVisibleAt);
      const clickedAt = stampAfter(previousMark);
      await retryButton.click();

      // Instantes observados, tal cual: el inicio del intento lo registra el
      // canal y el estado manual lo observa la espera. No se desplazan marcas
      // observadas (B1 de la validación).
      let attemptStartedAt = 0;
      try {
        attemptStartedAt = await gate.waitForChannelRequestAfter(clickedAt, MAX_MS.manualVisible);
      } catch (error) {
        fail(
          'behavioral',
          'attempt-not-started',
          `la pulsación del ciclo ${index + 1} no inició ninguna petición al canal: ${describeError(
            error,
          )}`,
        );
      }

      let manualVisibleAt = 0;
      try {
        manualVisibleAt = await observer.waitFor('retrying', MAX_MS.manualVisible, 'manual-visible');
      } catch (error) {
        fail(
          'behavioral',
          'manual-not-visible',
          `tras el clic del ciclo ${index + 1} no apareció el estado manual: ${describeError(error)}`,
        );
      }

      // El estado manual permanece mientras el intento sigue en curso y el
      // control solo existe en `error`: con el estado manual ya no está.
      await expect(retryButton).toHaveCount(0);
      const manualNow = await observer.read();
      if (manualNow.status !== 'retrying') {
        fail(
          'behavioral',
          'manual-not-visible',
          `el estado manual no estaba visible al comprobarlo en el ciclo ${index + 1}: ${JSON.stringify(
            manualNow.texts,
          )}`,
        );
      }

      if (input.pageState?.assertDuringManual) {
        try {
          await input.pageState.assertDuringManual(page);
        } catch (error) {
          fail(
            'behavioral',
            'page-interference-during-manual',
            `el estado manual del ciclo ${index + 1} interfirió con la página ${view.id}: ${describeError(
              error,
            )}`,
          );
        }
      }

      const cycle: MutableCycle = {
        clickedAt,
        attemptStartedAt,
        manualVisibleAt,
        manualGoneAt: -1,
      };
      marks.cycles.push(cycle);

      await gate.releaseHeld();
      // La desaparición del estado manual es una observación real: se espera a
      // que el estado deje de ser `retrying` (si sobrevive, es un fallo, no una
      // espera agotada) y se usa el instante de la transición ya registrada si
      // la hubo, sin adelantar ninguna marca.
      const manualGoneObservedAt = await observer.waitForOtherThan(
        'retrying',
        MAX_MS.attemptFailed,
        `manual-gone-${index + 1}`,
      );
      try {
        await retryButton.waitFor({ state: 'visible', timeout: MAX_MS.attemptFailed });
      } catch (error) {
        fail(
          'behavioral',
          'manual-survived',
          `el intento del ciclo ${index + 1} no devolvió el error con el control disponible: ${describeError(
            error,
          )}`,
        );
      }
      const transition = observer.firstChangeAfter('retrying', manualVisibleAt);
      cycle.manualGoneAt = transition ? transition.at : manualGoneObservedAt;
    }

    // 6. Desbloqueo, reconexión y asentamiento sin nuevas secuencias.
    if (!gate.isBlocked()) {
      fail('invalid', 'channel-not-blocked', 'el canal ya estaba desbloqueado antes del paso final');
    }
    const lastGone = marks.cycles[marks.cycles.length - 1]?.manualGoneAt ?? marks.errorVisibleAt;
    marks.unblockedAt = stampAfter(lastGone);
    await gate.unblock();

    try {
      // Instante observado tal cual: es la misma marca que la muestra de estado.
      marks.connectedAt = await observer.waitFor('connected', MAX_MS.reconnect, 'reconnect');
    } catch (error) {
      fail(
        'behavioral',
        'reconnect-timeout',
        `el estado visible no llegó a conectado tras desbloquear: ${describeError(error)}`,
      );
    }

    try {
      await gate.waitForEstablished(
        expectedConnectionCount({ cycles: SCENARIO_CYCLES }).established,
        MAX_MS.reconnect,
      );
    } catch (error) {
      fail(
        'behavioral',
        'transport-not-established',
        `el transporte final no se estableció: ${describeError(error)}`,
      );
    }

    try {
      marks.settledAt = await gate.settle(marks.connectedAt, MAX_MS.settle, MAX_MS.reconnect);
    } catch (error) {
      fail(
        'behavioral',
        'connection-after-settle',
        `se inició otra secuencia de conexión después de conectar: ${describeError(error)}`,
      );
    }

    // 6b. El reintento no descarta el trabajo en curso de la vista ni ejecuta
    //     sus acciones: el estado propio sigue intacto tras reconectar.
    if (input.pageState) {
      try {
        await input.pageState.assertPreserved(page, gate);
      } catch (error) {
        fail(
          'behavioral',
          'page-state-changed',
          `el reintento alteró el estado propio de la vista ${view.id}: ${describeError(error)}`,
        );
      }
    }

    // 7. Recuentos de conexión y recargas.
    const expected = expectedConnectionCount({ cycles: SCENARIO_CYCLES });
    const counts = gate.counts();
    if (counts.established !== expected.established) {
      fail(
        'behavioral',
        'unexpected-connections',
        `se esperaban ${expected.established} conexiones persistentes y se observaron ${counts.established}`,
      );
    }

    const reloads = reloadsFor(gate, view, ids, marks.connectedAt);
    if (reloads.documentReloads !== 0) {
      fail(
        'behavioral',
        'document-reload',
        `el documento se recargó ${reloads.documentReloads} veces durante el escenario`,
      );
    }
    if (reloads.duplicates > 0) {
      fail(
        'behavioral',
        'duplicate-reloads',
        `el consumidor ${view.endpoint(ids)} recargó ${reloads.duplicates + 1} veces en la ventana de reconexión`,
      );
    }
    if (reloads.attributable > 1) {
      fail(
        'behavioral',
        'multiple-reloads',
        `más de una recarga atribuible a la reconexión (${reloads.attributable})`,
      );
    }

    // 8. El estado manual nunca aparece sin una pulsación previa, ni conectado
    //    mientras el canal está bloqueado, ni sobrevive al desbloqueo.
    const firstClick = marks.cycles[0]?.clickedAt ?? Number.POSITIVE_INFINITY;
    if (observer.states().some((state) => state.status === 'retrying' && state.at < firstClick)) {
      fail(
        'behavioral',
        'manual-without-click',
        'se observó el estado manual antes de cualquier pulsación',
      );
    }
    // Solo cuenta un conectado posterior al cierre del transporte: una muestra
    // anterior al cierre es la conexión inicial, no una recuperación.
    const connectedWhileBlocked = observer
      .states()
      .some(
        (state) =>
          state.status === 'connected' &&
          state.at > marks.closedAt &&
          state.at <= marks.unblockedAt,
      );
    if (connectedWhileBlocked) {
      fail(
        'behavioral',
        'connected-while-blocked',
        'el estado visible llegó a conectado con el canal todavía bloqueado',
      );
    }

    // 9. Orden canónico: una violación es un fallo con su código.
    const violations = assertScenarioOrder(freezeMarks(marks));
    if (violations.length > 0) {
      fail('behavioral', 'scenario-order', `orden del escenario inválido: ${violations.join(', ')}`);
    }
  } catch (error) {
    failure =
      error instanceof ScenarioFailure
        ? error
        : new ScenarioFailure('infrastructure', 'scenario-error', describeError(error));
  } finally {
    await observer.stop();
    page.off('console', onConsole);
    page.off('pageerror', onPageError);
  }

  const result = await finalize(failure ? failure.verdict : 'passed', failure?.cause ?? null);
  await gate.dispose();

  if (failure) {
    throw failure;
  }
  return result;
}

/** Ruta del artefacto de una vista (comprobable por el runner y por las specs). */
export function viewArtifactPath(view: ViewId): string {
  return reportPath(`view-${view}.json`);
}
