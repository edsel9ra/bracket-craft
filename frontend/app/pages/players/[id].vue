<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import HorizontalScroll from '~/components/ui/HorizontalScroll.vue';
import { isNotFound } from '~/utils/api';
import {
  PROFILE_STAT_FIELDS,
  isPlayerProfileId,
  playerProfileApiPath,
  playerProfileInitials,
  playerProfileName,
  profilePhotoVisible,
  type PublicPlayerProfile,
} from '~/utils/publicPlayerProfile';

const route = useRoute();
const { request } = useApi();
const { t } = useI18n();
const playerId = String(route.params.id);
const validId = isPlayerProfileId(playerId);

const { data: profile, status, error: dataError, refresh } = await useAsyncData<PublicPlayerProfile | null>(
  `public-player-${playerId}`,
  async () => (validId ? request<PublicPlayerProfile>(playerProfileApiPath(playerId)) : null),
);

const loading = computed(() => status.value === 'pending');
// RF-002: un identificador mal formado se muestra igual que una ficha inexistente.
const notFound = computed(() => !validId || (Boolean(dataError.value) && isNotFound(dataError.value)));
const failed = computed(() => Boolean(dataError.value) && !notFound.value);
const playerName = computed(() => (profile.value ? playerProfileName(profile.value) : ''));
const initials = computed(() => (profile.value ? playerProfileInitials(profile.value) : ''));
const failedPhotoUrl = ref<string | null>(null);
const showPhoto = computed(() => Boolean(profile.value && profilePhotoVisible(profile.value, failedPhotoUrl.value)));

function markPhotoFailed() {
  failedPhotoUrl.value = profile.value?.photo_url ?? null;
}

useHead(() => ({
  title: playerName.value
    ? t('publicPlayer.title', { name: playerName.value })
    : `${t('publicPlayer.eyebrow')} | Bracket Craft`,
}));
</script>

