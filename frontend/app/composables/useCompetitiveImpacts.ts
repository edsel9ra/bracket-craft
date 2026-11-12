import { inboxQuery, type CompetitiveImpact, type InboxFilters, type Page } from '~/utils/rectifications';

export function useCompetitiveImpacts() {
  const { request } = useApi();
  return {
    list: (filters?: InboxFilters) => request<Page<CompetitiveImpact>>(`/competitive-impacts${inboxQuery(filters)}`),
    listByTournament: (id: string) => request<CompetitiveImpact[]>(`/tournaments/${id}/competitive-impacts`),
    close: (id: string, reason: string) => request<CompetitiveImpact>(`/competitive-impacts/${id}/close`, { method: 'POST', body: { reason } }),
  };
}
