<template>
  <label class="field" :for="forId">
    <span v-if="label" class="field-label">{{ label }}</span>
    <div class="field-control">
      <slot :id="forId" :ariaDescribedby="describedBy" :ariaInvalid="hasError ? 'true' : undefined" />
    </div>
    <span v-if="hint" :id="hintId" class="field-hint">{{ hint }}</span>
    <FieldError :message="error" :id="errorId" />
  </label>
</template>

<script setup lang="ts">
import { computed } from 'vue';

const props = withDefaults(defineProps<{
  label?: string;
  hint?: string;
  error?: string | null;
  forId?: string;
}>(), {
  label: '',
  hint: '',
  error: null,
  forId: '',
});

const hasError = computed(() => Boolean(props.error));
const hintId = computed(() => (props.forId ? `${props.forId}-hint` : undefined));
const errorId = computed(() => (props.forId ? `${props.forId}-error` : undefined));
const describedBy = computed(() => [props.hint ? hintId.value : null, props.error ? errorId.value : null].filter(Boolean).join(' ') || undefined);
</script>