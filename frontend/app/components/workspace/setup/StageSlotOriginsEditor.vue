<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import {
  MAX_SLOTS, MIN_SLOTS, emptyOrigin, originLabel, originsPayload, slotErrorKey, slotErrorsBySeed,
  slotsCountError, stageAdvancementErrorCode, type OriginKind, type SlotOrigin, type SlotOriginsState, type SourceStage,
} from '~/utils/stageAdvancement';
import type { StageSummary } from './types';

const props = defineProps<{ tournamentId: string; stage: StageSummary; canManage: boolean; hasMatches?: boolean }>();
const emit = defineEmits<{ saved: [] }>();

const { t, errorMessage } = useI18n();
const { confirm } = useConfirm({ singleFlight: true });
const api = useStageAdvancement();
const uid = useId();

const state = ref<SlotOriginsState | null>(null);
const draft = ref<SlotOrigin[]>([]);
const loading = ref(true);
const busy = ref(false);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);
const slotErrors = ref<Record<number, string>>({});
const templateSourceId = ref('');
const slotsCount = ref(4);
const startDate = ref('');
const roundIntervalDays = ref(7);
const matchIntervalHours = ref(2);

const editable = computed(() => props.canManage && state.value?.status === 'editable');
const sources = computed<SourceStage[]>(() => state.value?.source_stages ?? []);
const dirty = computed(() => JSON.stringify(originsPayload(draft.value)) !== JSON.stringify(originsPayload(state.value?.origins ?? [])));
const countError = computed(() => slotsCountError(draft.value.length, props.stage.stage_type));
const statusKey = computed(() => `stageAdvancement.status.${state.value?.status ?? 'editable'}`);

const sourceOf = (origin: SlotOrigin) => sources.value.find((item) => item.id === origin.source_stage_id);
const hasGroups = (origin: SlotOrigin) => Boolean(sourceOf(origin)?.groups.some((group) => group.id !== null));
const rowErrorId = (index: number) => `${uid}-slot-${index + 1}-error`;

function apply(next: SlotOriginsState) {
  state.value = next;
  draft.value = next.origins.map((origin) => ({ ...origin }));
  if (!templateSourceId.value && next.source_stages[0]) templateSourceId.value = next.source_stages[0].id;
  if (next.origins.length) slotsCount.value = next.origins.length;
}

async function reload() {
  loading.value = true;
  error.value = null;
  try {
    apply(await api.load(props.tournamentId, props.stage.id));
  } catch (cause) {
    error.value = errorMessage(cause, t('stageAdvancement.noLoad'));
  } finally {
    loading.value = false;
  }
}

function addSlot() {
  const source = sources.value[0];
  if (source && draft.value.length < MAX_SLOTS) draft.value = [...draft.value, emptyOrigin(source)];
}

function removeSlot(index: number) {
  draft.value = draft.value.filter((_, position) => position !== index);
  slotErrors.value = {};
}

function setKind(origin: SlotOrigin, kind: OriginKind) {
  origin.kind = kind;
  if (kind === 'best_of_position') {
    origin.group_id = null;
    origin.ordinal = origin.ordinal ?? 1;
  } else {
    origin.ordinal = null;
    origin.group_id = sourceOf(origin)?.groups[0]?.id ?? null;
  }
}

function setSource(origin: SlotOrigin, sourceId: string) {
  origin.source_stage_id = sourceId;
  if (origin.kind === 'group_position') origin.group_id = sourceOf(origin)?.groups[0]?.id ?? null;
}

async function applyTemplate() {
  const invalid = slotsCountError(slotsCount.value, props.stage.stage_type);
  if (invalid) {
    error.value = t(invalid);
    return;
  }
  if (!templateSourceId.value) return;
  busy.value = true;
  error.value = null;
  notice.value = null;
  try {
    draft.value = await api.template(props.tournamentId, props.stage.id, templateSourceId.value, slotsCount.value);
    slotErrors.value = {};
    notice.value = t('stageAdvancement.templateApplied');
  } catch (cause) {
    const code = stageAdvancementErrorCode(cause);
    error.value = code ? t(`stageAdvancement.templateError.${code}`) : errorMessage(cause, t('stageAdvancement.noTemplate'));
  } finally {
    busy.value = false;
  }
}

