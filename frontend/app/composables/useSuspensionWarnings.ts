import type { MaybeRefOrGetter } from 'vue';
import { sanctionErrorKey, type SuspensionWarning } from '~/utils/sanctions';

export function useSuspensionWarnings(matchId: MaybeRefOrGetter<string>, enabled: MaybeRefOrGetter<boolean>, refreshKey: MaybeRefOrGetter<string>) {
  const { organizationId } = useApi(); const auth = useAuthStore(); const api = useSanctionCases();
  const rows = ref<SuspensionWarning[]>([]); const error = ref(''); const loading = ref(false); let generation = 0;
  function clear() { generation++; rows.value = []; loading.value = false; error.value = ''; }
  async function load() {
    clear();
    if (!toValue(enabled) || !toValue(matchId) || !auth.userId || organizationId.value !== auth.access?.organization_id) return;
    const token = generation; loading.value = true;
    try { const value = await api.warnings(toValue(matchId)); if (token === generation) rows.value = value; }
    catch (cause) { if (token === generation) error.value = sanctionErrorKey(cause); }
    finally { if (token === generation) loading.value = false; }
  }
  watch(() => [toValue(matchId), toValue(enabled), toValue(refreshKey), organizationId.value, auth.userId, auth.access?.organization_id, auth.access?.permissions.join(','), auth.access?.role_code], load, { flush: 'sync' });
  onMounted(load); onBeforeUnmount(clear);
  return { rows, error, loading, load };
}
