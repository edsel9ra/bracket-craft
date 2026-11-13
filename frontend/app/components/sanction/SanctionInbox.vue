<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import SanctionFilters from './SanctionFilters.vue';
import SanctionCaseList from './SanctionCaseList.vue';
import SanctionPagination from './SanctionPagination.vue';
defineEmits<{ select: [id: string] }>();
const { t } = useI18n();
const { canRead, status, caseType, sanctionStatus, rows, sanctions, total, sanctionTotal, offset, sanctionOffset, loading, error, load, page } = useSanctionInbox();
defineExpose({ reload: load });
</script>

<template>
  <Surface v-if="canRead" as="section">
    <SanctionFilters v-model:status="status" v-model:case-type="caseType" v-model:sanction-status="sanctionStatus" />
    <Button variant="secondary" :busy="loading" @click="load">{{ t('common.refresh') }}</Button>
    <p v-if="loading" role="status">{{ t('common.loading') }}</p>
    <p v-else-if="error" role="alert">{{ t(error) }} <Button variant="secondary" @click="load">{{ t('common.retry') }}</Button></p>
    <template v-else>
      <SanctionCaseList :rows="rows" :sanctions="sanctions" @select="$emit('select', $event)" />
      <p>{{ t('sanction.inbox') }}</p><SanctionPagination :total="total" :offset="offset" :busy="loading" @page="page('cases', $event)" />
      <p>{{ t('sanction.sanctions') }}</p><SanctionPagination :total="sanctionTotal" :offset="sanctionOffset" :busy="loading" @page="page('sanctions', $event)" />
    </template>
  </Surface>
  <p v-else role="status">{{ t('sanction.noReadAccess') }}</p>
</template>
