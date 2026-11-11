<script setup lang="ts">
import FormField from '~/components/ui/FormField.vue';
import { isEventFieldRequired } from '~/utils/matchEvents';
import type { MatchRecord, MatchOperation } from '~/components/match/types';

import type { MatchOperationContext } from '~/composables/useMatchOperation';

const props = defineProps<{ context: MatchOperationContext; operation: MatchOperation; match: MatchRecord }>();
const { t, draftEvents, draftRestored, draftDroppedEvents, eventForm, eventIdError, eventTypes, isTerminal, canOperateMatch, selectedSegmentIsActive, eventPlayers, eventOwnFields, eventTypeNotice, eventAssistCandidates, resolutionLimits, draftMinuteMessage, eventSubstitutionTeam, eventSubstitutionAvailability, eventSubstitutionCounters, eventOutgoingOptions, eventIncomingOptions, hasUnsavedDraft, substitutionMessage, eventFieldError, eventFieldErrorId, eventFieldDescribedBy, playerName, draftEventSummary, persistedEventSummary, teamName, eventLabel } = props.context;
const { operation, match } = toRefs(props);
const emit = defineEmits<{
  addEvent: [];
  removeEvent: [clientEventId: string];
  discardDraft: [];
}>();
const addEvent = () => emit('addEvent');
const removeEvent = (clientEventId: string) => emit('removeEvent', clientEventId);
const discardDraft = () => emit('discardDraft');
</script>

