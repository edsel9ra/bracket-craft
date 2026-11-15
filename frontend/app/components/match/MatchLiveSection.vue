<script setup lang="ts">
import FormField from '~/components/ui/FormField.vue';
import type { MatchRecord } from '~/components/match/types';
import type { MatchOperationContext } from '~/composables/useMatchOperation';
import type { SharedLiveEvent } from '~/utils/matchLiveEditor';

const props = defineProps<{ context: MatchOperationContext; match: MatchRecord }>();
const { t, liveView, liveEditor, liveTransitions, liveCapture, liveEdit, liveClock, liveReview, liveClose } = props.context;
const { match } = toRefs(props);

const EVENT_TYPE_OPTIONS = ['goal', 'own_goal', 'penalty_goal', 'yellow_card', 'red_card', 'substitution', 'foul'] as const;
const RESOLUTION_OPTIONS = ['regular', 'extra_time', 'penalties', 'walkover', 'administrative'] as const;
const RED_CARD_OPTIONS = ['direct_red', 'double_yellow_red'] as const;
const liveOutcome = ref('');

const shared = computed(() => liveEditor.shared);
const pending = computed(() => liveEditor.pending);
const receipt = computed(() => liveReview.currentReceipt());
const clock = computed(() => shared.value?.clock ?? null);
const editing = computed(() => liveEdit.editing());
const segmentId = computed(() => clock.value?.segmentId ?? '');

const captureForm = reactive({
  event_type: 'goal', team_id: '', player_id: '', minute: null as number | null,
  added_minute: 0, beneficiary_team_id: '', player_out_id: '', player_in_id: '',
  assist_player_id: '', red_card_type: 'direct_red',
});
const editForm = reactive({ minute: null as number | null, added_minute: 0 });
const reviewForm = reactive({
  resolution_type: 'regular', home_score_regular: null as number | null,
  away_score_regular: null as number | null, home_score: null as number | null,
  away_score: null as number | null, home_penalties: null as number | null,
  away_penalties: null as number | null, winner_team_id: '', reason: '',
});

const uuidOrNull = (value: string) => value.trim() === '' ? null : value.trim();

async function runOutcome(promise: Promise<string>) {
  liveOutcome.value = await promise;
}

const startLive = () => runOutcome(liveTransitions.start());
const suspendLive = () => runOutcome(liveTransitions.suspend());
const resumeLive = () => runOutcome(liveTransitions.resume());
const startClock = () => runOutcome(liveClock.startClock(segmentId.value));
const pauseClock = () => runOutcome(liveClock.pauseClock());
const resumeClock = () => runOutcome(liveClock.resumeClock());

function captureSubmit() {
  runOutcome(liveCapture.capture({
    client_event_id: crypto.randomUUID(),
    event_type: captureForm.event_type,
    team_id: captureForm.team_id,
    beneficiary_team_id: uuidOrNull(captureForm.beneficiary_team_id),
    player_id: captureForm.player_id,
    player_out_id: uuidOrNull(captureForm.player_out_id),
    player_in_id: uuidOrNull(captureForm.player_in_id),
    assist_player_id: uuidOrNull(captureForm.assist_player_id),
    minute: captureForm.minute,
    added_minute: captureForm.added_minute,
    segment_id: segmentId.value,
    metadata: captureForm.event_type === 'red_card' ? { red_card_type: captureForm.red_card_type } : null,
  }));
}

