import type { MatchOperationState } from '~/composables/useMatchOperationState';
import { formationSlots, type FormationCode } from '~/constants/formations';
import { readMatchSelection, teamRosterHref, writeMatchSelection } from '~/utils/matchNavigation';
import { applyInterruptionMinute, applySegmentProposal, forceMinuteOnRefresh, type SegmentRefreshCause } from '~/utils/matchSegments';
import { deriveLineupSource } from '~/utils/lineupSource';
import type { LineupRole, TacticalLineupRow, MatchOperation } from '~/components/match/types';

export function useMatchLineup(state: MatchOperationState, dependencies: {
  refreshOperation(cause?: SegmentRefreshCause): Promise<void>;
  runAction(action: string, callback: () => Promise<void>, onError?: (cause: unknown) => boolean): Promise<void>;
}) {
  const { request, t, matchId, operation, actionError, openingBlocked, selectedSegmentId, lineupRoles, lineupPositions, lineupFormations, segmentForm, interruptionForm, eventForm, match, selectedSegmentIsActive, teamRosters, lineupEntries, selectedTacticalLineups, selectedSegmentStorageKey } = state;
  const { refreshOperation, runAction } = dependencies;

  /**
   * RF-015/D-5: el formulario de segmento sale de la propuesta del servidor
   * (`next_segment`), no de una suma del cliente. El número es siempre el del
   * servidor; el minuto solo se escribe si la propuesta es derivada y el refresco
   * lo permite (`forceMinuteOnRefresh`): al montar y tras crear o interrumpir,
   * pero no en un refresco manual ni en el que provoca el socket.
   */
  function syncSegmentForm(proposal: unknown, cause: SegmentRefreshCause): void {
    const resolved = applySegmentProposal({
      segment_number: segmentForm.segment_number,
      minute_start: segmentForm.minute_start,
      minuteDirty: segmentForm.minuteDirty,
    }, proposal, { forceMinute: forceMinuteOnRefresh(cause) });
    segmentForm.segment_number = resolved.segment_number;
    segmentForm.minute_start = resolved.minute_start;
    segmentForm.minuteDirty = resolved.minuteDirty;
  }

  /** El operador ha escrito el minuto: un refresco normal ya no lo pisa. */
  function markSegmentMinuteDirty(): void {
    segmentForm.minuteDirty = true;
  }

  /**
   * El minuto de la interrupción sigue la misma regla que el del segmento (D-5):
   * se prefija con el `minute_start` del segmento activo al montar y tras crear o
   * interrumpir, y un refresco normal —incluido el que provoca el socket— no pisa
   * lo que el operador está escribiendo.
   */
  function syncInterruptionForm(proposal: number | null, cause: SegmentRefreshCause): void {
    const resolved = applyInterruptionMinute(
      { minute: interruptionForm.minute, dirty: interruptionForm.minuteDirty },
      proposal,
      { forceMinute: forceMinuteOnRefresh(cause) },
    );
    interruptionForm.minute = resolved.minute;
    interruptionForm.minuteDirty = resolved.dirty;
  }

  /** El operador ha escrito el minuto de la interrupción: un refresco no lo pisa. */
  function markInterruptionMinuteDirty(): void {
    interruptionForm.minuteDirty = true;
  }

  function applyOperation(value: MatchOperation, cause: SegmentRefreshCause = 'refresh') {
    operation.value = value;
    // Si el partido ya tiene segmentos (por ejemplo, abierto en otra pestaña) el
    // aviso de apertura bloqueada dejó de ser cierto.
    if (value.segments.length) openingBlocked.value = null;
    const currentSegment = value.segments.find((segment) => segment.id === selectedSegmentId.value);
    const nextActiveSegment = value.segments.find((segment) => segment.status === 'active');
    if (!currentSegment || (currentSegment.status !== 'active' && nextActiveSegment)) {
      selectedSegmentId.value = nextActiveSegment?.id || value.segments.at(-1)?.id || '';
    }
    syncSegmentForm(value.next_segment, cause);
    syncInterruptionForm(nextActiveSegment?.minute_start ?? null, cause);
    if (!eventForm.team_id) {
      eventForm.team_id = value.match.home_team_id || value.match.away_team_id || '';
    }
    syncTacticalEditor();
  }

  function syncTacticalEditor() {
    const rows = selectedTacticalLineups.value;
    const formations: Record<string, FormationCode | ''> = {};
    const positions: Record<string, string> = {};
    const roles: Record<string, LineupRole | ''> = {};
    const persistedTeams = new Set(rows.map((row) => row.team_id));
    for (const entry of operation.value?.lineup || []) {
      if (!persistedTeams.has(entry.team_id)) roles[entry.roster_id] = entry.role;
    }
    for (const row of rows) {
      formations[row.team_id] = row.formation_code;
      if (row.player_id && row.position_slot) {
        const roster = operation.value?.rosters.find((entry) => entry.player_id === row.player_id && entry.team_id === row.team_id);
        if (roster) positions[roster.roster_id] = row.position_slot;
      }
      if (row.player_id) {
        const roster = operation.value?.rosters.find((entry) => entry.player_id === row.player_id && entry.team_id === row.team_id);
        if (roster) roles[roster.roster_id] = row.is_starter ? 'starter' : 'substitute';
      }
    }
    // Precarga desde la fuente para equipos sin formacion persistida en el segmento
    // seleccionado (spec 028, RF-001/RF-003/RF-010). La formacion persistida
    // prevalece: deriveLineupSource devuelve null para esos equipos.
    // RF-012/RF-013: se omite la precarga en partido terminal (incluido
    // `suspended`) o en version no publicada (salvo borrador, que aplica la
    // misma regla que publicada).
    const isTerminalForPreload = ['finished', 'cancelled', 'administrative_resolution', 'suspended'].includes(match.value?.status || '');
    const versionStatus = match.value?.version_status || '';
    const allowPreload = !isTerminalForPreload && (versionStatus === 'published' || versionStatus === 'draft');
    if (allowPreload) {
      const source = deriveLineupSource(
        (operation.value?.tactical_lineups || []) as any,
        (operation.value?.rosters || []) as any,
        selectedSegmentId.value,
      );
      for (const [teamId, src] of Object.entries(source || {})) {
        if (!src || persistedTeams.has(teamId)) continue;
        formations[teamId] = (src.formation_code || '') as FormationCode | '';
        for (const rosterId of Object.keys(src.roles)) {
          roles[rosterId] = src.roles[rosterId] ?? '';
        }
        for (const rosterId of Object.keys(src.positions)) {
          const pos = src.positions[rosterId];
          if (pos) positions[rosterId] = pos;
        }
      }
    }
    lineupFormations.value = formations;
    lineupPositions.value = positions;
    for (const roster of operation.value?.rosters || []) {
      if (roster.team_id === match.value?.home_team_id || roster.team_id === match.value?.away_team_id) {
        roles[roster.roster_id] ||= '';
      }
    }
    lineupRoles.value = roles;
  }

  function setFormation(teamId: string, event: Event) {
    const formation = (event.target as HTMLSelectElement).value as FormationCode | '';
    lineupFormations.value[teamId] = formation;
    const allowed = new Set(formationSlots(formation));
    for (const roster of operation.value?.rosters.filter((entry) => entry.team_id === teamId) || []) {
      const current = lineupPositions.value[roster.roster_id];
      if (current === undefined || !allowed.has(current)) delete lineupPositions.value[roster.roster_id];
    }
  }

  function availablePositions(teamId: string): string[] {
    return formationSlots(lineupFormations.value[teamId] || '');
  }

  function tacticalRowsForTeam(teamId: string): TacticalLineupRow[] {
    return selectedTacticalLineups.value.filter((entry) => entry.team_id === teamId);
  }

  function isTeamLineupPublic(teamId: string): boolean {
    return tacticalRowsForTeam(teamId).some((entry) => entry.is_public);
  }

  async function toggleLineupPublication(teamId: string) {
    if (!selectedSegmentId.value) return;
    await runAction(`lineup-publication-${teamId}`, async () => {
      await request(`/matches/${matchId}/lineup/publication`, {
        method: 'PATCH',
        body: {
          segment_id: selectedSegmentId.value,
          team_id: teamId,
          is_public: !isTeamLineupPublic(teamId),
        },
      });
      await refreshOperation();
    });
  }

  function teamRosterLink(teamId: string): string {
    return teamRosterHref({
      tournamentId: match.value?.tournament_id || '',
      teamId,
      matchId,
    });
  }

  function persistSelectedSegment(segmentId: string) {
    if (!import.meta.client || !segmentId) return;
    try {
      sessionStorage.setItem(selectedSegmentStorageKey.value, writeMatchSelection(segmentId));
    } catch {
      // Storage can be unavailable in private browsing; the in-memory selection remains usable.
    }
  }

  function restoreSelectedSegment() {
    if (!import.meta.client || !operation.value) return;
    try {
      const stored = readMatchSelection(
        sessionStorage.getItem(selectedSegmentStorageKey.value),
        operation.value.segments.map((segment) => segment.id),
      );
      if (stored) selectedSegmentId.value = stored;
    } catch {
      // Storage can be unavailable in private browsing; the default selection remains.
    }
  }

  async function saveLineup() {
    if (!selectedSegmentId.value || !selectedSegmentIsActive.value) {
      actionError.value = t('match.createSegmentFirst');
      return;
    }
    await runAction('lineup', async () => {
      await request(`/matches/${matchId}/lineup`, {
        method: 'PUT',
        body: {
          segment_id: selectedSegmentId.value,
          entries: lineupEntries.value,
          team_lineups: teamRosters.value
            .filter((team) => team.team_id && lineupFormations.value[team.team_id])
            .map((team) => ({ team_id: team.team_id, formation_code: lineupFormations.value[team.team_id] })),
        },
      });
      await refreshOperation();
    });
  }

  return { syncSegmentForm, markSegmentMinuteDirty, syncInterruptionForm, markInterruptionMinuteDirty, applyOperation, syncTacticalEditor, setFormation, availablePositions, tacticalRowsForTeam, isTeamLineupPublic, toggleLineupPublication, teamRosterLink, persistSelectedSegment, restoreSelectedSegment, saveLineup };
}
