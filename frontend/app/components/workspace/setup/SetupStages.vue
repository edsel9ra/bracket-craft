<script setup lang="ts">
import StageTeamsWizard from '~/components/StageTeamsWizard.vue';
import StageSlotOriginsEditor from './StageSlotOriginsEditor.vue';
import { isEliminationStage } from '~/utils/stageAdvancement';
import type { RosterLimits } from '~/utils/rosterLimits';
import type { StageSummary, TeamSummary, VersionSummary } from './types';

const props = defineProps<{
  tournamentId: string; selectedVersionId: string; selectedVersionStages: StageSummary[];
  teams: TeamSummary[]; selectedVersionRosterLimits: RosterLimits;
  rosterCountsByTeam: Record<string, number>; rosterLockActive: boolean;
  canManageTournaments: boolean; activeVersion?: VersionSummary; saving: boolean; wizardResetToken: number;
}>();
const emit = defineEmits<{ saved: []; confirmed: []; reload: []; 'dirty-change': [value: boolean] }>();
const refreshConfiguration = () => emit('reload');
const onStagesConfirmed = () => emit('confirmed');
const eliminationStages = computed(() => props.selectedVersionStages.filter((stage) => isEliminationStage(stage.stage_type)));
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
<StageSlotOriginsEditor
              v-for="stage in eliminationStages"
              :key="`${selectedVersionId}:${stage.id}`"
              class="panel-wide"
              :tournament-id="tournamentId"
              :stage="stage"
              :can-manage="canManageTournaments"
              @saved="refreshConfiguration"
            />
</template>
