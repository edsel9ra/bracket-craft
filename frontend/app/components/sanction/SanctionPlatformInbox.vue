<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import SanctionDetail from './SanctionDetail.vue';
import SanctionDecisionForm from './SanctionDecisionForm.vue';
import SanctionPagination from './SanctionPagination.vue';
const { t, formatDateTime } = useI18n(); const auth = useAuthStore();
const { rows, selected, offset, total, loading, error, load, select, page } = usePlatformSanctionInbox();
const notice = ref(''); const panel = ref<HTMLElement | null>(null);
async function review(id: string) { await select(id); await nextTick(); panel.value?.focus(); }
async function changed(message = 'sanction.stateUpdated') { notice.value = message; await load(); }
</script>

<template>
  <Surface as="section">
    <h2>{{ t('sanction.inbox') }}</h2>
    <Button variant="secondary" :busy="loading" @click="load">{{ t('common.refresh') }}</Button>
    <p v-if="loading" role="status">{{ t('common.loading') }}</p>
    <p v-if="notice" role="status">{{ t(notice) }}</p>
    <p v-if="error" role="alert">{{ t(error) }} <Button variant="secondary" @click="load">{{ t('common.retry') }}</Button></p>
    <p v-else-if="!loading && !rows.length" role="status">{{ t('sanction.noCases') }}</p>
    <ul><li v-for="row in rows" :key="row.id"><p>{{ t(`sanction.type.${row.case_type}`) }} · {{ t(`sanction.status.${row.status}`) }} · {{ formatDateTime(row.submitted_at) }}</p><Button variant="secondary" @click="review(row.id)">{{ t('sanction.review') }} <span class="sr-only">{{ row.id }}</span></Button></li></ul>
    <SanctionPagination :offset="offset" :total="total" :busy="loading" @page="page" />
  </Surface>
  <section v-if="selected" ref="panel" tabindex="-1" :aria-label="t('sanction.review')">
    <SanctionDetail :detail="selected"><SanctionDecisionForm :key="selected.case.id" platform :case="selected.case" :user-id="auth.userId" :can-resolve="true" @changed="changed" /></SanctionDetail>
  </section>
</template>

<style scoped>
li { padding-block: var(--space-4); overflow-wrap: anywhere; }
</style>
