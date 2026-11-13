<script setup lang="ts">
import Surface from '~/components/ui/Surface.vue';
import SanctionEvidence from './SanctionEvidence.vue';
import type { SanctionDetail } from '~/utils/sanctions';
defineProps<{ detail: SanctionDetail }>();
const { t, formatDateTime } = useI18n();
</script>

<template>
  <Surface as="article" class="detail">
    <h2>{{ t(`sanction.type.${detail.case.case_type}`) }} · {{ t(`sanction.status.${detail.case.status}`) }}</h2>
    <p>{{ t('sanction.caseId') }}: {{ detail.case.id }}</p><p>{{ detail.case.reason }}</p>
    <p>{{ t('sanction.author') }}: {{ detail.case.submitted_by_user_id }} · {{ formatDateTime(detail.case.submitted_at) }}</p>
    <p v-if="detail.case.prior_case_id">{{ t('sanction.priorCase') }}: {{ detail.case.prior_case_id }}</p>
    <p v-if="detail.case.proposed_action">{{ t('sanction.proposedAction') }}: {{ t(`sanction.decision.${detail.case.proposed_action}`) }} <span v-if="detail.case.proposed_duration !== null">· {{ detail.case.proposed_duration }}</span></p>
    <SanctionEvidence :text="detail.case.evidence_text" :links="detail.case.evidence_links" />
    <section>
      <h3>{{ t('sanction.source') }}</h3><p>{{ t(`sanction.source.${detail.source.source_type}`) }} · {{ t(`sanction.scope.${detail.source.scope_type}`) }}</p>
      <p>{{ detail.source.reason }}</p><p>{{ t('sanction.player') }}: {{ detail.source.player_id }}</p>
      <p>{{ t('sanction.sanctionId') }}: {{ detail.source.id }}</p>
      <p v-if="detail.source.origin_match_id">{{ t('sanction.sourceMatch') }}: {{ detail.source.origin_match_id }}</p>
      <dl><dt>{{ t('sanction.original') }}</dt><dd>{{ detail.projection.original_duration }}</dd><dt>{{ t('sanction.effective') }}</dt><dd>{{ detail.projection.effective_duration }}</dd><dt>{{ t('sanction.served') }}</dt><dd>{{ detail.projection.served_count }}</dd><dt>{{ t('sanction.remaining') }}</dt><dd>{{ detail.projection.remaining }}</dd></dl>
      <p v-if="detail.projection.pending_effect" role="status">{{ t('sanction.pendingEffect') }}</p>
    </section>
    <section>
      <h3>{{ t('sanction.resolutions') }}</h3><p v-if="!detail.resolutions.length">{{ t('sanction.noResolutions') }}</p>
      <ul><li v-for="resolution in detail.resolutions" :key="resolution.id">
        <p>{{ t(`sanction.decision.${resolution.action}`) }} · {{ formatDateTime(resolution.created_at) }}<span v-if="resolution.new_duration !== null"> · {{ resolution.new_duration }}</span></p>
        <p v-if="resolution.excluded">{{ t('sanction.excluded') }}</p><p v-else-if="resolution.is_declarative">{{ t('sanction.declarative') }}</p>
        <p v-else-if="!detail.applications.some((application) => application.resolution_id === resolution.id)">{{ t('sanction.pendingEffect') }}</p>
        <p v-for="application in detail.applications.filter((item) => item.resolution_id === resolution.id)" :key="application.id">{{ t('sanction.appliedAt') }}: {{ formatDateTime(application.effective_at) }} · {{ application.match_id }}</p>
      </li></ul>
    </section>
    <section>
      <h3>{{ t('sanction.history') }}</h3>
      <ul><li v-for="event in detail.events" :key="event.id"><p>{{ t(`sanction.event.${event.event_type}`) }} · {{ formatDateTime(event.created_at) }}</p><p>{{ event.reason }}</p><p v-if="event.rectification_version_id">{{ t('sanction.rectification') }}: {{ event.rectification_version_id }}</p><SanctionEvidence :text="event.evidence_text" :links="event.evidence_links" /></li></ul>
      <ul><li v-for="decision in detail.decisions" :key="decision.id"><p>{{ t(`sanction.decision.${decision.decision}`) }} · {{ formatDateTime(decision.created_at) }}</p><p>{{ decision.reason }}</p><p>{{ t('sanction.author') }}: {{ decision.decided_by_user_id }}</p><SanctionEvidence :text="decision.evidence_text" :links="decision.evidence_links" /></li></ul>
      <ul><li v-for="serve in detail.serves" :key="serve.id">{{ serve.match_id }} · {{ t(serve.is_voided ? 'sanction.voidedServe' : 'sanction.validServe') }}</li></ul>
    </section>
    <section v-if="detail.prejudice.length"><h3>{{ t('sanction.prejudice') }}</h3><ul><li v-for="record in detail.prejudice" :key="record.id">{{ record.reason }} · {{ record.match_id }} · {{ formatDateTime(record.created_at) }}</li></ul></section>
    <slot />
  </Surface>
</template>

<style scoped>
.detail { display: grid; gap: var(--space-4); overflow-wrap: anywhere; }
dl { display: grid; grid-template-columns: auto auto; gap: var(--space-2); }
dd { margin: 0; }
li { margin-block: var(--space-3); }
</style>
