<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import SetupHeader from '~/components/workspace/setup/SetupHeader.vue';
import SetupChecklist from '~/components/workspace/setup/SetupChecklist.vue';
import SetupRules from '~/components/workspace/setup/SetupRules.vue';
import SetupTeams from '~/components/workspace/setup/SetupTeams.vue';
import SetupStages from '~/components/workspace/setup/SetupStages.vue';
import { useTournamentSetup } from '~/composables/useTournamentSetup';
import type { ConfigurationData } from '~/components/workspace/setup/types';

definePageMeta({ middleware: 'auth' });
const id = String(useRoute().params.id);
const redirectLegacyTournamentHash = useLegacyTournamentSectionRedirect(id);
await redirectLegacyTournamentHash();
const {
  auth, tournamentId, t, statusLabel, tournamentName, tournamentLabel, loading, loadError, error, saving,
  versions, selectedVersionId, draftVersion, activeVersion, canManageTournaments, canPublish, configurationReadOnly,
  rulesEditable, declaredGameFormat, setupChecks, rulesConfig, serverRulesConfig, selectedVersionStages,
  rulesServerDetail, rulesError, rulesMinutesNotice, wizardResetToken, wizardDirty, rulesTitle, teamsTitle,
  teams, selectedVersionRosterLimits, rosterCountsByTeam, rosterLockActive,
  onVersionChange, publishVersion, createDraftVersion, retryConfiguration, useDefaultRules,
  updateRulesConfig, saveRules, continueAfterNotice, stayAfterNotice, onTeamsSaved, onStagesConfirmed, refreshConfiguration,
  fetchConfiguration, applyConfiguration, redirectOnSessionFailure, failureMessage,
  crestBusyTeamId, crestStatusMessage, crestErrors, crestInputVersions, crestInputId, crestErrorId, onCrestFileSelected, removeCrest
} = useTournamentSetup(id);

const { data: initialConfiguration, error: initialConfigurationError } = await useAsyncData<ConfigurationData>(
  `workspace-tournament-${tournamentId}-${auth.userId || 'none'}-${auth.organizationId || 'none'}-${auth.sessionVersion}`,
  fetchConfiguration,
);

if (initialConfigurationError.value) {
  if (!(await redirectOnSessionFailure(initialConfigurationError.value))) {
     loadError.value = failureMessage(initialConfigurationError.value, t('setup.loading'));
  }
} else if (initialConfiguration.value) {
  applyConfiguration(initialConfiguration.value);
}
loading.value = false;

</script>

<template>
<WorkspaceShell
  :breadcrumbs="[{ label: t('shell.tournaments'), to: '/workspace' }, { label: tournamentLabel, current: true }]"
  :tournament="{ id: tournamentId, name: tournamentName }"
