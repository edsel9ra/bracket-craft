<script setup lang="ts">
import {
  DEFAULT_RULES_CONFIG,
  RANKING_CRITERIA,
  RULES_VALIDATION_MESSAGE_KEYS,
  cloneRulesConfig,
  isRankingCriterion,
  normalizeRulesConfig,
  parseRulesConfigJson,
  recalculatePipeline,
  serializeRulesConfig,
  type RankingCriterion,
  type RulesConfig,
  type RulesValidationError,
  type StageOverride,
} from '~/utils/rulesConfig';

interface StageOption {
  id: string;
  name: string;
  stage_order?: number;
}

const props = withDefaults(defineProps<{
  modelValue?: RulesConfig | null;
  stages?: StageOption[];
  disabled?: boolean;
}>(), {
  modelValue: null,
  stages: () => [],
  disabled: false,
});

const emit = defineEmits<{
  'update:modelValue': [value: RulesConfig];
}>();

const { t } = useI18n();
const config = ref<RulesConfig>(normalizeRulesConfig(props.modelValue || DEFAULT_RULES_CONFIG));
const advancedJson = ref(serializeRulesConfig(config.value));
const advancedError = ref('');
const validationErrors = ref<RulesValidationError[]>([]);
const showAdvanced = ref(false);

const availableCriteria = computed(() => {
  const used = new Set(config.value.ranking_pipeline.map((item) => item.criterion));
  return RANKING_CRITERIA.filter((criterion) => !used.has(criterion));
});

watch(() => props.modelValue, (value) => {
  const next = normalizeRulesConfig(value || DEFAULT_RULES_CONFIG);
  if (JSON.stringify(next) === JSON.stringify(config.value)) return;
  config.value = next;
  advancedJson.value = serializeRulesConfig(next);
  advancedError.value = '';
  validationErrors.value = [];
}, { deep: true });

function commitConfig(next: RulesConfig = config.value) {
  config.value = normalizeRulesConfig(next);
  advancedJson.value = serializeRulesConfig(config.value);
  advancedError.value = '';
  validationErrors.value = [];
  emit('update:modelValue', cloneRulesConfig(config.value));
}

function criterionOptions(index: number): RankingCriterion[] {
  const selected = config.value.ranking_pipeline[index]?.criterion;
  const used = new Set(config.value.ranking_pipeline.map((item) => item.criterion));
  return RANKING_CRITERIA.filter((criterion) => criterion === selected || !used.has(criterion));
}

function setCriterion(index: number, event: Event) {
  const value = (event.target as HTMLSelectElement).value;
  if (!isRankingCriterion(value) || !config.value.ranking_pipeline[index]) return;
  config.value.ranking_pipeline[index] = {
    ...config.value.ranking_pipeline[index],
    criterion: value,
    params: value === 'head_to_head' ? { total_rounds_expected: 1 } : {},
  };
  commitConfig(config.value);
}

function setHeadToHeadRounds(index: number, event: Event) {
  const value = Number((event.target as HTMLInputElement).value);
  if (!config.value.ranking_pipeline[index] || !Number.isFinite(value)) return;
  config.value.ranking_pipeline[index].params = { total_rounds_expected: value <= 1 ? 1 : 2 };
  commitConfig(config.value);
}

function addPipelineStep() {
  const criterion = availableCriteria.value[0];
  if (!criterion) return;
  config.value.ranking_pipeline = recalculatePipeline([
    ...config.value.ranking_pipeline,
    { criterion, params: criterion === 'head_to_head' ? { total_rounds_expected: 1 } : {} },
  ]);
  commitConfig(config.value);
}

function removePipelineStep(index: number) {
  if (index === 0 || config.value.ranking_pipeline.length <= 1) return;
  config.value.ranking_pipeline.splice(index, 1);
  config.value.ranking_pipeline = recalculatePipeline(config.value.ranking_pipeline);
  commitConfig(config.value);
}

function canMovePipelineStep(index: number, direction: -1 | 1): boolean {
  if (props.disabled) return false;
  const target = index + direction;
  if (index <= 0 || target <= 0 || target >= config.value.ranking_pipeline.length) return false;
  const item = config.value.ranking_pipeline[index];
  const targetItem = config.value.ranking_pipeline[target];
  if (item?.criterion === 'random_draw' && direction < 0) return false;
  if (targetItem?.criterion === 'random_draw' && direction > 0) return false;
  return true;
}

function movePipelineStep(index: number, direction: -1 | 1) {
  if (!canMovePipelineStep(index, direction)) return;
  const target = index + direction;
  const pipeline = [...config.value.ranking_pipeline];
  [pipeline[index], pipeline[target]] = [pipeline[target], pipeline[index]];
  config.value.ranking_pipeline = recalculatePipeline(pipeline);
  commitConfig(config.value);
}

