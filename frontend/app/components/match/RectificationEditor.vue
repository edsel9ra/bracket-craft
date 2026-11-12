<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import FormField from '~/components/ui/FormField.vue';
import { buildDraftEvent, visibleEventFields, type EventField } from '~/utils/matchEvents';
import { WALKOVER_REASONS, WALKOVER_REASON_LABEL_KEYS } from '~/utils/matchClose';
import { EVENT_LABEL_KEYS, RECTIFICATION_RESOLUTION_LABEL_KEYS, SCORE_FIELDS, reportProposal, rectificationErrorKey, type ReportVersion, type MatchOperation } from '~/utils/rectifications';
import type { DraftEvent } from './types';

const props = defineProps<{ matchId: string; version: ReportVersion }>();
const emit = defineEmits<{ submitted: []; cancel: [] }>();
const api = useMatchRectifications();
const { t } = useI18n();
const { confirm } = useConfirm({ singleFlight: true });
const draft = reactive(reportProposal(props.version.report));
const reason = ref(''); const evidence = ref(''); const error = ref(''); const busy = ref(false);
const operation = ref<MatchOperation | null>(null);
const prefix = useId();
const teams = computed(() => operation.value ? [
  { id: operation.value.match.home_team_id, name: operation.value.match.home_team_name },
  { id: operation.value.match.away_team_id, name: operation.value.match.away_team_name },
] : []);
const players = computed(() => operation.value?.rosters || []);
const playerFields = ['player', 'player_out', 'player_in', 'assist'] as const;
const playerKeys = { player: 'player_id', player_out: 'player_out_id', player_in: 'player_in_id', assist: 'assist_player_id' } as const;
const optionalPlayerFields: Record<EventField, string> = { player: 'rectification.player', player_out: 'rectification.playerOut', player_in: 'rectification.playerIn', assist: 'rectification.assist', beneficiary: 'rectification.beneficiary', red_card_type: 'rectification.redCardType' };
function fieldVisible(event: DraftEvent, field: EventField) { return visibleEventFields(event.event_type).includes(field); }
async function load() {
  error.value = '';
  try { operation.value = await api.operation(props.matchId); }
  catch (cause) { error.value = t(rectificationErrorKey(cause)); }
}
function addProposedEvent() {
  if (!globalThis.crypto?.randomUUID) { error.value = t('match.eventIdUnavailable'); return; }
  draft.events.push({ client_event_id: crypto.randomUUID(), event_type: 'goal', team_id: '', player_id: '',
    beneficiary_team_id: null, player_out_id: null, player_in_id: null, minute: 0, added_minute: 0, segment_id: operation.value?.segments[0]?.id || '', metadata: {} });
}
function move(index: number, delta: number) {
  const destination = index + delta;
  if (destination < 0 || destination >= draft.events.length) return;
  const row = draft.events.splice(index, 1)[0]!; draft.events.splice(destination, 0, row);
}
async function submit() {
  if (busy.value || !operation.value) return;
  error.value = '';
  const events = draft.events.map((event) => buildDraftEvent({ ...event, red_card_type: event.metadata?.red_card_type }, event.segment_id, event.client_event_id));
  if (!reason.value.trim() || !evidence.value.trim() || events.some((event) => !event)) { error.value = t('rectification.invalid'); return; }
  busy.value = true;
  try {
    if (!await confirm({ title: t('rectification.request'), message: t('rectification.submitWarning'), confirmLabel: t('rectification.submit') })) return;
    const body = reportProposal({ ...draft, reason: draft.reason?.trim() || null, events });
    await api.create(props.matchId, { proposed_report: body, reason: reason.value.trim(), evidence: evidence.value.trim() });
    emit('submitted');
  } catch (cause) { error.value = t(rectificationErrorKey(cause)); }
  finally { busy.value = false; }
}
async function cancel() {
  if (busy.value) return;
  if (await confirm({ title: t('confirm.discardChanges.title'), message: t('rectification.discardWarning'), confirmLabel: t('confirm.discardChanges.action'), tone: 'danger' })) emit('cancel');
}
onMounted(load);
</script>

