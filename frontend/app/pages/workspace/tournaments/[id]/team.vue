<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import Button from '~/components/ui/Button.vue';
import PageHeader from '~/components/ui/PageHeader.vue';
import Surface from '~/components/ui/Surface.vue';
import type { TournamentTeamMember } from '~/utils/tournamentTeam';

// «Equipo del torneo» (spec 049, RF-003b, RF-012): lo ve cualquier miembro; lo cambian dueño y administrador.
definePageMeta({ middleware: 'auth' });
const { t } = useI18n();
const route = useRoute();
const tournamentsStore = useTournamentsStore();
const tournamentId = String(route.params.id);
const tournamentName = computed(
  () => tournamentsStore.tournaments.find((tournament) => tournament.id === tournamentId)?.name || '',
);
const tournamentLabel = computed(() => tournamentName.value || t('shell.tournament'));
useHead({ title: computed(() => `${t('tournamentTeam.title')} | Bracket Craft`) });
const { canManage, items, candidates, loading, busy, error, actionError, notice, assign, remove } = useTournamentTeam(() => tournamentId);

const selected = ref('');
watch(candidates, (list) => {
  if (!list.some((item) => item.organization_user_id === selected.value)) selected.value = '';
});

async function submit() {
  if (!selected.value) return;
  if (await assign(selected.value)) selected.value = '';
}

function removeMember(item: TournamentTeamMember) {
  void remove(item);
}
</script>

<template>
  <WorkspaceShell
    :breadcrumbs="[
      { label: t('shell.tournaments'), to: '/workspace' },
      { label: tournamentLabel, current: true },
    ]"
    :tournament="{ id: tournamentId, name: tournamentName || null }"
  >
    <main id="main-content" class="container team-page">
      <PageHeader :title="t('tournamentTeam.title')">
        <template #context>{{ tournamentLabel }}</template>
      </PageHeader>
      <p class="team-muted">{{ t('tournamentTeam.help') }}</p>
      <p v-if="notice" role="status" class="team-notice">{{ t(notice) }}</p>
      <p v-if="error" role="alert" class="team-error">{{ t(error) }}</p>
      <p v-if="actionError" role="alert" class="team-error">{{ t(actionError) }}</p>

      <Surface v-if="canManage" as="section" class="team-assign" aria-labelledby="tournament-team-assign-title">
        <h2 id="tournament-team-assign-title">{{ t('tournamentTeam.assign') }}</h2>
        <form v-if="candidates.length" class="team-form" @submit.prevent="submit">
          <label for="tournament-team-member">{{ t('tournamentTeam.assignLabel') }}</label>
          <select id="tournament-team-member" v-model="selected" :disabled="busy">
            <option value="">{{ t('tournamentTeam.selectPlaceholder') }}</option>
            <option v-for="candidate in candidates" :key="candidate.organization_user_id" :value="candidate.organization_user_id">{{ candidate.full_name }} · {{ t(`roles.${candidate.role_code}`) }}</option>
          </select>
          <Button type="submit" :busy="busy" :disabled="!selected">{{ t('tournamentTeam.assign') }}</Button>
        </form>
        <p v-else class="team-muted">{{ t('tournamentTeam.noCandidates') }}</p>
      </Surface>
      <p v-else class="team-muted">{{ t('tournamentTeam.readOnly') }}</p>

      <p v-if="loading" role="status" class="team-muted">{{ t('tournamentTeam.loading') }}</p>
      <p v-else-if="!items.length" class="team-muted">{{ t('tournamentTeam.empty') }}</p>
      <div v-else class="team-table-wrap">
        <table class="team-table">
          <caption class="visually-hidden">{{ t('tournamentTeam.title') }}</caption>
          <thead>
            <tr>
              <th scope="col">{{ t('tournamentTeam.member') }}</th>
              <th scope="col">{{ t('tournamentTeam.organizationRole') }}</th>
              <th scope="col">{{ t('tournamentTeam.status') }}</th>
              <th v-if="canManage" scope="col">{{ t('tournamentTeam.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.organization_user_id">
              <th scope="row">
                <span>{{ item.full_name }}</span>
                <span v-if="!item.adds_permissions" class="team-hint">{{ t('tournamentTeam.noAddedPermissions') }}</span>
              </th>
              <td>{{ t(`roles.${item.organization_role_code}`) }}</td>
              <td>{{ t(item.is_active ? 'tournamentTeam.active' : 'tournamentTeam.inactive') }}</td>
              <td v-if="canManage">
                <Button
                  variant="secondary" :disabled="busy"
                  :aria-label="`${t('tournamentTeam.remove')}: ${item.full_name}`" @click="removeMember(item)"
                >
                  {{ t('tournamentTeam.remove') }}
                </Button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </main>
  </WorkspaceShell>
</template>

<style scoped>
.team-page { display: grid; gap: var(--space-4); padding-block: var(--space-6); }
.team-muted { margin: 0; color: var(--color-muted); }
.team-notice { margin: 0; color: var(--color-ink); font-weight: var(--weight-lg); }
.team-error { margin: 0; color: var(--color-danger); }
.team-assign { display: grid; gap: var(--space-3); }
.team-assign h2 { margin: 0; font-size: var(--text-lg); line-height: var(--leading-lg); }
.team-form { display: flex; flex-wrap: wrap; align-items: end; gap: var(--space-3); }
.team-form label { flex-basis: 100%; font-weight: var(--weight-lg); }
.team-form select { min-width: 0; flex: 1 1 16rem; }
.team-table-wrap { overflow-x: auto; }
.team-table { width: 100%; border-collapse: collapse; }
.team-table th, .team-table td { padding: var(--space-2) var(--space-3); text-align: start; vertical-align: top; border-bottom: 1px solid var(--color-line); }
.team-table tbody th { display: grid; gap: var(--space-1); font-weight: var(--weight-lg); }
.team-hint { color: var(--color-muted); font-size: var(--text-sm); line-height: var(--leading-sm); font-weight: normal; }
</style>
