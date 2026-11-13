<script setup lang="ts">
import type { CaseStatus, CaseType, SanctionFilters } from '~/utils/sanctions';
const status = defineModel<CaseStatus | ''>('status', { required: true });
const caseType = defineModel<CaseType | ''>('caseType', { required: true });
const sanctionStatus = defineModel<NonNullable<SanctionFilters['status']> | ''>('sanctionStatus', { required: true });
const { t } = useI18n();
</script>

<template>
  <div class="filters">
    <label class="field">{{ t('sanction.caseStatus') }}<select v-model="status"><option value="">{{ t('sanction.all') }}</option><option v-for="value in ['pending', 'resolved', 'withdrawn', 'closed_by_rectification']" :key="value" :value="value">{{ t(`sanction.status.${value}`) }}</option></select></label>
    <label class="field">{{ t('sanction.caseType') }}<select v-model="caseType"><option value="">{{ t('sanction.all') }}</option><option v-for="value in ['appeal', 'administrative_proposal']" :key="value" :value="value">{{ t(`sanction.type.${value}`) }}</option></select></label>
    <label class="field">{{ t('sanction.sanctionStatus') }}<select v-model="sanctionStatus"><option value="">{{ t('sanction.all') }}</option><option v-for="value in ['active', 'served', 'cancelled', 'appealed']" :key="value" :value="value">{{ t(`sanction.status.${value}`) }}</option></select></label>
  </div>
</template>

<style scoped>
.filters { display: flex; flex-wrap: wrap; gap: var(--space-4); }
</style>
