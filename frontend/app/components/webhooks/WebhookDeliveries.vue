<script setup lang="ts">
import { deliveryStatusKey, webhookTypeKey, type WebhookDelivery, type WebhookDeliveryStatus } from '~/utils/webhooks';

defineProps<{ deliveries: WebhookDelivery[]; loading: boolean; error: string }>();
const { t, formatDateTime, formatNumber } = useI18n();
const tone = (status: WebhookDeliveryStatus) => (status === 'delivered' ? 'success' : status === 'pending' ? 'neutral' : 'danger');
</script>

<template>
  <div class="webhook-deliveries">
    <p v-if="loading" role="status">{{ t('common.loading') }}</p>
    <p v-else-if="error" role="alert" class="webhook-deliveries-error">{{ t(error) }}</p>
    <div v-else class="webhook-deliveries-scroll">
      <table>
        <caption>{{ t('webhook.deliveries.title') }}</caption>
        <thead>
          <tr>
            <th scope="col">{{ t('webhook.deliveries.type') }}</th>
            <th scope="col">{{ t('webhook.deliveries.date') }}</th>
            <th scope="col">{{ t('webhook.deliveries.attempts') }}</th>
            <th scope="col">{{ t('webhook.deliveries.code') }}</th>
            <th scope="col">{{ t('webhook.deliveries.status') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!deliveries.length"><td colspan="5">{{ t('webhook.deliveries.empty') }}</td></tr>
          <tr v-for="delivery in deliveries" :key="delivery.id">
            <td>{{ t(webhookTypeKey(delivery.event_type)) }}</td>
            <td>{{ formatDateTime(delivery.created_at) }}</td>
            <td>{{ formatNumber(delivery.attempts) }}</td>
            <td>{{ delivery.last_status_code ?? '—' }}</td>
            <td><span class="webhook-delivery-status" :class="`webhook-delivery-${tone(delivery.status)}`">{{ t(deliveryStatusKey(delivery.status)) }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.webhook-deliveries p { margin: 0; }
.webhook-deliveries-error { color: var(--color-danger); }
.webhook-deliveries-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
caption { margin-bottom: var(--space-2); text-align: start; font-weight: var(--weight-lg); }
th, td { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--color-line); text-align: start; white-space: nowrap; }
th { color: var(--color-muted); font-size: var(--text-sm); line-height: var(--leading-sm); }
.webhook-delivery-status { font-weight: var(--weight-lg); }
.webhook-delivery-success { color: var(--color-success); }
.webhook-delivery-danger { color: var(--color-danger); }
</style>
