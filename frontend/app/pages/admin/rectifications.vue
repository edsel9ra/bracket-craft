<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import PageHeader from '~/components/ui/PageHeader.vue';
import Surface from '~/components/ui/Surface.vue';
import RectificationReview from '~/components/match/RectificationReview.vue';
import { isForbidden, isUnauthorized } from '~/utils/api';
import { rectificationErrorKey, type Rectification, type RectificationDetail, type ReportVersion } from '~/utils/rectifications';

definePageMeta({ middleware: 'platform' });
const auth = useAuthStore();
const api = usePlatformRectifications();
const { t, formatDateTime } = useI18n();
useHead(() => ({ title: t('rectification.platformTitle'), meta: [{ name: 'robots', content: 'noindex, nofollow' }] }));
const rows = ref<Rectification[]>([]);
const selected = ref<(RectificationDetail & { current_version: ReportVersion }) | null>(null);
const loading = ref(false); const error = ref('');
let generation = 0; let detailGeneration = 0;
async function failure(cause: unknown) {
  if (isUnauthorized(cause)) { await auth.logout(); await navigateTo({ path: '/login', query: { redirect: '/admin/rectifications' } }); return; }
  if (isForbidden(cause)) { await navigateTo({ path: '/forbidden', query: { returnTo: '/admin/rectifications', resource: 'admin' } }); return; }
  error.value = t(rectificationErrorKey(cause));
}
async function load() {
  const token = ++generation;
  detailGeneration++; selected.value = null; rows.value = []; loading.value = true; error.value = '';
  try { const result = await api.list(); if (token === generation) rows.value = result; }
  catch (cause) { if (token === generation) await failure(cause); }
  finally { if (token === generation) loading.value = false; }
}
async function select(id: string) {
  const token = ++detailGeneration;
  selected.value = null; error.value = '';
  try { const result = await api.detail(id); if (token === detailGeneration) selected.value = result; }
  catch (cause) { if (token === detailGeneration) await failure(cause); }
}
onMounted(load);
onBeforeUnmount(() => { generation++; detailGeneration++; });
</script>

<template>
  <WorkspaceShell :breadcrumbs="[{ label: t('admin.title'), to: '/admin' }, { label: t('rectification.inbox') }]">
    <main id="main-content" class="container platform-rectifications">
      <PageHeader :title="t('rectification.platformTitle')" :description="t('rectification.platformHint')" />
      <Surface as="section">
        <Button variant="secondary" :busy="loading" @click="load">{{ t('common.refresh') }}</Button>
        <p v-if="loading" role="status">{{ t('common.loading') }}</p>
        <p v-else-if="error" role="alert">{{ error }} <Button variant="secondary" @click="load">{{ t('common.retry') }}</Button></p>
        <p v-else-if="!rows.length" role="status">{{ t('rectification.noRequests') }}</p>
        <ul><li v-for="row in rows" :key="row.id"><h2>{{ row.reason }}</h2><p>{{ formatDateTime(row.requested_at) }} · {{ t(`rectification.status.${row.status}`) }}</p><Button variant="secondary" @click="select(row.id)">{{ t('rectification.review') }}</Button></li></ul>
      </Surface>
      <RectificationReview v-if="selected" :key="selected.id" platform :detail="selected" :member-id="auth.userId" :can-approve="true" :owner="false" @changed="load" />
    </main>
  </WorkspaceShell>
</template>

<style scoped>
.platform-rectifications { display: grid; gap: var(--space-6); padding-block: var(--space-6); }
li { padding-block: var(--space-4); overflow-wrap: anywhere; }
</style>
