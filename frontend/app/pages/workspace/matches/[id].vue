<script setup lang="ts">
import RectificationVersions from '~/components/match/RectificationVersions.vue';
import CompetitiveImpacts from '~/components/match/CompetitiveImpacts.vue';
import { useMatchOperation } from '~/composables/useMatchOperation';
import MatchOperationHeader from '~/components/match/MatchOperationHeader.vue';
import MatchBar from '~/components/match/MatchBar.vue';
import MatchSectionNav from '~/components/match/MatchSectionNav.vue';
import MatchActionBar from '~/components/match/MatchActionBar.vue';
import { useMatchOperationView } from '~/composables/useMatchOperationView';
import MatchResolutionPanel from '~/components/match/MatchResolutionPanel.vue';
import MatchFieldSection from '~/components/match/MatchFieldSection.vue';
import MatchRosterLinks from '~/components/match/MatchRosterLinks.vue';
import MatchLineupSection from '~/components/match/MatchLineupSection.vue';
import MatchEventsSection from '~/components/match/MatchEventsSection.vue';
import MatchCloseSection from '~/components/match/MatchCloseSection.vue';
import { OPENING_BLOCKED_LABEL_KEYS } from '~/utils/rosterLimits';
import type { MatchOperation } from '~/components/match/types';

definePageMeta({ middleware: 'auth' });

const context = useMatchOperation();
const { action, actionDisabled, activateAction } = useMatchOperationView(context);
const { auth, t, matchId, operation, loading, error, actionError, openingBlocked, busyAction, match, isTerminal, canOperateMatch, workspaceBreadcrumbs, tournamentContext, operationChecklist, loadPersistedDraft, failureMessage, redirectOnSessionFailure, applyOperation, fetchOperation, retryOperation, createSegment, teamRosterLink, restoreSelectedSegment } = context;

const { data: initialOperation, error: initialOperationError } = await useAsyncData<MatchOperation>(
  `workspace-match-${matchId}-${auth.userId || 'none'}-${auth.organizationId || 'none'}-${auth.sessionVersion}`,
  fetchOperation,
);

if (initialOperationError.value) {
  if (!(await redirectOnSessionFailure(initialOperationError.value))) {
    error.value = failureMessage(initialOperationError.value, t('match.noLoad'));
  }
} else if (initialOperation.value) {
  // Primer prerrelleno del formulario de segmento: es el único refresco que
  // escribe el minuto propuesto además de crear o interrumpir.
  applyOperation(initialOperation.value, 'mount');
}

loading.value = false;

if (operation.value) {
  restoreSelectedSegment();
  loadPersistedDraft();
}

onMounted(context.mountOperation);
onBeforeUnmount(context.unmountOperation);
</script>

<template>
  <WorkspaceShell
    :breadcrumbs="workspaceBreadcrumbs"
    :tournament="tournamentContext"
  >
   <main id="main-content" class="operation-shell">
    <MatchOperationHeader :context="context" />
    <MatchBar v-if="match" :context="context" @retry-realtime="context.realtime.retry()" />
    <MatchSectionNav v-if="operation && match" />
    <MatchActionBar v-if="operation && match" :action="action" :disabled="actionDisabled" :busy="Boolean(busyAction)" @activate="activateAction" />

    <section id="operacion" class="container operation-content">
      <div v-if="loading" class="empty-state loading-state" role="status"><span class="loading-orb" aria-hidden="true" /> {{ t('match.loadingOperation') }}</div>
       <div v-else-if="error" class="form-error" role="alert"><span>{{ error }}</span><button class="button-secondary" type="button" @click="retryOperation">{{ t('common.retry') }}</button></div>
      <template v-else-if="operation && match">
        <RectificationVersions v-if="match.result_confirmed" :key="match.id" :match-id="match.id" :can-request="auth.hasPermission('REQUEST_MATCH_REPORT_RECTIFICATION')" />
        <CompetitiveImpacts :key="`${match.tournament_id}-${auth.access?.organization_id}`" :tournament-id="match.tournament_id" :can-approve="auth.hasPermission('APPROVE_MATCH_REPORT_RECTIFICATION')" />
        <div class="checklist" :aria-label="t('match.matchReport')">
          <div v-for="item in operationChecklist" :key="item.label" class="check-item" :class="{ valid: item.valid, neutral: item.neutral }">
            <span aria-hidden="true">{{ item.icon }}</span><strong>{{ item.label }}</strong><small>{{ t(item.statusKey) }}</small>
          </div>
        </div>

        <p v-if="isTerminal" class="segment-warning report-locked" role="status">{{ t('match.reportLocked') }}</p>

        <div v-if="actionError" class="form-error" role="alert">{{ actionError }}</div>

        <section v-if="openingBlocked" class="stage-partial opening-blocked" role="alert" aria-live="assertive">
          <strong>{{ t(OPENING_BLOCKED_LABEL_KEYS.title) }}</strong>
          <p>{{ t(OPENING_BLOCKED_LABEL_KEYS.reason) }}</p>
          <ul>
            <li v-for="team in openingBlocked.teams" :key="`opening-blocked-${team.teamId}`">{{ team.message }}</li>
          </ul>
          <p class="field-hint">{{ t(OPENING_BLOCKED_LABEL_KEYS.retry) }}</p>
          <ul class="roster-links">
            <li v-for="team in openingBlocked.teams" :key="`opening-roster-${team.teamId}`">
              <NuxtLink :to="teamRosterLink(team.teamId)">{{ t(OPENING_BLOCKED_LABEL_KEYS.openRoster, { team: team.teamName }) }}</NuxtLink>
            </li>
          </ul>
          <p class="muted-note">{{ t(OPENING_BLOCKED_LABEL_KEYS.serverDetail, { detail: openingBlocked.detail }) }}</p>
          <button v-if="canOperateMatch" class="button-secondary" type="button" :disabled="Boolean(busyAction) || isTerminal" @click="createSegment">{{ t(OPENING_BLOCKED_LABEL_KEYS.retryAction) }}</button>
        </section>

        <MatchResolutionPanel :context="context" @on-resolution-change="context.onResolutionChange" />

        <div class="operation-grid">
          <MatchFieldSection :context="context" :operation="operation" @mark-segment-minute-dirty="context.markSegmentMinuteDirty" @create-segment="context.createSegment" @interrupt-segment="context.interruptSegment" @mark-interruption-minute-dirty="context.markInterruptionMinuteDirty" @assign-official="context.assignOfficial" @remove-official="context.removeOfficial" />

          <MatchRosterLinks :context="context" />

           <MatchLineupSection :context="context" @save-lineup="context.saveLineup" @set-formation="context.setFormation" @toggle-lineup-publication="context.toggleLineupPublication" />

           <MatchEventsSection :context="context" :operation="operation" :match="match" @add-event="context.addEvent" @remove-event="context.removeEvent" @discard-draft="context.discardDraft" />

           <MatchCloseSection :context="context" :match="match" @begin-close="context.beginClose" @close-match="context.closeMatch" />
        </div>
      </template>
    </section>
   </main>
  </WorkspaceShell>
</template>

<style scoped src="~/components/match/operation.css" />