async function save() {
  if (countError.value) {
    error.value = t(countError.value);
    return;
  }
  if (!startDate.value) {
    error.value = t('setup.scheduleStartRequired');
    return;
  }
  const replaceExisting = Boolean(state.value?.origins.length) || props.hasMatches;
  if (replaceExisting && !(await confirm({
    title: t('stageAdvancement.confirmReplace.title'), message: t('stageAdvancement.confirmReplace.message'),
    confirmLabel: t('stageAdvancement.confirmReplace.action'), tone: 'danger',
  }))) return;
  busy.value = true;
  error.value = null;
  notice.value = null;
  slotErrors.value = {};
  try {
    apply(await api.save(props.tournamentId, props.stage.id, {
      origins: originsPayload(draft.value),
      start_date: new Date(startDate.value).toISOString(),
      round_interval_days: roundIntervalDays.value,
      match_interval_hours: matchIntervalHours.value,
      replace_existing: replaceExisting,
    }));
    notice.value = t('stageAdvancement.saved');
    emit('saved');
  } catch (cause) {
    slotErrors.value = slotErrorsBySeed(cause);
    error.value = Object.keys(slotErrors.value).length
      ? t('stageAdvancement.invalidOrigins')
      : errorMessage(cause, t('stageAdvancement.noSave'));
  } finally {
    busy.value = false;
  }
}

async function removeOrigins() {
  if (!(await confirm({
    title: t('stageAdvancement.confirmRemove.title'), message: t('stageAdvancement.confirmRemove.message'),
    confirmLabel: t('stageAdvancement.confirmRemove.action'), tone: 'danger',
  }))) return;
  busy.value = true;
  error.value = null;
  notice.value = null;
  try {
    await api.remove(props.tournamentId, props.stage.id);
    await reload();
    notice.value = t('stageAdvancement.removed');
    emit('saved');
  } catch (cause) {
    error.value = errorMessage(cause, t('stageAdvancement.noSave'));
  } finally {
    busy.value = false;
  }
}

onMounted(reload);
</script>

