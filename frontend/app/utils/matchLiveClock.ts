/**
 * Reloj del editor compartido (spec 036, T66).
 *
 * La referencia aceptada (`elapsed_us` + `anchor_at` del snapshot) es la única
 * fuente; la vista calcula el tiempo transcurrido con un `now` inyectable y
 * ningún intervalo escribe al servidor. Una corrección solo cambia la
 * referencia del reloj: los hechos aceptados y sus minutos no se tocan
 * (RF-030). La conexión caída se presenta como vista desactualizada, nunca
 * como tiempo oficial.
 */

import { classifyCaptureFailure, type LiveCaptureOutcome } from './matchLiveCapture.ts';
import { isDraftEditable, type LiveEditorState } from './matchLiveEditor.ts';

export interface LiveClockView {
  state: 'not_started' | 'running' | 'paused';
  /** µs mostrados: acumulado aceptado + transcurrido si running. */
  elapsedUs: number;
  /** µs aceptados por el servidor (referencia, sin cómputo local). */
  acceptedElapsedUs: number;
  /** true cuando elapsedUs incorpora el tramo local desde anchor_at. */
  computed: boolean;
}

interface ClockWire {
  state: string;
  segment_id: string | null;
  segment_number: number | null;
  elapsed_us: number | null;
  anchor_at: string | null;
  observed_at: string;
}

/** Vista del reloj con tiempo inyectable (`now` como parámetro). */
export function displayedClock(clock: ClockWire, now: Date): LiveClockView {
  const accepted = clock.elapsed_us ?? 0;
  if (clock.state !== 'running' || clock.anchor_at === null) {
    return {
      state: clock.state as LiveClockView['state'],
      elapsedUs: accepted,
      acceptedElapsedUs: accepted,
      computed: false,
    };
  }
  const anchor = Date.parse(clock.anchor_at);
  const elapsed = Number.isNaN(anchor) ? accepted : accepted + Math.max(0, Math.floor((now.getTime() - anchor) * 1000));
  return { state: 'running', elapsedUs: elapsed, acceptedElapsedUs: accepted, computed: true };
}

/** Presentación con marca de desactualización por estado de conexión. */
export function clockPresentation(
  clock: ClockWire,
  connection: 'connected' | 'reconnecting' | 'error' | 'idle' | 'connecting' | 'retrying',
  now: Date,
): LiveClockView & { stale: boolean } {
  return { ...displayedClock(clock, now), stale: connection !== 'connected' };
}

export type LiveClockOutcome = Extract<LiveCaptureOutcome, 'sent' | 'invalid' | 'conflict' | 'denied' | 'error' | 'busy' | 'unavailable'>;

export interface LiveClockOptions {
  send(body: Record<string, unknown>): Promise<unknown>;
  requestSnapshot(): Promise<void>;
  editor: LiveEditorState;
  commandId(): string;
}

export interface LiveClock {
  startClock(segmentId: string): Promise<LiveClockOutcome>;
  pauseClock(): Promise<LiveClockOutcome>;
  resumeClock(): Promise<LiveClockOutcome>;
  correctClock(segmentId: string, elapsedUs: number): Promise<LiveClockOutcome>;
  readonly inFlight: boolean;
}

function validAck(ack: unknown, commandId: string): boolean {
  const shape = ack as Record<string, unknown> | null;
  return typeof shape === 'object' && shape !== null
    && shape.command_id === commandId
    && typeof shape.revision === 'number'
    && Number.isInteger(shape.revision)
    && shape.revision >= 0;
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function createLiveClock(options: LiveClockOptions): LiveClock {
  let inFlight = false;

  async function run(command: Record<string, unknown>): Promise<LiveClockOutcome> {
    if (inFlight) return 'busy';
    const shared = options.editor.shared;
    // Suspendido: el reloj no recibe comandos (T67).
    if (shared === null || !isDraftEditable(shared.status)) return 'unavailable';
    inFlight = true;
    const commandId = options.commandId();
    try {
      const ack = await options.send({ ...command, command_id: commandId, expected_revision: shared.revision });
      if (!validAck(ack, commandId)) return 'error';
      await options.requestSnapshot();
      return 'sent';
    } catch (cause) {
      return classifyCaptureFailure(cause);
    } finally {
      inFlight = false;
    }
  }

  return {
    startClock(segmentId) {
      return UUID_PATTERN.test(segmentId)
        ? run({ type: 'start_clock', segment_id: segmentId })
        : Promise.resolve('invalid' as const);
    },
    pauseClock() {
      return run({ type: 'pause_clock' });
    },
    resumeClock() {
      return run({ type: 'resume_clock' });
    },
    correctClock(segmentId, elapsedUs) {
      if (!UUID_PATTERN.test(segmentId)) return Promise.resolve('invalid' as const);
      if (typeof elapsedUs !== 'number' || !Number.isInteger(elapsedUs) || elapsedUs < 0) {
        return Promise.resolve('invalid' as const);
      }
      // Solo la referencia cambia (RF-030); hechos y minutos quedan intactos.
      return run({ type: 'correct_clock', segment_id: segmentId, elapsed_us: elapsedUs });
    },
    get inFlight() {
      return inFlight;
    },
  };
}
