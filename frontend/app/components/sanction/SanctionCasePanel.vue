<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import SanctionDetail from './SanctionDetail.vue';
import { sanctionErrorKey, type SanctionDetail as Detail } from '~/utils/sanctions';
const props = defineProps<{ caseId: string }>();
const { t } = useI18n();
const auth = useAuthStore();
const { organizationId } = useApi();
const api = useSanctionCases();
const detail = ref<Detail | null>(null); const error = ref(''); const loading = ref(false);
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
</script>

<template>
  <section tabindex="-1" :aria-label="t('sanction.review')">
    <p v-if="loading" role="status">{{ t('common.loading') }}</p>
    <p v-else-if="error" role="alert">{{ t(error) }} <Button variant="secondary" @click="load">{{ t('common.retry') }}</Button></p>
    <SanctionDetail v-else-if="detail" :detail="detail" />
  </section>
</template>
