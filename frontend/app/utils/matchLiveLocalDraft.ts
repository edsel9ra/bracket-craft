/**
 * Resolución del borrador clásico local antes de iniciar F1 (spec 036, T62).
 *
 * El borrador de la operación clásica nunca se importa ni se reenvía al editor
 * compartido: antes del `start` se avisa de que no está aceptado y se exige una
 * decisión expresa del usuario. `keep` lo conserva intacto, `discard` lo limpia
 * de forma expresa y cancelar/fallar aborta el inicio sin tocar el texto.
 */

export type LocalDraftChoice = 'keep' | 'discard';
export type LocalDraftResolution = 'proceed' | 'cancelled';

export interface LocalDraftResolverOptions {
  /** Si hay texto clásico pendiente (eventos o resultado sin enviar). */
  hasLocalDraft(): boolean;
  /**
   * Confirmación de decisión (useConfirm). Devuelve la elección expresa;
   * `null` cuando el usuario cancela.
   */
  confirmResolve(): Promise<LocalDraftChoice | null>;
  /** Descarta el borrador clásico persistido. */
  clearDraft(): void;
  /** Reservado: ninguna vía inserta hechos locales en el editor compartido. */
  markPending(raw: unknown): void;
}

export interface LocalDraftResolver {
  /** `proceed` permite iniciar F1; `cancelled` conserva todo como estaba. */
  resolveBeforeStart(): Promise<LocalDraftResolution>;
}

export function createLocalDraftResolver(options: LocalDraftResolverOptions): LocalDraftResolver {
  return {
    async resolveBeforeStart(): Promise<LocalDraftResolution> {
      if (!options.hasLocalDraft()) return 'proceed';
      let choice: LocalDraftChoice | null;
      try {
        choice = await options.confirmResolve();
      } catch {
        // Una confirmación que no puede mostrarse no decide: se conserva todo.
        return 'cancelled';
      }
      if (choice === null) return 'cancelled';
      if (choice === 'discard') options.clearDraft();
      // 'keep': el texto queda donde estaba; nunca se marca pendiente ni se
      // entrega al borrador compartido.
      return 'proceed';
    },
  };
}
