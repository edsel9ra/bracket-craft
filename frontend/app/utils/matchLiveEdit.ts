/**
 * Corrección y retirada de hechos del borrador compartido (spec 036, T64).
 *
 * La edición conserva su texto ante cualquier conflicto: si la base avanza
 * mientras se escribe (otro operador, snapshot nuevo o un 409 del servidor),
 * la sesión queda `stale` y exige `reviewBase()` —releer el estado vigente—
 * antes de guardar. Las acciones piden confirmación expresa y son
 * single-flight.
 */

import { classifyCaptureFailure, validateLiveEventForm, type LiveCaptureOutcome } from './matchLiveCapture.ts';
import type { LiveEditorState } from './matchLiveEditor.ts';

export interface LiveEditSession {
  /** `client_event_id` del hecho en edición (su `event_id` en el wire). */
  eventId: string;
  /** Revisión del borrador en la que empezó la edición. */
  baseRevision: number;
  /** La base avanzó: guardar exige revisar antes. */
  stale: boolean;
  /** El hecho ya no está en el borrador vigente (lo retiró otro operador). */
  removed: boolean;
}

export type LiveEditOutcome =
  | Extract<LiveCaptureOutcome, 'sent' | 'invalid' | 'conflict' | 'denied' | 'error' | 'busy' | 'unavailable'>
  | 'cancelled'
  | 'missing'
  | 'stale';

export interface LiveEditOptions {
  /** POST `/matches/{id}/live/commands` vía useApi. */
  send(body: Record<string, unknown>): Promise<unknown>;
  requestSnapshot(): Promise<void>;
  editor: LiveEditorState;
  /** Confirmación expresa (`useConfirm`), por tipo de acción. */
  confirm(kind: 'correct' | 'remove'): Promise<boolean>;
  commandId(): string;
}

export interface LiveEdit {
  /** Abre la sesión sobre un hecho aceptado del borrador. */
  beginEdit(clientEventId: string): 'ok' | 'missing' | 'unavailable';
  editing(): LiveEditSession | null;
  /** Cierra la sesión descartando solo la edición, nunca el hecho aceptado. */
  cancelEdit(): void;
  /** Marca la sesión cuando el compartido cambió durante la edición. */
  onSharedChanged(): void;
  /**
   * Relee la base vigente: la edición pasa a anclarse en la revisión actual y
   * deja de estar `stale`. Devuelve false si el hecho ya no existe.
   */
  reviewBase(): boolean;
  saveEdit(form: unknown): Promise<LiveEditOutcome>;
  removeFact(clientEventId: string): Promise<LiveEditOutcome>;
}

function validAck(ack: unknown, commandId: string): boolean {
  const shape = ack as Record<string, unknown> | null;
  return typeof shape === 'object' && shape !== null
    && shape.command_id === commandId
    && typeof shape.revision === 'number'
    && Number.isInteger(shape.revision)
    && shape.revision >= 0;
}

export function createLiveEdit(options: LiveEditOptions): LiveEdit {
  let editing: LiveEditSession | null = null;
  let inFlight = false;

  function eventExists(clientEventId: string): boolean {
    const shared = options.editor.shared;
    return shared !== null && shared.events.some((event) => event.clientEventId === clientEventId);
  }

  async function deliver(command: Record<string, unknown>): Promise<LiveEditOutcome> {
    const commandId = options.commandId();
    try {
      const ack = await options.send({ ...command, command_id: commandId });
      if (!validAck(ack, commandId)) return 'error';
      await options.requestSnapshot();
      return 'sent';
    } catch (cause) {
      const outcome = classifyCaptureFailure(cause);
      if (outcome === 'conflict' && editing) editing.stale = true;
      return outcome;
    }
  }

  return {
    beginEdit(clientEventId: string) {
      if (options.editor.shared === null) return 'unavailable';
      if (!eventExists(clientEventId)) return 'missing';
      editing = {
        eventId: clientEventId,
        baseRevision: options.editor.shared.revision,
        stale: false,
        removed: false,
      };
      return 'ok';
    },

    editing() {
      return editing;
    },

    cancelEdit() {
      editing = null;
    },

    onSharedChanged() {
      const shared = options.editor.shared;
      if (!editing || shared === null) return;
      if (shared.revision !== editing.baseRevision) editing.stale = true;
      if (!shared.events.some((event) => event.clientEventId === editing!.eventId)) {
        editing.removed = true;
        editing.stale = true;
      }
    },

    reviewBase() {
      const shared = options.editor.shared;
      if (!editing || shared === null) return false;
      editing.baseRevision = shared.revision;
      editing.stale = false;
      return true;
    },

    async saveEdit(form: unknown): Promise<LiveEditOutcome> {
      if (inFlight) return 'busy';
      const shared = options.editor.shared;
      if (shared === null) return 'unavailable';
      if (!editing) return 'missing';
      // Nunca guardar sobre una base movida sin revisar primero (RF-023).
      if (editing.stale) return 'stale';
      if (editing.removed) return 'stale';
      const event = validateLiveEventForm(form);
      if (event === null) return 'invalid';
      // Single-flight cubre también la confirmación: dos activaciones no
      // pueden solaparse ni mostrar dos diálogos.
      inFlight = true;
      try {
        if (!(await options.confirm('correct'))) return 'cancelled';
        return await deliver({
          type: 'correct_event',
          event_id: editing.eventId,
          expected_revision: shared.revision,
          event,
        });
      } finally {
        inFlight = false;
      }
    },

    async removeFact(clientEventId: string): Promise<LiveEditOutcome> {
      if (inFlight) return 'busy';
      const shared = options.editor.shared;
      if (shared === null) return 'unavailable';
      if (!eventExists(clientEventId)) return 'missing';
      inFlight = true;
      try {
        if (!(await options.confirm('remove'))) return 'cancelled';
        return await deliver({
          type: 'remove_event',
          event_id: clientEventId,
          expected_revision: shared.revision,
        });
      } finally {
        inFlight = false;
      }
    },
  };
}