function commitVisualChange() {
  commitConfig(config.value);
}

function applyAdvancedJson() {
  const result = parseRulesConfigJson(advancedJson.value);
  if (result.errors.length || !result.config) {
    validationErrors.value = result.errors;
    advancedError.value = t(RULES_VALIDATION_MESSAGE_KEYS[result.errors[0]?.code || 'invalid_json']);
    return;
  }
  commitConfig(result.config);
}

function overrideFor(stageId: string): StageOverride | undefined {
  return config.value.stage_overrides[stageId];
}

function ensureOverride(stageId: string): StageOverride {
  const existing = overrideFor(stageId);
  if (existing) return existing;
  const defaults = config.value.stage_defaults;
  const created: StageOverride = {
    extra_time_enabled: defaults.extra_time_enabled,
    penalties_enabled: defaults.penalties_enabled,
    walkover_score: cloneRulesConfig(defaults.walkover_score),
  };
  config.value.stage_overrides[stageId] = created;
  return created;
}

function toggleOverride(stageId: string, event: Event) {
  const enabled = (event.target as HTMLInputElement).checked;
  if (enabled) ensureOverride(stageId);
  else delete config.value.stage_overrides[stageId];
  commitConfig(config.value);
}

function overrideBoolean(stageId: string, field: 'extra_time_enabled' | 'penalties_enabled'): boolean {
  const value = overrideFor(stageId)?.[field];
  return typeof value === 'boolean' ? value : config.value.stage_defaults[field];
}

function setOverrideBoolean(stageId: string, field: 'extra_time_enabled' | 'penalties_enabled', event: Event) {
  const override = ensureOverride(stageId);
  override[field] = (event.target as HTMLInputElement).checked;
  commitConfig(config.value);
}

function overrideScore(stageId: string, field: 'winner' | 'loser'): number {
  const value = overrideFor(stageId)?.walkover_score?.[field];
  return typeof value === 'number' ? value : config.value.stage_defaults.walkover_score[field];
}

function setOverrideScore(stageId: string, field: 'winner' | 'loser', event: Event) {
  const override = ensureOverride(stageId);
  const value = Number((event.target as HTMLInputElement).value);
  const score = Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
  const current = override.walkover_score || cloneRulesConfig(config.value.stage_defaults.walkover_score);
  override.walkover_score = { ...current, [field]: score };
  commitConfig(config.value);
}

function removeOverride(stageId: string) {
  delete config.value.stage_overrides[stageId];
  commitConfig(config.value);
}
</script>

