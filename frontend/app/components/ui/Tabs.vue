<script setup lang="ts">
import { nextTabIndex } from '~/utils/tabs';
const props = defineProps<{ tabs: { id: string; label: string }[]; label: string }>();
const model = defineModel<string>({ required: true });
const id = useId();
const buttons = ref<HTMLButtonElement[]>([]);

watch([() => props.tabs.map((tab) => tab.id), model], ([ids]) => {
  if (!ids.includes(model.value)) model.value = ids[0] ?? '';
}, { immediate: true });

function onKeydown(event: KeyboardEvent, index: number) {
  const next = nextTabIndex(event.key, index, props.tabs.length);
  if (next === null) return;
  event.preventDefault();
  model.value = props.tabs[next]!.id;
  buttons.value[next]?.focus();
}
</script>

<template>
  <div class="ui-tabs">
    <div role="tablist" :aria-label="label" class="ui-tablist">
      <button
        v-for="(tab, index) in tabs" :id="`${id}-tab-${index}`" :key="tab.id" ref="buttons"
        type="button" role="tab" :aria-selected="model === tab.id" :aria-controls="`${id}-panel-${index}`"
        :tabindex="model === tab.id ? 0 : -1" @click="model = tab.id" @keydown="onKeydown($event, index)"
      >{{ tab.label }}</button>
    </div>
    <section
      v-for="(tab, index) in tabs" :id="`${id}-panel-${index}`" :key="tab.id"
      role="tabpanel" :aria-labelledby="`${id}-tab-${index}`" :hidden="model !== tab.id" tabindex="0"
    ><slot :name="tab.id" /></section>
  </div>
</template>

<style scoped>
.ui-tablist { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-bottom: var(--space-4); }
[role="tab"] { padding: var(--space-2) var(--space-4); border: 1px solid var(--color-muted); border-radius: var(--radius-pill); background: var(--color-surface); color: var(--color-ink); font-size: var(--text-sm); }
[role="tab"][aria-selected="true"] { background: var(--color-accent); color: var(--color-accent-ink); }
@media (prefers-reduced-motion: reduce) { [role="tab"] { transition: none; } }
</style>
