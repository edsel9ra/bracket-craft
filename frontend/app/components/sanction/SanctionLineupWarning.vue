<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
const props = defineProps<{ matchId: string; enabled: boolean; refreshKey: string; players?: { id: string; label: string }[] }>();
const { t } = useI18n();
const { rows, error, loading, load } = useSuspensionWarnings(() => props.matchId, () => props.enabled, () => props.refreshKey);
</script>

<template>
  <aside v-if="enabled" class="warning" :aria-label="t('sanction.warning')">
    <h3>{{ t('sanction.warning') }}</h3><p>{{ t('sanction.warningHint') }}</p>
    <p v-if="loading" role="status">{{ t('common.loading') }}</p>
    <p v-else-if="error" role="alert">{{ t('sanction.warningUnavailable') }} <Button variant="secondary" @click="load">{{ t('common.retry') }}</Button></p>
    <ul v-else-if="rows.length" role="status"><li v-for="row in rows" :key="row.player_id">{{ players?.find((player) => player.id === row.player_id)?.label || row.player_id }} · {{ t('sanction.remaining') }}: {{ row.remaining }}</li></ul>
  </aside>
</template>

<style scoped>
.warning { margin-block: var(--space-4); padding: var(--space-4); border-inline-start: var(--space-1) solid var(--color-accent); background: var(--color-surface-raised); color: var(--color-ink); border-radius: var(--radius-md); }
li { overflow-wrap: anywhere; }
</style>
