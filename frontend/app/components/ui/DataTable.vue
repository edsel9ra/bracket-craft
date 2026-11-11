<script setup lang="ts">
import HorizontalScroll from './HorizontalScroll.vue';
defineProps<{
  caption: string;
  columns: { key: string; label: string; rowHeader?: boolean }[];
  rows: Record<string, unknown>[];
  rowKey: string;
}>();
</script>

<template>
  <HorizontalScroll :label="caption">
    <table class="ui-table">
      <caption>{{ caption }}</caption>
      <thead><tr><th v-for="column in columns" :key="column.key" scope="col">{{ column.label }}</th></tr></thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row[rowKey])">
          <component :is="column.rowHeader ? 'th' : 'td'" v-for="column in columns" :key="column.key" :scope="column.rowHeader ? 'row' : undefined">
            <slot :name="`cell-${column.key}`" :row="row" :value="row[column.key]">{{ row[column.key] }}</slot>
          </component>
        </tr>
      </tbody>
    </table>
  </HorizontalScroll>
</template>

<style scoped>
.ui-table { width: 100%; border-collapse: collapse; color: var(--color-ink); background: var(--color-surface); font-size: var(--text-md); line-height: var(--leading-md); }
.ui-table caption { padding: var(--space-3); text-align: left; font-weight: var(--weight-lg); }
.ui-table th, .ui-table td { padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--color-line); text-align: left; }
.ui-table th { font-weight: var(--weight-lg); }
</style>
