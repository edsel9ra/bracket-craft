<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import StatusPill from '~/components/ui/StatusPill.vue';
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
      <Button as="NuxtLink" to="/login" variant="secondary">{{ t('common.login') }}</Button>
    </header>

    <section class="container hero">
      <div class="hero-copy">
         <p class="eyebrow">{{ t('home.eyebrow') }}</p>
         <h1>{{ t('home.headline') }}</h1>
        <p class="hero-lede">
           {{ t('home.lede') }}
        </p>
        <div class="hero-actions">
           <a href="#public-tournaments" class="public-browse">{{ t('home.browseTournaments') }}</a>
           <Button as="NuxtLink" to="/login?mode=register" variant="secondary">{{ t('home.createTournament') }}</Button>
           <Button as="NuxtLink" variant="secondary" :to="docsUrl">{{ t('home.documentation') }}</Button>
        </div>
      </div>
      <Surface class="hero-card">
        <div class="card-caption">
           <span>{{ t('home.liveControl') }}</span>
           <StatusPill class="example-score">{{ t('home.exampleScore') }}</StatusPill>
        </div>
        <div class="scoreline">
          <div><strong>RIV</strong><span>2</span></div>
          <div class="match-minute">78:42</div>
          <div><span>1</span><strong>ATL</strong></div>
        </div>
         <div class="event-row"><span class="event-time">72'</span><span>{{ t('home.goal') }}</span><b>2-1</b></div>
         <div class="event-row"><span class="event-time">64'</span><span>{{ t('home.yellowCard') }}</span><b>{{ t('home.fairPlay') }}</b></div>
         <div class="card-footer"><span>{{ t('home.groupMatchday') }}</span><span>{{ t('home.rules') }}</span></div>
      </Surface>
    </section>

    <section id="public-tournaments" class="container dashboard-preview" tabindex="-1">
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
           <Button variant="secondary" @click="tournamentsStore.loadPublic()">{{ t('common.retry') }}</Button>
         </div>
        <div v-else-if="!tournamentsStore.publicTournaments.length" key="empty" class="empty-state">
           {{ t('home.emptyPublic') }}
        </div>
        <TransitionGroup v-else key="tournaments" name="card-list" tag="div" class="tournament-grid">
          <NuxtLink v-for="tournament in tournamentsStore.publicTournaments" :key="tournament.id" :to="`/tournaments/${tournament.id}`" class="tournament-card">
             <StatusPill class="status-tag">{{ statusLabel(tournament.status) }}</StatusPill>
            <h3>{{ tournament.name }}</h3>
            <p>{{ tournament.season }} · {{ t('public.starts') }} {{ tournament.start_date }}</p>
            <span class="card-arrow" aria-hidden="true">↗</span>
          </NuxtLink>
         </TransitionGroup>
       </Transition>
       <div v-if="tournamentsStore.publicHasMore" class="load-more-row">
         <Button variant="secondary" :disabled="tournamentsStore.publicLoading" @click="tournamentsStore.loadMorePublic()">
           {{ tournamentsStore.publicLoading ? t('common.loading') : t('home.loadMore') }}
         </Button>
       </div>
     </section>
  </main>
</template>

