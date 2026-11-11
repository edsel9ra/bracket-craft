import type { MatchOperationState } from '~/composables/useMatchOperationState';
import { validateEventMinute } from '~/utils/matchResolution';
import { buildDraftEvent, eventSummary, newClientEventId, validateAssist, validateEventValues, validateSegmentMinute, type EventFormValues } from '~/utils/matchEvents';
import { SUBSTITUTION_EVENT_TYPE, validateSubstitutionPair, type SubstitutionOption, type SubstitutionUnavailableReason } from '~/utils/substitutions';
import type { EventType, OfficialRole, RosterEntry, MatchEvent, DraftEvent, EventFieldKey } from '~/components/match/types';

export function useMatchEvents(state: MatchOperationState) {
  const { t, formatDateTime, operation, actionError, selectedSegmentId, draftEvents, eventForm, eventIdError, eventFieldIssues, officialRoles, eventTypes, substitutionReasonKeys, match, selectedSegment, selectedSegmentIsActive, eventPlayers, eventRosterPlayers, resolutionLimits, eventSubstitutionTeam, eventValidationIssues, eventSegmentMinuteKeys, eventAssistIssueKeys, eventFormIssueKeys } = state;

  function rosterOptions(options: SubstitutionOption[]): Array<{ player: RosterEntry; option: SubstitutionOption }> {
    const byPlayer = new Map(options.map((option) => [option.player_id, option]));
    return eventRosterPlayers.value
      .filter((player) => byPlayer.has(player.player_id))
      .map((player) => ({ player, option: byPlayer.get(player.player_id) as SubstitutionOption }));
  }

  function substitutionMessage(reason: SubstitutionUnavailableReason | null): string {
    return t(substitutionReasonKeys[reason || 'no_state']);
  }

  function clearEventFieldIssues(): void {
    eventFieldIssues.value = {};
  }

  function setEventFieldIssue(
    field: EventFieldKey,
    key: string,
    params?: Record<string, string | number>,
  ): void {
    eventFieldIssues.value = {
      ...eventFieldIssues.value,
      [field]: params ? { key, params } : { key },
    };
  }

  /** Texto del error del campo en el idioma activo; vacío cuando es válido. */
  function eventFieldError(field: EventFieldKey): string {
    const issue = eventFieldIssues.value[field];
    return issue ? t(issue.key, issue.params) : '';
  }

  function eventFieldErrorId(field: EventFieldKey): string {
    return `event-field-${field}-error`;
  }

  /** `aria-describedby` del control: su mensaje de error, si lo tiene. */
  function eventFieldDescribedBy(field: EventFieldKey): string | undefined {
    return eventFieldError(field) ? eventFieldErrorId(field) : undefined;
  }

  function pushDraftEvent(formValues: EventFormValues): boolean {
    // RF-015: el identificador sale de `crypto.randomUUID()`. Sin él no se
    // inventa un texto: el evento no entra y se avisa (el texto fino es T11).
    const clientEventId = newClientEventId(globalThis.crypto);
    if (!clientEventId) {
      eventIdError.value = t('match.eventIdUnavailable');
      return false;
    }
    // RF-001/RF-002: el payload se construye desde el catálogo del tipo, así que
    // nunca lleva un campo prohibido con valor ni una clave desconocida.
    const event = buildDraftEvent(formValues, selectedSegmentId.value, clientEventId);
    if (!event) return false;
    draftEvents.value.push(event);
    return true;
  }

  function addEvent() {
    eventIdError.value = null;
    clearEventFieldIssues();

    if (!selectedSegmentId.value || !selectedSegmentIsActive.value) {
      setEventFieldIssue('segment', eventFormIssueKeys.segment.key);
      return;
    }
    if (!eventForm.team_id) {
      setEventFieldIssue('team', eventFormIssueKeys.team.key);
      return;
    }

    const values: EventFormValues = { ...eventForm };
    // RF-006: solo el subconjunto declarado. La plantilla del partido, las
    // sanciones, el estado en campo y los límites de sustitución son autoridad
    // del servidor. Cada problema se queda junto a su campo (RNF-007).
    let blocked = false;
    for (const issue of validateEventValues(values).issues) {
      const target = eventValidationIssues[issue.code];
      if (!target) continue;
      setEventFieldIssue(target.field, target.key);
      blocked = true;
    }

    const limits = resolutionLimits.value;
    // RF-032: la misma regla que el cierre, sobre `minute + added_minute`; el
    // evento inválido no se añade y lo escrito se conserva para corregirlo.
    const minuteCheck = validateEventMinute(
      eventForm.minute,
      eventForm.added_minute,
      limits.maxMinute,
      limits.addedMax,
    );
    if (!minuteCheck.ok) {
      if (minuteCheck.reason === 'added') {
        // El añadido por sí solo no es válido o supera su tope: el error se
        // queda junto a su campo, que es el único que hay que corregir. El
        // exceso combinado sigue junto al minuto, que es el campo principal.
        setEventFieldIssue('added_minute', 'match.addedMinuteOutOfRange', { max: limits.addedMax });
      } else {
        // Los valores que se nombran son los escritos, no una normalización: el
        // operador ve exactamente qué minuto y qué añadido corregir.
        setEventFieldIssue('minute', 'match.eventMinuteExceedsMaximum', {
          minute: eventForm.minute,
          added: eventForm.added_minute,
          max: limits.maxMinute,
        });
      }
      blocked = true;
    } else {
      // RF-006: el minuto debe caer dentro del segmento seleccionado cuando ya
      // tiene fin; el servidor lo vuelve a comprobar al cerrar.
      const segmentCheck = validateSegmentMinute(eventForm.minute, selectedSegment.value);
      if (!segmentCheck.ok) {
        const before = segmentCheck.issue === 'before_segment';
        setEventFieldIssue(
          'minute',
          eventSegmentMinuteKeys[before ? 'before_segment' : 'after_segment'].key,
          before ? { start: segmentCheck.start ?? 0 } : { end: segmentCheck.end ?? 0 },
        );
        blocked = true;
      }
    }

    if (eventForm.event_type === 'goal' && eventForm.assist_player_id) {
      const assist = validateAssist(
        eventForm.assist_player_id,
        eventForm.player_id,
        eventPlayers.value,
      );
      if (!assist.ok && assist.issue === 'not_in_team') {
        setEventFieldIssue('assist', eventAssistIssueKeys.not_in_team.key);
        blocked = true;
      }
    }

    if (blocked) return;

    if (eventForm.event_type === SUBSTITUTION_EVENT_TYPE) {
      const pair = validateSubstitutionPair(
        eventSubstitutionTeam.value,
        draftEvents.value,
        eventForm.player_out_id,
        eventForm.player_in_id,
      );
      if (!pair.ok) {
        const field: EventFieldKey = pair.reason === 'not_on_field' ? 'player_out' : 'player_in';
        setEventFieldIssue(field, substitutionReasonKeys[pair.reason || 'no_state']);
        return;
      }
      if (!pushDraftEvent({
        ...values,
        player_out_id: pair.player_out_id,
        player_in_id: pair.player_in_id,
      })) {
        if (!eventIdError.value) setEventFieldIssue('team', eventFormIssueKeys.team.key);
        return;
      }
      eventForm.player_out_id = '';
      eventForm.player_in_id = '';
      actionError.value = null;
      return;
    }

    if (!pushDraftEvent(values)) {
      // Un evento no construible no entra al borrador; el aviso ya está puesto.
      if (!eventIdError.value) setEventFieldIssue('team', eventFormIssueKeys.team.key);
      return;
    }
    eventForm.player_id = '';
    eventForm.assist_player_id = '';
    eventForm.beneficiary_team_id = '';
    eventForm.red_card_type = 'direct_red';
    actionError.value = null;
  }

  function removeEvent(clientEventId: string) {
    draftEvents.value = draftEvents.value.filter((event) => event.client_event_id !== clientEventId);
  }

  function playerName(roster: RosterEntry): string {
    return `${roster.first_name} ${roster.last_name}`;
  }

  function rosterPlayerName(playerId: string | null): string {
    const roster = operation.value?.rosters.find((entry) => entry.player_id === playerId);
    return roster ? playerName(roster) : '';
  }

  /** Textos del resumen, siempre por i18n y con paridad es/en (RF-005). */
  function eventSummaryLabels() {
    return {
      assist: t('match.assistShort'),
      ownGoal: t('match.ownGoalBeneficiaryShort'),
      redCardDirect: t('match.redCardDirectShort'),
      redCardDouble: t('match.redCardDoubleShort'),
    };
  }

  function draftEventSummary(event: DraftEvent): string {
    // RF-005: borrador y acta comparten el resumen; el asistente del gol y el
    // equipo beneficiado del autogol se resuelven desde la operación. Las
    // palabras son formas cortas del catálogo, no etiquetas de campo.
    return eventSummary(event, rosterPlayerName, eventSummaryLabels(), teamName);
  }

  function persistedEventSummary(event: MatchEvent): string {
    // RF-011: la operación no devuelve el nombre del asistente; se resuelve de la
    // plantilla. El jugador principal conserva el nombre que trae el evento.
    const ownName = `${event.first_name} ${event.last_name}`.trim();
    return eventSummary(
      event,
      (playerId) => (playerId === event.player_id && ownName ? ownName : rosterPlayerName(playerId)),
      eventSummaryLabels(),
      teamName,
    );
  }

  function teamName(teamId: string | null): string {
    if (teamId === match.value?.home_team_id) return match.value?.home_team_name || t('setup.home');
    if (teamId === match.value?.away_team_id) return match.value?.away_team_name || t('setup.away');
    return t('setup.teams');
  }

  function eventLabel(eventType: EventType): string {
    const key = eventTypes.find((event) => event.value === eventType)?.labelKey;
    return key ? t(key) : eventType;
  }

  function officialLabel(role: OfficialRole): string {
    const key = officialRoles.find((item) => item.value === role)?.labelKey;
    return key ? t(key) : role;
  }

  function formatDate(value: string | null): string {
    if (!value) return t('public.dateToDefine');
    return formatDateTime(value);
  }

  return { rosterOptions, substitutionMessage, clearEventFieldIssues, setEventFieldIssue, eventFieldError, eventFieldErrorId, eventFieldDescribedBy, pushDraftEvent, addEvent, removeEvent, playerName, rosterPlayerName, eventSummaryLabels, draftEventSummary, persistedEventSummary, teamName, eventLabel, officialLabel, formatDate };
}
