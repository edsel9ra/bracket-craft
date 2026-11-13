<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
defineProps<{ total: number; offset: number; busy: boolean }>();
defineEmits<{ page: [delta: number] }>();
const { t } = useI18n();
</script>

<template>
  <nav v-if="total > 25 || offset" :aria-label="t('sanction.pagination')">
    <Button variant="secondary" :disabled="!offset || busy" @click="$emit('page', -1)">{{ t('sanction.previous') }}</Button>
    <span>{{ Math.min(offset + 1, total) }}–{{ Math.min(offset + 25, total) }} / {{ total }}</span>
    <Button variant="secondary" :disabled="offset + 25 >= total || busy" @click="$emit('page', 1)">{{ t('sanction.next') }}</Button>
  </nav>
</template>

<style scoped>
nav { display: flex; flex-wrap: wrap; gap: var(--space-4); align-items: center; }
</style>
