<script setup lang="ts">
import type { VNode } from 'vue';
withDefaults(defineProps<{ tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'live' }>(), { tone: 'neutral' });
defineSlots<{ default(): VNode[] }>();
</script>

<template>
  <span class="ui-status" :class="`ui-status-${tone}`"><slot /></span>
</template>

<style scoped>
.ui-status { display: inline-flex; align-items: center; gap: var(--space-1); padding: var(--space-1) var(--space-2); border-radius: var(--radius-pill); background: var(--color-surface-raised); color: var(--color-ink); font-size: var(--text-xs); line-height: var(--leading-xs); font-weight: var(--weight-lg); }
.ui-status-success { color: var(--color-success); }
.ui-status-warning { color: var(--color-warning); }
.ui-status-danger { color: var(--color-danger); }
.ui-status-live { color: var(--color-accent); }
</style>
