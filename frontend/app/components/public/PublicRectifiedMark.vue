<script setup lang="ts">
const props = defineProps<{ rectifiedAt?: string | null }>();
const { t, formatDateTime } = useI18n();
const valid = computed(() => Boolean(props.rectifiedAt && Number.isFinite(Date.parse(props.rectifiedAt))));
</script>

<template>
  <p v-if="rectifiedAt && valid" class="rectified-mark">{{ t('public.rectifiedResult') }} · <time :datetime="rectifiedAt">{{ formatDateTime(rectifiedAt) }}</time></p>
</template>

<style scoped>
.rectified-mark { color: var(--color-text); font-size: var(--text-sm); margin-block: var(--space-2); overflow-wrap: anywhere; }
</style>
