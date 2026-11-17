import type { ResolutionPreview, SlotOrigin, SlotOriginsState } from '~/utils/stageAdvancement';

export interface SaveSlotOriginsBody {
  origins: SlotOrigin[];
  start_date: string;
  round_interval_days: number;
  match_interval_hours: number;
  replace_existing: boolean;
}

/** Llamadas de la spec 040; todas pasan por `useApi` (CSRF, cookies y SSR). */
export function useStageAdvancement() {
  const { request } = useApi();
  const path = (tournamentId: string, stageId: string) => `/tournaments/${tournamentId}/stages/${stageId}/slot-origins`;

  async function load(tournamentId: string, stageId: string): Promise<SlotOriginsState> {
    return await request<SlotOriginsState>(path(tournamentId, stageId));
  }

  async function template(tournamentId: string, stageId: string, sourceStageId: string, slotsCount: number): Promise<SlotOrigin[]> {
    const query = new URLSearchParams({ source_stage_id: sourceStageId, slots_count: String(slotsCount) });
    const response = await request<{ origins: SlotOrigin[] }>(`${path(tournamentId, stageId)}/template?${query}`);
    return response.origins;
  }

  async function save(tournamentId: string, stageId: string, body: SaveSlotOriginsBody): Promise<SlotOriginsState> {
    return await request<SlotOriginsState>(path(tournamentId, stageId), { method: 'PUT', body });
  }

  async function remove(tournamentId: string, stageId: string): Promise<void> {
    await request(path(tournamentId, stageId), { method: 'DELETE' });
  }

  const resolutionPath = (tournamentId: string, stageId: string) => `/tournaments/${tournamentId}/stages/${stageId}/resolution`;

  async function preview(tournamentId: string, stageId: string): Promise<ResolutionPreview> {
    return await request<ResolutionPreview>(`${resolutionPath(tournamentId, stageId)}/preview`);
  }

  async function confirmResolution(tournamentId: string, stageId: string, fingerprint: string): Promise<ResolutionPreview> {
    return await request<ResolutionPreview>(resolutionPath(tournamentId, stageId), { method: 'POST', body: { fingerprint } });
  }

  return { load, template, save, remove, preview, confirmResolution };
}
