<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import { isForbidden, isNotFound, isUnauthorized } from '~/utils/api';
import {
  createReloadCoordinator,
  decideReload,
  resyncTrigger,
  type ReloadTrigger,
} from '~/utils/realtimeReload';
import { realtimeStatusLabelKey } from '~/utils/realtimeStatusLabel';
import { buildTournamentDraftBody } from '~/utils/requestBodies';

definePageMeta({ middleware: 'auth' });

const auth = useAuthStore();
const tournamentsStore = useTournamentsStore();
const realtime = useRealtime();
const { request } = useApi();
const { t, statusLabel, errorMessage } = useI18n();
const { confirm } = useConfirm({ singleFlight: true });
const canManageTournaments = computed(() => auth.hasPermission('MANAGE_TOURNAMENTS'));
const workspaceError = ref<string | null>(null);
const showCreateForm = ref(false);
const creating = ref(false);
const createError = ref<string | null>(null);
const publishingTournamentId = ref<string | null>(null);
const createForm = reactive({
  name: '',
  season: '',
  start_date: '',
});
let disposed = false;

const workspaceReload = createReloadCoordinator(async () => {
  if (disposed) return;
  try {
    await tournamentsStore.load();
  } catch (cause) {
    await redirectOnSessionFailure(cause);
  }
});

function reloadRealtime(trigger: ReloadTrigger) {
  const decision = decideReload({
    consumer: 'workspace',
    trigger,
    initialized: realtime.initialization.initialized,
    initializedWithJoin: realtime.initialization.initializedWithJoin,
  });
  if (decision.action === 'reload') {
    void workspaceReload.request({ resetPagination: decision.resetPagination });
  }
}

useHead(() => ({
  title: `${t('shell.tournaments')} | Bracket Craft`,
  meta: [{ name: 'robots', content: 'noindex, nofollow' }],
}));

function failureMessage(cause: unknown): string {
  return errorMessage(cause, t('workspace.noCreate'));
}

function openCreateForm() {
  showCreateForm.value = true;
  createError.value = null;
  const today = new Date();
  createForm.season ||= today.getFullYear().toString();
  createForm.start_date ||= new Date(today.getTime() - today.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 10);
}

async function redirectOnSessionFailure(cause: unknown): Promise<boolean> {
  if (isUnauthorized(cause) || isNotFound(cause)) {
    await auth.logout();
    await navigateTo({ path: '/login', query: { redirect: '/workspace' } });
    return true;
  }
  if (isForbidden(cause)) {
    await navigateTo({ path: '/forbidden', query: { returnTo: '/workspace', resource: 'workspace' } });
    return true;
  }
  return false;
}

async function loadMoreTournaments() {
  try {
    await tournamentsStore.loadMore();
  } catch (cause) {
    await redirectOnSessionFailure(cause);
  }
}

function connectRealtime() {
  realtime.connect({
    onEvent: (event) => {
      if (['MATCH_CLOSED', 'MATCH_UPDATED', 'STANDINGS_UPDATED'].includes(event)) reloadRealtime('event');
    },
    onReconnect: () => reloadRealtime('reconnect'),
    onResync: (payload) => reloadRealtime(resyncTrigger(payload.reason)),
  });
}

const realtimeStatusLabel = computed(() => {
  const key = realtimeStatusLabelKey(realtime.status.value, 'workspace');
  return key ? t(key) : t('workspace.activeOperation');
});

async function createTournament() {
  creating.value = true;
  createError.value = null;
  try {
    await request('/tournaments', {
      method: 'POST',
      body: buildTournamentDraftBody(createForm),
    });
    createForm.name = '';
    showCreateForm.value = false;
    await tournamentsStore.load();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    createError.value = failureMessage(cause);
  } finally {
    creating.value = false;
  }
}

async function publishTournament(tournament: { id: string; draft_version_id?: string | null }) {
  if (!tournament.draft_version_id) return;
  if (import.meta.client && !(await confirm({ title: t('confirm.publish.title'), message: t('workspace.confirmPublish'), confirmLabel: t('confirm.publish.action'), tone: 'danger' }))) return;
  publishingTournamentId.value = tournament.id;
  workspaceError.value = null;
  try {
    await request(`/tournaments/${tournament.draft_version_id}/publish`, { method: 'POST' });
    await tournamentsStore.load();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    workspaceError.value = failureMessage(cause);
  } finally {
    publishingTournamentId.value = null;
  }
}

async function initializeWorkspace() {
  await auth.verifyWorkspace();
  await tournamentsStore.load();
}

async function retryWorkspace() {
  workspaceError.value = null;
  try {
    await initializeWorkspace();
  } catch (cause) {
    if (!(await redirectOnSessionFailure(cause))) workspaceError.value = errorMessage(cause, t('workspace.noLoad'));
  }
}

