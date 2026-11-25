<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import { NOTIFICATION_CHANNELS, NOTIFICATION_TYPES, notificationTypeKey, type NotificationChannel, type NotificationType } from '~/utils/notifications';
const { t } = useI18n();
const { items, loading, saving, saved, error, dirty, save } = useNotificationPreferences();
const pair = (type: NotificationType, channel: NotificationChannel) => items.value.find((item) => item.type === type && item.channel === channel);
function toggle(type: NotificationType, channel: NotificationChannel, event: Event) {
  const preference = pair(type, channel);
  if (preference) { preference.enabled = (event.target as HTMLInputElement).checked; saved.value = false; }
}
</script>

<template>
  <Surface as="section" aria-labelledby="notification-preferences-title" class="notification-preferences">
    <h2 id="notification-preferences-title">{{ t('notification.preferencesTitle') }}</h2>
    <p class="notification-preferences-hint">{{ t('notification.emailHint') }}</p>
    <p v-if="loading" role="status">{{ t('common.loading') }}</p>
    <form v-else-if="items.length" @submit.prevent="save">
      <div class="notification-preferences-scroll">
        <table>
          <caption class="visually-hidden">{{ t('notification.preferences') }}</caption>
          <thead>
            <tr>
              <th scope="col">{{ t('notification.typeColumn') }}</th>
              <th v-for="channel in NOTIFICATION_CHANNELS" :key="channel" scope="col">{{ t(`notification.channel.${channel}`) }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="type in NOTIFICATION_TYPES" :key="type">
              <th scope="row">{{ t(notificationTypeKey(type)) }}</th>
              <td v-for="channel in NOTIFICATION_CHANNELS" :key="channel">
                <input
                  type="checkbox"
                  :checked="pair(type, channel)?.enabled === true"
                  :disabled="saving"
                  :aria-label="t('notification.preferenceLabel', { channel: t(`notification.channel.${channel}`), type: t(notificationTypeKey(type)) })"
                  @change="toggle(type, channel, $event)"
                >
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="notification-preferences-actions">
        <Button type="submit" :disabled="saving || !dirty">{{ t('notification.save') }}</Button>
        <p v-if="saved" role="status">{{ t('notification.saved') }}</p>
      </div>
    </form>
    <p v-if="error" role="alert">{{ t(error) }}</p>
  </Surface>
</template>

<style scoped>
.notification-preferences-hint { margin-top: 0; color: var(--color-muted); }
.notification-preferences-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--color-line); text-align: start; }
td { text-align: center; }
thead th:not(:first-child) { text-align: center; }
input[type='checkbox'] { width: var(--space-5); height: var(--space-5); accent-color: var(--color-accent); }
.notification-preferences-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); margin-top: var(--space-4); }
.notification-preferences-actions p { margin: 0; }
</style>
