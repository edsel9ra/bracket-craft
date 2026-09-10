<script setup lang="ts">
import { isForbidden, isNotFound, isUnauthorized } from '~/utils/api';

definePageMeta({ middleware: 'auth' });

const auth = useAuthStore();
const tournamentsStore = useTournamentsStore();
const realtime = useRealtime();
const { request } = useApi();
const { t, statusLabel, errorMessage } = useI18n();
const workspaceError = ref<string | null>(null);
const showCreateForm = ref(false);
const creating = ref(false);
const createError = ref<string | null>(null);
const publishingTournamentId = ref<string | null>(null);
let realtimeRefreshPending = false;
const createForm = reactive({
  name: '',
  season: '',
  start_date: '',
});
let disposed = false;

useHead({
  meta: [{ name: 'robots', content: 'noindex, nofollow' }],
});

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

async function refreshWorkspace() {
  if (realtimeRefreshPending || disposed) return;
  realtimeRefreshPending = true;
  try {
    await tournamentsStore.load();
  } catch (cause) {
    await redirectOnSessionFailure(cause);
  } finally {
    realtimeRefreshPending = false;
  }
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
      if (['MATCH_CLOSED', 'MATCH_UPDATED', 'STANDINGS_UPDATED'].includes(event)) void refreshWorkspace();
    },
  });
}

const realtimeStatusLabel = computed(() => {
  if (realtime.status.value === 'connected') return t('workspace.realtimeConnected');
  if (realtime.status.value === 'reconnecting') return t('workspace.realtimeReconnecting');
  if (realtime.status.value === 'error') return t('workspace.realtimeError');
  return t('workspace.activeOperation');
});

