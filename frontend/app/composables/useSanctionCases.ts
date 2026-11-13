import { sanctionQuery, type AppealBody, type AuthorizationBody, type CaseFilters, type DecisionBody, type Evidence, type Pagination, type ProposalBody, type SanctionAuthorization, type SanctionCase, type SanctionDetail, type SanctionFilters, type SanctionNotice, type SanctionPage, type SanctionPreview, type SanctionReceipt, type SanctionRow } from '~/utils/sanctions';

export function useSanctionCases() {
  const { request } = useApi();
  return {
    list: (filters?: CaseFilters) => request<SanctionPage<SanctionCase>>(`/sanction-cases${sanctionQuery(filters)}`),
    sanctions: (filters?: SanctionFilters) => request<SanctionPage<SanctionRow>>(`/sanctions${sanctionQuery(filters)}`),
    detail: (id: string) => request<SanctionDetail>(`/sanction-cases/${id}`),
    preview: (id: string) => request<SanctionPreview>(`/sanction-cases/${id}/preview`),
    appeal: (id: string, body: AppealBody) => request<SanctionReceipt>(`/sanctions/${id}/appeals`, { method: 'POST', body }),
    propose: (id: string, body: ProposalBody) => request<SanctionReceipt>(`/sanctions/${id}/administrative-proposals`, { method: 'POST', body }),
    decide: (id: string, body: DecisionBody) => request<SanctionReceipt>(`/sanction-cases/${id}/decision`, { method: 'POST', body }),
    withdraw: (id: string, body: Evidence) => request<SanctionReceipt>(`/sanction-cases/${id}/withdraw`, { method: 'POST', body }),
    authorizations: (id: string) => request<SanctionAuthorization[]>(`/sanction-cases/${id}/platform-authorizations`),
    grant: (id: string, body: AuthorizationBody) => request<SanctionAuthorization>(`/sanction-cases/${id}/platform-authorizations`, { method: 'POST', body }),
    revoke: (id: string, authorization: string) => request<SanctionAuthorization>(`/sanction-cases/${id}/platform-authorizations/${authorization}`, { method: 'DELETE' }),
    notifications: (filters?: Pagination) => request<{ items: SanctionNotice[] }>(`/sanction-notifications${sanctionQuery(filters)}`),
  };
}
