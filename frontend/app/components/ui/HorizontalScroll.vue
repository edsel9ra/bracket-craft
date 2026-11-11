<script setup lang="ts">
import { onBeforeUnmount, onMounted, onUpdated, shallowRef, useTemplateRef } from 'vue';

defineProps<{ label: string }>();
const { t } = useI18n();
const hintId = useId();
const content = useTemplateRef<HTMLElement>('content');
const hasOverflow = shallowRef(false);
let observer: ResizeObserver | undefined;

function measure() {
  const element = content.value;
  hasOverflow.value = Boolean(element && element.scrollWidth > element.clientWidth);
}

function observe() {
  observer?.disconnect();
  const element = content.value;
  if (!element) return;
  observer?.observe(element);
  for (const child of element.children) observer?.observe(child);
  measure();
}

onMounted(() => {
  observer = new ResizeObserver(measure);
  observe();
});
onUpdated(observe);
onBeforeUnmount(() => observer?.disconnect());
</script>

<template>
  <div class="scroll-surface" :class="{ 'has-overflow': hasOverflow }">
    <p v-show="hasOverflow" class="scroll-hint">{{ t('common.horizontalScrollHint') }}</p>
    <p :id="hintId" class="visually-hidden">{{ t('common.horizontalScroll') }}</p>
    <div ref="content" class="scroll-content" role="region" :aria-label="label" :aria-describedby="hintId" tabindex="0">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.scroll-surface { position: relative; min-width: 0; }
.scroll-content { overflow-x: auto; padding-bottom: var(--space-2); }
.scroll-content:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 3px; }
.scroll-hint { margin: 0 0 var(--space-2); color: var(--color-muted); font-size: var(--text-sm); line-height: 1.5; }
.scroll-surface.has-overflow::after { position: absolute; top: 0; right: 0; bottom: 8px; width: 14px; background: linear-gradient(to right, transparent, color-mix(in srgb, var(--color-shadow) 55%, transparent)); content: ''; pointer-events: none; }
@media (prefers-reduced-motion: reduce) {
  .scroll-content { scroll-behavior: auto; }
}
</style>
