<script setup lang="ts">
import PageHeader from '~/components/ui/PageHeader.vue';
import SanctionNotifications from '~/components/sanction/SanctionNotifications.vue';
definePageMeta({ middleware: 'auth' });
const { t } = useI18n(); const auth = useAuthStore();
useHead({ title: computed(() => t('sanction.notifications')) });
</script>

<template>
  <WorkspaceShell><main id="main-content" class="container"><PageHeader :title="t('sanction.notifications')" :description="t('sanction.notificationsHint')" /><SanctionNotifications :can-view="auth.hasPermission('VIEW_SANCTION_CASES')" /></main></WorkspaceShell>
</template>