try {
  await callOnce(
    `workspace-${auth.userId || 'none'}-${auth.organizationId || 'none'}-${auth.sessionVersion}`,
    initializeWorkspace,
  );
} catch (cause) {
  if (!(await redirectOnSessionFailure(cause))) workspaceError.value = errorMessage(cause, t('workspace.noLoad'));
}

onMounted(() => {
  if (disposed) return;
  connectRealtime();
});

onBeforeUnmount(() => {
  disposed = true;
  realtime.disconnect();
});
</script>

<template>
  <WorkspaceShell :breadcrumbs="[{ label: t('shell.tournaments'), current: true }]">
   <main id="main-content" class="workspace-shell">
    <section class="container workspace-hero">
      <div class="hero-line">
         <p class="eyebrow">{{ t('workspace.private') }}</p>
          <span class="live-status" :class="`realtime-${realtime.status.value}`" role="status">
            <span aria-hidden="true" /> {{ realtimeStatusLabel }}
          </span>
          <button v-if="realtime.status.value === 'error'" class="realtime-retry" type="button" @click="realtime.retry()">{{ t('common.retry') }}</button>
      </div>
       <h1>{{ t('workspace.headline') }}</h1>
       <p class="workspace-copy">{{ t('workspace.copy') }}</p>
    </section>

    <section class="container workspace-content">
      <div class="section-heading">
        <div>
           <p class="eyebrow">{{ t('workspace.tournaments') }}</p>
           <h2>{{ t('workspace.yourTournaments') }}</h2>
        </div>
        <div class="section-actions">
            <span v-if="tournamentsStore.loading" class="muted" role="status">{{ t('common.loading') }}</span>
             <Button variant="primary" v-if="canManageTournaments && !showCreateForm" class="button-primary" type="button" @click="openCreateForm">
             {{ t('workspace.newTournament') }}
          </Button>
        </div>
      </div>
       <Transition name="panel-reveal" mode="out-in">
         <form v-if="showCreateForm" key="create-tournament" class="creation-panel" :aria-busy="creating" @submit.prevent="createTournament">
           <div class="creation-heading">
             <div>
             <p class="eyebrow">{{ t('workspace.draft') }}</p>
             <h3>{{ t('workspace.newCompetition') }}</h3>
             </div>
              <button class="close-button" type="button" :aria-label="t('common.close')" @click="showCreateForm = false">{{ t('common.close') }}</button>
           </div>
           <div class="creation-fields">
             <label class="field">
                {{ t('workspace.name') }}
               <input v-model="createForm.name" type="text" minlength="2" maxlength="100" required />
             </label>
             <label class="field">
                {{ t('workspace.season') }}
               <input v-model="createForm.season" type="text" maxlength="20" required />
             </label>
             <label class="field">
                {{ t('workspace.start') }}
               <input v-model="createForm.start_date" type="date" required />
             </label>
           </div>
           <div v-if="createError" class="form-error" role="alert">{{ createError }}</div>
           <Button variant="primary" class="button-primary" type="submit" :disabled="creating">
              {{ creating ? t('workspace.creating') : t('workspace.createDraft') }}
           </Button>
         </form>
       </Transition>
       <Transition name="content-fade" mode="out-in">
          <div v-if="workspaceError" key="workspace-error" class="empty-state" role="alert">
            <span>{{ workspaceError }}</span>
            <Button variant="secondary" class="button-secondary" type="button" @click="retryWorkspace">{{ t('common.retry') }}</Button>
          </div>
          <div v-else-if="tournamentsStore.error" key="store-error" class="empty-state" role="alert">
            <span>{{ tournamentsStore.error }}</span>
            <Button variant="secondary" class="button-secondary" type="button" @click="tournamentsStore.load()">{{ t('common.retry') }}</Button>
          </div>
         <div v-else-if="!tournamentsStore.loading && !tournamentsStore.tournaments.length" key="empty" class="empty-state">
            {{ t('workspace.empty') }}
         </div>
         <TransitionGroup v-else key="tournaments" name="card-list" tag="div" class="tournament-grid">
           <Surface as="article" v-for="tournament in tournamentsStore.tournaments" :key="tournament.id" class="tournament-card">
              <span class="status-tag">{{ statusLabel(tournament.status) }}</span>
             <h3>{{ tournament.name }}</h3>
             <p>{{ tournament.season }} · {{ t('public.starts') }} {{ tournament.start_date }}</p>
              <NuxtLink class="card-action" :to="`/workspace/tournaments/${tournament.id}`">{{ t('workspace.configure') }} <span aria-hidden="true">↗</span></NuxtLink>
             <button
               v-if="canManageTournaments && tournament.status === 'draft' && tournament.draft_version_id"
               class="card-action"
               type="button"
               :disabled="publishingTournamentId === tournament.id"
               @click="publishTournament(tournament)"
             >
                {{ publishingTournamentId === tournament.id ? t('workspace.publishing') : t('workspace.publish') }}
             </button>
           </Surface>
          </TransitionGroup>
        </Transition>
        <div v-if="tournamentsStore.hasMore" class="load-more-row">
           <Button variant="secondary" class="button-secondary" type="button" :disabled="tournamentsStore.loading" @click="loadMoreTournaments">
            {{ tournamentsStore.loading ? t('common.loading') : t('workspace.loadMore') }}
          </Button>
        </div>
      </section>
   </main>
  </WorkspaceShell>