async function createTournament() {
  creating.value = true;
  createError.value = null;
  try {
    await request('/tournaments', {
      method: 'POST',
      body: createForm,
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
  if (import.meta.client && !window.confirm(t('workspace.confirmPublish'))) return;
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
          <button v-if="realtime.status.value === 'error'" class="realtime-retry" type="button" @click="connectRealtime">{{ t('common.retry') }}</button>
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
             <button v-if="!showCreateForm" class="button-primary" type="button" @click="openCreateForm">
             {{ t('workspace.newTournament') }}
          </button>
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
             <label>
                {{ t('workspace.name') }}
               <input v-model="createForm.name" type="text" minlength="2" maxlength="100" required />
             </label>
             <label>
                {{ t('workspace.season') }}
               <input v-model="createForm.season" type="text" maxlength="20" required />
             </label>
             <label>
                {{ t('workspace.start') }}
               <input v-model="createForm.start_date" type="date" required />
             </label>
           </div>
           <div v-if="createError" class="form-error" role="alert">{{ createError }}</div>
           <button class="button-primary" type="submit" :disabled="creating">
              {{ creating ? t('workspace.creating') : t('workspace.createDraft') }}
           </button>
         </form>
       </Transition>
       <Transition name="content-fade" mode="out-in">
          <div v-if="workspaceError" key="workspace-error" class="empty-state" role="alert">
            <span>{{ workspaceError }}</span>
            <button class="button-secondary" type="button" @click="retryWorkspace">{{ t('common.retry') }}</button>
          </div>
          <div v-else-if="tournamentsStore.error" key="store-error" class="empty-state" role="alert">
            <span>{{ tournamentsStore.error }}</span>
            <button class="button-secondary" type="button" @click="tournamentsStore.load()">{{ t('common.retry') }}</button>
          </div>
         <div v-else-if="!tournamentsStore.loading && !tournamentsStore.tournaments.length" key="empty" class="empty-state">
            {{ t('workspace.empty') }}
         </div>
         <TransitionGroup v-else key="tournaments" name="card-list" tag="div" class="tournament-grid">
           <article v-for="tournament in tournamentsStore.tournaments" :key="tournament.id" class="tournament-card">
              <span class="status-tag">{{ statusLabel(tournament.status) }}</span>
             <h3>{{ tournament.name }}</h3>
             <p>{{ tournament.season }} · inicia {{ tournament.start_date }}</p>
              <NuxtLink class="card-action" :to="`/workspace/tournaments/${tournament.id}`">{{ t('workspace.configure') }} <span aria-hidden="true">↗</span></NuxtLink>
             <button
               v-if="tournament.status === 'draft' && tournament.draft_version_id"
               class="card-action"
               type="button"
               :disabled="publishingTournamentId === tournament.id"
               @click="publishTournament(tournament)"
             >
                {{ publishingTournamentId === tournament.id ? t('workspace.publishing') : t('workspace.publish') }}
             </button>
           </article>
          </TransitionGroup>
        </Transition>
        <div v-if="tournamentsStore.hasMore" class="load-more-row">
           <button class="button-secondary" type="button" :disabled="tournamentsStore.loading" @click="loadMoreTournaments">
            {{ tournamentsStore.loading ? t('common.loading') : t('workspace.loadMore') }}
          </button>
        </div>
      </section>
   </main>
  </WorkspaceShell>
</template>

<style scoped>
.workspace-shell { min-height: 100vh; background: radial-gradient(circle at 90% 8%, rgba(212, 243, 106, 0.08), transparent 28rem), #0c0f0c; }
.workspace-hero { padding: 5vh 0 5vh; animation: rise-in 700ms var(--ease-out) both; }
.hero-line { display: flex; align-items: center; gap: 18px; }
.live-status { display: inline-flex; align-items: center; gap: 7px; color: var(--muted); font-size: 0.7rem; letter-spacing: 0.1em; text-transform: uppercase; }
.live-status span { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 12px var(--accent); }
.live-status.realtime-reconnecting span, .live-status.realtime-error span { background: #ffcb7a; box-shadow: 0 0 12px rgba(255, 203, 122, 0.7); }
.realtime-retry { padding: 0; background: transparent; color: var(--accent); font-size: 0.7rem; text-decoration: underline; }
.workspace-hero h1 { max-width: 760px; margin: 14px 0; font-size: clamp(2.5rem, 6vw, 5.5rem); line-height: 0.92; letter-spacing: -0.08em; }
.workspace-copy { max-width: 520px; color: var(--muted); font-size: 1.1rem; line-height: 1.6; }
.workspace-content { padding-bottom: 80px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
.section-actions { display: flex; align-items: center; gap: 14px; }
.section-heading h2 { margin: 8px 0 0; font-size: 2rem; letter-spacing: -0.05em; }
.muted, .empty-state, .tournament-card p { color: var(--muted); }
.empty-state { padding: 28px; border: 1px dashed var(--line); border-radius: 16px; }
.empty-state { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.load-more-row { display: flex; justify-content: center; margin-top: 22px; }
.creation-panel { display: grid; gap: 20px; margin-bottom: 28px; padding: 22px; border: 1px solid var(--line); border-radius: 18px; background: linear-gradient(145deg, var(--surface-raised), rgba(21, 24, 20, 0.9)); box-shadow: 0 18px 50px rgba(0, 0, 0, 0.16); }
.creation-heading { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
.creation-heading h3 { margin: 8px 0 0; }
.creation-fields { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 14px; }
label { display: grid; gap: 7px; color: var(--muted); font-size: 0.82rem; }
input { width: 100%; padding: 0.82rem 0.9rem; border: 1px solid var(--line); border-radius: 10px; background: #0c0f0c; color: var(--ink); }
.form-error { padding: 12px; border: 1px solid #a45b5b; border-radius: 10px; color: #ffb0a8; font-size: 0.85rem; }
.close-button { padding: 0; color: var(--muted); background: transparent; }
.tournament-grid { position: relative; display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.tournament-card { min-height: 150px; padding: 20px; border: 1px solid var(--line); border-radius: 18px; background: linear-gradient(145deg, var(--surface), rgba(32, 37, 30, 0.72)); }
.tournament-card:hover { border-color: var(--accent); transform: translateY(-5px); box-shadow: 0 18px 36px rgba(0, 0, 0, 0.2); }
.tournament-card h3 { margin: 28px 0 8px; }
.tournament-card p { margin: 0; font-size: 0.9rem; }
.card-action { display: block; margin-top: 18px; padding: 0; color: var(--accent); background: transparent; font-size: 0.78rem; font-weight: 800; text-decoration: none; }
.card-action:hover:not(:disabled) { color: var(--ink); transform: translateX(3px); }
.card-action:disabled { cursor: wait; opacity: 0.6; }
.status-tag { color: var(--accent); font-size: 0.7rem; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; }
@media (max-width: 800px) {
  .container { width: min(100% - 28px, 620px); }
  .section-heading, .section-actions { align-items: start; flex-direction: column; }
  .creation-fields { grid-template-columns: 1fr; }
  .tournament-grid { grid-template-columns: 1fr; }
}
@media (max-width: 375px) {
  .empty-state { align-items: stretch; flex-direction: column; }
}
</style>
