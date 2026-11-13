import { sanctionAccess, sanctionErrorKey, type CaseStatus, type CaseType, type SanctionCase, type SanctionRow, type SanctionFilters } from '~/utils/sanctions';

export function useSanctionInbox() {
  const api = useSanctionCases();
  const auth = useAuthStore();
  const { organizationId } = useApi();
  const access = computed(() => sanctionAccess(auth.access?.permissions || [], auth.access?.role_code));
  const canRead = computed(() => access.value.view && organizationId.value === auth.access?.organization_id);
  const status = ref<CaseStatus | ''>('pending');
  const caseType = ref<CaseType | ''>('');
  const sanctionStatus = ref<NonNullable<SanctionFilters['status']> | ''>('active');
  const offset = ref(0); const sanctionOffset = ref(0);
  const rows = ref<SanctionCase[]>([]); const sanctions = ref<SanctionRow[]>([]);
  const total = ref(0); const sanctionTotal = ref(0);
  const loading = ref(false); const error = ref('');
  let generation = 0;
  function clear() {
    generation++; rows.value = []; sanctions.value = []; total.value = 0; sanctionTotal.value = 0; error.value = ''; loading.value = false;
  }
  async function load() {
    clear();
    if (!canRead.value) return;
    const token = generation;
    loading.value = true;
    try {
      const [cases, sources] = await Promise.all([
        api.list({ status: status.value || undefined, case_type: caseType.value || undefined, limit: 25, offset: offset.value }),
        api.sanctions({ status: sanctionStatus.value || undefined, limit: 25, offset: sanctionOffset.value }),
      ]);
      if (token !== generation) return;
      rows.value = cases.items; total.value = cases.total; sanctions.value = sources.items; sanctionTotal.value = sources.total;
    } catch (cause) { if (token === generation) error.value = sanctionErrorKey(cause); }
    finally { if (token === generation) loading.value = false; }
  }
  async function page(kind: 'cases' | 'sanctions', delta: number) {
    const position = kind === 'cases' ? offset : sanctionOffset;
    position.value = Math.max(0, position.value + delta * 25);
    await load();
  }
  watch([status, caseType, sanctionStatus], () => { offset.value = 0; sanctionOffset.value = 0; void load(); });
  watch(() => [organizationId.value, auth.userId, auth.access?.organization_id, auth.access?.permissions.join(',')], () => {
    offset.value = 0; sanctionOffset.value = 0; void load();
  }, { flush: 'sync' });
  onMounted(load);
  onBeforeUnmount(clear);
  return { access, canRead, status, caseType, sanctionStatus, rows, sanctions, total, sanctionTotal, offset, sanctionOffset, loading, error, load, clear, page };
}
