<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import PageHeader from '~/components/ui/PageHeader.vue';
import Surface from '~/components/ui/Surface.vue';
import RectificationReview from '~/components/match/RectificationReview.vue';
import CompetitiveImpacts from '~/components/match/CompetitiveImpacts.vue';
import { rectificationErrorKey, type Rectification, type RectificationDetail } from '~/utils/rectifications';

definePageMeta({ middleware: 'auth' });
const { t, formatDateTime } = useI18n();
useHead({ title: computed(() => t('rectification.inbox')) });
const auth = useAuthStore();
const tournaments = useTournamentsStore();
const api = useMatchRectifications();
const status = ref('pending'); const impactStatus = ref('open'); const tournament = ref('');
const rows = ref<Rectification[]>([]); const total = ref(0); const offset = ref(0);
const selected = ref<RectificationDetail | null>(null); const loading = ref(false); const error = ref('');
const impacts = ref<InstanceType<typeof CompetitiveImpacts> | null>(null);
const canApprove = computed(() => auth.hasPermission('APPROVE_MATCH_REPORT_RECTIFICATION'));
const owner = computed(() => auth.access?.role_code === 'owner');
let generation = 0; let detailGeneration = 0;
async function load() {
  const token = ++generation;
  detailGeneration++; selected.value = null; rows.value = []; loading.value = true; error.value = '';
  try {
    const result = await api.list({ status: status.value, tournament_id: tournament.value, limit: 25, offset: offset.value });
    if (token !== generation) return;
    if (offset.value && offset.value >= result.total) { offset.value = Math.floor(Math.max(0, result.total - 1) / 25) * 25; return await load(); }
    rows.value = result.items; total.value = result.total;
  } catch (cause) { if (token === generation) error.value = t(rectificationErrorKey(cause)); }
  finally { if (token === generation) loading.value = false; }
}
async function select(id: string) {
  const token = ++detailGeneration;
  error.value = ''; selected.value = null;
  try { const detail = await api.detail(id); if (token === detailGeneration) selected.value = detail; }
  catch (cause) { if (token === detailGeneration) error.value = t(rectificationErrorKey(cause)); }
}
async function changed() { await load(); await impacts.value?.reload(); }
function page(delta: number) { offset.value = Math.max(0, offset.value + delta * 25); void load(); }
watch([status, tournament], () => { offset.value = 0; void load(); });
watch(() => auth.access?.organization_id, () => { offset.value = 0; void load(); void impacts.value?.reload(); });
onMounted(async () => { await load(); try { await tournaments.load(); } catch { /* El filtro sigue permitiendo todos los torneos. */ } });
onBeforeUnmount(() => { generation++; detailGeneration++; });
</script>

<template>
  <WorkspaceShell :breadcrumbs="[{ label: t('shell.tournaments'), to: '/workspace' }, { label: t('rectification.inbox') }]">
    <main id="main-content" class="rectification-inbox container">
      <PageHeader :title="t('rectification.inbox')" :description="t('rectification.immutable')" />
      <Surface as="section">
        <div class="filters"><label class="field">{{ t('rectification.tournament') }}<select v-model="tournament"><option value="">{{ t('rectification.allTournaments') }}</option><option v-for="entry in tournaments.tournaments" :key="entry.id" :value="entry.id">{{ entry.name }}</option></select></label><label class="field">{{ t('rectification.status') }}<select v-model="status"><option value="">{{ t('rectification.allStatuses') }}</option><option v-for="state in ['pending', 'published', 'rejected', 'withdrawn']" :key="state" :value="state">{{ t(`rectification.status.${state}`) }}</option></select></label></div>
        <Button variant="secondary" :busy="loading" @click="load">{{ t('common.refresh') }}</Button>
        <p v-if="loading" role="status">{{ t('common.loading') }}</p><p v-else-if="error" role="alert">{{ error }} <Button variant="secondary" @click="load">{{ t('common.retry') }}</Button></p><p v-else-if="!rows.length" role="status">{{ t('rectification.noRequests') }}</p>
        <ul class="requests"><li v-for="row in rows" :key="row.id"><h2>{{ row.reason }}</h2><p>{{ t(`rectification.status.${row.status}`) }} · {{ formatDateTime(row.requested_at) }}</p><Button variant="secondary" @click="select(row.id)">{{ t('rectification.review') }}</Button> <Button as="NuxtLink" :to="`/workspace/matches/${row.match_id}`" variant="ghost">{{ t('rectification.sourceMatch') }}</Button></li></ul>
        <nav v-if="total > 25" :aria-label="t('rectification.pagination')"><Button variant="secondary" :disabled="!offset || loading" @click="page(-1)">{{ t('rectification.previous') }}</Button><span>{{ offset + 1 }}–{{ Math.min(offset + 25, total) }} / {{ total }}</span><Button variant="secondary" :disabled="offset + 25 >= total || loading" @click="page(1)">{{ t('rectification.next') }}</Button></nav>
      </Surface>
      <RectificationReview v-if="selected" :key="selected.id" :detail="selected" :member-id="auth.access?.organization_user_id || null" :can-approve="canApprove" :owner="owner" @changed="changed" />
      <label class="field">{{ t('rectification.impactStatus') }}<select v-model="impactStatus"><option value="open">{{ t('rectification.status.open') }}</option><option value="closed">{{ t('rectification.status.closed') }}</option></select></label>
      <CompetitiveImpacts ref="impacts" :tournament-id="tournament" :status="impactStatus" :can-approve="canApprove" />
    </main>
  </WorkspaceShell>
</template>

<style scoped>
.rectification-inbox { display: grid; gap: var(--space-6); padding-block: var(--space-6); }
.filters, nav { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-4); }
.requests { list-style: none; padding: 0; } .requests li { border-top: 1px solid var(--color-muted); padding-block: var(--space-4); }
</style>
