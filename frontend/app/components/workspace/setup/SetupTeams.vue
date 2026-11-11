<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import TeamsWizard from '~/components/TeamsWizard.vue';
import TeamCrest from '~/components/TeamCrest.vue';
import type { TeamSummary, VersionSummary } from './types';

defineProps<{
  tournamentId: string; selectedVersionId: string; activeVersion?: VersionSummary;
  canManageTournaments: boolean; saving: boolean; wizardResetToken: number;
  teams: TeamSummary[]; crestStatusMessage: string | null; crestBusyTeamId: string | null;
  crestInputVersions: Record<string, number>; crestErrors: Record<string, string>;
  crestInputId: (teamId: string) => string; crestErrorId: (teamId: string) => string;
}>();
const emit = defineEmits<{
  saved: []; 'dirty-change': [value: boolean]; title: [element: HTMLElement | null];
  'crest-file-selected': [teamId: string, event: Event]; 'remove-crest': [team: TeamSummary];
}>();
const { t } = useI18n();
const teamsTitle = ref<HTMLElement | null>(null);
onMounted(() => emit('title', teamsTitle.value));
onBeforeUnmount(() => emit('title', null));
const onTeamsSaved = () => emit('saved');
const onCrestFileSelected = (teamId: string, event: Event) => emit('crest-file-selected', teamId, event);
const removeCrest = (team: TeamSummary) => emit('remove-crest', team);
</script>

<template>
<Surface as="div" id="equipos" class="panel teams-panel panel-wide">
              <p class="eyebrow">{{ t('setup.teamsEyebrow') }}</p>
              <h2 ref="teamsTitle" tabindex="-1">{{ t('setup.nameTheField') }}</h2>
              <TeamsWizard
                :tournament-id="tournamentId"
                :version-id="selectedVersionId"
                :disabled="!canManageTournaments || activeVersion?.status !== 'draft'"
                :busy="saving"
                :reset-token="wizardResetToken"
                @saved="onTeamsSaved"
                @dirty-change="emit('dirty-change', $event)"
              />
              <p v-if="crestStatusMessage" class="muted-note" role="status">{{ crestStatusMessage }}</p>
              <TransitionGroup name="card-list" tag="ul" class="team-crest-grid">
                <li
                  v-for="team in teams"
                  :key="team.team_id"
                  class="team-crest-card"
                  :aria-busy="crestBusyTeamId === team.team_id"
                >
                  <TeamCrest
                    :team="team"
                    :crest-url="team.crest_url ?? null"
                    :logo-url="team.logo_url ?? null"
                    surface="workspace"
                  />
                  <span class="team-name">{{ team.name }}</span>
                  <small>{{ team.short_code }}</small>
                  <div v-if="canManageTournaments" class="crest-actions">
                    <label class="photo-picker crest-file-picker" :for="crestInputId(team.team_id)">{{ crestBusyTeamId === team.team_id ? t('crest.uploading') : (team.crest_url ? t('crest.replace') : t('crest.fileLabel')) }}
                    <input
                      :id="crestInputId(team.team_id)"
                      :key="crestInputVersions[team.team_id] ?? 0"
                      type="file"
                      accept="image/jpeg,image/png,image/webp"
                      :disabled="crestBusyTeamId === team.team_id"
                      :aria-invalid="crestErrors[team.team_id] ? 'true' : undefined"
                      :aria-describedby="crestErrors[team.team_id] ? crestErrorId(team.team_id) : undefined"
                      @change="onCrestFileSelected(team.team_id, $event)"
                    >
                    </label>
                    <Button
                      variant="secondary"
                      v-if="team.crest_url"
                      type="button"
                      class="button-secondary"
                      :disabled="crestBusyTeamId === team.team_id"
                      :aria-describedby="crestErrors[team.team_id] ? crestErrorId(team.team_id) : undefined"
                      @click="removeCrest(team)"
                    >{{ t('crest.remove') }}</Button>
                    <p
                      v-if="crestErrors[team.team_id]"
                      :id="crestErrorId(team.team_id)"
                      class="form-error"
                      role="alert"
                    >{{ crestErrors[team.team_id] }}</p>
                  </div>
                </li>
              </TransitionGroup>
            </Surface>
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
.team-crest-grid { position: relative; display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 320px)); justify-content: center; gap: var(--space-3); margin: var(--space-2) 0 0; padding: var(--space-3) 0 0; border-top: 1px solid var(--color-line); list-style: none; }
.team-crest-card { display: grid; justify-items: center; text-align: center; gap: var(--space-2); padding: var(--space-4); max-width: 320px; width: 100%; margin-inline: auto; border: 1px solid var(--color-line); border-radius: var(--radius-md); background: color-mix(in srgb, var(--color-canvas) 30%, transparent); }
.team-crest-meta { display: grid; gap: var(--space-1); min-width: 0; justify-items: center; }
.team-crest-meta .team-name { color: var(--color-ink); font-size: var(--text-md); }
.team-crest-meta small { color: var(--color-muted); font-size: var(--text-2xs); }
.team-name { color: var(--color-ink); font-size: var(--text-md); overflow-wrap: anywhere; }
.crest-actions { grid-column: 1 / -1; display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2); width: 100%; }
.crest-actions .photo-picker,
.crest-actions .button-secondary { min-height: 40px; padding: var(--space-2) var(--space-4); font-size: var(--text-xs); border-radius: var(--radius-sm); justify-content: center; }
.crest-actions label { font-size: var(--text-xs); }
.crest-actions .form-error { flex-basis: 100%; margin: 0; }
.photo-picker { position: relative; display: inline-flex; align-items: center; justify-content: center; min-height: 34px; padding: var(--space-1) var(--space-3); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: transparent; color: var(--color-ink); font-size: var(--text-xs); font-weight: 700; cursor: pointer; transition: border-color 180ms ease, color 180ms ease, background-color 180ms ease; }
.photo-picker:hover:not(:has(input:disabled)) { border-color: var(--color-accent); color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 6%, transparent); }
.photo-picker:has(input:disabled) { opacity: 0.45; cursor: not-allowed; }
.photo-picker input[type="file"] { position: absolute; width: 1px; height: 1px; opacity: 0; overflow: hidden; }
</style>
