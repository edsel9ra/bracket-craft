import { useMatchOperationState } from '~/composables/useMatchOperationState';
import { useMatchClose } from '~/composables/useMatchClose';
import { useMatchLineup } from '~/composables/useMatchLineup';
import { useMatchEventsDraft } from '~/composables/useMatchEventsDraft';
import { useMatchEvents } from '~/composables/useMatchEvents';
import { isForbidden, isNotFound, isUnauthorized } from '~/utils/api';
import { classifyMatchConflict, matchConflictDetail, resolutionEnabled, resolutionPayload } from '~/utils/matchResolution';
import { type SegmentRefreshCause } from '~/utils/matchSegments';
import { describeOpeningBlocked } from '~/utils/rosterLimits';
import { type MatchDraftStorage } from '~/utils/matchDraft';
import { safeInternalRedirect } from '~/utils/navigation';
import { createReloadCoordinator, decideReload, resyncTrigger, type ReloadTrigger } from '~/utils/realtimeReload';
import { buildOfficialAssignmentBody } from '~/utils/requestBodies';
import { SUBSTITUTION_EVENT_TYPE, type SubstitutionOption } from '~/utils/substitutions';
import type { Official, RosterEntry, MatchOperation } from '~/components/match/types';

export function useMatchOperation() {
  const state = useMatchOperationState({
    eventMinuteMessage: (...args): string => closeActions.eventMinuteMessage(...args),
    changeResolution: (...args): Promise<void> => closeActions.changeResolution(...args),
    rosterOptions: (...args): Array<{ player: RosterEntry; option: SubstitutionOption }> => eventsActions.rosterOptions(...args),
    draftStorageOrNull: (...args): MatchDraftStorage | null => draftActions.draftStorageOrNull(...args),
    teamName: (...args): string => eventsActions.teamName(...args),
  });
  const { route, auth, request, t, errorMessage, confirm, realtime, matchId, operation, error, actionError, openingBlocked, busyAction, selectedSegmentId, draftEvents, segmentForm, interruptionForm, officialForm, eventForm, eventIdError, eventFieldIssues, closeForm, isTerminal, activeSegment, eventPlayers, eventAssistCandidates, operationLimits, resolution, restoreResolution, selectResolution, resolutionFallback, eventOutgoingOptions, eventIncomingOptions, openingRosterLimits, openingRosterParticipants, hasUnsavedDraft, closeFieldIssue, rostersHref } = state;

  const closeActions = useMatchClose(state, {
    removePersistedDraft: (...args): void => draftActions.removePersistedDraft(...args),
    refreshOperation,
    runAction,
  });
  const lineupActions = useMatchLineup(state, {
    refreshOperation,
    runAction,
  });
  const draftActions = useMatchEventsDraft(state, {
    clearEventFieldIssues: (...args): void => eventsActions.clearEventFieldIssues(...args),
  });
  const eventsActions = useMatchEvents(state);

  const { applyOperation, syncTacticalEditor, persistSelectedSegment } = lineupActions;
  const { persistDraft } = draftActions;
  const { clearEventFieldIssues } = eventsActions;

  let disposed = false;

  function failureMessage(cause: unknown, fallback: string): string {
    return errorMessage(cause, fallback);
  }

  async function redirectOnSessionFailure(cause: unknown): Promise<boolean> {
    if (isUnauthorized(cause) || isNotFound(cause)) {
      await auth.logout();
      await navigateTo({ path: '/login', query: { redirect: safeInternalRedirect(route.fullPath, '/workspace') } });
      return true;
    }
    if (isForbidden(cause)) {
      await navigateTo({ path: '/forbidden', query: { returnTo: safeInternalRedirect(route.fullPath, '/workspace'), resource: 'match' } });
      return true;
    }
    return false;
  }

  async function fetchOperation(): Promise<MatchOperation> {
    return await request<MatchOperation>(`/matches/${matchId}/operation`);
  }

  async function refreshOperation(cause: SegmentRefreshCause = 'refresh') {
    applyOperation(await fetchOperation(), cause);
  }

  function requestOperationReload(trigger: ReloadTrigger, payload?: unknown) {
    if (!payloadTargetsMatch(payload) || busyAction.value || isTerminal.value) return;
    const decision = decideReload({
      consumer: 'workspace',
      trigger,
      initialized: realtime.initialization.initialized,
      initializedWithJoin: realtime.initialization.initializedWithJoin,
    });
    if (decision.action === 'reload') {
      void operationReload.request({ resetPagination: decision.resetPagination });
    }
  }

  async function retryOperation() {
    error.value = null;
    try {
      await refreshOperation();
    } catch (cause) {
      if (!(await redirectOnSessionFailure(cause))) error.value = failureMessage(cause, t('match.noLoad'));
    }
  }

  function payloadTargetsMatch(payload: unknown): boolean {
    if (!payload || typeof payload !== 'object') return true;
    const value = payload as { match_id?: unknown };
    return value.match_id === undefined || String(value.match_id) === matchId;
  }

  async function runAction(
    action: string,
    callback: () => Promise<void>,
    onError?: (cause: unknown) => boolean,
  ) {
    busyAction.value = action;
    actionError.value = null;
    clearEventFieldIssues();
    try {
      await callback();
    } catch (cause) {
      if (await redirectOnSessionFailure(cause)) return;
      if (onError?.(cause)) return;
      openingBlocked.value = null;
      // RF-050/RNF-003: el 409 de resolución se distingue por su `code` aditivo.
      // Un 409 anterior sin `code` conserva el mensaje de `detail`.
      if (classifyMatchConflict(cause) === 'resolution_not_enabled') {
        actionError.value = t('match.resolutionNotEnabled');
        return;
      }
      actionError.value = failureMessage(cause, t('match.noOperation'));
    } finally {
      busyAction.value = null;
    }
  }

  /**
   * Apertura del partido = primer segmento (RF-050). El servidor es la autoridad
   * del tamaño de plantilla: la petición se envía siempre. Si responde **409**
   * `ROSTER_SIZE_OUT_OF_RANGE`, el segmento no se crea en la interfaz, el estado
   * no se recarga —el partido sigue sin abrir— y se muestra el aviso con los
   * equipos implicados, el rango, la cantidad y el enlace a su plantilla para
   * corregir y reintentar.
   */
  function showOpeningBlocked(cause: unknown): void {
    actionError.value = null;
    openingBlocked.value = describeOpeningBlocked({
      detail: matchConflictDetail(cause),
      limits: openingRosterLimits.value,
      participants: openingRosterParticipants.value,
    }, t);
  }

  async function createSegment() {
    const opening = (operation.value?.segments.length ?? 0) === 0;
    await runAction('segment', async () => {
      await request(`/matches/${matchId}/segments`, {
        method: 'POST',
        body: {
          segment_number: segmentForm.segment_number,
          minute_start: segmentForm.minute_start,
          ...resolutionPayload(operationLimits.value, resolution.value),
        },
      });
      openingBlocked.value = null;
      segmentForm.minuteDirty = false;
      await refreshOperation('segment-changed');
    }, (cause) => {
      if (opening && classifyMatchConflict(cause) === 'roster_size_out_of_range') {
        showOpeningBlocked(cause);
        return true;
      }
      return false;
    });
  }

  async function interruptSegment() {
    if (!activeSegment.value) {
      actionError.value = t('match.noActiveSegment');
      return;
    }
    if (draftEvents.value.some((event) => event.segment_id === activeSegment.value!.id)) {
      actionError.value = t('match.pendingEventsBeforeInterruption');
      return;
    }
    await runAction('interrupt-segment', async () => {
      await request(`/matches/${matchId}/segments/${activeSegment.value!.id}/interrupt`, {
        method: 'POST',
        body: {
          reason: interruptionForm.reason,
          minute: interruptionForm.minute,
          notes: interruptionForm.notes || null,
          ...resolutionPayload(operationLimits.value, resolution.value),
        },
      });
      segmentForm.minuteDirty = false;
      interruptionForm.minuteDirty = false;
      interruptionForm.notes = '';
      await refreshOperation('segment-changed');
    });
  }

  async function assignOfficial() {
    if (!officialForm.organization_user_id) return;
    await runAction('official', async () => {
      await request(`/matches/${matchId}/officials`, { method: 'POST', body: buildOfficialAssignmentBody(officialForm) });
      officialForm.organization_user_id = '';
      await refreshOperation();
    });
  }

  async function removeOfficial(official: Official) {
    await runAction(`remove-official-${official.id}`, async () => {
      await request(`/matches/${matchId}/officials/${official.organization_user_id}/${official.official_role}`, { method: 'DELETE' });
      await refreshOperation();
    });
  }

  function handleBeforeUnload(event: BeforeUnloadEvent) {
    if (!hasUnsavedDraft.value || isTerminal.value) return;
    event.preventDefault();
    event.returnValue = '';
  }

  const operationReload = createReloadCoordinator(async () => {
    if (disposed) return;
    try {
      await refreshOperation();
    } catch (cause) {
      if (!(await redirectOnSessionFailure(cause))) actionError.value = failureMessage(cause, t('match.noLoad'));
    }
  });

  useHead(() => ({
    title: `${t('match.matchReport')} | Bracket Craft`,
    meta: [{ name: 'robots', content: 'noindex, nofollow' }],
  }));

  watch(selectedSegmentId, (segmentId) => {
    if (operation.value) syncTacticalEditor();
    persistSelectedSegment(segmentId);
  });

  watch([draftEvents, closeForm], persistDraft, { deep: true });

  // RNF-007: al corregir el formulario, el error asociado a su campo deja de
  // estar vigente; el aviso general se limpia al reintentar el cierre.
  watch(closeForm, () => {
    if (closeFieldIssue.value) closeFieldIssue.value = null;
  }, { deep: true });

  onBeforeRouteLeave((to) => {
    if (!import.meta.client || !hasUnsavedDraft.value || isTerminal.value) return true;
    // RF-022: el enlace a la plantilla conserva el segmento y el borrador local y
    // los restaura al volver, así que avisar de una pérdida que no ocurre sería
    // falso. Cualquier otro destino mantiene la confirmación.
    if (to.path === rostersHref.value) return true;
    return confirm({ title: t('confirm.leaveMatch.title'), message: t('match.unsavedLeave'), confirmLabel: t('confirm.leaveMatch.action'), tone: 'primary' });
  });

  watch(() => eventForm.team_id, () => {
    if (!eventPlayers.value.some((player) => player.player_id === eventForm.player_id)) eventForm.player_id = '';
    if (eventForm.beneficiary_team_id === eventForm.team_id) eventForm.beneficiary_team_id = '';
    // RF-007: un asistente del equipo anterior deja de ser candidato.
    if (!eventAssistCandidates.value.some((player) => player.player_id === eventForm.assist_player_id)) {
      eventForm.assist_player_id = '';
    }
    eventForm.player_out_id = '';
    eventForm.player_in_id = '';
  });

  watch(() => eventForm.event_type, (eventType) => {
    clearEventFieldIssues();
    eventIdError.value = null;
    // RF-001: al cambiar de tipo se descarta el valor de un campo que el nuevo
    // tipo no admite; ningún valor residual viaja al evento.
    if (eventType !== 'goal') eventForm.assist_player_id = '';
    if (eventType !== 'own_goal') eventForm.beneficiary_team_id = '';
    if (eventType !== 'red_card') eventForm.red_card_type = 'direct_red';
    if (eventType === SUBSTITUTION_EVENT_TYPE) {
      eventForm.player_id = '';
    } else {
      eventForm.player_out_id = '';
      eventForm.player_in_id = '';
    }
  });

  watch(() => eventForm.player_id, (playerId) => {
    // RF-008: el goleador no puede ser su propio asistente.
    if (eventForm.event_type === 'goal' && eventForm.assist_player_id === playerId) {
      eventForm.assist_player_id = '';
    }
  });

  // RNF-007: al corregir un valor, su error deja de estar vigente. El aviso de
  // identificador no depende de un campo y vive aparte.
  watch(eventForm, () => {
    if (Object.keys(eventFieldIssues.value).length) clearEventFieldIssues();
  });

  watch([eventOutgoingOptions, eventIncomingOptions], () => {
    if (!eventOutgoingOptions.value.some((row) => row.player.player_id === eventForm.player_out_id && !row.option.disabled)) {
      eventForm.player_out_id = '';
    }
    if (!eventIncomingOptions.value.some((row) => row.player.player_id === eventForm.player_in_id && !row.option.disabled)) {
      eventForm.player_in_id = '';
    }
  });

  watch(resolution, () => {
    // D-8: `reason` es el mismo campo con dos dominios (catálogo del walkover y
    // texto libre de la administrativa). Al cambiar de resolución se vacía para
    // no arrastrar un texto libre al catálogo cerrado ni al revés.
    closeForm.reason = '';
    closeFieldIssue.value = null;
  });

  // RF-034: si la configuración efectiva deja de habilitar la resolución elegida,
  // se cae a tiempo reglamentario sin romper y se avisa en pantalla.
  watch(operationLimits, (limits) => {
    if (!operation.value || resolutionEnabled(limits, resolution.value)) return;
    selectResolution('regular', limits);
    resolutionFallback.value = true;
  });

  const mountOperation = () => {
    // RF-034/P3: la resolución prevista se restaura después de montar para no
    // desajustar la hidratación; solo existe en la sesión de esta pestaña.
    const restored = restoreResolution(operation.value?.limits ?? null);
    resolutionFallback.value = restored.fellBack;
    window.addEventListener('beforeunload', handleBeforeUnload);
    realtime.connect({
      onEvent: (event, payload) => {
        if (['MATCH_CLOSED', 'MATCH_UPDATED'].includes(event)) requestOperationReload('event', payload);
      },
      onReconnect: () => requestOperationReload('reconnect'),
      onResync: (payload) => requestOperationReload(resyncTrigger(payload.reason)),
    });
  };

  const unmountOperation = () => {
    disposed = true;
    window.removeEventListener('beforeunload', handleBeforeUnload);
    realtime.disconnect();
  };

  return { ...state, ...closeActions, ...lineupActions, ...draftActions, ...eventsActions, failureMessage, redirectOnSessionFailure, fetchOperation, refreshOperation, requestOperationReload, retryOperation, payloadTargetsMatch, runAction, showOpeningBlocked, createSegment, interruptSegment, assignOfficial, removeOfficial, handleBeforeUnload, mountOperation, unmountOperation };
}

export type MatchOperationContext = ReturnType<typeof useMatchOperation>;
