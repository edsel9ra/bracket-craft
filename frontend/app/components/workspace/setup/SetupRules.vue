<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import RulesWizard from '~/components/rules/RulesWizard.vue';
import type { RulesConfig } from '~/utils/rulesConfig';
import type { StageSummary, VersionSummary } from './types';

defineProps<{
  activeVersion?: VersionSummary;
  rulesEditable: boolean;
  canManageTournaments: boolean;
  saving: boolean;
  rulesConfig: RulesConfig | null;
  serverRulesConfig: RulesConfig | null;
  selectedVersionStages: StageSummary[];
  tournamentId: string;
  selectedVersionId: string;
  rulesServerDetail: unknown[] | null;
  wizardResetToken: number;
  rulesError: string | null;
  rulesMinutesNotice: string | null;
}>();
const emit = defineEmits<{
  save: []; defaults: []; 'update:modelValue': [value: RulesConfig];
  'dirty-change': [value: boolean]; continue: []; stay: []; title: [element: HTMLElement | null];
}>();
const { t } = useI18n();
const rulesTitle = ref<HTMLElement | null>(null);
onMounted(() => emit('title', rulesTitle.value));
onBeforeUnmount(() => emit('title', null));
const saveRules = () => emit('save');
const useDefaultRules = () => emit('defaults');
const updateRulesConfig = (value: RulesConfig) => emit('update:modelValue', value);
const continueAfterNotice = () => emit('continue');
const stayAfterNotice = () => emit('stay');
</script>

<template>
<form id="configuracion" class="panel panel-wide rules-panel" :aria-busy="saving" @submit.prevent="saveRules">
             <div class="panel-heading">
               <div><p class="eyebrow">{{ t('setup.rulesEyebrow') }}</p><h2 ref="rulesTitle" tabindex="-1">{{ t('setup.editRules') }}</h2></div>
               <div class="rules-heading-actions">
                 <span v-if="activeVersion && !rulesEditable" class="muted-note">{{ t('rules.readOnlyVersion') }}</span>
                <Button variant="secondary" v-if="canManageTournaments && rulesEditable && !rulesConfig" class="button-secondary" type="button" @click="useDefaultRules">{{ t('setup.useDefaultRules') }}</Button>
               </div>
             </div>
             <p class="field-hint">{{ t('setup.rulesDescription') }}</p>
             <RulesWizard
               :model-value="rulesConfig"
               :server-config="serverRulesConfig"
               :stages="selectedVersionStages"
               :disabled="!canManageTournaments || !rulesEditable"
               :busy="saving"
               :save-disabled="!rulesConfig"
               :tournament-id="tournamentId"
               :version-id="selectedVersionId"
               :server-detail="rulesServerDetail"
               :reset-token="wizardResetToken"
               @update:model-value="updateRulesConfig"
               @dirty-change="emit('dirty-change', $event)"
               @save="saveRules"
             />
             <p v-if="!rulesConfig && rulesEditable" class="muted-note">{{ t('setup.rulesLoadNote') }}</p>
             <p v-if="rulesError" class="form-error" role="alert">{{ rulesError }}</p>
             <!-- RF-017: se anuncia solo el texto del aviso; sus dos controles
                  van fuera de la región anunciada y conservan el orden de
                  lectura (texto primero, controles después). -->
             <template v-if="rulesMinutesNotice">
               <p class="minutes-warning" role="status">{{ rulesMinutesNotice }}</p>
               <div class="minutes-warning-actions">
                 <Button variant="secondary" type="button" class="button-secondary" @click="continueAfterNotice">{{ t('rules.minutesWarning.continue') }}</Button>
                 <Button variant="secondary" type="button" class="button-secondary" @click="stayAfterNotice">{{ t('rules.minutesWarning.stay') }}</Button>
               </div>
             </template>
           </form>
</template>

<style scoped>
.panel { display: grid; align-content: start; gap: var(--space-3); min-width: 0; padding: var(--space-5); border: 1px solid var(--color-line); border-radius: var(--radius-lg); background: linear-gradient(145deg, color-mix(in srgb, var(--color-surface-raised) 90%, transparent), color-mix(in srgb, var(--color-surface) 94%, transparent)); box-shadow: 0 18px 50px color-mix(in srgb, var(--color-shadow) 12%, transparent); }
.panel-wide { grid-column: 1 / -1; }
.panel:hover { border-color: color-mix(in srgb, var(--color-accent) 32%, transparent); }
.panel h2 { margin: 0 0 var(--space-2); font-size: 1.6rem; letter-spacing: -0.05em; }
.panel h2:focus { outline: 2px solid var(--color-accent); outline-offset: 3px; border-radius: var(--radius-sm); }
.panel-heading { display: flex; align-items: start; justify-content: space-between; gap: var(--space-4); }
.panel-heading h2 { margin-bottom: 0; }
.empty-state, .form-error { padding: var(--space-5); border: 1px dashed var(--color-line); border-radius: var(--radius-md); color: var(--color-muted); }
.form-error { border-style: solid; border-color: var(--color-danger-border); color: var(--color-danger); }
.rules-heading-actions { display: flex; align-items: center; justify-content: end; gap: var(--space-2); }
.rules-panel { margin-bottom: var(--space-5); }
.rules-panel textarea { min-height: 260px; resize: vertical; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: var(--text-xs); }
.minutes-warning { margin: 0; padding: var(--space-3) var(--space-3); border: 1px solid color-mix(in srgb, var(--color-warning) 30%, transparent); border-radius: var(--radius-md); background: color-mix(in srgb, var(--color-warning) 6%, transparent); color: var(--color-warning); font-size: var(--text-sm); }
.minutes-warning-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
@media (max-width: 480px) { .panel-heading { align-items: stretch; flex-direction: column; } }
</style>
