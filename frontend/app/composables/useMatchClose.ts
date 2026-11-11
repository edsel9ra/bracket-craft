import type { MatchOperationState } from '~/composables/useMatchOperationState';
import { RESOLUTION_LABEL_KEYS, closeResolutionDecision, maximumMinuteFor, normalizeResolution, resolutionChangeOutcome, type EventMinuteValidation, type ResolutionType } from '~/utils/matchResolution';
import { buildCloseReportBody, closePreflight, type ClosePreflightIssue } from '~/utils/matchClose';
import { classifyCloseConflict, closeConflictMessageKey, type SegmentRefreshCause } from '~/utils/matchSegments';

export function useMatchClose(state: MatchOperationState, dependencies: {
  removePersistedDraft(): void;
  refreshOperation(cause?: SegmentRefreshCause): Promise<void>;
  runAction(action: string, callback: () => Promise<void>, onError?: (cause: unknown) => boolean): Promise<void>;
}) {
  const { request, t, confirm, matchId, operation, actionError, draftEvents, draftRestored, draftDroppedEvents, closeForm, match, selectedSegmentIsActive, operationLimits, resolution, plannedResolution, selectResolution, snapshotResolution, resolutionFallback, resolutionChangeNotice, closeSnapshotTaken, draftMinuteViolations, hasCompleteLineup, closeFieldIssue } = state;
  const { removePersistedDraft, refreshOperation, runAction } = dependencies;

  function beginClose(): void {
    if (closeSnapshotTaken.value) return;
    closeSnapshotTaken.value = true;
    snapshotResolution();
  }

  function resolutionLabel(value: ResolutionType): string {
    return t(RESOLUTION_LABEL_KEYS[value]);
  }

  /**
   * Mensaje del tope combinado (RF-032): nombra el minuto, el añadido y el
   * máximo que el cierre aplicará. No vacía el formulario y no añade el evento.
   */
  function eventMinuteMessage(validation: EventMinuteValidation): string {
    return t('match.eventMinuteExceedsMaximum', {
      minute: validation.minute,
      added: validation.added,
      max: validation.max,
    });
  }

  /**
   * Cambio de la resolución prevista (RF-033, P2). Antes de aplicarlo se juzga
   * contra los segmentos persistidos y los eventos del borrador: con segmentos
   * fuera del nuevo máximo el cambio no se permite, y con solo eventos del
   * borrador se pide confirmación y se avisa sin borrar nada. El valor vigente no
   * se escribe en el servidor ni en el borrador local.
   */
  async function changeResolution(next: ResolutionType): Promise<void> {
    const effective = normalizeResolution(operationLimits.value, next);
    if (effective === resolution.value) {
      resolutionFallback.value = false;
      resolutionChangeNotice.value = null;
      return;
    }
    const outcome = resolutionChangeOutcome(
      operation.value?.segments,
      draftEvents.value,
      maximumMinuteFor(operationLimits.value, effective),
      // Spec 016, D-13: el W.O. no valida segmentos, así que un segmento
      // persistido por encima del máximo no bloquea el cambio a `walkover`.
      { resolution: effective },
    );
    if (outcome.outcome === 'blocked') {
      resolutionFallback.value = false;
      // P2: no se corrige ningún segmento guardado; se pide resolver primero.
      resolutionChangeNotice.value = { key: outcome.messageKey, params: outcome.messageParams };
      actionError.value = t(outcome.messageKey, outcome.messageParams);
      return;
    }
    if (outcome.outcome === 'confirm') {
      if (import.meta.client && !(await confirm({ title: t('confirm.changeResolution.title'), message: t(outcome.messageKey, outcome.messageParams), confirmLabel: t('confirm.changeResolution.action'), tone: 'primary' }))) return;
      resolutionChangeNotice.value = { key: outcome.messageKey, params: outcome.messageParams };
    } else {
      resolutionChangeNotice.value = null;
    }
    resolutionFallback.value = false;
    selectResolution(effective, operationLimits.value);
  }

  async function onResolutionChange(event: Event) {
    const select = event.target as HTMLSelectElement;
    const next = select.value as ResolutionType;
    select.value = resolution.value;
    await changeResolution(next);
    select.value = resolution.value;
  }

  /**
   * Primer problema del cierre (RF-012). La decisión vive en la utilidad pura: el
   * walkover no exige segmento activo ni planilla y exige motivo de catálogo; el
   * resto de resoluciones conserva sus exigencias. El servidor sigue siendo la
   * autoridad y esto solo evita un 422 evitable.
   */
  function closeValidationIssue(): ClosePreflightIssue | null {
    const minuteViolation = draftMinuteViolations.value[0];
    return closePreflight({
      resolution: resolution.value,
      limits: operationLimits.value,
      homeTeamId: match.value?.home_team_id,
      awayTeamId: match.value?.away_team_id,
      segmentActive: selectedSegmentIsActive.value,
      lineupComplete: hasCompleteLineup.value,
      scores: { ...closeForm },
      winnerTeamId: closeForm.winner_team_id,
      reason: closeForm.reason,
      draftEvents: draftEvents.value,
      minuteIssue: minuteViolation
        ? {
            key: 'match.eventMinuteExceedsMaximum',
            params: {
              minute: minuteViolation.validation.minute,
              added: minuteViolation.validation.added,
              max: minuteViolation.validation.max,
            },
          }
        : null,
    });
  }

  function closeValidationError(): string | null {
    const issue = closeValidationIssue();
    // RNF-007: el problema se guarda además de mostrarse, para que el motivo del
    // walkover lo anuncie su propio campo y no solo la región del error.
    closeFieldIssue.value = issue;
    if (!issue) return null;
    return t(issue.key, issue.params);
  }

  async function closeMatch() {
    const validationError = closeValidationError();
    if (validationError) {
      actionError.value = validationError;
      return;
    }
    // RF-034/RP-1: el cierre usa la resolución prevista. Si se elige otra
    // compatible, hay aviso y confirmación explícita; sin ella no se cierra. Con
    // segmentos persistidos fuera del máximo no hay confirmación posible (P2).
    const closeInput = {
      planned: plannedResolution.value,
      chosen: resolution.value,
      limits: operationLimits.value,
      segments: operation.value?.segments,
      draftEvents: draftEvents.value,
      confirmed: false,
    };
    const decision = closeResolutionDecision(closeInput);
    if (decision.outcome === 'blocked') {
      actionError.value = t(decision.messageKey, decision.messageParams);
      return;
    }
    if (decision.needsConfirmation) {
      if (!import.meta.client) return;
      const params = {
        ...decision.messageParams,
        resolution: resolutionLabel(resolution.value),
        planned: resolutionLabel(plannedResolution.value),
      };
      if (!(await confirm({ title: t('confirm.closeReport.title'), message: t(decision.messageKey, params), confirmLabel: t('confirm.closeReport.action'), tone: 'danger' }))) return;
      if (!closeResolutionDecision({ ...closeInput, confirmed: true }).send) return;
    } else if (import.meta.client && !(await confirm({ title: t('confirm.closeReport.title'), message: t('match.confirmClosePrompt'), confirmLabel: t('confirm.closeReport.action'), tone: 'danger' }))) {
      return;
    }
    await runAction('close', async () => {
      await request(`/matches/${matchId}/close`, {
        method: 'POST',
        // RF-005/RF-012: el cuerpo lo construye la utilidad pura. En `walkover` no
        // se envía ninguna de las seis claves de marcador: lo deriva el servidor.
        body: buildCloseReportBody({
          resolution: resolution.value,
          limits: operationLimits.value,
          scores: { ...closeForm },
          winnerTeamId: closeForm.winner_team_id,
          reason: closeForm.reason,
          events: draftEvents.value,
        }),
      });
      draftEvents.value = [];
      draftRestored.value = false;
      draftDroppedEvents.value = 0;
      await refreshOperation();
      removePersistedDraft();
    }, (cause) => {
      // RF-006/RF-010: el 409 del cierre se explica por su `code` aditivo con el
      // clasificador de `matchSegments`. Una causa sin código conocido conserva
      // el `detail` del servidor, que es más concreto que un texto genérico.
      const kind = classifyCloseConflict(cause);
      const key = kind === 'other' ? null : closeConflictMessageKey(kind);
      if (!key) return false;
      actionError.value = t(key);
      return true;
    });
  }

  return { beginClose, resolutionLabel, eventMinuteMessage, changeResolution, onResolutionChange, closeValidationIssue, closeValidationError, closeMatch };
}