</template>

<style scoped>
.workspace-shell { min-height: 100vh; background: radial-gradient(circle at 90% 8%, color-mix(in srgb, var(--color-accent) 8%, transparent), transparent 28rem), var(--color-canvas); }
.workspace-hero { padding: 5vh 0 5vh; animation: rise-in 700ms var(--ease-out) both; }
.hero-line { display: flex; align-items: center; gap: var(--space-4); }
.live-status { display: inline-flex; align-items: center; gap: var(--space-2); color: var(--color-muted); font-size: var(--text-2xs); letter-spacing: 0.1em; text-transform: uppercase; }
.live-status span { width: 7px; height: 7px; border-radius: 50%; background: var(--color-accent); box-shadow: 0 0 12px var(--color-accent); }
.live-status.realtime-reconnecting span, .live-status.realtime-retrying span, .live-status.realtime-error span { background: var(--color-warning); box-shadow: 0 0 12px color-mix(in srgb, var(--color-warning) 70%, transparent); }
.realtime-retry { padding: 0; background: transparent; color: var(--color-accent); font-size: var(--text-2xs); text-decoration: underline; }
.workspace-hero h1 { max-width: 760px; margin: var(--space-3) 0; font-size: var(--text-display); line-height: 0.92; letter-spacing: -0.08em; }
.workspace-copy { max-width: 520px; color: var(--color-muted); font-size: var(--text-base); line-height: 1.6; }
.workspace-content { padding-bottom: var(--space-10); }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: var(--space-4); margin-bottom: var(--space-5); }
.section-actions { display: flex; align-items: center; gap: var(--space-3); }
.section-heading h2 { margin: var(--space-2) 0 0; font-size: var(--text-xl); letter-spacing: -0.05em; }
.muted, .empty-state, .tournament-card p { color: var(--color-muted); }
.empty-state { padding: var(--space-6); border: 1px dashed var(--color-line); border-radius: var(--radius-md); }
.empty-state { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.load-more-row { display: flex; justify-content: center; margin-top: var(--space-5); }
.creation-panel { display: grid; gap: var(--space-5); margin-bottom: var(--space-6); padding: var(--space-5); border: 1px solid var(--color-line); border-radius: var(--radius-lg); background: linear-gradient(145deg, var(--color-surface-raised), color-mix(in srgb, var(--color-surface) 90%, transparent)); box-shadow: 0 18px 50px color-mix(in srgb, var(--color-shadow) 16%, transparent); }
.creation-heading { display: flex; align-items: start; justify-content: space-between; gap: var(--space-4); }
.creation-heading h3 { margin: var(--space-2) 0 0; }
.creation-fields { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: var(--space-3); }
label { display: grid; gap: var(--space-2); color: var(--color-muted); font-size: var(--text-sm); }
input { width: 100%; padding: var(--space-3) var(--space-4); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: var(--color-canvas); color: var(--color-ink); }
.form-error { padding: var(--space-3); border: 1px solid var(--color-danger-border); border-radius: var(--radius-sm); color: var(--color-danger); font-size: var(--text-md); }
.close-button { padding: 0; color: var(--color-muted); background: transparent; }
.tournament-grid { position: relative; display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-3); }
.tournament-card { min-height: 150px; padding: var(--space-5); border: 1px solid var(--color-line); border-radius: var(--radius-lg); background: linear-gradient(145deg, var(--color-surface), color-mix(in srgb, var(--color-surface-raised) 72%, transparent)); }
.tournament-card:hover { border-color: var(--color-accent); transform: translateY(-5px); box-shadow: 0 18px 36px color-mix(in srgb, var(--color-shadow) 20%, transparent); }
.tournament-card h3 { margin: var(--space-6) 0 var(--space-2); }
.tournament-card p { margin: 0; font-size: var(--text-md); }
.card-action { display: block; margin-top: var(--space-4); padding: 0; color: var(--color-accent); background: transparent; font-size: var(--text-xs); font-weight: 800; text-decoration: none; }
.card-action:hover:not(:disabled) { color: var(--color-ink); transform: translateX(3px); }
.card-action:disabled { cursor: wait; opacity: 0.6; }
.status-tag { color: var(--color-accent); font-size: var(--text-2xs); font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; }
@media (max-width: 760px) {
  .container { width: min(100% - 28px, 620px); }
  .section-heading, .section-actions { align-items: start; flex-direction: column; }
  .creation-fields { grid-template-columns: 1fr; }
  .tournament-grid { grid-template-columns: 1fr; }
}
@media (max-width: 480px) {
  .empty-state { align-items: stretch; flex-direction: column; }
}
</style>
