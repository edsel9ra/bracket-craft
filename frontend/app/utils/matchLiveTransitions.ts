/**
 * Transiciones del partido en vivo (spec 036, T67): iniciar, suspender,
 * reanudar.
 *
 * `start` solo procede sobre un partido programado y tras resolver
 * expresamente el borrador clásico local (T62). `suspend` exige `live`;
 * `resume` exige `suspended` y solo devuelve a `live` — nunca arranca el reloj
 * ni crea otro segmento (RF-029). Toda acción pide confirmación expresa y es
 * single-flight.
 */

import { classifyCaptureFailure, type LiveCaptureOutcome } from './matchLiveCapture.ts';
import { isDraftEditable, type LiveEditorState } from './matchLiveEditor.ts';

export { isDraftEditable };

export type LiveTransitionOutcome =
  | Extract<LiveCaptureOutcome, 'sent' | 'conflict' | 'denied' | 'error' | 'busy'>
  | 'cancelled'
  | 'invalid';

const TERMINAL_STATUSES = new Set(['finished', 'cancelled', 'administrative_resolution']);

export interface LiveTransitionsOptions {
  send(body: Record<string, unknown>): Promise<unknown>;
  requestSnapshot(): Promise<void>;
  editor: LiveEditorState;
  commandId(): string;
  confirm(kind: 'start' | 'suspend' | 'resume'): Promise<boolean>;
  /** Resolución del borrador clásico antes de `start` (T62). */
  resolveLocalDraft(): Promise<'proceed' | 'cancelled'>;
  /** Estado clásico del partido cuando no hay borrador compartido. */
  matchStatus(): string;
}

export interface LiveTransitions {
  start(): Promise<LiveTransitionOutcome>;
  suspend(): Promise<LiveTransitionOutcome>;
  resume(): Promise<LiveTransitionOutcome>;
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

export function createLiveTransitions(options: LiveTransitionsOptions): LiveTransitions {
  let inFlight = false;

  async function run(type: 'start' | 'suspend' | 'resume', revision: number): Promise<LiveTransitionOutcome> {
    inFlight = true;
    const commandId = options.commandId();
    try {
      if (!(await options.confirm(type))) return 'cancelled';
      const ack = await options.send({
        command_id: commandId,
        expected_revision: revision,
        type,
      });
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
    async start() {
      if (inFlight) return 'busy';
      // Solo un programado sin borrador compartido puede pasar a live.
      if (options.editor.shared !== null) return 'invalid';
      if (options.matchStatus() !== 'scheduled' || TERMINAL_STATUSES.has(options.matchStatus())) return 'invalid';
      // El borrador clásico local exige decisión expresa antes de iniciar.
      if ((await options.resolveLocalDraft()) !== 'proceed') return 'cancelled';
      return run('start', 0);
    },
    async suspend() {
      if (inFlight) return 'busy';
      if (options.editor.shared?.status !== 'live') return 'invalid';
      return run('suspend', options.editor.shared.revision);
    },
    async resume() {
      if (inFlight) return 'busy';
      if (options.editor.shared?.status !== 'suspended') return 'invalid';
      // Solo devuelve a live: el reloj queda pausado y sin segmento nuevo.
      return run('resume', options.editor.shared.revision);
    },
    get inFlight() {
      return inFlight;
    },
  };
}
