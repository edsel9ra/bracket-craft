<script setup lang="ts">
defineOptions({ inheritAttrs: false });
const props = withDefaults(defineProps<{
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  as?: 'button' | 'NuxtLink';
  to?: string;
  type?: 'button' | 'submit' | 'reset';
  busy?: boolean;
  disabled?: boolean;
}>(), { variant: 'primary', as: 'button', to: undefined, type: 'button', busy: false, disabled: false });
const emit = defineEmits<{ click: [event: MouseEvent] }>();
const link = resolveComponent('NuxtLink');

function onClick(event: MouseEvent) {
  if (props.busy || props.disabled) {
    event.preventDefault();
    event.stopImmediatePropagation();
    return;
  }
  emit('click', event);
}
</script>

<template>
  <component
    :is="as === 'NuxtLink' ? link : 'button'"
    v-bind="$attrs"
    class="ui-button"
    :class="`ui-button-${variant}`"
    :to="as === 'NuxtLink' ? to : undefined"
    :type="as === 'button' ? type : undefined"
    :disabled="as === 'button' ? disabled || busy : undefined"
    :aria-disabled="disabled || busy || undefined"
    :aria-busy="busy || undefined"
    :tabindex="as === 'NuxtLink' && (disabled || busy) ? -1 : undefined"
    @click.capture="onClick"
  ><slot /></component>
</template>

<style scoped>
.ui-button { display: inline-flex; align-items: center; justify-content: center; gap: var(--space-2); padding: var(--space-3) var(--space-4); border: 1px solid transparent; border-radius: var(--radius-pill); font: inherit; font-size: var(--text-md); font-weight: var(--weight-lg); text-decoration: none; }
.ui-button-primary { background: var(--color-accent); color: var(--color-accent-ink); }
.ui-button-secondary { background: var(--color-surface-raised); color: var(--color-ink); border-color: var(--color-muted); }
.ui-button-danger { background: var(--color-danger); color: var(--color-accent-ink); }
.ui-button-ghost { background: transparent; color: var(--color-ink); }
.ui-button:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 4px; }
.ui-button[aria-disabled="true"] { cursor: not-allowed; opacity: 0.65; }
@media (prefers-reduced-motion: reduce) { .ui-button { transition: none; } }
</style>
