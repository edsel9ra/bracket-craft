<script setup lang="ts">
import Button from './Button.vue';
withDefaults(defineProps<{ kind: 'empty' | 'loading' | 'error'; retry?: boolean }>(), { retry: false });
const emit = defineEmits<{ retry: [] }>();
const { t } = useI18n();
</script>

<template>
  <div class="ui-state" :class="`ui-state-${kind}`" :role="kind === 'error' ? 'alert' : 'status'">
    <p><slot /></p>
    <Button v-if="kind === 'error' && retry" variant="secondary" @click="emit('retry')">{{ t('common.retry') }}</Button>
  </div>
</template>

<style scoped>
.ui-state { padding: var(--space-6); border: 1px solid var(--color-line); border-radius: var(--radius-md); color: var(--color-muted); background: var(--color-surface); font-size: var(--text-base); line-height: var(--leading-base); }
.ui-state p { margin: 0 0 var(--space-3); }
.ui-state-error { color: var(--color-danger); }
</style>