<style scoped>
/* RF-006/VI-1: composición proporcional del hero, título móvil y cifra ilustrada de 4rem fuera de escala. */
.topbar { display: flex; align-items: center; justify-content: space-between; padding: var(--space-6) 0; }
.topbar, .hero-copy, .hero-card, .dashboard-preview { animation: rise-in 700ms var(--ease-out) both; }
.hero-card { animation-delay: 120ms; }
.dashboard-preview { animation-delay: 220ms; }
.brand-mark { display: flex; align-items: center; gap: var(--space-2); font-size: var(--text-xs); font-weight: 900; letter-spacing: 0.16em; }
.brand-dot { width: 11px; height: 11px; border-radius: 50%; background: var(--color-accent); box-shadow: 0 0 24px var(--color-accent); }
.hero { display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, 0.78fr); align-items: center; gap: 8vw; padding: 10vh 0 14vh; }
.hero h1 { max-width: 720px; margin: var(--space-4) 0; font-size: var(--text-display); line-height: 0.93; letter-spacing: -0.075em; }
.hero-lede { max-width: 520px; color: var(--color-muted); font-size: var(--text-base); line-height: 1.6; }
.hero-actions { display: flex; flex-wrap: wrap; gap: var(--space-3); margin-top: var(--space-7); }
.hero-card { position: relative; overflow: hidden; padding: var(--space-5); border: 1px solid var(--color-line); border-radius: var(--radius-lg); background: linear-gradient(150deg, color-mix(in srgb, var(--color-surface-bright) 90%, transparent), color-mix(in srgb, var(--color-surface) 95%, transparent)); box-shadow: var(--shadow-deep); transform: rotate(2deg); }
.hero-card::after { position: absolute; top: -90px; right: -90px; width: 220px; height: 220px; border: 1px solid color-mix(in srgb, var(--color-accent) 20%, transparent); border-radius: 50%; content: ''; }
.card-caption, .card-footer, .event-row { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); }
.card-caption, .card-footer { color: var(--color-muted); font-size: var(--text-2xs); letter-spacing: 0.1em; text-transform: uppercase; }
.public-browse { display: inline-flex; align-items: center; justify-content: center; padding: var(--space-3) var(--space-4); border: 1px solid transparent; border-radius: var(--radius-pill); background: var(--color-accent); color: var(--color-accent-ink); font-weight: var(--weight-lg); text-decoration: none; }
.public-browse:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 4px; }
#public-tournaments { scroll-margin-top: var(--space-6); }
.topbar :deep(.ui-button), .hero-actions :deep(.ui-button) { font-size: var(--text-base); }
.topbar :deep(.ui-button-secondary), .hero-actions :deep(.ui-button-secondary) { background: transparent; border-color: var(--color-line); }
.scoreline { display: flex; align-items: center; justify-content: space-between; padding: var(--space-8) 0 var(--space-7); font-size: var(--text-xl); }
.scoreline div:not(.match-minute) { display: flex; align-items: center; gap: var(--space-4); }
.scoreline span { color: var(--color-accent); font-size: 4rem; font-weight: 900; }
.match-minute { color: var(--color-muted); font-size: var(--text-sm); }
.event-row { padding: var(--space-4) 0; border-top: 1px solid color-mix(in srgb, var(--color-muted) 15%, transparent); font-size: var(--text-md); }
.event-time { color: var(--color-accent); font-weight: 800; }
.event-row b { color: var(--color-muted); font-size: var(--text-2xs); }
.card-footer { padding-top: var(--space-5); }
.dashboard-preview { padding-bottom: var(--space-10); }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: var(--space-4); margin-bottom: var(--space-5); }
.section-heading h2 { margin: var(--space-2) 0 0; font-size: var(--text-xl); letter-spacing: -0.05em; }
.muted, .empty-state, .tournament-card p { color: var(--color-muted); }
.empty-state { padding: var(--space-6); border: 1px dashed var(--color-line); border-radius: var(--radius-md); }
.empty-state { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.load-more-row { display: flex; justify-content: center; margin-top: var(--space-5); }
.loading-state { display: flex; align-items: center; gap: var(--space-3); }
.loading-orb { width: 9px; height: 9px; border-radius: 50%; background: var(--color-accent); box-shadow: 0 0 18px var(--color-accent); animation: pulse 1s ease-in-out infinite; }
.tournament-grid { position: relative; display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-3); }
.tournament-card { position: relative; min-height: 150px; padding: var(--space-5); border: 1px solid var(--color-line); border-radius: var(--radius-lg); background: linear-gradient(145deg, var(--color-surface), color-mix(in srgb, var(--color-surface-raised) 72%, transparent)); color: var(--color-ink); text-decoration: none; }
.tournament-card:hover { border-color: var(--color-accent); background: var(--color-surface-raised); transform: translateY(-5px); box-shadow: 0 18px 36px color-mix(in srgb, var(--color-shadow) 20%, transparent); }
.tournament-card h3 { margin: var(--space-6) 0 var(--space-2); }
.tournament-card p { margin: 0; font-size: var(--text-md); }
.status-tag { color: var(--color-accent); font-size: var(--text-2xs); font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; }
.card-arrow { position: absolute; right: 18px; bottom: 16px; color: var(--color-accent); font-size: var(--text-lg); opacity: 0.65; transform: translate(0, 0); }
.tournament-card:hover .card-arrow { opacity: 1; transform: translate(3px, -3px); }

@media (max-width: 760px) {
  .container { width: min(100% - 28px, 620px); }
  .hero { grid-template-columns: 1fr; gap: var(--space-8); padding-top: 8vh; }
  .hero h1 { font-size: clamp(3rem, 15vw, 5.5rem); }
  .hero-card { transform: none; }
  .tournament-grid { grid-template-columns: 1fr; }
}
@media (max-width: 480px) {
  .topbar { flex-wrap: wrap; gap: var(--space-3); }
  .topbar > * { justify-content: center; text-align: center; }
  .empty-state { align-items: stretch; flex-direction: column; }
}
</style>
