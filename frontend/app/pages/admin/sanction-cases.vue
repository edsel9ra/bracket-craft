<script setup lang="ts">
import PageHeader from '~/components/ui/PageHeader.vue';
import SanctionPlatformInbox from '~/components/sanction/SanctionPlatformInbox.vue';
definePageMeta({ middleware: 'platform' });
const { t } = useI18n(); const auth = useAuthStore();
useHead(() => ({ title: t('sanction.platformTitle'), meta: [{ name: 'robots', content: 'noindex, nofollow' }] }));
</script>

<template>
  <WorkspaceShell :breadcrumbs="[{ label: t('admin.title'), to: '/admin' }, { label: t('sanction.platformTitle') }]">
    <main id="main-content" class="container sanction-platform">
      <PageHeader :title="t('sanction.platformTitle')" :description="t('sanction.authorizationHint')" />
      <SanctionPlatformInbox :key="auth.userId || ''" />
    </main>
  </WorkspaceShell>
</template>

<style scoped>
.sanction-platform { display: grid; gap: var(--space-6); padding-block: var(--space-6); }
</style>
