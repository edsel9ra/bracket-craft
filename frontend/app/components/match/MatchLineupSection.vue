<script setup lang="ts">
import { FORMATION_OPTIONS } from '~/constants/formations';
import Button from '~/components/ui/Button.vue';
import SanctionLineupWarning from '~/components/sanction/SanctionLineupWarning.vue';
import { positionLabel } from '~/utils/positions';

import type { MatchOperationContext } from '~/composables/useMatchOperation';

const props = defineProps<{ context: MatchOperationContext }>();
const { t, busyAction, lineupRoles, lineupPositions, lineupFormations, isTerminal, canOperateMatch, selectedSegment, selectedSegmentIsActive, teamRosters, availablePositions, tacticalRowsForTeam, isTeamLineupPublic, playerName } = props.context;
const emit = defineEmits<{
  saveLineup: [];
  setFormation: [teamId: string, event: Event];
  toggleLineupPublication: [teamId: string];
}>();
const saveLineup = () => emit('saveLineup');
const setFormation = (teamId: string, event: Event) => emit('setFormation', teamId, event);
const toggleLineupPublication = (teamId: string) => emit('toggleLineupPublication', teamId);
</script>

<template>
<section class="panel panel-wide" id="seccion-planilla" tabindex="-1">
               <div class="panel-heading"><div><p class="eyebrow">03 · {{ t('match.roster') }}</p><h2>{{ t('match.definePlayers') }}</h2></div><Button v-if="canOperateMatch" type="button" :disabled="Boolean(busyAction) || isTerminal || !selectedSegmentIsActive" @click="saveLineup">{{ busyAction === 'lineup' ? t('match.savingLineup') : t('match.saveLineup') }}</Button></div>
              <p class="panel-description">{{ t('match.selectRoles', { segment: selectedSegment?.segment_number || t('match.activeSegment') }) }}</p>
              <SanctionLineupWarning :match-id="context.matchId" :enabled="canOperateMatch && !isTerminal" :refresh-key="selectedSegment?.id || ''" :players="teamRosters.flatMap((team) => team.players).map((player) => ({ id: player.player_id, label: playerName(player) }))" />
              <p v-if="!selectedSegmentIsActive" class="segment-warning">{{ t('match.noActiveSegment') }}</p>
             <div class="formation-config-grid">
               <div v-for="team in teamRosters" :key="`${team.key}-formation`" class="formation-config">
                 <div class="formation-config-heading">
                   <strong>{{ team.name }}</strong>
                   <span v-if="team.team_id && tacticalRowsForTeam(team.team_id).length" :class="['publication-state', { published: isTeamLineupPublic(team.team_id) }]">
                     {{ isTeamLineupPublic(team.team_id) ? t('match.lineupPublished') : t('match.lineupPrivate') }}
                   </span>
                 </div>
                 <label class="field">{{ t('match.formation') }}
                    <select :value="lineupFormations[team.team_id] || ''" :disabled="!canOperateMatch || !team.team_id || isTerminal || !selectedSegmentIsActive" @change="setFormation(team.team_id, $event)">
                     <option value="">{{ t('match.classicLineup') }}</option>
                     <option v-for="formation in FORMATION_OPTIONS" :key="formation" :value="formation">{{ formation }}</option>
                   </select>
                 </label>
                  <button v-if="canOperateMatch && team.team_id && lineupFormations[team.team_id]" class="text-button publication-button" type="button" :disabled="Boolean(busyAction) || isTerminal || !tacticalRowsForTeam(team.team_id).length" @click="toggleLineupPublication(team.team_id)">
                   {{ isTeamLineupPublic(team.team_id) ? t('match.unpublishLineup') : t('match.publishLineup') }}
                 </button>
               </div>
             </div>
             <div class="roster-columns">
               <div v-for="team in teamRosters" :key="team.key" class="roster-team">
                 <div class="team-heading"><strong>{{ team.name }}</strong><span>{{ t('match.eligible', { count: team.players.length }) }}</span></div>
                 <div v-if="team.players.length" class="player-list">
                   <label v-for="player in team.players" :key="player.roster_id" class="player-row">
                     <span class="player-number">{{ player.dorsal_number }}</span><span class="player-name">{{ playerName(player) }}</span>
                       <select v-model="lineupRoles[player.roster_id]" :disabled="!canOperateMatch || !player.is_active || isTerminal || !selectedSegmentIsActive" :aria-label="`${t('match.role')} ${playerName(player)}`"><option value="">{{ t('match.notParticipating') }}</option><option value="starter">{{ t('match.starter') }}</option><option value="substitute">{{ t('match.substitute') }}</option></select>
                       <select v-if="lineupRoles[player.roster_id] === 'starter'" v-model="lineupPositions[player.roster_id]" :disabled="!canOperateMatch || !player.is_active || isTerminal || !selectedSegmentIsActive || !lineupFormations[team.team_id]" :aria-label="`${t('match.position')} ${playerName(player)}`">
                        <option value="">{{ t('match.selectPosition') }}</option>
                        <option v-for="position in availablePositions(team.team_id)" :key="position" :value="position">{{ positionLabel(position, t) }}</option>
                      </select>
                      <span v-else class="position-placeholder">{{ t('match.noTacticalPosition') }}</span>
                   </label>
                 </div>
                <p v-else class="muted-note">{{ t('match.noPlayers') }}</p>
              </div>
            </div>
          </section>
</template>

<style scoped src="./operation.css" />
