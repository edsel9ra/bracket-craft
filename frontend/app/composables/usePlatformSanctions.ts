import { sanctionQuery, type CaseFilters, type DecisionBody, type SanctionCase, type SanctionDetail, type SanctionPage, type SanctionPreview, type SanctionReceipt } from '~/utils/sanctions';

export type PlatformSanctionCase = Pick<SanctionCase, 'id' | 'suspension_id' | 'case_type' | 'status' | 'submitted_at'> & { authorization_id: string; organization_id: string };

export function usePlatformSanctions() {
  const { request } = useApi();
  return {
    list: (filters?: CaseFilters) => request<SanctionPage<PlatformSanctionCase>>(`/platform/sanction-cases${sanctionQuery(filters)}`),
    detail: (id: string) => request<SanctionDetail>(`/platform/sanction-cases/${id}`),
    preview: (id: string) => request<SanctionPreview>(`/platform/sanction-cases/${id}/preview`),
    decide: (id: string, body: DecisionBody) => request<SanctionReceipt>(`/platform/sanction-cases/${id}/decision`, { method: 'POST', body }),
  };
}
