import { isForbidden, isUnauthorized } from '~/utils/api';
import { sanctionErrorKey, type SanctionDetail } from '~/utils/sanctions';
import type { PlatformSanctionCase } from './usePlatformSanctions';

export function usePlatformSanctionInbox() {
  const api = usePlatformSanctions(); const auth = useAuthStore(); const { organizationId } = useApi();
  const rows = ref<PlatformSanctionCase[]>([]); const selected = ref<SanctionDetail | null>(null);
  const offset = ref(0); const total = ref(0); const loading = ref(false); const error = ref('');
  let generation = 0; let selection = 0;
  function clear() { generation++; selection++; rows.value = []; selected.value = null; total.value = 0; error.value = ''; loading.value = false; }
  async function failure(cause: unknown) {
    error.value = sanctionErrorKey(cause);
    if (isUnauthorized(cause)) { await auth.logout(); await navigateTo({ path: '/login', query: { redirect: '/admin/sanction-cases' } }); }
    else if (isForbidden(cause)) await navigateTo({ path: '/forbidden', query: { resource: 'admin', returnTo: '/admin/sanction-cases' } });
  }
  async function load() {
    clear(); if (!auth.userId) return;
    const token = generation; loading.value = true;
    try { const result = await api.list({ limit: 25, offset: offset.value }); if (token === generation) { rows.value = result.items; total.value = result.total; } }
    catch (cause) { if (token === generation) await failure(cause); }
    finally { if (token === generation) loading.value = false; }
  }
  async function select(id: string) {
    const token = ++selection; selected.value = null; error.value = '';
    try { const result = await api.detail(id); if (token === selection) selected.value = result; }
    catch (cause) { if (token === selection) await failure(cause); }
  }
  async function page(delta: number) { offset.value = Math.max(0, offset.value + delta * 25); await load(); }
  watch(() => [auth.userId, organizationId.value], () => { offset.value = 0; void load(); }, { flush: 'sync' });
  onMounted(load); onBeforeUnmount(clear);
  return { rows, selected, offset, total, loading, error, load, select, page };
}
