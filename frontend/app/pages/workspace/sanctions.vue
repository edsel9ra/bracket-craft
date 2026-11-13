<script setup lang="ts">
import PageHeader from '~/components/ui/PageHeader.vue';
import SanctionInbox from '~/components/sanction/SanctionInbox.vue';
import SanctionCasePanel from '~/components/sanction/SanctionCasePanel.vue';
import SanctionAppealForm from '~/components/sanction/SanctionAppealForm.vue';
import SanctionProposalForm from '~/components/sanction/SanctionProposalForm.vue';
definePageMeta({ middleware: 'auth' });
const { t } = useI18n();
useHead({ title: computed(() => t('sanction.inbox')) });
const { organizationId } = useApi();
const auth = useAuthStore();
const canSubmit = computed(() => auth.hasPermission('SUBMIT_SANCTION_APPEALS') && organizationId.value === auth.access?.organization_id);
const canResolve = computed(() => auth.hasPermission('RESOLVE_SANCTION_CASES') && organizationId.value === auth.access?.organization_id);
const inbox = ref<InstanceType<typeof SanctionInbox> | null>(null);
const selected = ref('');
const prior = ref('');
watch(organizationId, () => { selected.value = ''; prior.value = ''; }, { flush: 'sync' });
</script>

<template>
  <WorkspaceShell :breadcrumbs="[{ label: t('shell.tournaments'), to: '/workspace' }, { label: t('sanction.inbox') }]">
    <main id="main-content" class="container sanctions"><PageHeader :title="t('sanction.inbox')" :description="t('sanction.separation')" /><SanctionInbox ref="inbox" @select="selected = $event" /><SanctionCasePanel v-if="selected" :case-id="selected" @changed="inbox?.reload()" @new-presentation="prior = $event" /><SanctionAppealForm v-if="canSubmit" :key="`appeal:${organizationId}:${auth.userId}:${prior}`" :allowed="canSubmit" :prior-case-id="prior" @created="inbox?.reload()" /><SanctionProposalForm v-if="canResolve" :key="`proposal:${organizationId}:${auth.userId}:${prior}`" :allowed="canResolve" :prior-case-id="prior" @created="inbox?.reload()" /></main>
  </WorkspaceShell>
</template>

<style scoped>
.sanctions { display: grid; gap: var(--space-6); padding-block: var(--space-6); }
</style>