<template>
<section class="panel panel-wide" id="seccion-eventos" tabindex="-1">
             <div class="panel-heading">
               <div><p class="eyebrow">04 · {{ t('match.events') }}</p><h2>{{ t('match.buildReport') }}</h2></div>
               <div class="draft-status-group">
                 <span v-if="hasUnsavedDraft" class="draft-indicator" role="status">{{ draftRestored ? t('match.draftRestored') : t('match.unsavedDraft') }}</span>
                 <span class="muted-note">{{ t('match.pendingEvents', { count: draftEvents.length }) }}</span>
               </div>
             </div>
             <p v-if="draftDroppedEvents > 0" class="segment-warning" role="status">{{ t('match.draftEventsDropped', { count: draftDroppedEvents }) }}</p>
             <div v-if="canOperateMatch" class="event-form">
              <label class="field">{{ t('match.eventType') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="eventForm.event_type" required :aria-invalid="Boolean(eventFieldError('event_type'))" :aria-describedby="eventFieldDescribedBy('event_type')"><option v-for="event in eventTypes" :key="event.value" :value="event.value">{{ t(event.labelKey) }}</option></select><small v-if="eventFieldError('event_type')" :id="eventFieldErrorId('event_type')" class="form-error" role="alert">{{ eventFieldError('event_type') }}</small></label>
              <p class="field-hint full-width" role="status">{{ eventTypeNotice }}</p>
              <label class="field">{{ t('setup.teams') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="eventForm.team_id" required :aria-invalid="Boolean(eventFieldError('team'))" :aria-describedby="eventFieldDescribedBy('team')"><option value="" disabled>{{ t('match.select') }}</option><option v-if="match.home_team_id" :value="match.home_team_id">{{ match.home_team_name }}</option><option v-if="match.away_team_id" :value="match.away_team_id">{{ match.away_team_name }}</option></select><small v-if="eventFieldError('team')" :id="eventFieldErrorId('team')" class="form-error" role="alert">{{ eventFieldError('team') }}</small></label>
               <template v-if="eventOwnFields.includes('player_out')">
                  <label class="field">{{ t('match.playerOut') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="eventForm.player_out_id" :disabled="eventSubstitutionAvailability.disabled" :required="isEventFieldRequired(eventForm.event_type, 'player_out')" :aria-invalid="Boolean(eventFieldError('player_out'))" :aria-describedby="eventFieldDescribedBy('player_out')"><option value="" disabled>{{ t('match.select') }}</option><option v-for="row in eventOutgoingOptions" :key="`out-${row.player.roster_id}`" :value="row.player.player_id" :disabled="row.option.disabled">#{{ row.player.dorsal_number }} · {{ playerName(row.player) }}<template v-if="row.option.disabled"> · {{ substitutionMessage(row.option.reason) }}</template></option></select><small v-if="eventFieldError('player_out')" :id="eventFieldErrorId('player_out')" class="form-error" role="alert">{{ eventFieldError('player_out') }}</small></label>
                  <label class="field">{{ t('match.playerIn') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="eventForm.player_in_id" :disabled="eventSubstitutionAvailability.disabled" :required="isEventFieldRequired(eventForm.event_type, 'player_in')" :aria-invalid="Boolean(eventFieldError('player_in'))" :aria-describedby="eventFieldDescribedBy('player_in')"><option value="" disabled>{{ t('match.select') }}</option><option v-for="row in eventIncomingOptions" :key="`in-${row.player.roster_id}`" :value="row.player.player_id" :disabled="row.option.disabled">#{{ row.player.dorsal_number }} · {{ playerName(row.player) }}<template v-if="row.option.disabled"> · {{ substitutionMessage(row.option.reason) }}</template></option></select><small v-if="eventFieldError('player_in')" :id="eventFieldErrorId('player_in')" class="form-error" role="alert">{{ eventFieldError('player_in') }}</small></label>
                </template>
                <template v-else>
                  <label class="field">{{ t('match.player') }}<span v-if="isEventFieldRequired(eventForm.event_type, 'player')" class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="eventForm.player_id" :required="isEventFieldRequired(eventForm.event_type, 'player')" :aria-invalid="Boolean(eventFieldError('player'))" :aria-describedby="eventFieldDescribedBy('player')"><option value="" disabled>{{ t('match.select') }}</option><option v-for="player in eventPlayers" :key="player.roster_id" :value="player.player_id">#{{ player.dorsal_number }} · {{ playerName(player) }}</option></select><small v-if="eventFieldError('player')" :id="eventFieldErrorId('player')" class="form-error" role="alert">{{ eventFieldError('player') }}</small></label>
                  <label v-if="eventOwnFields.includes('beneficiary')">{{ t('match.beneficiary') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="eventForm.beneficiary_team_id" required :aria-invalid="Boolean(eventFieldError('beneficiary'))" :aria-describedby="eventFieldDescribedBy('beneficiary')"><option value="" disabled>{{ t('match.select') }}</option><option v-if="match.home_team_id && match.home_team_id !== eventForm.team_id" :value="match.home_team_id">{{ match.home_team_name }}</option><option v-if="match.away_team_id && match.away_team_id !== eventForm.team_id" :value="match.away_team_id">{{ match.away_team_name }}</option></select><small v-if="eventFieldError('beneficiary')" :id="eventFieldErrorId('beneficiary')" class="form-error" role="alert">{{ eventFieldError('beneficiary') }}</small></label>
                  <label v-if="eventOwnFields.includes('assist')">{{ t('match.assist') }}<select v-model="eventForm.assist_player_id" :aria-invalid="Boolean(eventFieldError('assist'))" :aria-describedby="eventFieldDescribedBy('assist')"><option value="">{{ t('match.assistNone') }}</option><option v-for="player in eventAssistCandidates" :key="`assist-${player.roster_id}`" :value="player.player_id">#{{ player.dorsal_number }} · {{ playerName(player) }}</option></select><small v-if="eventFieldError('assist')" :id="eventFieldErrorId('assist')" class="form-error" role="alert">{{ eventFieldError('assist') }}</small></label>
                </template>
               <label v-if="eventOwnFields.includes('red_card_type')">{{ t('match.redCardType') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="eventForm.red_card_type" :required="isEventFieldRequired(eventForm.event_type, 'red_card_type')" :aria-invalid="Boolean(eventFieldError('red_card_type'))" :aria-describedby="eventFieldDescribedBy('red_card_type')"><option value="direct_red">{{ t('match.directRed') }}</option><option value="double_yellow_red">{{ t('match.doubleYellowRed') }}</option></select><small v-if="eventFieldError('red_card_type')" :id="eventFieldErrorId('red_card_type')" class="form-error" role="alert">{{ eventFieldError('red_card_type') }}</small></label>
               <label class="field">{{ t('match.minute') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><input v-model.number="eventForm.minute" type="number" min="0" :max="resolutionLimits.maxMinute" required :aria-invalid="Boolean(eventFieldError('minute'))" :aria-describedby="eventFieldDescribedBy('minute')" /><small v-if="eventFieldError('minute')" :id="eventFieldErrorId('minute')" class="form-error" role="alert">{{ eventFieldError('minute') }}</small></label>
              <FormField :label="t('match.addedMinute')" for-id="event-added-minute" :error="eventFieldError('added_minute') || null">
                <template #default="{ id, ariaDescribedby, ariaInvalid }">
                  <input :id="id" v-model.number="eventForm.added_minute" type="number" min="0" :max="resolutionLimits.addedMax" :aria-invalid="ariaInvalid ? true : undefined" :aria-describedby="ariaDescribedby" />
                </template>
              </FormField>
              <p v-if="eventForm.event_type === 'goal'" class="field-hint" role="status">{{ t('match.assistHint') }}</p>
              <p v-else-if="eventForm.event_type === 'foul'" class="field-hint" role="status">{{ t('match.foulInformative') }}</p>
                <div v-if="eventForm.event_type === 'substitution'" class="substitution-preview" role="status">
                  <strong>{{ t('match.substitutionPreview') }}</strong>
                  <span>{{ t('match.substitutionsRemaining', { used: eventSubstitutionCounters.substitutions_used, max: eventSubstitutionTeam?.max_per_team ?? 0 }) }}</span>
                  <span>{{ t('match.windowsRemaining', { used: eventSubstitutionCounters.windows_used, max: eventSubstitutionTeam?.max_windows ?? 0 }) }}</span>
                  <span v-if="eventSubstitutionAvailability.disabled || !eventSubstitutionCounters.can_register" class="substitution-blocked">{{ substitutionMessage(eventSubstitutionAvailability.reason || 'exhausted') }}</span>
                </div>
                <button class="button-secondary" type="button" :disabled="isTerminal || !selectedSegmentIsActive || (eventForm.event_type === 'substitution' && (eventSubstitutionAvailability.disabled || !eventSubstitutionCounters.can_register))" @click="addEvent">{{ t('match.addEvent') }}</button>
                <p v-if="eventIdError" class="form-error event-id-error" role="alert">{{ eventIdError }}</p>
            </div>
              <p v-if="draftMinuteMessage" class="segment-warning" role="alert">{{ draftMinuteMessage }}</p>
              <ul v-if="draftEvents.length" class="event-list">
                <li v-for="event in draftEvents" :key="event.client_event_id"><span><strong>{{ event.minute }}' · {{ eventLabel(event.event_type) }}</strong> · {{ teamName(event.team_id) }} · {{ draftEventSummary(event) }}</span><button v-if="canOperateMatch" type="button" class="text-button" @click="removeEvent(event.client_event_id)">{{ t('match.remove') }}</button></li>
             </ul>
              <button v-if="canOperateMatch && hasUnsavedDraft" class="text-button draft-discard" type="button" @click="discardDraft">{{ t('match.discardDraft') }}</button>
             <ul v-if="!draftEvents.length && operation.events.length" class="event-list persisted-events">
               <li v-for="event in operation.events" :key="event.id"><span><strong>{{ event.minute }}' · {{ eventLabel(event.event_type) }}</strong> · {{ event.team_name }} · {{ persistedEventSummary(event) }}</span><small>{{ event.is_voided ? t('match.voided') : t('match.confirmed') }}</small></li>
            </ul>
              <p v-else-if="!draftEvents.length" class="muted-note">{{ t('match.eventsAtomic') }}</p>
          </section>
</template>

<style scoped src="./operation.css" />
