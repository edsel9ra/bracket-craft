<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import type { SanctionCase, SanctionRow } from '~/utils/sanctions';
defineProps<{ rows: SanctionCase[]; sanctions: SanctionRow[] }>();
defineEmits<{ select: [id: string] }>();
const { t, formatDateTime } = useI18n();
</script>

<template>
  <section>
    <h2>{{ t('sanction.inbox') }}</h2>
    <p v-if="!rows.length" role="status">{{ t('sanction.noCases') }}</p>
    <ul><li v-for="row in rows" :key="row.id"><span>{{ t(`sanction.type.${row.case_type}`) }} · {{ t(`sanction.status.${row.status}`) }} · {{ formatDateTime(row.submitted_at) }}</span><Button variant="secondary" @click="$emit('select', row.id)">{{ t('sanction.review') }} <span class="sr-only">{{ row.id }}</span></Button></li></ul>
    <h2>{{ t('sanction.sanctions') }}</h2>
    <p v-if="!sanctions.length" role="status">{{ t('sanction.noSanctions') }}</p>
    <ul><li v-for="row in sanctions" :key="row.source.id"><p>{{ t('sanction.player') }}: {{ row.source.player_id }}</p><p>{{ t(`sanction.status.${row.projection.status}`) }} · {{ t('sanction.original') }}: {{ row.projection.original_duration }} · {{ t('sanction.effective') }}: {{ row.projection.effective_duration }} · {{ t('sanction.remaining') }}: {{ row.projection.remaining }}</p><code>{{ row.source.id }}</code></li></ul>
  </section>
</template>

<style scoped>
li { padding-block: var(--space-4); border-top: 1px solid var(--color-muted); overflow-wrap: anywhere; }
ul { list-style: none; padding: 0; }
</style>
