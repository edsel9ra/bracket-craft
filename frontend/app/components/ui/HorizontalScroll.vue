<script setup lang="ts">
defineProps<{ label: string }>();
const { t } = useI18n();
const hintId = useId();
</script>

<template>
  <div class="scroll-surface">
    <p class="scroll-hint">{{ t('common.horizontalScrollHint') }}</p>
    <p :id="hintId" class="visually-hidden">{{ t('common.horizontalScroll') }}</p>
    <div class="scroll-content" role="region" :aria-label="label" :aria-describedby="hintId" tabindex="0">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.scroll-surface { position: relative; min-width: 0; }
.scroll-content { overflow-x: auto; padding-bottom: var(--space-2); }
.scroll-content:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 3px; }
.scroll-hint { margin: 0 0 var(--space-2); color: var(--color-muted); font-size: var(--text-sm); line-height: 1.5; }
.scroll-surface::after { position: absolute; top: 0; right: 0; bottom: 8px; width: 14px; background: linear-gradient(to right, transparent, color-mix(in srgb, var(--color-shadow) 55%, transparent)); content: ''; pointer-events: none; }
@media (min-width: 760px) {
  .scroll-hint { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
  .scroll-surface::after { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .scroll-content { scroll-behavior: auto; }
}
</style>
