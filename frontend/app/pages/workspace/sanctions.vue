<script setup lang="ts">
import PageHeader from '~/components/ui/PageHeader.vue';
import SanctionInbox from '~/components/sanction/SanctionInbox.vue';
import SanctionCasePanel from '~/components/sanction/SanctionCasePanel.vue';
definePageMeta({ middleware: 'auth' });
const { t } = useI18n();
useHead({ title: computed(() => t('sanction.inbox')) });
const { organizationId } = useApi();
const selected = ref('');
watch(organizationId, () => { selected.value = ''; }, { flush: 'sync' });
</script>

<template>
  <WorkspaceShell :breadcrumbs="[{ label: t('shell.tournaments'), to: '/workspace' }, { label: t('sanction.inbox') }]">
    <main id="main-content" class="container sanctions"><PageHeader :title="t('sanction.inbox')" :description="t('sanction.separation')" /><SanctionInbox @select="selected = $event" /><SanctionCasePanel v-if="selected" :case-id="selected" /></main>
  </WorkspaceShell>
</template>

<style scoped>
.sanctions { display: grid; gap: var(--space-6); padding-block: var(--space-6); }
</style>
