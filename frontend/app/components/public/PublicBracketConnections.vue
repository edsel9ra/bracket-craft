<script setup lang="ts">
import type { PublicBracketLayout } from '~/utils/publicBracketLayout';

defineProps<{ layout: PublicBracketLayout }>();
</script>

<template>
  <svg class="bracket-connections" :width="layout.width" :height="layout.height" :viewBox="`0 0 ${layout.width} ${layout.height}`" aria-hidden="true" focusable="false">
    <path v-for="path in layout.paths" :key="path.sourceId" :d="path.d" :data-source-id="path.sourceId" :data-target-id="path.targetId" />
  </svg>
</template>

<style scoped>
.bracket-connections { position: absolute; top: 0; left: 0; pointer-events: none; overflow: visible; color: var(--color-muted); }
path { fill: none; stroke: currentColor; stroke-width: 2; }
</style>