<template>
  <main id="main-content" class="public-shell">
    <header class="container detail-topbar">
      <NuxtLink to="/" class="brand-mark"><span class="brand-dot" aria-hidden="true" /> BRACKET CRAFT</NuxtLink>
      <NuxtLink to="/login" class="button-secondary">{{ t('common.login') }}</NuxtLink>
    </header>

    <div v-if="loading" class="container profile-state" role="status">{{ t('publicPlayer.loading') }}</div>
    <div v-else-if="notFound" class="container profile-state" role="alert">
      <p>{{ t('publicPlayer.notFound') }}</p>
      <NuxtLink to="/" class="profile-link">{{ t('publicPlayer.backHome') }}</NuxtLink>
    </div>
    <div v-else-if="failed" class="container profile-state" role="alert">
      <p>{{ t('publicPlayer.error') }}</p>
      <Button variant="secondary" class="button-secondary" type="button" @click="refresh()">{{ t('common.retry') }}</Button>
    </div>
    <div v-else-if="profile" class="container profile-content">
      <section class="profile-hero">
        <img
          v-if="showPhoto"
          class="profile-photo"
          :src="profile.photo_url ?? ''"
          :alt="playerName"
          decoding="async"
          @error="markPhotoFailed"
        >
        <span v-else class="profile-photo profile-photo--initials" role="img" :aria-label="playerName">{{ initials }}</span>
        <div class="profile-heading">
          <p class="eyebrow">{{ t('publicPlayer.eyebrow') }}</p>
          <h1>{{ playerName }}</h1>
          <p class="muted">{{ t('publicPlayer.scope') }}</p>
        </div>
      </section>

      <Surface class="panel">
        <h2>{{ t('publicPlayer.totals') }}</h2>
        <dl class="profile-totals">
          <div v-for="field in PROFILE_STAT_FIELDS" :key="field.key" class="profile-total">
            <dt>{{ t(field.label) }}</dt>
            <dd>{{ profile.totals[field.key] }}</dd>
          </div>
        </dl>
      </Surface>

      <Surface class="panel">
        <h2>{{ t('publicPlayer.career') }}</h2>
        <HorizontalScroll :label="t('publicPlayer.career')">
          <table>
            <caption class="visually-hidden">{{ t('publicPlayer.career') }}</caption>
            <thead>
              <tr>
                <th scope="col">{{ t('publicPlayer.tournament') }}</th>
                <th scope="col">{{ t('public.team') }}</th>
                <th v-for="field in PROFILE_STAT_FIELDS" :key="field.key" scope="col">{{ t(field.label) }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in profile.tournaments" :key="row.tournament_id">
                <th scope="row"><NuxtLink class="profile-link" :to="`/tournaments/${row.tournament_id}`">{{ row.tournament_name }}</NuxtLink></th>
                <td>{{ row.team_name }}</td>
                <td v-for="field in PROFILE_STAT_FIELDS" :key="field.key">{{ row[field.key] }}</td>
              </tr>
            </tbody>
          </table>
        </HorizontalScroll>
      </Surface>
    </div>
  </main>
</template>

<style scoped>
.public-shell { min-height: 100vh; padding-bottom: var(--space-10); background: var(--color-canvas); }
.detail-topbar { display: flex; justify-content: space-between; align-items: center; padding: var(--space-6) 0; }
.brand-mark { display: inline-flex; align-items: center; gap: var(--space-2); color: var(--color-ink); font-size: var(--text-xs); font-weight: 900; letter-spacing: 0.16em; text-decoration: none; }
.brand-mark:hover { color: var(--color-accent); }
.brand-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--color-accent); }
.profile-state { display: grid; justify-items: start; gap: var(--space-3); padding: var(--space-8) 0; color: var(--color-muted); }
.profile-state p { margin: 0; }
.profile-content { display: grid; gap: var(--space-5); }
.profile-hero { display: flex; align-items: center; gap: var(--space-5); padding: var(--space-6) 0; min-width: 0; }
.profile-heading { min-width: 0; }
.profile-heading h1 { margin: var(--space-2) 0; font-size: var(--text-display); line-height: 1; letter-spacing: -0.06em; overflow-wrap: anywhere; }
.profile-heading p.muted { margin: 0; font-size: var(--text-sm); }
.profile-photo { width: 6rem; height: 6rem; flex-shrink: 0; border-radius: 50%; object-fit: cover; background: var(--color-surface-raised); }
.profile-photo--initials { display: inline-flex; align-items: center; justify-content: center; border: 1px solid var(--color-line); color: var(--color-avatar-ink); font-size: var(--text-xl); font-weight: 800; }
.eyebrow { margin: 0; color: var(--color-accent); font-size: var(--text-2xs); font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; }
.muted { color: var(--color-muted); }
.panel { min-width: 0; padding: var(--space-5); }
.panel h2 { margin: 0 0 var(--space-4); font-size: var(--text-xl); letter-spacing: -0.04em; }
.profile-totals { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: var(--space-3); margin: 0; }
.profile-total { min-width: 0; padding: var(--space-3); border: 1px solid var(--color-line); border-radius: var(--radius-md); }
.profile-total dt { color: var(--color-muted); font-size: var(--text-2xs); font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; overflow-wrap: anywhere; }
.profile-total dd { margin: var(--space-1) 0 0; font-size: var(--text-xl); font-weight: 800; font-variant-numeric: tabular-nums; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
thead th { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--color-line); color: var(--color-muted); font-size: var(--text-2xs); font-weight: 700; letter-spacing: 0.08em; text-align: left; text-transform: uppercase; white-space: nowrap; }
tbody th, tbody td { padding: var(--space-3); border-bottom: 1px solid var(--color-line); font-size: var(--text-md); text-align: left; }
thead th:nth-child(n+3), tbody td:nth-child(n+3) { text-align: right; }
tbody th { font-weight: 700; overflow-wrap: anywhere; }
.profile-link { color: var(--color-accent); text-underline-offset: var(--space-1); }
.profile-link:focus-visible, .brand-mark:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 4px; }
@media (max-width: 760px) {
  .profile-hero { align-items: flex-start; gap: var(--space-4); }
  .profile-photo { width: 4rem; height: 4rem; }
  .profile-totals { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  table { min-width: 640px; }
}
</style>