<template>
  <form class="rectification-editor" @submit.prevent="submit">
    <h3>{{ t('rectification.request') }} · {{ t('rectification.version') }} {{ version.version_number }}</h3>
    <p>{{ t('rectification.immutable') }}</p>
    <p v-if="error" role="alert">{{ error }} <Button variant="secondary" @click="load">{{ t('common.retry') }}</Button></p>
    <fieldset :disabled="busy || !operation">
      <legend>{{ t('rectification.proposal') }}</legend>
      <label class="field">{{ t('match.resolution') }}<select v-model="draft.resolution_type"><option v-for="(key, value) in RECTIFICATION_RESOLUTION_LABEL_KEYS" :key="value" :value="value">{{ t(key) }}</option></select></label>
      <label v-if="draft.resolution_type === 'walkover'" class="field">{{ t('match.walkoverReason') }}<select v-model="draft.reason" required><option :value="null">—</option><option v-for="value in WALKOVER_REASONS" :key="value" :value="value">{{ t(WALKOVER_REASON_LABEL_KEYS[value]) }}</option></select></label>
      <label v-else class="field">{{ t('rectification.resolutionReason') }}<textarea v-model="draft.reason" :required="draft.resolution_type === 'administrative'" maxlength="1000" /></label>
      <div v-if="draft.resolution_type !== 'walkover'" class="score-grid"><label v-for="field in SCORE_FIELDS" :key="field" class="field">{{ t(`rectification.field.${field}`) }}<input v-model.number="draft[field]" type="number" min="0" step="1" :required="field === 'home_score_regular' || field === 'away_score_regular'"></label></div>
      <label class="field">{{ t('rectification.field.winner_team_id') }}<select v-model="draft.winner_team_id"><option :value="null">—</option><option v-for="team in teams" :key="team.id || ''" :value="team.id">{{ team.name }}</option></select></label>
      <h4>{{ t('rectification.events') }}</h4>
      <article v-for="(event, index) in draft.events" :key="event.client_event_id" class="event-editor">
        <h5>{{ t('rectification.event') }} {{ index + 1 }}</h5>
        <label class="field">{{ t('match.eventType') }}<select v-model="event.event_type"><option v-for="(key, type) in EVENT_LABEL_KEYS" :key="type" :value="type">{{ t(key) }}</option></select></label>
        <label class="field">{{ t('rectification.segment') }}<select v-model="event.segment_id" required><option v-for="segment in operation?.segments" :key="segment.id" :value="segment.id">{{ segment.segment_number }} · {{ segment.minute_start }}′</option></select></label>
        <label class="field">{{ t('rectification.team') }}<select v-model="event.team_id" required><option value="">—</option><option v-for="team in teams" :key="team.id || ''" :value="team.id">{{ team.name }}</option></select></label>
        <label class="field">{{ t('rectification.minute') }}<input v-model.number="event.minute" type="number" min="0" step="1" required></label>
        <label class="field">{{ t('rectification.addedMinute') }}<input v-model.number="event.added_minute" type="number" min="0" step="1" required></label>
        <template v-for="field in playerFields" :key="field"><label v-if="fieldVisible(event, field)" class="field">{{ t(optionalPlayerFields[field]) }}<select v-model="event[playerKeys[field]]" :required="field !== 'assist'"><option :value="null">—</option><option v-for="player in players.filter((row) => row.team_id === event.team_id)" :key="player.player_id" :value="player.player_id">{{ player.first_name }} {{ player.last_name }} · {{ player.dorsal_number }}</option></select></label></template>
        <label v-if="fieldVisible(event, 'beneficiary')" class="field">{{ t('rectification.beneficiary') }}<select v-model="event.beneficiary_team_id" required><option :value="null">—</option><option v-for="team in teams.filter((row) => row.id !== event.team_id)" :key="team.id || ''" :value="team.id">{{ team.name }}</option></select></label>
        <label v-if="fieldVisible(event, 'red_card_type')" class="field">{{ t('rectification.redCardType') }}<select :value="event.metadata?.red_card_type || 'direct_red'" @change="event.metadata = { red_card_type: ($event.target as HTMLSelectElement).value }"><option value="direct_red">{{ t('rectification.directRed') }}</option><option value="double_yellow_red">{{ t('rectification.doubleYellow') }}</option></select></label>
        <div class="actions"><Button variant="secondary" :disabled="index === 0" @click="move(index, -1)">{{ t('rectification.moveUp') }}</Button><Button variant="secondary" :disabled="index === draft.events.length - 1" @click="move(index, 1)">{{ t('rectification.moveDown') }}</Button><Button variant="danger" @click="draft.events.splice(index, 1)">{{ t('rectification.removeEvent') }}</Button></div>
      </article>
      <Button variant="secondary" @click="addProposedEvent">{{ t('rectification.addEvent') }}</Button>
      <FormField :for-id="`${prefix}-reason`" :label="t('rectification.reason')"><textarea :id="`${prefix}-reason`" v-model="reason" required /></FormField>
      <FormField :for-id="`${prefix}-evidence`" :label="t('rectification.evidence')" :hint="t('rectification.evidenceHint')"><textarea :id="`${prefix}-evidence`" v-model="evidence" required /></FormField>
      <Button type="submit" :busy="busy">{{ t('rectification.submit') }}</Button>
    </fieldset>
    <Button variant="secondary" :disabled="busy" @click="cancel">{{ t('common.cancel') }}</Button>
  </form>
</template>

<style scoped>
.rectification-editor, fieldset { display: grid; gap: var(--space-4); } fieldset { min-width: 0; border: 0; padding: 0; }
.score-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: var(--space-3); }
.event-editor { border: 1px solid var(--color-muted); padding: var(--space-4); border-radius: var(--radius-md); }
.actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
</style>
