<script setup lang="ts">
const tournamentsStore = useTournamentsStore();
const config = useRuntimeConfig();
const { t, statusLabel } = useI18n();
const docsUrl = computed(() => config.public.apiBase.replace(/\/api\/v1\/?$/, '/docs'));

useHead(() => ({
  title: t('home.title'),
  meta: [
    {
      name: 'description',
      content: t('home.description'),
    },
    { property: 'og:title', content: t('home.title') },
    { property: 'og:description', content: t('home.ogDescription') },
    { property: 'og:type', content: 'website' },
  ],
}));

await callOnce('public-tournaments', () => tournamentsStore.loadPublic());
</script>

<template>
  <main id="main-content" class="page-shell">
    <header class="container topbar">
      <div class="brand-mark">
        <span class="brand-dot" aria-hidden="true" />
        <span>BRACKET CRAFT</span>
      </div>
      <NuxtLink to="/login" class="button-secondary">{{ t('common.login') }}</NuxtLink>
    </header>

    <section class="container hero">
      <div class="hero-copy">
         <p class="eyebrow">{{ t('home.eyebrow') }}</p>
         <h1>{{ t('home.headline') }}</h1>
        <p class="hero-lede">
           {{ t('home.lede') }}
        </p>
        <div class="hero-actions">
           <NuxtLink to="/login?mode=register" class="button-primary">{{ t('home.createTournament') }}</NuxtLink>
           <a class="button-secondary" :href="docsUrl">{{ t('home.documentation') }}</a>
        </div>
      </div>
      <div class="hero-card">
        <div class="card-caption">
           <span>{{ t('home.liveControl') }}</span>
           <span class="live-pill">● {{ t('home.live') }}</span>
        </div>
        <div class="scoreline">
          <div><strong>RIV</strong><span>2</span></div>
          <div class="match-minute">78:42</div>
          <div><span>1</span><strong>ATL</strong></div>
        </div>
         <div class="event-row"><span class="event-time">72'</span><span>{{ t('home.goal') }}</span><b>2-1</b></div>
         <div class="event-row"><span class="event-time">64'</span><span>{{ t('home.yellowCard') }}</span><b>{{ t('home.fairPlay') }}</b></div>
         <div class="card-footer"><span>{{ t('home.groupMatchday') }}</span><span>{{ t('home.rules') }}</span></div>
      </div>
    </section>

    <section class="container dashboard-preview">
      <div class="section-heading">
        <div>
           <p class="eyebrow">{{ t('home.workspace') }}</p>
           <h2>{{ t('home.recentTournaments') }}</h2>
        </div>
         <span v-if="tournamentsStore.publicLoading" class="muted" role="status">{{ t('common.loading') }}</span>
      </div>
      <Transition name="content-fade" mode="out-in">
        <div v-if="tournamentsStore.publicLoading" key="loading" class="empty-state loading-state" role="status">
          <span class="loading-orb" aria-hidden="true" />
           <span>{{ t('home.preparing') }}</span>
        </div>
         <div v-else-if="tournamentsStore.publicError" key="error" class="empty-state" role="alert">
           <span>{{ tournamentsStore.publicError }}</span>
           <button class="button-secondary" type="button" @click="tournamentsStore.loadPublic()">{{ t('common.retry') }}</button>
         </div>
        <div v-else-if="!tournamentsStore.publicTournaments.length" key="empty" class="empty-state">
           {{ t('home.emptyPublic') }}
        </div>
        <TransitionGroup v-else key="tournaments" name="card-list" tag="div" class="tournament-grid">
          <NuxtLink v-for="tournament in tournamentsStore.publicTournaments" :key="tournament.id" :to="`/tournaments/${tournament.id}`" class="tournament-card">
             <span class="status-tag">{{ statusLabel(tournament.status) }}</span>
            <h3>{{ tournament.name }}</h3>
            <p>{{ tournament.season }} · inicia {{ tournament.start_date }}</p>
            <span class="card-arrow" aria-hidden="true">↗</span>
          </NuxtLink>
         </TransitionGroup>
       </Transition>
       <div v-if="tournamentsStore.publicHasMore" class="load-more-row">
         <button class="button-secondary" type="button" :disabled="tournamentsStore.publicLoading" @click="tournamentsStore.loadMorePublic()">
           {{ tournamentsStore.publicLoading ? t('common.loading') : t('home.loadMore') }}
         </button>
       </div>
     </section>
  </main>
</template>

