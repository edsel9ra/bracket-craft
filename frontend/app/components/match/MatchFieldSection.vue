<script setup lang="ts">
import FormField from '~/components/ui/FormField.vue';
import type { Official, MatchOperation } from '~/components/match/types';

import type { MatchOperationContext } from '~/composables/useMatchOperation';

const props = defineProps<{ context: MatchOperationContext; operation: MatchOperation }>();
const { t, statusLabel, busyAction, selectedSegmentId, segmentForm, interruptionForm, officialForm, officialRoles, isTerminal, canManageTournaments, canOperateMatch, selectedSegment, activeSegment, selectedInterruption, segmentProposalHintText, resolutionLimits, eventFieldError, eventFieldErrorId, eventFieldDescribedBy, officialLabel } = props.context;
const { operation } = toRefs(props);
const emit = defineEmits<{
  markSegmentMinuteDirty: [];
  createSegment: [];
  interruptSegment: [];
  markInterruptionMinuteDirty: [];
  assignOfficial: [];
  removeOfficial: [official: Official];
}>();
const markSegmentMinuteDirty = () => emit('markSegmentMinuteDirty');
const createSegment = () => emit('createSegment');
const interruptSegment = () => emit('interruptSegment');
const markInterruptionMinuteDirty = () => emit('markInterruptionMinuteDirty');
const assignOfficial = () => emit('assignOfficial');
const removeOfficial = (official: Official) => emit('removeOfficial', official);
</script>