<template>
  <section class="slot-origins" :aria-labelledby="`${uid}-title`" :aria-busy="loading || busy">
    <div class="slot-origins-heading">
      <h3 :id="`${uid}-title`">{{ t('stageAdvancement.title', { stage: stage.name }) }}</h3>
      <span v-if="state" class="muted-note">{{ t(statusKey) }}</span>
    </div>
    <p class="field-hint">{{ t('stageAdvancement.description') }}</p>
    <p v-if="loading" class="muted-note">{{ t('stageAdvancement.loading') }}</p>
    <template v-else-if="state">
      <p v-if="!sources.length" class="muted-note">{{ t('stageAdvancement.noSources') }}</p>
      <template v-else-if="state.status === 'editable' && canManage">
        <div class="slot-origins-template">
          <label class="field">{{ t('stageAdvancement.templateSource') }}
            <select v-model="templateSourceId" :disabled="busy">
              <option v-for="source in sources" :key="source.id" :value="source.id">{{ source.name }}</option>
            </select>
          </label>
          <label class="field">{{ t('stageAdvancement.slotsCount') }}
            <input v-model.number="slotsCount" :disabled="busy" type="number" :min="MIN_SLOTS" :max="MAX_SLOTS" />
          </label>
          <Button variant="secondary" type="button" :disabled="busy" @click="applyTemplate">{{ t('stageAdvancement.useTemplate') }}</Button>
        </div>
        <ol class="slot-origins-list">
          <li v-for="(origin, index) in draft" :key="index" class="slot-origin-row">
            <span class="slot-origin-seed">{{ t('stageAdvancement.seed', { seed: index + 1 }) }}</span>
            <label class="field">{{ t('stageAdvancement.kind') }}
              <select :value="origin.kind" :disabled="busy" :aria-describedby="slotErrors[index + 1] ? rowErrorId(index) : undefined" :aria-invalid="slotErrors[index + 1] ? 'true' : undefined" @change="setKind(origin, ($event.target as HTMLSelectElement).value as OriginKind)">
                <option value="group_position">{{ t('stageAdvancement.kind.group_position') }}</option>
                <option value="best_of_position">{{ t('stageAdvancement.kind.best_of_position') }}</option>
              </select>
            </label>
            <label class="field">{{ t('stageAdvancement.source') }}
              <select :value="origin.source_stage_id" :disabled="busy" @change="setSource(origin, ($event.target as HTMLSelectElement).value)">
                <option v-for="source in sources" :key="source.id" :value="source.id">{{ source.name }}</option>
              </select>
            </label>
            <label v-if="origin.kind === 'group_position' && hasGroups(origin)" class="field">{{ t('stageAdvancement.group') }}
              <select v-model="origin.group_id" :disabled="busy">
                <option v-for="group in sourceOf(origin)?.groups ?? []" :key="group.id ?? ''" :value="group.id">{{ group.name }}</option>
              </select>
            </label>
            <label class="field">{{ t('stageAdvancement.position') }}
              <input v-model.number="origin.position" :disabled="busy" type="number" min="1" max="999" />
            </label>
            <label v-if="origin.kind === 'best_of_position'" class="field">{{ t('stageAdvancement.ordinal') }}
              <input v-model.number="origin.ordinal" :disabled="busy" type="number" min="1" max="999" />
            </label>
            <Button variant="ghost" type="button" :disabled="busy" :aria-label="t('stageAdvancement.removeSlot', { seed: index + 1 })" @click="removeSlot(index)">{{ t('stageAdvancement.removeSlotShort') }}</Button>
            <p v-if="slotErrors[index + 1]" :id="rowErrorId(index)" class="field-error">{{ t(slotErrorKey(slotErrors[index + 1]!)) }}</p>
          </li>
        </ol>
        <Button variant="secondary" type="button" :disabled="busy || draft.length >= MAX_SLOTS" @click="addSlot">{{ t('stageAdvancement.addSlot') }}</Button>
        <div class="schedule-generator-grid">
          <label class="field">{{ t('setup.generatorStart') }}<input v-model="startDate" :disabled="busy" type="datetime-local" /></label>
          <label class="field">{{ t('setup.generatorRoundInterval') }}<input v-model.number="roundIntervalDays" :disabled="busy" type="number" min="1" max="365" /></label>
          <label class="field">{{ t('setup.generatorMatchInterval') }}<input v-model.number="matchIntervalHours" :disabled="busy" type="number" min="1" max="168" /></label>
        </div>
        <p v-if="dirty" class="muted-note">{{ t('stageAdvancement.unsaved') }}</p>
        <div class="slot-origins-actions">
          <Button variant="primary" type="button" :disabled="busy || !draft.length" @click="save">{{ t('stageAdvancement.save') }}</Button>
          <Button v-if="state.origins.length" variant="ghost" type="button" :disabled="busy" @click="removeOrigins">{{ t('stageAdvancement.remove') }}</Button>
        </div>
      </template>
      <template v-else>
        <ol v-if="state.origins.length" class="slot-origins-list">
          <li v-for="origin in state.origins" :key="origin.seed">
            {{ t('stageAdvancement.seed', { seed: origin.seed ?? 0 }) }} · {{ originLabel(origin, sources, t) }}
          </li>
        </ol>
        <p v-else class="muted-note">{{ t('stageAdvancement.none') }}</p>
      </template>
    </template>
    <p v-if="notice" class="muted-note" role="status">{{ notice }}</p>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.slot-origins { display: grid; gap: var(--space-3); margin-top: var(--space-5); }
.slot-origins-heading { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: var(--space-2); }
.slot-origins-template, .slot-origins-actions { display: flex; flex-wrap: wrap; align-items: end; gap: var(--space-3); }
.slot-origins-list { display: grid; gap: var(--space-3); margin: 0; padding: 0; list-style: none; }
.slot-origin-row { display: flex; flex-wrap: wrap; align-items: end; gap: var(--space-3); }
.slot-origin-seed { min-width: 4rem; font-weight: 600; }
.slot-origin-row .field-error { flex-basis: 100%; margin: 0; }
</style>