<style scoped>
.topbar { display: flex; align-items: center; justify-content: space-between; padding: 24px 0; }
.topbar, .hero-copy, .hero-card, .dashboard-preview { animation: rise-in 700ms var(--ease-out) both; }
.hero-card { animation-delay: 120ms; }
.dashboard-preview { animation-delay: 220ms; }
.brand-mark { display: flex; align-items: center; gap: 10px; font-size: 0.78rem; font-weight: 900; letter-spacing: 0.16em; }
.brand-dot { width: 11px; height: 11px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 24px var(--accent); }
.hero { display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, 0.78fr); align-items: center; gap: 8vw; padding: 10vh 0 14vh; }
.hero h1 { max-width: 720px; margin: 16px 0; font-size: clamp(3rem, 7vw, 6.8rem); line-height: 0.93; letter-spacing: -0.075em; }
.hero-lede { max-width: 520px; color: var(--muted); font-size: 1.12rem; line-height: 1.6; }
.hero-actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 30px; }
.hero-card { position: relative; overflow: hidden; padding: 22px; border: 1px solid var(--line); border-radius: 24px; background: linear-gradient(150deg, rgba(50, 62, 43, 0.9), rgba(20, 25, 19, 0.95)); box-shadow: var(--shadow-deep); transform: rotate(2deg); }
.hero-card::after { position: absolute; top: -90px; right: -90px; width: 220px; height: 220px; border: 1px solid rgba(212, 243, 106, 0.2); border-radius: 50%; content: ''; }
.card-caption, .card-footer, .event-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.card-caption, .card-footer { color: var(--muted); font-size: 0.7rem; letter-spacing: 0.1em; text-transform: uppercase; }
.live-pill { color: var(--accent); }
.scoreline { display: flex; align-items: center; justify-content: space-between; padding: 52px 0 40px; font-size: 2rem; }
.scoreline div:not(.match-minute) { display: flex; align-items: center; gap: 18px; }
.scoreline span { color: var(--accent); font-size: 4rem; font-weight: 900; }
.match-minute { color: var(--muted); font-size: 0.8rem; }
.event-row { padding: 15px 0; border-top: 1px solid rgba(166, 170, 159, 0.15); font-size: 0.85rem; }
.event-time { color: var(--accent); font-weight: 800; }
.event-row b { color: var(--muted); font-size: 0.7rem; }
.card-footer { padding-top: 20px; }
.dashboard-preview { padding-bottom: 80px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
.section-heading h2 { margin: 8px 0 0; font-size: 2rem; letter-spacing: -0.05em; }
.muted, .empty-state, .tournament-card p { color: var(--muted); }
.empty-state { padding: 28px; border: 1px dashed var(--line); border-radius: 16px; }
.empty-state { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.load-more-row { display: flex; justify-content: center; margin-top: 22px; }
.loading-state { display: flex; align-items: center; gap: 12px; }
.loading-orb { width: 9px; height: 9px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 18px var(--accent); animation: pulse 1s ease-in-out infinite; }
.tournament-grid { position: relative; display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.tournament-card { position: relative; min-height: 150px; padding: 20px; border: 1px solid var(--line); border-radius: 18px; background: linear-gradient(145deg, var(--surface), rgba(32, 37, 30, 0.72)); color: var(--ink); text-decoration: none; }
.tournament-card:hover { border-color: var(--accent); background: var(--surface-raised); transform: translateY(-5px); box-shadow: 0 18px 36px rgba(0, 0, 0, 0.2); }
.tournament-card h3 { margin: 28px 0 8px; }
.tournament-card p { margin: 0; font-size: 0.9rem; }
.status-tag { color: var(--accent); font-size: 0.7rem; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; }
.card-arrow { position: absolute; right: 18px; bottom: 16px; color: var(--accent); font-size: 1.15rem; opacity: 0.65; transform: translate(0, 0); }
.tournament-card:hover .card-arrow { opacity: 1; transform: translate(3px, -3px); }

@media (max-width: 800px) {
  .container { width: min(100% - 28px, 620px); }
  .hero { grid-template-columns: 1fr; gap: 48px; padding-top: 8vh; }
  .hero h1 { font-size: clamp(3rem, 15vw, 5.5rem); }
  .hero-card { transform: none; }
  .tournament-grid { grid-template-columns: 1fr; }
}
@media (max-width: 375px) {
  .topbar { align-items: stretch; flex-direction: column; gap: 14px; }
  .topbar > * { justify-content: center; text-align: center; }
  .empty-state { align-items: stretch; flex-direction: column; }
}
</style>
