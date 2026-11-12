import type { Preview, Rectification, RectificationDetail, ReportVersion } from '~/utils/rectifications';

export function usePlatformRectifications() {
  const { request } = useApi();
  return {
    list: () => request<Rectification[]>('/platform/rectifications'),
    detail: (id: string) => request<RectificationDetail & { current_version: ReportVersion }>(`/platform/rectifications/${id}`),
    preview: (id: string) => request<Preview>(`/platform/rectifications/${id}/preview`),
    decide: (id: string, body: { decision: 'approve' | 'reject'; reason: string; expected_base_version: number }) => request<Rectification>(`/platform/rectifications/${id}/decision`, { method: 'POST', body }),
  };
}
