import type { Ref } from 'vue';
import type { SetupServices, MatchSummary } from '~/components/workspace/setup/types';
import { DEFAULT_RULES_CONFIG, type RulesConfig } from '~/utils/rulesConfig';
import { createMatchDraftStore } from '~/utils/matchDraft';
import { findMinutesOutside, minutesLimits } from '~/utils/rulesMinutes';
import type { ResolutionDraftEventInput, ResolutionSegmentInput } from '~/utils/matchResolution';

export function useTournamentSetupRules({ auth, request, serverRulesConfig, selectedVersionMatches }: Pick<SetupServices, 'auth' | 'request'> & {
  serverRulesConfig: Ref<RulesConfig | null>;
  selectedVersionMatches: Ref<MatchSummary[]>;
}) {
  /** Borradores locales de partido: solo se leen para el aviso de minutos. */
  function matchDraftStorageOrNull(): Storage | null {
    if (!import.meta.client) return null;
    try {
      return window.localStorage;
    } catch {
      return null;
    }
  }

  const CLOSED_MATCH_STATUSES = ['finished', 'cancelled', 'administrative_resolution'];

  /**
   * Impacto de un cambio de minutos en un borrador (RF-035, criterio 23).
   *
   * Solo se miran partidos no cerrados de la versión seleccionada: las actas
   * confirmadas no se revalidan. Los segmentos persistidos se leen de la
   * operación de los partidos en juego o suspendidos; los eventos salen del
   * borrador local del navegador. La comprobación es informativa: no borra ni
   * reescribe nada y el servidor sigue siendo la autoridad del guardado.
   */
  async function minutesImpactBeforeSave(config: RulesConfig) {
    const previous = serverRulesConfig.value ?? DEFAULT_RULES_CONFIG;
    const storage = matchDraftStorageOrNull();
    const relevant = selectedVersionMatches.value.filter(
      (match) => !CLOSED_MATCH_STATUSES.includes(match.status),
    );

    const draftEvents = new Map<string, readonly ResolutionDraftEventInput[]>();
    for (const match of relevant) {
      let events: readonly ResolutionDraftEventInput[] = [];
      if (storage) {
        const draft = createMatchDraftStore({
          userId: auth.userId,
          organizationId: auth.organizationId,
          matchId: match.id,
        }, storage).read().draft;
        if (draft) events = draft.events as unknown as readonly ResolutionDraftEventInput[];
      }
      draftEvents.set(match.id, events);
    }

    const segments = new Map<string, readonly ResolutionSegmentInput[]>();
    await Promise.all(relevant
      .filter((match) => match.status === 'live' || match.status === 'suspended')
      .map(async (match) => {
        try {
          const operation = await request<{ segments?: ResolutionSegmentInput[] }>(
            `/matches/${match.id}/operation`,
          );
          segments.set(match.id, Array.isArray(operation.segments) ? operation.segments : []);
        } catch {
          // Si la lectura falla, el aviso es parcial; el guardado no se bloquea.
          segments.set(match.id, []);
        }
      }));

    return findMinutesOutside(relevant.map((match) => ({
      matchId: match.id,
      previous: minutesLimits(previous, match.stage_id),
      next: minutesLimits(config, match.stage_id),
      segments: segments.get(match.id) ?? [],
      draftEvents: draftEvents.get(match.id) ?? [],
    })));
  }

  return { minutesImpactBeforeSave };
}
