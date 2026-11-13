<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
defineProps<{ canView: boolean }>();
const { t, formatDateTime } = useI18n();
const { rows, offset, loading, error, canNext, load, page } = useSanctionNotifications();
</script>

<template>
  <Surface as="section"><h2>{{ t('sanction.notifications') }}</h2>
    <p v-if="loading" role="status">{{ t('common.loading') }}</p>
    <p v-else-if="error" role="alert">{{ t(error) }} <Button variant="secondary" @click="load">{{ t('common.retry') }}</Button></p>
    <template v-else><p v-if="!rows.length">{{ t('sanction.noNotifications') }}</p>
      <ul><li v-for="notice in rows" :key="notice.id"><h3>{{ t(`sanction.notice.${notice.notification_type}`) }}</h3><p>{{ notice.reason }}</p><p v-if="notice.decision">{{ t(`sanction.decision.${notice.decision}`) }}</p><p>{{ formatDateTime(notice.created_at) }}</p><NuxtLink v-if="canView" :to="`/workspace/sanctions?case=${notice.case_id}`">{{ t('sanction.review') }}</NuxtLink><p v-else>{{ t('sanction.noticeNoAccess') }}</p></li></ul>
    </template>
    <nav :aria-label="t('sanction.pagination')"><Button variant="secondary" :disabled="loading || offset === 0" @click="page(offset - 25)">{{ t('sanction.previous') }}</Button><Button variant="secondary" :disabled="loading || !canNext" @click="page(offset + 25)">{{ t('sanction.next') }}</Button></nav>
  </Surface>
</template>

<style scoped>
li { overflow-wrap: anywhere; margin-block: var(--space-4); }
nav { display: flex; gap: var(--space-3); }
</style>
