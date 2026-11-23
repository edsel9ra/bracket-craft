import type { Ref } from 'vue';
import { auditErrorKey, auditQuery, type AuditActorOption, type AuditEntry, type AuditFilters, type AuditPage } from '~/utils/organizationAudit';

export function useOrganizationAudit(filters: Readonly<Ref<AuditFilters>>) {
  const { request, organizationId } = useApi();
  const auth = useAuthStore();
  const canRead = computed(() => auth.hasPermission('VIEW_ORGANIZATION_AUDIT') && organizationId.value === auth.access?.organization_id);
  const items = ref<AuditEntry[]>([]);
  const total = ref(0);
  const actors = ref<AuditActorOption[]>([]);
  const loading = ref(false);
  const error = ref('');
  let generation = 0;
  let actorGeneration = 0;

  function clear() {
    generation++; actorGeneration++;
    items.value = []; total.value = 0; actors.value = []; error.value = ''; loading.value = false;
  }

  async function load() {
    const token = ++generation;
    items.value = []; total.value = 0; error.value = ''; loading.value = false;
    if (!canRead.value) return;
    loading.value = true;
    try {
      const page = await request<AuditPage>(`/organization-audit${auditQuery(filters.value)}`);
      if (token !== generation) return;
      items.value = page.items; total.value = page.total;
    } catch (cause) { if (token === generation) error.value = auditErrorKey(cause); }
    finally { if (token === generation) loading.value = false; }
  }

  async function loadActors() {
    const token = ++actorGeneration;
    actors.value = [];
    if (!canRead.value) return;
    try {
      const result = await request<AuditActorOption[]>('/organization-audit/actors');
      if (token === actorGeneration) actors.value = result;
    } catch { /* El filtro de responsable queda vacío; la lista informa del error. */ }
  }

  watch(() => [organizationId.value, auth.userId, auth.access?.organization_id, auth.access?.permissions.join(',')], () => {
    clear(); void load(); void loadActors();
  }, { flush: 'sync' });
  watch(filters, () => { void load(); }, { deep: true });
  onMounted(() => { void load(); void loadActors(); });
  onBeforeUnmount(clear);
  return { canRead, items, total, actors, loading, error, load, loadActors, clear };
}
