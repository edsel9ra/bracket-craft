<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import AuditEntryDialog from '~/components/workspace/audit/AuditEntryDialog.vue';
import AuditEntryTable from '~/components/workspace/audit/AuditEntryTable.vue';
import AuditFilters from '~/components/workspace/audit/AuditFilters.vue';
import Button from '~/components/ui/Button.vue';
import PageHeader from '~/components/ui/PageHeader.vue';
import StateMessage from '~/components/ui/StateMessage.vue';
import Surface from '~/components/ui/Surface.vue';
import {
  AUDIT_PAGE_SIZE, filtersFromQuery, filtersToQuery, type AuditEntry, type AuditFilters as Filters, type AuditRouteQuery,
} from '~/utils/organizationAudit';

definePageMeta({ middleware: 'auth' });
const { t } = useI18n();
useHead({ title: computed(() => t('audit.title')) });
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const filters = computed(() => filtersFromQuery(route.query as AuditRouteQuery));
const { canRead, items, total, actors, loading, error, load } = useOrganizationAudit(filters);
const permissions = computed(() => auth.access?.permissions ?? []);
const selected = ref<AuditEntry | null>(null);
const firstShown = computed(() => (filters.value.page - 1) * AUDIT_PAGE_SIZE + 1);
const lastShown = computed(() => Math.min(filters.value.page * AUDIT_PAGE_SIZE, total.value));

function navigate(next: Filters) { void router.push({ query: filtersToQuery(next) }); }
function goTo(page: number) { navigate({ ...filters.value, page }); }

watch([items, total, loading, error], () => {
  if (!loading.value && !error.value && !items.value.length && total.value > 0 && filters.value.page > 1) {
    goTo(Math.ceil(total.value / AUDIT_PAGE_SIZE));
  }
});
watch(canRead, (allowed) => { if (!allowed) selected.value = null; });
</script>

<template>
  <WorkspaceShell :breadcrumbs="[{ label: t('audit.nav') }]">
    <main id="main-content" class="audit-page container">
      <PageHeader :title="t('audit.title')" />
      <p class="audit-description">{{ t('audit.description') }}</p>
      <StateMessage v-if="!canRead" kind="error">{{ t('audit.error.forbidden') }}</StateMessage>
      <template v-else>
        <Surface as="section" class="audit-section">
          <AuditFilters :filters="filters" :actors="actors" :busy="loading" @apply="navigate" @clear="navigate(filtersFromQuery({}))" />
        </Surface>
        <Surface as="section" class="audit-section" :aria-busy="loading">
          <StateMessage v-if="loading" kind="loading">{{ t('audit.loading') }}</StateMessage>
          <StateMessage v-else-if="error" kind="error" retry @retry="load">{{ t(error) }}</StateMessage>
          <StateMessage v-else-if="!items.length" kind="empty">{{ t('audit.empty') }}</StateMessage>
          <template v-else>
            <AuditEntryTable :entries="items" :permissions="permissions" @open="selected = $event" />
            <nav v-if="total > AUDIT_PAGE_SIZE" class="audit-pagination" :aria-label="t('audit.pagination')">
              <Button variant="secondary" :disabled="filters.page <= 1 || loading" @click="goTo(filters.page - 1)">{{ t('audit.previous') }}</Button>
              <span>{{ t('audit.range', { from: firstShown, to: lastShown, total }) }}</span>
              <Button variant="secondary" :disabled="lastShown >= total || loading" @click="goTo(filters.page + 1)">{{ t('audit.next') }}</Button>
            </nav>
          </template>
        </Surface>
      </template>
      <AuditEntryDialog :entry="selected" :permissions="permissions" @close="selected = null" />
    </main>
  </WorkspaceShell>
</template>

<style scoped>
.audit-page { display: grid; gap: var(--space-4); }
.audit-description { margin: 0; color: var(--color-muted); }
.audit-section { display: grid; gap: var(--space-4); }
.audit-pagination { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-3); }
</style>
