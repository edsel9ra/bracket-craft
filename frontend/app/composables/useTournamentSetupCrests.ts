import type { Ref } from 'vue';
import type { SetupServices, TeamSummary, TeamCrestResponse } from '~/components/workspace/setup/types';
import { getApiCode } from '~/utils/api';
import { applyCrestResponse, crestErrorMessageKey } from '~/utils/teamCrest';

export function useTournamentSetupCrests({ request, t, confirm, tournamentId, redirectOnSessionFailure, failureMessage, teams, canManageTournaments }: Omit<SetupServices, 'auth'> & {
  teams: Ref<TeamSummary[]>;
  canManageTournaments: Ref<boolean>;
}) {
  // RF-055/RF-056: una imagen por equipo, gestionada solo desde el torneo donde
  // está inscrito. El estado vive en la página: la fila se actualiza en sitio y
  // no se recarga ni se tocan la versión seleccionada ni los borradores de la 012.
  const crestBusyTeamId = ref<string | null>(null);
  const crestStatusMessage = ref<string | null>(null);
  const crestErrors = reactive<Record<string, string>>({});
  const crestFiles = reactive<Record<string, File | null>>({});
  const crestInputVersions = reactive<Record<string, number>>({});

  function crestInputId(teamId: string): string {
    return `crest-file-${teamId}`;
  }

  function crestErrorId(teamId: string): string {
    return `crest-error-${teamId}`;
  }

  function onCrestFileSelected(teamId: string, event: Event): void {
    const input = event.target as HTMLInputElement;
    crestFiles[teamId] = input.files?.[0] ?? null;
    delete crestErrors[teamId];
    if (!crestFiles[teamId]) return;
    const team = teams.value.find((candidate) => candidate.team_id === teamId);
    if (team) void uploadCrest(team);
  }

  function applyCrestRow(response: TeamCrestResponse): void {
    const index = teams.value.findIndex((candidate) => candidate.team_id === response.team_id);
    if (index < 0) return;
    const team = teams.value[index];
    if (!team) return;
    const updated = applyCrestResponse(team, response);
    if (updated) teams.value[index] = updated;
  }

  function crestFailureMessage(teamId: string, cause: unknown): void {
    const key = crestErrorMessageKey(getApiCode(cause));
    crestErrors[teamId] = key ? t(key) : failureMessage(cause, t('crest.error.generic'));
  }

  async function uploadCrest(team: TeamSummary): Promise<void> {
    if (!canManageTournaments.value) return;
    const file = crestFiles[team.team_id] ?? null;
    delete crestErrors[team.team_id];
    if (!file) {
      crestErrors[team.team_id] = t('crest.error.selectFile');
      return;
    }
    crestBusyTeamId.value = team.team_id;
    crestStatusMessage.value = t('crest.uploading');
    const body = new FormData();
    // El nombre del campo es el del contrato; el nombre del archivo no se usa.
    body.append('file', file);
    try {
      // `FormData` fija el Content-Type con su boundary: no se sobrescribe.
      const updated = await request<TeamCrestResponse>(
        `/tournaments/${tournamentId}/teams/${team.team_id}/crest`,
        { method: 'POST', body },
      );
      applyCrestRow(updated);
      crestFiles[team.team_id] = null;
      crestInputVersions[team.team_id] = (crestInputVersions[team.team_id] ?? 0) + 1;
      crestStatusMessage.value = t('crest.updated');
    } catch (cause) {
      if (await redirectOnSessionFailure(cause)) return;
      crestFailureMessage(team.team_id, cause);
      crestStatusMessage.value = null;
    } finally {
      crestBusyTeamId.value = null;
    }
  }

  async function removeCrest(team: TeamSummary): Promise<void> {
    if (!canManageTournaments.value || !team.crest_url) return;
    if (import.meta.client && !(await confirm({ title: t('confirm.removeCrest.title'), message: t('crest.confirmRemove', { team: team.name }), confirmLabel: t('confirm.removeCrest.action'), tone: 'danger' }))) return;
    crestBusyTeamId.value = team.team_id;
    crestStatusMessage.value = t('crest.removing');
    delete crestErrors[team.team_id];
    try {
      await request(`/tournaments/${tournamentId}/teams/${team.team_id}/crest`, { method: 'DELETE' });
      applyCrestRow({ team_id: team.team_id, crest_url: null, logo_url: null });
      crestStatusMessage.value = t('crest.removed');
    } catch (cause) {
      if (await redirectOnSessionFailure(cause)) return;
      crestFailureMessage(team.team_id, cause);
      crestStatusMessage.value = null;
    } finally {
      crestBusyTeamId.value = null;
    }
  }


  return { crestBusyTeamId, crestStatusMessage, crestErrors, crestInputVersions, crestInputId, crestErrorId, onCrestFileSelected, removeCrest };
}
