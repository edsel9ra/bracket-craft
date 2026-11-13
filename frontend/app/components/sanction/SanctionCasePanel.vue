<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import SanctionDetail from './SanctionDetail.vue';
import SanctionDecisionForm from './SanctionDecisionForm.vue';
import SanctionWithdrawalForm from './SanctionWithdrawalForm.vue';
import SanctionAuthorizations from './SanctionAuthorizations.vue';
import { sanctionErrorKey, type SanctionDetail as Detail } from '~/utils/sanctions';
const props = defineProps<{ caseId: string }>();
const emit = defineEmits<{ changed: []; newPresentation: [priorCaseId: string] }>();
const { t } = useI18n();
const auth = useAuthStore();
const { organizationId } = useApi();
const api = useSanctionCases();
const detail = ref<Detail | null>(null); const error = ref(''); const loading = ref(false);
const notice = ref('');
const canPresent = computed(() => auth.hasPermission('SUBMIT_SANCTION_APPEALS') || auth.hasPermission('RESOLVE_SANCTION_CASES'));
let generation = 0;
async function load() {
  const token = ++generation;
  detail.value = null; error.value = ''; loading.value = false;
  if (!auth.hasPermission('VIEW_SANCTION_CASES') || organizationId.value !== auth.access?.organization_id) return;
  loading.value = true;
  try { const value = await api.detail(props.caseId); if (token === generation) detail.value = value; }
  catch (cause) { if (token === generation) error.value = sanctionErrorKey(cause); }
  finally { if (token === generation) loading.value = false; }
}
watch(() => [props.caseId, organizationId.value, auth.userId, auth.access?.organization_id, auth.access?.permissions.join(',')], load, { flush: 'sync' });
onMounted(load);
onBeforeUnmount(() => { generation++; });
defineExpose({ reload: load });
async function changed(message = 'sanction.stateUpdated') { notice.value = message; await load(); emit('changed'); }
</script>

<template>
  <section tabindex="-1" :aria-label="t('sanction.review')">
    <p v-if="notice" role="status">{{ t(notice) }}</p>
    <p v-if="loading" role="status">{{ t('common.loading') }}</p>
    <p v-else-if="error" role="alert">{{ t(error) }} <Button variant="secondary" @click="load">{{ t('common.retry') }}</Button></p>
    <SanctionDetail v-else-if="detail" :detail="detail">
      <SanctionDecisionForm :case="detail.case" :user-id="auth.userId" :can-resolve="auth.hasPermission('RESOLVE_SANCTION_CASES')" @changed="changed" />
      <SanctionWithdrawalForm :case="detail.case" :user-id="auth.userId" :submit-permission="auth.hasPermission('SUBMIT_SANCTION_APPEALS')" :resolve-permission="auth.hasPermission('RESOLVE_SANCTION_CASES')" @changed="changed" />
      <SanctionAuthorizations v-if="auth.access?.role_code === 'owner'" :key="detail.case.id" :owner="true" :case-id="detail.case.id" :pending="detail.case.status === 'pending'" />
      <Button v-if="canPresent && (detail.case.status === 'closed_by_rectification' || detail.events.some((event) => event.event_type === 'affected_by_rectification'))" variant="secondary" @click="$emit('newPresentation', detail.case.id)">{{ t('sanction.newPresentation') }}</Button>
    </SanctionDetail>
  </section>
</template>