function eventLabel(event: SharedLiveEvent): string {
  return `${t(`live.eventType.${event.eventType}`)} · ${event.minute}'`;
}
function editingEvent(): SharedLiveEvent | null {
  const session = editing.value;
  if (!session || !shared.value) return null;
  return shared.value.events.find((event) => event.clientEventId === session.eventId) ?? null;
}
function beginCorrect(event: SharedLiveEvent) {
  liveOutcome.value = '';
  const result = liveEdit.beginEdit(event.clientEventId);
  if (result !== 'ok') { liveOutcome.value = result; return; }
  editForm.minute = event.minute;
  editForm.added_minute = event.addedMinute;
}
function saveCorrect() {
  const event = editingEvent();
  if (event === null) { liveOutcome.value = 'missing'; return; }
  runOutcome(liveEdit.saveEdit({
    client_event_id: crypto.randomUUID(),
    event_type: event.eventType, team_id: event.teamId,
    beneficiary_team_id: event.beneficiaryTeamId, player_id: event.playerId,
    player_out_id: event.playerOutId, player_in_id: event.playerInId,
    assist_player_id: event.assistPlayerId,
    minute: editForm.minute, added_minute: editForm.added_minute,
    segment_id: event.segmentId, metadata: event.metadata,
  }));
}
const cancelCorrect = () => liveEdit.cancelEdit();
const removeFact = (event: SharedLiveEvent) => runOutcome(liveEdit.removeFact(event.clientEventId));

function beginReview() {
  runOutcome(liveReview.beginReview({
    resolution_type: reviewForm.resolution_type,
    home_score_regular: reviewForm.home_score_regular,
    away_score_regular: reviewForm.away_score_regular,
    home_score: reviewForm.home_score,
    away_score: reviewForm.away_score,
    home_penalties: reviewForm.home_penalties,
    away_penalties: reviewForm.away_penalties,
    winner_team_id: uuidOrNull(reviewForm.winner_team_id),
    reason: reviewForm.reason === '' ? null : reviewForm.reason,
  }));
}
const confirmClose = () => runOutcome(liveClose.confirmClose());
const outcomeKey = computed(() => liveOutcome.value === '' ? '' : `live.outcome.${liveOutcome.value}`);
</script>

