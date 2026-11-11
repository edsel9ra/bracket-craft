<script setup lang="ts">
import StageTeamsWizard from '~/components/StageTeamsWizard.vue';
import type { RosterLimits } from '~/utils/rosterLimits';
import type { StageSummary, TeamSummary, VersionSummary } from './types';

defineProps<{
  tournamentId: string; selectedVersionId: string; selectedVersionStages: StageSummary[];
  teams: TeamSummary[]; selectedVersionRosterLimits: RosterLimits;
  rosterCountsByTeam: Record<string, number>; rosterLockActive: boolean;
  canManageTournaments: boolean; activeVersion?: VersionSummary; saving: boolean; wizardResetToken: number;
}>();
const emit = defineEmits<{ saved: []; confirmed: []; reload: []; 'dirty-change': [value: boolean] }>();
const refreshConfiguration = () => emit('reload');
const onStagesConfirmed = () => emit('confirmed');
</script>

<template>
<StageTeamsWizard
              class="panel-wide"
              :tournament-id="tournamentId"
              :version-id="selectedVersionId"
              :stages="selectedVersionStages"
              :teams="teams"
              :roster-limits="selectedVersionRosterLimits"
              :roster-counts="rosterCountsByTeam"
              :lock-active="rosterLockActive"
              :disabled="!canManageTournaments || activeVersion?.status !== 'draft'"
              :busy="saving"
              :reset-token="wizardResetToken"
              @saved="emit('saved')"
              @confirmed="onStagesConfirmed"
              @reload="refreshConfiguration"
              @dirty-change="emit('dirty-change', $event)"
            />
</template>
