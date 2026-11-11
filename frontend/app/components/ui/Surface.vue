<script setup lang="ts">
withDefaults(defineProps<{ level?: 1 | 2 | 3; as?: 'div' | 'section' | 'article' }>(), { level: 1, as: 'div' });
</script>

<template>
  <component :is="as" class="ui-surface" :class="`ui-surface-${level}`"><slot /></component>
</template>

<style scoped>
.ui-surface { padding: var(--space-6); border: 1px solid var(--color-line); border-radius: var(--radius-lg); color: var(--color-ink); }
.ui-surface-1 { background: var(--color-surface); }
.ui-surface-2 { background: var(--color-surface-raised); }
.ui-surface-3 { background: var(--color-surface-bright); }
</style>