<template>
  <div class="rules-editor">
    <div class="editor-mode" role="tablist" :aria-label="t('rules.editorMode')">
      <button
        class="mode-button"
        :class="{ active: !showAdvanced }"
        type="button"
        role="tab"
        :aria-selected="!showAdvanced"
        @click="showAdvanced = false"
      >{{ t('rules.visualMode') }}</button>
      <button
        class="mode-button"
        :class="{ active: showAdvanced }"
        type="button"
        role="tab"
        :aria-selected="showAdvanced"
        @click="showAdvanced = true"
      >{{ t('rules.jsonMode') }}</button>
    </div>

    <p class="editor-description">{{ t(showAdvanced ? 'rules.jsonDescription' : 'rules.visualDescription') }}</p>

    <div v-if="!showAdvanced" class="rules-visual" @change="commitVisualChange">
      <fieldset :disabled="disabled">
        <section class="editor-section">
          <div class="section-heading">
            <div><p class="eyebrow">01</p><h3>{{ t('rules.pointsSection') }}</h3></div>
            <p>{{ t('rules.pointsDescription') }}</p>
          </div>
          <div class="field-grid field-grid-three">
            <label>{{ t('rules.winPoints') }}<input v-model.number="config.points_system.win" type="number" min="0" /></label>
            <label>{{ t('rules.drawPoints') }}<input v-model.number="config.points_system.draw" type="number" min="0" /></label>
            <label>{{ t('rules.lossPoints') }}<input v-model.number="config.points_system.loss" type="number" min="0" /></label>
          </div>
        </section>

        <section class="editor-section">
          <div class="section-heading">
            <div><p class="eyebrow">02</p><h3>{{ t('rules.pipelineSection') }}</h3></div>
            <p>{{ t('rules.pipelineDescription') }}</p>
          </div>
          <ol class="pipeline-list">
            <li v-for="(item, index) in config.ranking_pipeline" :key="index" class="pipeline-item">
              <span class="step-number">{{ item.step }}</span>
              <label class="pipeline-criterion">
                {{ t('rules.criterion') }}
                <select :value="item.criterion" @change="setCriterion(index, $event)">
                  <option v-for="criterion in criterionOptions(index)" :key="criterion" :value="criterion">{{ t(`rules.criterion.${criterion}`) }}</option>
                </select>
              </label>
              <label v-if="item.criterion === 'head_to_head'" class="pipeline-parameter">
                {{ t('rules.headToHeadRounds') }}
                <input :value="item.params.total_rounds_expected" type="number" min="1" max="2" @change="setHeadToHeadRounds(index, $event)" />
              </label>
              <span v-else class="pipeline-parameter muted-note">{{ t('rules.parameters') }}: {{ Object.keys(item.params).length ? JSON.stringify(item.params) : '-' }}</span>
              <div class="pipeline-actions">
                <button type="button" :aria-label="t('rules.moveUp')" :disabled="!canMovePipelineStep(index, -1)" @click="movePipelineStep(index, -1)">↑</button>
                <button type="button" :aria-label="t('rules.moveDown')" :disabled="!canMovePipelineStep(index, 1)" @click="movePipelineStep(index, 1)">↓</button>
                <button type="button" :aria-label="t('rules.removeCriterion')" :disabled="disabled || index === 0 || config.ranking_pipeline.length <= 1" @click="removePipelineStep(index)">×</button>
              </div>
            </li>
          </ol>
          <button class="button-secondary add-criterion" type="button" :disabled="disabled || !availableCriteria.length" @click="addPipelineStep">{{ t('rules.addCriterion') }}</button>
          <p v-if="!availableCriteria.length" class="muted-note">{{ t('rules.noCriteriaAvailable') }}</p>
        </section>

        <div class="editor-columns">
          <section class="editor-section">
            <div class="section-heading"><div><p class="eyebrow">03</p><h3>{{ t('rules.substitutionsSection') }}</h3></div><p>{{ t('rules.substitutionsDescription') }}</p></div>
            <div class="field-grid">
              <label>{{ t('rules.maxPerTeam') }}<input v-model.number="config.substitutions.max_per_team" type="number" min="0" /></label>
              <label>{{ t('rules.maxWindows') }}<input v-model.number="config.substitutions.max_windows" type="number" min="0" /></label>
            </div>
            <label class="checkbox-field"><input v-model="config.substitutions.allow_reentry" type="checkbox" /> {{ t('rules.allowReentry') }}</label>
          </section>

          <section class="editor-section">
            <div class="section-heading"><div><p class="eyebrow">04</p><h3>{{ t('rules.disciplineSection') }}</h3></div><p>{{ t('rules.disciplineDescription') }}</p></div>
            <div class="field-grid">
              <label>{{ t('rules.yellowCardLimit') }}<input v-model.number="config.discipline.yellow_card_limit" type="number" min="1" /></label>
              <label>{{ t('rules.yellowCardSuspensionMatches') }}<input v-model.number="config.discipline.yellow_card_suspension_matches" type="number" min="1" /></label>
              <label>{{ t('rules.directRedSuspensionMatches') }}<input v-model.number="config.discipline.direct_red_suspension_matches" type="number" min="1" /></label>
            </div>
            <label class="checkbox-field"><input v-model="config.discipline.clear_yellows_on_stage_change" type="checkbox" /> {{ t('rules.clearYellowsOnStageChange') }}</label>
            <div class="subheading">{{ t('rules.fairPlayPenalties') }}</div>
            <div class="field-grid field-grid-three">
              <label>{{ t('rules.fairPlayYellow') }}<input v-model.number="config.discipline.fair_play_penalties.yellow_card" type="number" min="0" /></label>
              <label>{{ t('rules.fairPlayDoubleYellow') }}<input v-model.number="config.discipline.fair_play_penalties.double_yellow_red" type="number" min="0" /></label>
              <label>{{ t('rules.fairPlayDirectRed') }}<input v-model.number="config.discipline.fair_play_penalties.direct_red" type="number" min="0" /></label>
            </div>
          </section>

          <section class="editor-section">
            <div class="section-heading"><div><p class="eyebrow">05</p><h3>{{ t('rules.transfersSection') }}</h3></div><p>{{ t('rules.transfersDescription') }}</p></div>
            <label class="checkbox-field"><input v-model="config.transfers.allow_mid_season_transfers" type="checkbox" /> {{ t('rules.allowMidSeasonTransfers') }}</label>
            <label class="checkbox-field"><input v-model="config.transfers.same_matchday_participation_allowed" type="checkbox" /> {{ t('rules.sameMatchdayParticipation') }}</label>
            <label>{{ t('rules.rosterLockMatchday') }}<input v-model.number="config.transfers.roster_lock_matchday" type="number" min="1" :placeholder="t('rules.noRosterLock')" /></label>
          </section>

          <section class="editor-section">
            <div class="section-heading"><div><p class="eyebrow">06</p><h3>{{ t('rules.resolutionSection') }}</h3></div><p>{{ t('rules.resolutionDescription') }}</p></div>
            <label class="checkbox-field"><input v-model="config.stage_defaults.extra_time_enabled" type="checkbox" /> {{ t('rules.extraTime') }}</label>
            <label class="checkbox-field"><input v-model="config.stage_defaults.penalties_enabled" type="checkbox" /> {{ t('rules.penalties') }}</label>
            <div class="field-grid">
              <label>{{ t('rules.walkoverWinnerScore') }}<input v-model.number="config.stage_defaults.walkover_score.winner" type="number" min="0" /></label>
              <label>{{ t('rules.walkoverLoserScore') }}<input v-model.number="config.stage_defaults.walkover_score.loser" type="number" min="0" /></label>
            </div>
          </section>
        </div>

        <section class="editor-section">
          <div class="section-heading"><div><p class="eyebrow">07</p><h3>{{ t('rules.stageOverridesSection') }}</h3></div><p>{{ t('rules.stageOverridesDescription') }}</p></div>
          <div v-if="stages.length" class="override-list">
            <article v-for="stage in stages" :key="stage.id" class="override-card">
              <div class="override-heading">
                <div><strong>{{ stage.stage_order ? `${stage.stage_order}. ` : '' }}{{ stage.name }}</strong><small>{{ stage.id }}</small></div>
                <label class="checkbox-field"><input type="checkbox" :checked="Boolean(overrideFor(stage.id))" @change="toggleOverride(stage.id, $event)" /> {{ t('rules.useStageOverride') }}</label>
              </div>
              <div v-if="overrideFor(stage.id)" class="field-grid override-fields">
                <label class="checkbox-field"><input type="checkbox" :checked="overrideBoolean(stage.id, 'extra_time_enabled')" @change="setOverrideBoolean(stage.id, 'extra_time_enabled', $event)" /> {{ t('rules.extraTime') }}</label>
                <label class="checkbox-field"><input type="checkbox" :checked="overrideBoolean(stage.id, 'penalties_enabled')" @change="setOverrideBoolean(stage.id, 'penalties_enabled', $event)" /> {{ t('rules.penalties') }}</label>
                <label>{{ t('rules.walkoverWinnerScore') }}<input :value="overrideScore(stage.id, 'winner')" type="number" min="0" @change="setOverrideScore(stage.id, 'winner', $event)" /></label>
                <label>{{ t('rules.walkoverLoserScore') }}<input :value="overrideScore(stage.id, 'loser')" type="number" min="0" @change="setOverrideScore(stage.id, 'loser', $event)" /></label>
                <button class="remove-override" type="button" @click="removeOverride(stage.id)">{{ t('rules.removeStageOverride') }}</button>
              </div>
            </article>
          </div>
          <p v-else class="muted-note">{{ t('rules.noStagesForOverrides') }}</p>
        </section>
      </fieldset>
    </div>

    <div v-else class="rules-advanced">
      <label>{{ t('rules.jsonMode') }}
        <textarea v-model="advancedJson" rows="24" maxlength="30000" :disabled="disabled" :placeholder="t('rules.jsonPlaceholder')" />
      </label>
      <p v-if="advancedError" class="form-error" role="alert">{{ advancedError }}</p>
      <ul v-if="validationErrors.length" class="validation-list" aria-live="polite">
        <li v-for="(ruleError, index) in validationErrors" :key="`${ruleError.code}-${ruleError.path || index}`">
          {{ t(RULES_VALIDATION_MESSAGE_KEYS[ruleError.code]) }}<code v-if="ruleError.path">{{ ruleError.path }}</code>
        </li>
      </ul>
      <button class="button-secondary" type="button" :disabled="disabled || !advancedJson.trim()" @click="applyAdvancedJson">{{ t('rules.applyJson') }}</button>
    </div>
  </div>
