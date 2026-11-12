<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import FormField from '~/components/ui/FormField.vue';
import Surface from '~/components/ui/Surface.vue';
import { rectificationErrorKey, type CompetitiveImpact } from '~/utils/rectifications';

const props = defineProps<{ tournamentId?: string; status?: string; canApprove: boolean }>();
const api = useCompetitiveImpacts();
const { t, formatDateTime } = useI18n();
const { confirm } = useConfirm({ singleFlight: true });
const items = ref<CompetitiveImpact[]>([]); const total = ref(0); const offset = ref(0);
const busy = ref(false); const loading = ref(false); const error = ref('');
const reasons = reactive<Record<string, string>>({});
let generation = 0;
async function load() {
  const token = ++generation;
  loading.value = true; error.value = ''; items.value = [];
  try {
    const result = await api.list({ tournament_id: props.tournamentId, status: props.status || 'open', limit: 25, offset: offset.value });
    if (token !== generation) return;
    if (offset.value && offset.value >= result.total) { offset.value = Math.floor(Math.max(0, result.total - 1) / 25) * 25; return await load(); }
    items.value = result.items; total.value = result.total;
  } catch (cause) { if (token === generation) error.value = t(rectificationErrorKey(cause)); }
  finally { if (token === generation) loading.value = false; }
}
async function close(procedure: CompetitiveImpact) {
  if (busy.value || !props.canApprove || !reasons[procedure.id]?.trim()) return;
  busy.value = true; error.value = '';
  try {
    if (!await confirm({ title: t('rectification.keepAsPlayed'), message: t('rectification.keepWarning'), confirmLabel: t('rectification.keepAsPlayed') })) return;
    await api.close(procedure.id, reasons[procedure.id]!.trim());
    delete reasons[procedure.id]; await load();
  } catch (cause) { error.value = t(rectificationErrorKey(cause)); }
  finally { busy.value = false; }
}
function page(delta: number) { offset.value = Math.max(0, offset.value + delta * 25); void load(); }
onMounted(load);
watch(() => [props.tournamentId, props.status], () => { offset.value = 0; void load(); });
onBeforeUnmount(() => { generation++; });
defineExpose({ reload: load });
</script>

<template>
  <Surface as="section">
    <h2>{{ t('rectification.impacts') }}</h2>
    <p v-if="loading" role="status">{{ t('common.loading') }}</p>
    <p v-else-if="error" role="alert">{{ error }} <Button variant="secondary" @click="load">{{ t('common.retry') }}</Button></p>
    <p v-else-if="!items.length" role="status">{{ t('rectification.noImpacts') }}</p>
    <article v-for="item in items" :key="item.id" class="impact">
      <h3>{{ t(`rectification.status.${item.status}`) }} · {{ formatDateTime(item.created_at) }}</h3>
      <p>{{ t('rectification.impactWarning') }}</p>
      <Button as="NuxtLink" :to="`/workspace/matches/${item.match_id}`" variant="secondary">{{ t('rectification.sourceMatch') }}</Button>
      <details><summary>{{ t('rectification.affected') }}</summary><ul><li v-for="(affected, index) in item.affected_items" :key="index"><Button v-if="typeof affected.match_id === 'string'" as="NuxtLink" :to="`/workspace/matches/${affected.match_id}`" variant="ghost">{{ t('rectification.match') }} {{ affected.match_id }}</Button><pre>{{ JSON.stringify(affected, null, 2) }}</pre></li></ul></details>
      <p v-if="item.status === 'closed'">{{ t('rectification.keepAsPlayed') }} · {{ item.reason }}</p>
      <form v-if="canApprove && item.status === 'open'" @submit.prevent="close(item)">
        <FormField :for-id="`impact-${item.id}-reason`" :label="t('rectification.decisionReason')"><textarea :id="`impact-${item.id}-reason`" v-model="reasons[item.id]" required /></FormField>
        <Button type="submit" :busy="busy" :disabled="!reasons[item.id]?.trim()">{{ t('rectification.keepAsPlayed') }}</Button>
      </form>
    </article>
    <nav v-if="total > 25" :aria-label="t('rectification.pagination')"><Button variant="secondary" :disabled="!offset || loading" @click="page(-1)">{{ t('rectification.previous') }}</Button><span>{{ offset + 1 }}–{{ Math.min(offset + 25, total) }} / {{ total }}</span><Button variant="secondary" :disabled="offset + 25 >= total || loading" @click="page(1)">{{ t('rectification.next') }}</Button></nav>
  </Surface>
</template>

<style scoped>
.impact { border-top: 1px solid var(--color-muted); padding-block: var(--space-4); } pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: var(--text-sm); }
nav { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-3); }
</style>
