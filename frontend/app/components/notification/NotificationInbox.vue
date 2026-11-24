<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import { NOTIFICATION_PAGE_SIZE, notificationLink, notificationSummary, notificationTypeKey, sanctionSummary } from '~/utils/notifications';
const { t, formatDateTime } = useI18n();
const { items, unreadCount, offset, loading, busy, error, actionError, canNext, load, page, markRead, markAllRead } = useNotifications();
</script>

<template>
  <Surface as="section" aria-labelledby="notification-inbox-title" class="notification-inbox">
    <div class="notification-inbox-header">
      <h2 id="notification-inbox-title">{{ t('notification.inbox') }}</h2>
      <p class="notification-unread">{{ t('notification.unreadCount', { count: unreadCount ?? 0 }) }}</p>
      <Button variant="secondary" :disabled="busy || loading || !unreadCount" @click="markAllRead">{{ t('notification.markAllRead') }}</Button>
    </div>
    <p v-if="actionError" role="alert">{{ t(actionError) }}</p>
    <p v-if="loading" role="status">{{ t('common.loading') }}</p>
    <p v-else-if="error" role="alert">{{ t(error) }} <Button variant="secondary" @click="load">{{ t('common.retry') }}</Button></p>
    <template v-else>
      <p v-if="!items.length">{{ t('notification.empty') }}</p>
      <ul v-else class="notification-list">
        <li v-for="notice in items" :key="notice.id" class="notification-item" :class="{ 'notification-item-unread': !notice.read_at }">
          <h3>
            <span v-if="!notice.read_at" class="notification-dot" aria-hidden="true" />
            <span v-if="!notice.read_at" class="visually-hidden">{{ t('notification.unreadBadge') }}</span>
            {{ t(notificationTypeKey(notice.type)) }}
          </h3>
          <p>{{ notice.tournament_name }} · {{ notificationSummary(notice, t) }}</p>
          <p v-if="sanctionSummary(notice, t)">{{ sanctionSummary(notice, t) }}</p>
          <p class="notification-meta"><time :datetime="notice.created_at">{{ formatDateTime(notice.created_at) }}</time></p>
          <div class="notification-actions">
            <NuxtLink :to="notificationLink(notice)">{{ t(notice.match_id ? 'notification.openMatch' : 'notification.openCalendar') }}</NuxtLink>
            <Button v-if="!notice.read_at" variant="secondary" :disabled="busy" @click="markRead(notice.id)">{{ t('notification.markRead') }}</Button>
          </div>
        </li>
      </ul>
    </template>
    <nav class="notification-pagination" :aria-label="t('notification.pagination')">
      <Button variant="secondary" :disabled="loading || offset === 0" @click="page(offset - NOTIFICATION_PAGE_SIZE)">{{ t('notification.previous') }}</Button>
      <Button variant="secondary" :disabled="loading || !canNext" @click="page(offset + NOTIFICATION_PAGE_SIZE)">{{ t('notification.next') }}</Button>
    </nav>
  </Surface>
</template>

<style scoped>
.notification-inbox-header { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); justify-content: space-between; }
.notification-unread { margin: 0; color: var(--color-muted); }
.notification-list { list-style: none; margin: 0; padding: 0; }
.notification-item { overflow-wrap: anywhere; padding-block: var(--space-4); border-bottom: 1px solid var(--color-line); }
.notification-item h3 { display: flex; align-items: center; gap: var(--space-2); margin: 0; }
.notification-item p { margin-block: var(--space-1); }
.notification-item-unread h3 { color: var(--color-ink); }
.notification-dot { width: var(--space-2); height: var(--space-2); border-radius: 50%; background: var(--color-accent); }
.notification-meta { color: var(--color-muted); font-size: var(--text-xs); }
.notification-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); }
.notification-pagination { display: flex; gap: var(--space-3); margin-top: var(--space-4); }
</style>
