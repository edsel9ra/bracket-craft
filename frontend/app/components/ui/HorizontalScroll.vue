<script setup lang="ts">
defineProps<{ label: string }>();
const { t } = useI18n();
const hintId = useId();
</script>

<template>
  <div class="scroll-surface">
    <p :id="hintId" class="scroll-hint">{{ t('common.horizontalScroll') }}</p>
    <div class="scroll-content" role="region" :aria-label="label" :aria-describedby="hintId" tabindex="0">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.scroll-surface { position: relative; min-width: 0; }
.scroll-content { overflow-x: auto; padding-bottom: 8px; }
.scroll-content:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
.scroll-hint { margin: 0 0 10px; color: var(--muted); font-size: 0.8rem; line-height: 1.5; }
.scroll-surface::after { position: absolute; top: 0; right: 0; bottom: 8px; width: 14px; background: linear-gradient(to right, transparent, rgba(0, 0, 0, 0.55)); content: ''; pointer-events: none; }
@media (min-width: 761px) {
  .scroll-hint { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
  .scroll-surface::after { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .scroll-content { scroll-behavior: auto; }
}
</style>