<template>
  <section v-if="liveView.detailVisible" class="panel live-panel" id="seccion-en-vivo" tabindex="-1">
    <div class="panel-heading">
      <div><p class="eyebrow">{{ t('live.section.eyebrow') }}</p><h2>{{ t('live.section.title') }}</h2></div>
      <span v-if="shared" class="muted-note">{{ t(`live.status.${shared.status}`) }} · {{ shared.homeScore }}–{{ shared.awayScore }}</span>
    </div>

    <p v-if="outcomeKey" class="muted-note live-outcome" role="status">{{ t(outcomeKey) }}</p>

    <div v-if="shared === null && liveView.controlsEnabled" class="live-actions">
      <button class="button-primary" type="button" :disabled="liveTransitions.inFlight" @click="startLive">{{ t('live.transition.start.action') }}</button>
    </div>

    <template v-if="shared">
      <div class="live-clock muted-note" role="status">
        {{ t('live.clock.state') }}: {{ t(`live.clock.${clock?.state ?? 'not_started'}`) }}<template v-if="clock?.elapsedUs !== null && clock?.elapsedUs !== undefined"> · {{ t('live.clock.elapsed', { seconds: Math.floor(clock.elapsedUs / 1_000_000) }) }}</template>
      </div>
      <div v-if="liveView.controlsEnabled" class="live-actions">
        <button v-if="shared.status === 'live'" class="button-secondary" type="button" :disabled="liveTransitions.inFlight" @click="suspendLive">{{ t('live.transition.suspend.action') }}</button>
        <button v-if="shared.status === 'suspended'" class="button-secondary" type="button" :disabled="liveTransitions.inFlight" @click="resumeLive">{{ t('live.transition.resume.action') }}</button>
        <button v-if="shared.status === 'live' && clock?.state === 'not_started'" class="button-secondary" type="button" :disabled="liveClock.inFlight || !segmentId" @click="startClock">{{ t('live.clock.start') }}</button>
        <button v-if="clock?.state === 'running'" class="button-secondary" type="button" :disabled="liveClock.inFlight" @click="pauseClock">{{ t('live.clock.pause') }}</button>
        <button v-if="clock?.state === 'paused'" class="button-secondary" type="button" :disabled="liveClock.inFlight" @click="resumeClock">{{ t('live.clock.resume') }}</button>
      </div>

      <ul v-if="shared.events.length || pending.length" class="live-events">
        <li v-for="event in shared.events" :key="event.clientEventId" class="live-event">
          <span>{{ eventLabel(event) }}</span>
          <template v-if="liveView.controlsEnabled && shared.status === 'live'">
            <button class="button-secondary" type="button" @click="beginCorrect(event)">{{ t('live.editCorrect.action') }}</button>
            <button class="button-secondary" type="button" @click="removeFact(event)">{{ t('live.editRemove.action') }}</button>
          </template>
          <template v-if="editing && editing.eventId === event.clientEventId">
            <p v-if="editing.stale || editing.removed" class="form-error" role="alert">{{ t('live.edit.stale') }}</p>
            <FormField :label="t('live.capture.minute')" for-id="live-edit-minute"><template #default="{ id, ariaDescribedby }"><input :id="id" v-model.number="editForm.minute" type="number" min="0" max="180" :aria-describedby="ariaDescribedby" /></template></FormField>
            <FormField :label="t('live.capture.addedMinute')" for-id="live-edit-added"><template #default="{ id, ariaDescribedby }"><input :id="id" v-model.number="editForm.added_minute" type="number" min="0" max="30" :aria-describedby="ariaDescribedby" /></template></FormField>
            <button class="button-primary" type="button" :disabled="editing.stale || editing.removed" @click="saveCorrect">{{ t('live.editCorrect.action') }}</button>
            <button class="button-secondary" type="button" @click="cancelCorrect">{{ t('live.edit.cancel') }}</button>
          </template>
        </li>
        <li v-for="event in pending" :key="`pending-${event.clientEventId}`" class="live-event live-event-pending">
          <span>{{ t(`live.eventType.${event.eventType}`) }} · {{ event.minute }}' — {{ t('live.event.pending') }}</span>
        </li>
      </ul>

      <form v-if="liveView.controlsEnabled && shared.status === 'live'" class="live-capture" @submit.prevent="captureSubmit">
        <p class="eyebrow">{{ t('live.capture.title') }}</p>
        <div class="live-capture-grid">
          <FormField :label="t('live.capture.eventType')" for-id="live-capture-type"><template #default="{ id }"><select :id="id" v-model="captureForm.event_type"><option v-for="option in EVENT_TYPE_OPTIONS" :key="option" :value="option">{{ t(`live.eventType.${option}`) }}</option></select></template></FormField>
          <FormField :label="t('live.capture.team')" for-id="live-capture-team"><template #default="{ id }"><select :id="id" v-model="captureForm.team_id"><option value="" disabled>{{ t('live.capture.selectTeam') }}</option><option v-if="match.home_team_id" :value="match.home_team_id">{{ match.home_team_name }}</option><option v-if="match.away_team_id" :value="match.away_team_id">{{ match.away_team_name }}</option></select></template></FormField>
          <FormField :label="t('live.capture.player')" for-id="live-capture-player"><template #default="{ id, ariaDescribedby }"><input :id="id" v-model="captureForm.player_id" type="text" :aria-describedby="ariaDescribedby" /></template></FormField>
          <FormField :label="t('live.capture.minute')" for-id="live-capture-minute"><template #default="{ id, ariaDescribedby }"><input :id="id" v-model.number="captureForm.minute" type="number" min="0" max="180" :aria-describedby="ariaDescribedby" /></template></FormField>
          <FormField :label="t('live.capture.addedMinute')" for-id="live-capture-added"><template #default="{ id, ariaDescribedby }"><input :id="id" v-model.number="captureForm.added_minute" type="number" min="0" max="30" :aria-describedby="ariaDescribedby" /></template></FormField>
          <FormField v-if="captureForm.event_type === 'red_card'" :label="t('live.capture.redCardType')" for-id="live-capture-red"><template #default="{ id }"><select :id="id" v-model="captureForm.red_card_type"><option v-for="option in RED_CARD_OPTIONS" :key="option" :value="option">{{ t(`live.redCardType.${option}`) }}</option></select></template></FormField>
        </div>
        <button class="button-primary" type="submit" :disabled="liveCapture.inFlight">{{ t('live.capture.submit') }}</button>
      </form>

      <form v-if="liveView.closeEnabled" class="live-review" @submit.prevent="beginReview">
        <p class="eyebrow">{{ t('live.review.title') }}</p>
        <div class="live-capture-grid">
          <FormField :label="t('live.review.resolution')" for-id="live-review-resolution"><template #default="{ id }"><select :id="id" v-model="reviewForm.resolution_type"><option v-for="option in RESOLUTION_OPTIONS" :key="option" :value="option">{{ t(`live.resolution.${option}`) }}</option></select></template></FormField>
          <FormField :label="`${match.home_team_name} · ${t('live.review.regularScore')}`" for-id="live-review-hr"><template #default="{ id, ariaDescribedby }"><input :id="id" v-model.number="reviewForm.home_score_regular" type="number" min="0" :aria-describedby="ariaDescribedby" /></template></FormField>
          <FormField :label="`${match.away_team_name} · ${t('live.review.regularScore')}`" for-id="live-review-ar"><template #default="{ id, ariaDescribedby }"><input :id="id" v-model.number="reviewForm.away_score_regular" type="number" min="0" :aria-describedby="ariaDescribedby" /></template></FormField>
          <template v-if="reviewForm.resolution_type !== 'regular'">
            <FormField :label="`${match.home_team_name} · ${t('live.review.finalScore')}`" for-id="live-review-hf"><template #default="{ id, ariaDescribedby }"><input :id="id" v-model.number="reviewForm.home_score" type="number" min="0" :aria-describedby="ariaDescribedby" /></template></FormField>
            <FormField :label="`${match.away_team_name} · ${t('live.review.finalScore')}`" for-id="live-review-af"><template #default="{ id, ariaDescribedby }"><input :id="id" v-model.number="reviewForm.away_score" type="number" min="0" :aria-describedby="ariaDescribedby" /></template></FormField>
          </template>
          <template v-if="reviewForm.resolution_type === 'penalties'">
            <FormField :label="t('live.review.homePenalties')" for-id="live-review-hp"><template #default="{ id, ariaDescribedby }"><input :id="id" v-model.number="reviewForm.home_penalties" type="number" min="0" :aria-describedby="ariaDescribedby" /></template></FormField>
            <FormField :label="t('live.review.awayPenalties')" for-id="live-review-ap"><template #default="{ id, ariaDescribedby }"><input :id="id" v-model.number="reviewForm.away_penalties" type="number" min="0" :aria-describedby="ariaDescribedby" /></template></FormField>
          </template>
          <FormField v-if="reviewForm.resolution_type !== 'regular'" :label="t('live.review.winner')" for-id="live-review-winner"><template #default="{ id }"><select :id="id" v-model="reviewForm.winner_team_id"><option value="" disabled>{{ t('live.capture.selectTeam') }}</option><option v-if="match.home_team_id" :value="match.home_team_id">{{ match.home_team_name }}</option><option v-if="match.away_team_id" :value="match.away_team_id">{{ match.away_team_name }}</option></select></template></FormField>
          <FormField :label="t('live.review.reason')" for-id="live-review-reason"><template #default="{ id, ariaDescribedby }"><input :id="id" v-model="reviewForm.reason" type="text" maxlength="1000" :aria-describedby="ariaDescribedby" /></template></FormField>
        </div>
        <button class="button-secondary" type="submit" :disabled="liveReview.inFlight">{{ t('live.review.submit') }}</button>
        <p v-if="receipt" class="muted-note" role="status">{{ liveReview.receiptValid() ? t('live.review.receiptValid', { revision: receipt.contentRevision }) : t('live.review.receiptStale') }}</p>
        <button v-if="receipt" class="button-primary" type="button" :disabled="liveClose.inFlight || !liveReview.receiptValid()" @click="confirmClose">{{ t('live.closeConfirm.action') }}</button>
      </form>
    </template>
  </section>
</template>