</template>

<style scoped>
.rules-editor { display: grid; gap: 16px; }
.editor-mode { display: inline-flex; width: fit-content; padding: 4px; border: 1px solid var(--line); border-radius: 999px; background: rgba(12, 15, 12, 0.45); }
.mode-button { padding: 8px 13px; border-radius: 999px; background: transparent; color: var(--muted); font-size: 0.78rem; font-weight: 800; }
.mode-button.active { background: var(--accent); color: var(--accent-ink); }
.editor-description { margin: 0; color: var(--muted); font-size: 0.82rem; line-height: 1.5; }
fieldset { display: grid; gap: 16px; min-width: 0; margin: 0; padding: 0; border: 0; }
fieldset:disabled { opacity: 0.72; }
.editor-section { display: grid; gap: 13px; padding: 18px; border: 1px solid rgba(212, 243, 106, 0.14); border-radius: 14px; background: rgba(12, 15, 12, 0.28); }
.section-heading { display: flex; align-items: start; justify-content: space-between; gap: 14px; }
.section-heading .eyebrow { margin: 0; }
.section-heading h3 { margin: 3px 0 0; font-size: 1.1rem; letter-spacing: -0.04em; }
.section-heading > p { max-width: 390px; margin: 4px 0 0; color: var(--muted); font-size: 0.75rem; line-height: 1.4; text-align: right; }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.field-grid-three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
label { display: grid; gap: 6px; color: var(--muted); font-size: 0.75rem; }
input, select, textarea { min-width: 0; padding: 0.72rem 0.8rem; border: 1px solid var(--line); border-radius: 9px; background: #0c0f0c; color: var(--ink); }
input:focus, select:focus, textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-glow); outline: none; }
input[type='checkbox'] { width: 16px; height: 16px; accent-color: var(--accent); }
.checkbox-field { display: flex; grid-template-columns: none; align-items: center; gap: 8px; color: var(--ink); }
.pipeline-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.pipeline-item { display: grid; grid-template-columns: 30px minmax(160px, 1fr) minmax(150px, 1fr) auto; align-items: end; gap: 10px; padding: 10px; border: 1px solid var(--line); border-radius: 10px; }
.step-number { display: grid; width: 26px; height: 26px; place-items: center; align-self: center; border-radius: 50%; background: rgba(212, 243, 106, 0.12); color: var(--accent); font-size: 0.75rem; font-weight: 800; }
.pipeline-parameter { min-width: 0; align-self: center; }
.pipeline-parameter.muted-note { overflow: hidden; padding-bottom: 9px; text-overflow: ellipsis; white-space: nowrap; }
.pipeline-actions { display: flex; align-items: center; gap: 4px; padding-bottom: 1px; }
.pipeline-actions button { width: 28px; height: 28px; border: 1px solid var(--line); border-radius: 7px; background: transparent; color: var(--muted); font-size: 0.85rem; }
.pipeline-actions button:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
.pipeline-actions button:disabled { opacity: 0.35; }
.add-criterion { justify-self: start; padding: 0.65rem 0.85rem; font-size: 0.75rem; }
.editor-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.subheading { padding-top: 5px; border-top: 1px solid var(--line); color: var(--ink); font-size: 0.76rem; font-weight: 800; }
.override-list { display: grid; gap: 8px; }
.override-card { display: grid; gap: 12px; padding: 13px; border: 1px solid var(--line); border-radius: 10px; }
.override-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.override-heading > div { display: grid; gap: 4px; min-width: 0; }
.override-heading strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.override-heading small { overflow: hidden; color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.65rem; text-overflow: ellipsis; white-space: nowrap; }
.override-fields { align-items: end; }
.remove-override { justify-self: start; padding: 4px 0; background: transparent; color: var(--muted); font-size: 0.72rem; }
.remove-override:hover { color: var(--danger); }
.rules-advanced { display: grid; gap: 12px; }
.rules-advanced textarea { min-height: 360px; resize: vertical; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.76rem; line-height: 1.5; }
.form-error { margin: 0; padding: 10px 12px; border: 1px solid #a45b5b; border-radius: 9px; color: var(--danger); font-size: 0.78rem; }
.validation-list { display: grid; gap: 5px; margin: 0; padding: 10px 12px 10px 28px; border: 1px solid rgba(255, 203, 122, 0.3); border-radius: 9px; color: #ffcb7a; font-size: 0.76rem; }
code { margin-left: 5px; color: var(--accent); font-size: 0.68rem; }
.muted-note { color: var(--muted); font-size: 0.72rem; }
@media (max-width: 760px) {
  .section-heading, .override-heading { align-items: stretch; flex-direction: column; }
  .section-heading > p { max-width: none; text-align: left; }
  .field-grid, .field-grid-three, .editor-columns { grid-template-columns: 1fr; }
  .pipeline-item { grid-template-columns: 30px minmax(0, 1fr) auto; }
  .pipeline-parameter { grid-column: 2 / -1; }
  .pipeline-actions { grid-column: 3; grid-row: 1; }
}
</style>
