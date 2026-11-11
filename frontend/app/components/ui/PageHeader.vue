<script setup lang="ts">
defineProps<{ title: string }>();
</script>

<template>
  <header class="page-header">
    <div class="page-heading">
      <div v-if="$slots.context" class="page-context"><slot name="context" /></div>
      <div class="page-title">
        <h1>{{ title }}</h1>
        <div v-if="$slots.state" class="page-state"><slot name="state" /></div>
      </div>
    </div>
    <div v-if="$slots.actions" class="page-actions"><slot name="actions" /></div>
  </header>
</template>

<style scoped>
.page-header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--space-3); padding-block: var(--space-4); }
.page-heading { display: grid; gap: var(--space-1); min-width: 0; }
.page-context { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); color: var(--color-accent); font-size: var(--text-xs); line-height: var(--leading-xs); letter-spacing: 0.1em; text-transform: uppercase; }
.page-title, .page-state, .page-actions { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-3); }
h1 { margin: 0; font-family: var(--font-display); font-size: var(--text-xl); font-weight: var(--weight-xl); font-stretch: condensed; font-variation-settings: "wdth" 75; line-height: var(--leading-xl); letter-spacing: -0.04em; }
@media (max-width: 760px) { .page-actions { width: 100%; } }
</style>
