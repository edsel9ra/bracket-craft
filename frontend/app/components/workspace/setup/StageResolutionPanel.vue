<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import {
  needsNewPreview, originLabel, previewReasonKey, resolutionErrorKey, stageAdvancementErrorCode,
  type ResolutionPreview, type SourceStage,
} from '~/utils/stageAdvancement';
import type { StageSummary } from './types';

const props = defineProps<{ tournamentId: string; stage: StageSummary; canManage: boolean }>();
const emit = defineEmits<{ resolved: [] }>();

const { t, errorMessage } = useI18n();
const { confirm } = useConfirm({ singleFlight: true });
const api = useStageAdvancement();
const uid = useId();

const preview = ref<ResolutionPreview | null>(null);
const sources = ref<SourceStage[]>([]);
const hasOrigins = ref(false);
const resolved = ref(false);
const loading = ref(true);
const busy = ref(false);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);

const unfinished = computed(() => (preview.value?.source_stages ?? []).filter((item) => !item.finished)
  .map((item) => sources.value.find((source) => source.id === item.id)?.name ?? item.id));

async function loadPreview() {
  try {
    preview.value = await api.preview(props.tournamentId, props.stage.id);
  } catch (cause) {
    const code = stageAdvancementErrorCode(cause);
    const key = resolutionErrorKey(code);
    if (code === 'already_resolved') resolved.value = true;
    else error.value = key ? t(key) : errorMessage(cause, t('stageAdvancement.noPreview'));
  }
}

async function reload() {
  loading.value = true;
  error.value = null;
  try {
    const state = await api.load(props.tournamentId, props.stage.id);
    sources.value = state.source_stages;
    hasOrigins.value = state.origins.length > 0;
    resolved.value = state.status === 'resolved';
    if (hasOrigins.value && !resolved.value) await loadPreview();
  } catch (cause) {
    error.value = errorMessage(cause, t('stageAdvancement.noLoad'));
  } finally {
    loading.value = false;
  }
}

async function refreshPreview() {
  busy.value = true;
  error.value = null;
  notice.value = null;
  await loadPreview();
  busy.value = false;
}

async function confirmFill() {
  const current = preview.value;
  if (!current?.resolvable) return;
  if (!(await confirm({
    title: t('stageAdvancement.confirmResolution.title'), message: t('stageAdvancement.confirmResolution.message'),
    confirmLabel: t('stageAdvancement.confirmResolution.action'),
  }))) return;
  busy.value = true;
  error.value = null;
  notice.value = null;
  try {
    preview.value = await api.confirmResolution(props.tournamentId, props.stage.id, current.fingerprint);
    resolved.value = true;
    notice.value = t('stageAdvancement.resolutionConfirmed');
    emit('resolved');
  } catch (cause) {
    const code = stageAdvancementErrorCode(cause);
    const key = resolutionErrorKey(code);
    error.value = key ? t(key) : errorMessage(cause, t('stageAdvancement.noConfirm'));
    if (code === 'already_resolved') resolved.value = true;
    if (needsNewPreview(code)) await loadPreview();
  } finally {
    busy.value = false;
  }
}

onMounted(reload);
</script>

<template>
  <section v-if="loading || hasOrigins || error" class="stage-resolution" :aria-labelledby="`${uid}-title`" :aria-busy="loading || busy">
    <h3 :id="`${uid}-title`">{{ t('stageAdvancement.resolutionTitle', { stage: stage.name }) }}</h3>
    <p v-if="loading" class="muted-note">{{ t('stageAdvancement.loading') }}</p>
    <p v-else-if="resolved" class="muted-note" role="status">{{ t('stageAdvancement.resolvedNote') }}</p>
    <template v-else-if="preview">
      <p v-if="unfinished.length" class="muted-note">{{ t('stageAdvancement.sourceUnfinished', { stages: unfinished.join(', ') }) }}</p>
      <table class="stage-resolution-table">
        <thead>
          <tr>
            <th scope="col">{{ t('stageAdvancement.slot') }}</th>
            <th scope="col">{{ t('stageAdvancement.originColumn') }}</th>
            <th scope="col">{{ t('stageAdvancement.teamColumn') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="slot in preview.slots" :key="slot.seed">
            <td>{{ slot.seed }}</td>
            <td>{{ originLabel(slot, sources, t) }}</td>
            <td>
              <span v-if="slot.team_name">{{ slot.team_name }}</span>
              <span v-if="slot.reason" class="stage-resolution-reason">{{ t(previewReasonKey(slot.reason)) }}</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="!preview.resolvable" class="muted-note">{{ t('stageAdvancement.notResolvable') }}</p>
      <div v-if="canManage" class="stage-resolution-actions">
        <Button variant="secondary" type="button" :disabled="busy" @click="refreshPreview">{{ t('stageAdvancement.refreshPreview') }}</Button>
        <Button variant="primary" type="button" :disabled="busy || !preview.resolvable" @click="confirmFill">{{ t('stageAdvancement.confirmFill') }}</Button>
      </div>
    </template>
    <p v-if="notice" class="muted-note" role="status">{{ notice }}</p>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.stage-resolution { display: grid; gap: var(--space-3); margin-top: var(--space-5); }
.stage-resolution-table { width: 100%; border-collapse: collapse; }
.stage-resolution-table th, .stage-resolution-table td { padding: var(--space-2); text-align: start; }
.stage-resolution-reason { display: block; color: var(--color-muted); }
.stage-resolution-actions { display: flex; flex-wrap: wrap; gap: var(--space-3); }
</style>
