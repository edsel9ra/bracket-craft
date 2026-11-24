<script setup lang="ts">
import PageHeader from '~/components/ui/PageHeader.vue';
import NotificationInbox from '~/components/notification/NotificationInbox.vue';
definePageMeta({ middleware: 'auth' });
const { t } = useI18n();
useHead({ title: computed(() => `${t('notification.title')} | Bracket Craft`) });
</script>

<template>
  <WorkspaceShell>
    <main id="main-content" class="container notification-page">
      <PageHeader :title="t('notification.title')" />
      <p class="notification-hint">{{ t('notification.hint') }}</p>
      <NotificationInbox />
    </main>
  </WorkspaceShell>
</template>

<style scoped>
.notification-page { display: grid; gap: var(--space-4); padding-block: var(--space-6); }
.notification-hint { margin: 0; color: var(--color-muted); }
</style>
