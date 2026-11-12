import { inboxQuery, type InboxFilters, type Page, type Rectification, type RectificationDetail, type ReportProposal, type ReportVersion, type Preview, type PlatformAuthorization, type MatchOperation } from '~/utils/rectifications';

export function useMatchRectifications() {
  const { request } = useApi();
  return {
    list: (filters?: InboxFilters) => request<Page<Rectification>>(`/rectifications${inboxQuery(filters)}`),
    listByMatch: (id: string) => request<Rectification[]>(`/matches/${id}/rectifications`),
    versions: (id: string) => request<ReportVersion[]>(`/matches/${id}/report-versions`),
    version: (id: string, number: number) => request<ReportVersion>(`/matches/${id}/report-versions/${number}`),
    operation: (id: string) => request<MatchOperation>(`/matches/${id}/operation`),
    detail: (id: string) => request<RectificationDetail>(`/rectifications/${id}`),
    create: (id: string, body: { proposed_report: ReportProposal; reason: string; evidence: string }) => request<Rectification>(`/matches/${id}/rectifications`, { method: 'POST', body }),
    withdraw: (id: string) => request<Rectification>(`/rectifications/${id}/withdraw`, { method: 'POST' }),
    preview: (id: string) => request<Preview>(`/rectifications/${id}/preview`),
    decide: (id: string, body: { decision: 'approve' | 'reject'; reason: string; expected_base_version: number }) => request<Rectification>(`/rectifications/${id}/decision`, { method: 'POST', body }),
    authorizations: (id: string) => request<PlatformAuthorization[]>(`/rectifications/${id}/platform-authorizations`),
    grant: (id: string, body: { platform_admin_email: string; reason: string }) => request<PlatformAuthorization>(`/rectifications/${id}/platform-authorizations`, { method: 'POST', body }),
    revoke: (id: string, authorization: string) => request<PlatformAuthorization>(`/rectifications/${id}/platform-authorizations/${authorization}`, { method: 'DELETE' }),
  };
}
