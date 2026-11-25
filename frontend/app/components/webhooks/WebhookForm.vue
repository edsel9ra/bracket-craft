<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import Button from '~/components/ui/Button.vue';
import { WEBHOOK_EVENT_TYPES, orderedWebhookTypes, validateWebhookUrl, type WebhookEventType, type WebhookInput } from '~/utils/webhooks';

const props = withDefaults(defineProps<{ initial?: WebhookInput | null; submitLabel: string; busy?: boolean; error?: string; cancellable?: boolean }>(), {
  initial: null, busy: false, error: '', cancellable: false,
});
const emit = defineEmits<{ submit: [input: WebhookInput]; cancel: [] }>();
const { t } = useI18n();
const id = useId();
const url = ref(props.initial?.url ?? '');
const types = ref<WebhookEventType[]>([...(props.initial?.event_types ?? [])]);
const localError = ref('');
const shown = computed(() => localError.value || props.error);
const urlInvalid = computed(() => shown.value === 'webhook.error.url');
const describedBy = computed(() => (shown.value ? `${id}-hint ${id}-error` : `${id}-hint`));

// Se compara por valor: la página pasa un objeto nuevo en cada render (p. ej. al cambiar `busy`).
watch(() => JSON.stringify([props.initial?.url ?? '', props.initial?.event_types ?? []]), () => {
  url.value = props.initial?.url ?? '';
  types.value = [...(props.initial?.event_types ?? [])];
  localError.value = '';
});

function submit() {
  const selected = orderedWebhookTypes(types.value);
  localError.value = validateWebhookUrl(url.value) ?? (selected.length ? '' : 'webhook.error.types');
  if (!localError.value) emit('submit', { url: url.value, event_types: selected });
}
</script>

<template>
  <form class="webhook-form" novalidate @submit.prevent="submit">
    <div class="webhook-field field-control">
      <label :for="`${id}-url`">{{ t('webhook.form.url') }}</label>
      <input
        :id="`${id}-url`" type="url" :aria-invalid="urlInvalid ? 'true' : undefined" :aria-describedby="describedBy"
        v-model="url" inputmode="url" autocomplete="off" spellcheck="false" maxlength="2048" required
      >
      <p :id="`${id}-hint`" class="webhook-hint">{{ t('webhook.form.urlHint') }}</p>
    </div>
    <fieldset class="webhook-types" :aria-invalid="shown === 'webhook.error.types' ? 'true' : undefined">
      <legend>{{ t('webhook.form.types') }}</legend>
      <label v-for="type in WEBHOOK_EVENT_TYPES" :key="type" class="webhook-type">
        <input v-model="types" type="checkbox" :value="type">
        <span>{{ t(`webhook.type.${type}`) }}</span>
      </label>
    </fieldset>
    <p v-if="shown" :id="`${id}-error`" role="alert" class="webhook-form-error">{{ t(shown) }}</p>
    <div class="webhook-form-actions">
      <Button type="submit" :busy="busy" :disabled="busy">{{ t(submitLabel) }}</Button>
      <Button v-if="cancellable" variant="secondary" :disabled="busy" @click="emit('cancel')">{{ t('common.cancel') }}</Button>
    </div>
  </form>
</template>

<style scoped>
.webhook-form { display: grid; gap: var(--space-4); }
.webhook-field { display: grid; gap: var(--space-2); }
.webhook-field label, .webhook-types legend { font-weight: var(--weight-lg); }
.webhook-field input { width: 100%; }
.webhook-hint { margin: 0; color: var(--color-muted); font-size: var(--text-sm); line-height: var(--leading-sm); }
.webhook-types { display: grid; gap: var(--space-2); margin: 0; padding: 0; border: 0; }
.webhook-types legend { margin-bottom: var(--space-2); padding: 0; }
.webhook-type { display: flex; align-items: center; gap: var(--space-2); min-height: var(--space-8); }
.webhook-form-error { margin: 0; color: var(--color-danger); }
.webhook-form-actions { display: flex; flex-wrap: wrap; gap: var(--space-3); }
</style>