>
  <main id="main-content" class="workspace-shell">
    <SetupHeader :tournament-label="tournamentLabel" :draft-version="draftVersion" :declared-game-format="declaredGameFormat" />
    <section class="container config-content">
      <div v-if="loading" class="empty-state loading-state" role="status"><span class="loading-orb" aria-hidden="true" /> {{ t('setup.loading') }}</div>
      <div v-else-if="loadError" class="form-error" role="alert"><span>{{ loadError }}</span><Button variant="secondary" class="button-secondary" type="button" @click="retryConfiguration">{{ t('common.retry') }}</Button></div>
      <template v-else>
        <p v-if="configurationReadOnly" class="read-only-notice" role="status">{{ t('setup.readOnlyMode') }}</p>
        <div class="config-toolbar">
           <label class="field">
              {{ t('setup.version') }}
            <select :value="selectedVersionId" @change="onVersionChange">
              <option v-for="version in versions" :key="version.id" :value="version.id">
                 v{{ version.version_number }} · {{ statusLabel(version.status) }}
              </option>
            </select>
          </label>
             <Button variant="primary" v-if="canManageTournaments && draftVersion" class="button-primary" type="button" :disabled="saving || !canPublish" @click="publishVersion">
             {{ saving ? t('common.saving') : t('setup.publishDraft') }}
           </Button>
             <Button variant="secondary" v-else-if="canManageTournaments && activeVersion?.status === 'published'" class="button-secondary" type="button" :disabled="saving" @click="createDraftVersion">
              {{ saving ? t('common.saving') : t('setup.createDraftVersion') }}
           </Button>
          </div>
        <SetupChecklist :setup-checks="setupChecks" />
        <SetupRules
          :active-version="activeVersion" :rules-editable="rulesEditable" :can-manage-tournaments="canManageTournaments"
          :saving="saving" :rules-config="rulesConfig" :server-rules-config="serverRulesConfig"
          :selected-version-stages="selectedVersionStages" :tournament-id="tournamentId" :selected-version-id="selectedVersionId"
          :rules-server-detail="rulesServerDetail" :wizard-reset-token="wizardResetToken" :rules-error="rulesError" :rules-minutes-notice="rulesMinutesNotice"
          @save="saveRules" @defaults="useDefaultRules" @update:model-value="updateRulesConfig"
          @dirty-change="wizardDirty.rules = $event" @continue="continueAfterNotice" @stay="stayAfterNotice" @title="rulesTitle = $event"
        />
        <Transition name="content-fade" mode="out-in">
          <div key="configuration" class="config-grid">
            <SetupTeams
              :tournament-id="tournamentId" :selected-version-id="selectedVersionId" :active-version="activeVersion"
              :can-manage-tournaments="canManageTournaments" :saving="saving" :wizard-reset-token="wizardResetToken"
              :teams="teams" :crest-status-message="crestStatusMessage" :crest-busy-team-id="crestBusyTeamId"
              :crest-input-versions="crestInputVersions" :crest-errors="crestErrors" :crest-input-id="crestInputId" :crest-error-id="crestErrorId"
              @saved="onTeamsSaved" @dirty-change="wizardDirty.teams = $event" @title="teamsTitle = $event"
              @crest-file-selected="onCrestFileSelected" @remove-crest="removeCrest"
            />
            <SetupStages
              :tournament-id="tournamentId" :selected-version-id="selectedVersionId" :selected-version-stages="selectedVersionStages"
              :teams="teams" :selected-version-roster-limits="selectedVersionRosterLimits" :roster-counts-by-team="rosterCountsByTeam"
              :roster-lock-active="rosterLockActive" :can-manage-tournaments="canManageTournaments" :active-version="activeVersion"
              :saving="saving" :wizard-reset-token="wizardResetToken"
              @saved="refreshConfiguration" @confirmed="onStagesConfirmed" @reload="refreshConfiguration" @dirty-change="wizardDirty.phases = $event"
            />
          </div>
        </Transition>
        <div v-if="error" class="form-error" role="alert">{{ error }}</div>
      </template>
    </section>
  </main>
</WorkspaceShell>
</template>

<style scoped>
.workspace-shell { min-height: 100vh; background: radial-gradient(circle at 90% 8%, color-mix(in srgb, var(--color-accent) 8%, transparent), transparent 28rem), var(--color-canvas); }
.config-content { padding-bottom: var(--space-10); }
.read-only-notice { margin: 0 0 var(--space-4); padding: var(--space-3) var(--space-3); border: 1px solid var(--color-line); border-radius: var(--radius-md); color: var(--color-muted); font-size: var(--text-md); }
.config-toolbar { display: flex; align-items: end; justify-content: space-between; gap: var(--space-5); margin-bottom: var(--space-6); }
.config-toolbar label, label { display: grid; gap: var(--space-2); color: var(--color-muted); font-size: var(--text-sm); }
select, input { min-width: 0; padding: var(--space-3) var(--space-4); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: var(--color-canvas); color: var(--color-ink); }
select:hover, input:hover { border-color: var(--color-muted); }
select:focus, input:focus { border-color: var(--color-accent); box-shadow: 0 0 0 4px var(--accent-glow); }
.config-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; gap: var(--space-5); }
.panel-wide { grid-column: 1 / -1; }
.empty-state, .form-error { padding: var(--space-5); border: 1px dashed var(--color-line); border-radius: var(--radius-md); color: var(--color-muted); }
.loading-state { display: flex; align-items: center; gap: var(--space-3); }
.loading-orb { width: 9px; height: 9px; border-radius: 50%; background: var(--color-accent); box-shadow: 0 0 18px var(--color-accent); animation: pulse 1s ease-in-out infinite; }
.form-error { border-style: solid; border-color: var(--color-danger-border); color: var(--color-danger); }
@media (max-width: 1000px) { .config-grid { grid-template-columns: 1fr; } .panel-wide { grid-column: auto; } }
@media (max-width: 480px) { .container { width: min(100% - 28px, 620px); } .config-toolbar { align-items: stretch; flex-direction: column; } }
</style>
