<script setup lang="ts">
import FormField from '~/components/ui/FormField.vue';
import type { MatchRecord } from '~/components/match/types';

import type { MatchOperationContext } from '~/composables/useMatchOperation';

const props = defineProps<{ context: MatchOperationContext; match: MatchRecord }>();
const { t, busyAction, closeForm, isTerminal, canOperateMatch, selectedSegmentIsActive, resolution, resolutionLimits, rulesDefaults, walkoverScore, walkoverReasonOptions, WALKOVER_WINNER_ERROR_ID, WALKOVER_REASON_ERROR_ID, walkoverWinnerError, walkoverWinnerDescribedBy, walkoverReasonError, walkoverReasonDescribedBy, resolutionLabel } = props.context;
const { match } = toRefs(props);
const emit = defineEmits<{
  beginClose: [];
  closeMatch: [];
}>();
const beginClose = () => emit('beginClose');
const closeMatch = () => emit('closeMatch');
</script>

<template>
<section class="panel close-panel panel-wide" @focusin="beginClose">
            <div class="panel-heading"><div><p class="eyebrow">05 · {{ t('match.result') }}</p><h2>{{ t('match.closeReport') }}</h2></div><span class="muted-note">{{ rulesDefaults.extra_time_enabled ? t('match.overtimeEnabled') : t('match.noOvertime') }}</span></div>
             <div class="score-form">
               <p class="muted-note close-resolution full-width">{{ t('match.closeUsesResolution', { resolution: resolutionLabel(resolution) }) }}<template v-if="resolution !== 'walkover'"> · {{ t('match.resolutionMaximum', { max: resolutionLimits.maxMinute }) }}</template></p>
               <template v-if="resolution === 'walkover'">
                 <!-- RF-012/D-7: el W.O. no necesita segmento ni planilla; se dice para que el botón habilitado no parezca un defecto. -->
                 <p class="muted-note full-width walkover-notice" role="status">{{ t('match.walkoverNoSegment') }}</p>
                  <label class="field">{{ t('match.winner') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="closeForm.winner_team_id" required :disabled="!canOperateMatch || isTerminal" :aria-invalid="Boolean(walkoverWinnerError)" :aria-describedby="walkoverWinnerDescribedBy"><option value="" disabled>{{ t('match.selectWinner') }}</option><option v-if="match.home_team_id" :value="match.home_team_id">{{ match.home_team_name }}</option><option v-if="match.away_team_id" :value="match.away_team_id">{{ match.away_team_name }}</option></select><small v-if="walkoverWinnerError" :id="WALKOVER_WINNER_ERROR_ID" class="form-error" role="alert">{{ walkoverWinnerError }}</small></label>
                  <label class="field">{{ t('match.walkoverReason') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="closeForm.reason" required :disabled="!canOperateMatch || isTerminal" :aria-invalid="Boolean(walkoverReasonError)" :aria-describedby="walkoverReasonDescribedBy"><option value="" disabled>{{ t('match.selectWinner') }}</option><option v-for="option in walkoverReasonOptions" :key="option.value" :value="option.value">{{ t(option.labelKey) }}</option></select><small v-if="walkoverReasonError" :id="WALKOVER_REASON_ERROR_ID" class="form-error" role="alert">{{ walkoverReasonError }}</small></label>
                 <!-- RF-005: la pareja efectiva la deriva el servidor; aquí solo se muestra, nunca se edita ni se envía. -->
                 <p class="muted-note full-width walkover-score" role="status">{{ t('match.walkoverScore') }}: {{ walkoverScore ? `${walkoverScore.winner}-${walkoverScore.loser}` : '—' }}</p>
               </template>
               <template v-else>
               <FormField :label="`${match.home_team_name} · ${t('match.regularScore')}`" for-id="close-home-regular">
                 <template #default="{ id, ariaDescribedby }">
                   <input :id="id" v-model.number="closeForm.home_score_regular" type="number" min="0" required :disabled="!canOperateMatch || isTerminal" :aria-describedby="ariaDescribedby" />
                 </template>
               </FormField>
               <FormField :label="`${match.away_team_name} · ${t('match.regularScore')}`" for-id="close-away-regular">
                 <template #default="{ id, ariaDescribedby }">
                   <input :id="id" v-model.number="closeForm.away_score_regular" type="number" min="0" required :disabled="!canOperateMatch || isTerminal" :aria-describedby="ariaDescribedby" />
                 </template>
               </FormField>
              <template v-if="resolution !== 'regular'">
                  <FormField :label="`${match.home_team_name} · ${t('match.finalScore')}`" for-id="close-home-final">
                    <template #default="{ id, ariaDescribedby }">
                      <input :id="id" v-model.number="closeForm.home_score" type="number" min="0" required :disabled="!canOperateMatch || isTerminal" :aria-describedby="ariaDescribedby" />
                    </template>
                  </FormField>
                  <FormField :label="`${match.away_team_name} · ${t('match.finalScore')}`" for-id="close-away-final">
                    <template #default="{ id, ariaDescribedby }">
                      <input :id="id" v-model.number="closeForm.away_score" type="number" min="0" required :disabled="!canOperateMatch || isTerminal" :aria-describedby="ariaDescribedby" />
                    </template>
                  </FormField>
                  <FormField v-if="resolution === 'penalties'" :label="t('match.homePenalties')" for-id="close-home-penalties">
                    <template #default="{ id, ariaDescribedby }">
                      <input :id="id" v-model.number="closeForm.home_penalties" type="number" min="0" required :disabled="!canOperateMatch || isTerminal" :aria-describedby="ariaDescribedby" />
                    </template>
                  </FormField>
                  <FormField v-if="resolution === 'penalties'" :label="t('match.awayPenalties')" for-id="close-away-penalties">
                    <template #default="{ id, ariaDescribedby }">
                      <input :id="id" v-model.number="closeForm.away_penalties" type="number" min="0" required :disabled="!canOperateMatch || isTerminal" :aria-describedby="ariaDescribedby" />
                    </template>
                  </FormField>
                   <label class="field">{{ t('match.winner') }}<select v-model="closeForm.winner_team_id" required :disabled="!canOperateMatch || isTerminal"><option value="" disabled>{{ t('match.selectWinner') }}</option><option v-if="match.home_team_id" :value="match.home_team_id">{{ match.home_team_name }}</option><option v-if="match.away_team_id" :value="match.away_team_id">{{ match.away_team_name }}</option></select></label>
               </template>
                <label v-if="resolution === 'administrative'" class="full-width">{{ t('match.administrativeReason') }}<textarea v-model="closeForm.reason" maxlength="1000" required :disabled="!canOperateMatch || isTerminal" /></label>
               </template>
             </div>
                <div class="close-actions"><p class="muted-note">{{ t('match.backendValidation') }}</p><button v-if="canOperateMatch" class="button-primary close-button" type="button" :disabled="Boolean(busyAction) || isTerminal || (!selectedSegmentIsActive && resolution !== 'walkover')" @click="closeMatch">{{ busyAction === 'close' ? t('match.closing') : isTerminal ? t('match.closed') : t('match.confirmReport') }}</button></div>
          </section>
</template>

<style scoped src="./operation.css" />