<template>
<section class="panel panel-wide">
            <div class="panel-heading">
              <div><p class="eyebrow">01 · {{ t('match.matchReport') }}</p><h2>{{ t('match.prepareField') }}</h2></div>
              <span class="muted-note">{{ t('match.segments', { count: operation.segments.length }) }}</span>
            </div>
            <div class="sub-grid">
              <div class="soft-panel">
                <h3>{{ t('match.gameSegments') }}</h3>
                <div class="field-row">
                  <FormField :label="t('match.segmentNumber')" for-id="segment-number">
                    <template #default="{ id, ariaDescribedby }">
                      <input :id="id" v-model.number="segmentForm.segment_number" type="number" min="1" required :aria-describedby="ariaDescribedby" />
                    </template>
                  </FormField>
                  <FormField :label="t('match.startMinute')" for-id="segment-start-minute" :hint="segmentProposalHintText || undefined">
                    <template #default="{ id, ariaDescribedby }">
                      <input :id="id" v-model.number="segmentForm.minute_start" type="number" min="0" :max="resolutionLimits.maxMinute" required :aria-describedby="segmentProposalHintText ? 'segment-proposal-hint' : ariaDescribedby" @input="markSegmentMinuteDirty" />
                    </template>
                  </FormField>
                </div>
                <p v-if="segmentProposalHintText" id="segment-proposal-hint" class="field-hint" role="status">{{ segmentProposalHintText }}</p>
                  <label class="field">{{ t('match.activeSegment') }}
                   <select v-model="selectedSegmentId" required :aria-invalid="Boolean(eventFieldError('segment'))" :aria-describedby="eventFieldDescribedBy('segment')">
                     <option value="" disabled>{{ t('match.selectSegment') }}</option>
                     <option v-for="segment in operation.segments" :key="segment.id" :value="segment.id">{{ t('match.segmentOption', { number: segment.segment_number, minute: segment.minute_start }) }} · {{ statusLabel(segment.status) }}</option>
                   </select>
                   <small v-if="eventFieldError('segment')" :id="eventFieldErrorId('segment')" class="form-error" role="alert">{{ eventFieldError('segment') }}</small>
                 </label>
                 <div v-if="selectedSegment" class="segment-status">
                   <span class="muted-note">{{ t('match.segmentStatus') }}</span>
                   <strong>{{ statusLabel(selectedSegment.status) }}</strong>
                 </div>
                 <p v-if="!activeSegment" class="segment-warning">{{ t('match.noActiveSegment') }}</p>
                   <button v-if="canOperateMatch" class="button-primary" type="button" :disabled="Boolean(busyAction) || isTerminal" @click="createSegment">{{ activeSegment ? t('match.createSegment') : t('match.startNextSegment') }}</button>
                  <form v-if="canOperateMatch && activeSegment" class="interruption-form" @submit.prevent="interruptSegment">
                   <h3>{{ t('match.interruptSegment') }}</h3>
                   <p class="muted-note">{{ t('match.interruptionHint') }}</p>
                   <FormField :label="t('match.interruptReason')" for-id="interrupt-reason">
                     <template #default="{ id, ariaDescribedby }">
                       <select :id="id" v-model="interruptionForm.reason" :aria-describedby="ariaDescribedby"><option value="lighting_failure">{{ t('match.reasonLightingFailure') }}</option><option value="weather">{{ t('match.reasonWeather') }}</option><option value="pitch_invasion">{{ t('match.reasonPitchInvasion') }}</option><option value="other">{{ t('match.reasonOther') }}</option></select>
                     </template>
                   </FormField>
                   <FormField :label="t('match.interruptMinute')" for-id="interrupt-minute">
                     <template #default="{ id, ariaDescribedby }">
                       <input :id="id" v-model.number="interruptionForm.minute" type="number" min="0" :max="resolutionLimits.maxMinute" required :aria-describedby="ariaDescribedby" @input="markInterruptionMinuteDirty" />
                     </template>
                   </FormField>
                   <FormField :label="t('match.interruptNotes')" for-id="interrupt-notes">
                     <template #default="{ id, ariaDescribedby }">
                       <textarea :id="id" v-model="interruptionForm.notes" maxlength="1000" :placeholder="t('match.interruptNotesPlaceholder')" :aria-describedby="ariaDescribedby" />
                     </template>
                   </FormField>
                   <button class="button-secondary" type="submit" :disabled="Boolean(busyAction) || isTerminal">{{ busyAction === 'interrupt-segment' ? t('common.processing') : t('match.interruptSegment') }}</button>
                 </form>
                 <div v-if="selectedInterruption" class="interruption-note">
                   <strong>{{ t('match.interruptionRegistered') }}</strong>
                   <span>{{ t(`match.reason${selectedInterruption.reason === 'lighting_failure' ? 'LightingFailure' : selectedInterruption.reason === 'pitch_invasion' ? 'PitchInvasion' : selectedInterruption.reason === 'weather' ? 'Weather' : 'Other'}`) }} · {{ selectedInterruption.minute }}'</span>
                   <small v-if="selectedInterruption.notes">{{ selectedInterruption.notes }}</small>
                  </div>
                </div>

              <div class="soft-panel">
                <h3>{{ t('match.officials') }}</h3>
                <form v-if="canManageTournaments" class="field-row official-row" @submit.prevent="assignOfficial">
                  <label class="field">{{ t('match.person') }}<select v-model="officialForm.organization_user_id" required><option value="" disabled>{{ t('match.selectOfficial') }}</option><option v-for="official in operation.eligible_officials" :key="official.organization_user_id" :value="official.organization_user_id">{{ official.full_name }} · {{ official.email }}</option></select></label>
                  <label class="field">{{ t('match.role') }}<select v-model="officialForm.official_role"><option v-for="role in officialRoles" :key="role.value" :value="role.value">{{ t(role.labelKey) }}</option></select></label>
                  <button class="button-secondary compact-button" type="submit" :disabled="Boolean(busyAction) || isTerminal">{{ t('match.assign') }}</button>
                 </form>
                <ul v-if="operation.officials.length" class="compact-list">
                   <li v-for="official in operation.officials" :key="official.id"><span><strong>{{ officialLabel(official.official_role) }}</strong> · {{ official.full_name }}</span><button v-if="canManageTournaments" type="button" class="text-button" :disabled="Boolean(busyAction) || isTerminal" @click="removeOfficial(official)">{{ t('match.remove') }}</button></li>
                </ul>
                <p v-else class="muted-note">{{ t('match.noOfficials') }}</p>
              </div>
            </div>
          </section>
</template>

<style scoped src="./operation.css" />
