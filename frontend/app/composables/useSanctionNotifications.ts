import { sanctionErrorKey, type SanctionNotice } from '~/utils/sanctions';

export function useSanctionNotifications() {
  const auth = useAuthStore(); const { organizationId } = useApi(); const api = useSanctionCases();
  const rows = ref<SanctionNotice[]>([]); const offset = ref(0); const loading = ref(false); const error = ref('');
  const limit = 25; let generation = 0;
  function clear() { generation++; rows.value = []; loading.value = false; error.value = ''; }
  async function load() {
    clear();
    if (!auth.userId || !organizationId.value || organizationId.value !== auth.access?.organization_id) return;
    const token = generation; loading.value = true;
    try { const value = await api.notifications({ limit, offset: offset.value }); if (token === generation) rows.value = value.items; }
    catch (cause) { if (token === generation) error.value = sanctionErrorKey(cause); }
    finally { if (token === generation) loading.value = false; }
  }
  function page(value: number) { offset.value = Math.max(0, value); void load(); }
  watch(() => [organizationId.value, auth.userId, auth.access?.organization_id, auth.access?.permissions.join(','), auth.access?.role_code], () => { offset.value = 0; void load(); }, { flush: 'sync' });
  onMounted(load); onBeforeUnmount(clear);
  return { rows, offset, loading, error, canNext: computed(() => rows.value.length === limit), load, page };
}
