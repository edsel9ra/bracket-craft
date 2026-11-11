import type { MatchOperationState } from '~/composables/useMatchOperationState';
import { type MatchDraftStorage } from '~/utils/matchDraft';
import { readDraftEvents } from '~/utils/substitutions';

export function useMatchEventsDraft(state: MatchOperationState, dependencies: {
  clearEventFieldIssues(): void;
}) {
  const { t, confirm, operation, draftEvents, draftRestored, draftSavedAt, draftDroppedEvents, eventForm, closeForm, eventTypeValues, isTerminal, matchLimits, defaultCloseForm, hasUnsavedDraft, draftStore } = state;
  const { clearEventFieldIssues } = dependencies;

  let hydratingDraft = false;

  // RF-022/RF-034: el borrador local (eventos y formulario de cierre) se lee y
  // se escribe solo a través del saneado de `utils/matchDraft`; la resolución
  // prevista no forma parte de él. El almacenamiento se inyecta como en el resto
  // de utilidades puras.
  function draftStorageOrNull(): MatchDraftStorage | null {
    if (!import.meta.client) return null;
    try {
      return window.localStorage;
    } catch {
      // Storage can be unavailable in private browsing.
      return null;
    }
  }

  function closeFormSnapshot() {
    return { ...closeForm };
  }

  function removePersistedDraft() {
    if (!import.meta.client) return;
    draftStore.value.clear();
  }

  function loadPersistedDraft() {
    if (!import.meta.client || !operation.value) return;
    const { draft, discard } = draftStore.value.read();
    if (discard) {
      removePersistedDraft();
      return;
    }
    if (!draft) return;
    if (isTerminal.value) {
      removePersistedDraft();
      return;
    }

    hydratingDraft = true;
    try {
      // Spec 015, T10: un evento que ya no se puede reenviar (identificador que no
      // es UUID, asistente en un tipo ajeno, `metadata` cerrada…) se descarta y se
      // cuenta; el resto del borrador se restaura tal cual, en su orden.
      const restored = readDraftEvents(draft.events, eventTypeValues, matchLimits.value);
      draftEvents.value = restored.events;
      draftDroppedEvents.value = restored.dropped;
      // Solo los campos conocidos y válidos del formulario de cierre; un borrador
      // antiguo con la resolución prevista ya la trae descartada de `read()`.
      Object.assign(closeForm, draft.result);
      draftRestored.value = hasUnsavedDraft.value;
      draftSavedAt.value = draft.saved_at;
    } catch {
      // Un guardado que no se puede aplicar se descarta como antes de la spec 012.
      draftDroppedEvents.value = 0;
      removePersistedDraft();
    } finally {
      hydratingDraft = false;
    }
    // Lo descartado no vuelve: el guardado se reescribe ya limpio y, si no queda
    // nada que reenviar, se borra (D-9).
    if (draftDroppedEvents.value > 0) persistDraft();
  }

  function persistDraft() {
    if (!import.meta.client || hydratingDraft || !operation.value) return;
    if (isTerminal.value) {
      removePersistedDraft();
      return;
    }
    if (!hasUnsavedDraft.value) {
      removePersistedDraft();
      draftSavedAt.value = null;
      return;
    }
    const savedAt = new Date().toISOString();
    // `save` re-sanea el contenido: ninguna ruta escribe la resolución prevista.
    if (draftStore.value.save({ events: draftEvents.value, result: closeFormSnapshot(), saved_at: savedAt })) {
      draftSavedAt.value = savedAt;
    }
  }

  async function discardDraft() {
    if (!import.meta.client || !(await confirm({ title: t('confirm.discardDraft.title'), message: t('match.discardDraft'), confirmLabel: t('confirm.discardDraft.action'), tone: 'danger' }))) return;
    draftEvents.value = [];
    Object.assign(closeForm, defaultCloseForm);
    eventForm.player_out_id = '';
    eventForm.player_in_id = '';
    clearEventFieldIssues();
    draftRestored.value = false;
    draftDroppedEvents.value = 0;
    persistDraft();
  }

  return { draftStorageOrNull, closeFormSnapshot, removePersistedDraft, loadPersistedDraft, persistDraft, discardDraft };
}
