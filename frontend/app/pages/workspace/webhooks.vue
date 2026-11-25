<script setup lang="ts">
import { computed, ref } from 'vue';
import Button from '~/components/ui/Button.vue';
import PageHeader from '~/components/ui/PageHeader.vue';
import StatusPill from '~/components/ui/StatusPill.vue';
import Surface from '~/components/ui/Surface.vue';
import WebhookDeliveries from '~/components/webhooks/WebhookDeliveries.vue';
import WebhookForm from '~/components/webhooks/WebhookForm.vue';
import WebhookSecretDialog from '~/components/webhooks/WebhookSecretDialog.vue';
import { WEBHOOK_LIMIT, webhookTypeKey, type WebhookInput, type WebhookItem } from '~/utils/webhooks';

definePageMeta({ middleware: 'auth' });
const { t } = useI18n();
useHead({ title: computed(() => `${t('webhook.title')} | Bracket Craft`) });
const {
  canManage, items, loading, busy, error, actionError, notice, secret, limitReached,
  deliveriesFor, deliveries, deliveriesLoading, deliveriesError,
  load, create, update, setActive, remove, rotate, sendTest, showDeliveries, dismissSecret,
} = useWebhooks();
const formKey = ref(0);
const editingId = ref<string | null>(null);
const headingId = (webhook: WebhookItem) => `webhook-${webhook.id}`;

async function onCreate(input: WebhookInput) {
  if (await create(input)) formKey.value += 1;
}

async function onUpdate(webhook: WebhookItem, input: WebhookInput) {
  if (await update(webhook.id, input)) editingId.value = null;
}

function toggleDeliveries(webhook: WebhookItem) {
  if (deliveriesFor.value === webhook.id) deliveriesFor.value = null;
  else void showDeliveries(webhook);
}
</script>

<template>
  <WorkspaceShell>
    <main id="main-content" class="container webhook-page">
      <PageHeader :title="t('webhook.title')" />
      <p class="webhook-intro">{{ t('webhook.hint') }}</p>
      <p v-if="!canManage" role="alert" class="webhook-error">{{ t('webhook.error.forbidden') }}</p>
      <template v-else>
        <p v-if="notice" role="status" class="webhook-notice">{{ t(notice) }}</p>
        <p v-if="actionError" role="alert" class="webhook-error">{{ t(actionError) }}</p>
        <Surface as="section" class="webhook-section" aria-labelledby="webhook-new-title">
          <h2 id="webhook-new-title">{{ t('webhook.form.title') }}</h2>
          <p v-if="limitReached" class="webhook-muted">{{ t('webhook.limitReached', { limit: WEBHOOK_LIMIT }) }}</p>
          <WebhookForm v-else :key="formKey" submit-label="webhook.form.create" :busy="busy" @submit="onCreate" />
        </Surface>
        <section class="webhook-section webhook-list-section" aria-labelledby="webhook-list-title">
          <h2 id="webhook-list-title">{{ t('webhook.list.title') }}</h2>
          <p v-if="loading" role="status">{{ t('common.loading') }}</p>
          <div v-else-if="error" class="webhook-load-error">
            <p role="alert" class="webhook-error">{{ t(error) }}</p>
            <Button variant="secondary" @click="load">{{ t('common.retry') }}</Button>
          </div>
          <p v-else-if="!items.length" class="webhook-muted">{{ t('webhook.empty') }}</p>
          <ul v-else class="webhook-list">
            <li v-for="webhook in items" :key="webhook.id">
              <Surface as="article" class="webhook-item" :aria-labelledby="headingId(webhook)">
                <h3 :id="headingId(webhook)" class="webhook-url"><code>{{ webhook.url }}</code></h3>
                <div class="webhook-meta">
                  <span class="webhook-muted">{{ t('webhook.typesLabel') }}</span>
                  <ul class="webhook-type-list">
                    <li v-for="type in webhook.event_types" :key="type">{{ t(webhookTypeKey(type)) }}</li>
                  </ul>
                  <StatusPill :tone="webhook.is_active ? 'success' : 'neutral'">{{ t(webhook.is_active ? 'webhook.state.active' : 'webhook.state.inactive') }}</StatusPill>
                </div>
                <WebhookForm
                  v-if="editingId === webhook.id" :initial="{ url: webhook.url, event_types: webhook.event_types }"
                  submit-label="webhook.form.save" :busy="busy" cancellable
                  @submit="onUpdate(webhook, $event)" @cancel="editingId = null"
                />
                <div v-else class="webhook-actions">
                  <Button variant="secondary" :disabled="busy" :aria-describedby="headingId(webhook)" @click="editingId = webhook.id">{{ t('webhook.action.edit') }}</Button>
                  <Button variant="secondary" :disabled="busy" :aria-describedby="headingId(webhook)" @click="setActive(webhook, !webhook.is_active)">
                    {{ t(webhook.is_active ? 'webhook.action.disable' : 'webhook.action.enable') }}
                  </Button>
                  <Button variant="secondary" :disabled="busy" :aria-describedby="headingId(webhook)" @click="rotate(webhook)">{{ t('webhook.action.rotate') }}</Button>
                  <Button variant="secondary" :disabled="busy || !webhook.is_active" :aria-describedby="headingId(webhook)" @click="sendTest(webhook)">{{ t('webhook.action.test') }}</Button>
                  <Button
                    variant="ghost" :aria-expanded="deliveriesFor === webhook.id ? 'true' : 'false'" :aria-controls="`${headingId(webhook)}-deliveries`"
                    :aria-describedby="headingId(webhook)" @click="toggleDeliveries(webhook)"
                  >
                    {{ t('webhook.action.deliveries') }}
                  </Button>
                  <Button variant="danger" :disabled="busy" :aria-describedby="headingId(webhook)" @click="remove(webhook)">{{ t('webhook.action.delete') }}</Button>
                </div>
                <div :id="`${headingId(webhook)}-deliveries`">
                  <WebhookDeliveries v-if="deliveriesFor === webhook.id" :deliveries="deliveries" :loading="deliveriesLoading" :error="deliveriesError" />
                </div>
              </Surface>
            </li>
          </ul>
        </section>
      </template>
      <WebhookSecretDialog :secret="secret" @close="dismissSecret" />
    </main>
  </WorkspaceShell>
</template>

<style scoped>
.webhook-page { display: grid; gap: var(--space-6); padding-block: var(--space-6); }
.webhook-intro, .webhook-muted { margin: 0; color: var(--color-muted); }
.webhook-error { margin: 0; color: var(--color-danger); }
.webhook-notice { margin: 0; color: var(--color-ink); font-weight: var(--weight-lg); }
.webhook-section { display: grid; gap: var(--space-4); }
.webhook-section h2 { margin: 0; font-size: var(--text-lg); line-height: var(--leading-lg); }
.webhook-load-error { display: grid; justify-items: start; gap: var(--space-3); }
.webhook-list { display: grid; gap: var(--space-4); margin: 0; padding: 0; list-style: none; }
.webhook-item { display: grid; gap: var(--space-3); }
.webhook-url { margin: 0; font-size: var(--text-base); line-height: var(--leading-base); overflow-wrap: anywhere; }
.webhook-meta { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.webhook-type-list { display: flex; flex-wrap: wrap; gap: var(--space-2); margin: 0; padding: 0; list-style: none; }
.webhook-type-list li { padding: var(--space-1) var(--space-2); border: 1px solid var(--color-muted); border-radius: var(--radius-pill); font-size: var(--text-sm); line-height: var(--leading-sm); }
.webhook-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
</style>
