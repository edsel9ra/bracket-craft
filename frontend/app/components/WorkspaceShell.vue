<script setup lang="ts">
import ThemeSwitcher from '~/components/ThemeSwitcher.vue';
import { isForbidden, isNotFound, isUnauthorized } from '~/utils/api';
import { safeInternalRedirect } from '~/utils/navigation';
import {
  matchIdFromPath,
  tournamentSectionForPath,
  tournamentSectionHref,
  type TournamentSection,
} from '~/utils/tournamentNavigation';

export interface WorkspaceBreadcrumb {
  label: string;
  to?: string;
  current?: boolean;
}

export interface WorkspaceTournament {
  id: string;
  name?: string | null;
}

const props = withDefaults(defineProps<{
  breadcrumbs?: WorkspaceBreadcrumb[];
  tournament?: WorkspaceTournament | null;
}>(), {
  breadcrumbs: () => [],
  tournament: null,
});

const route = useRoute();
const auth = useAuthStore();
const tournamentsStore = useTournamentsStore();
const { request } = useApi();
const { t, errorMessage } = useI18n();

const mobileMenuOpen = ref(false);
const accountMenuOpen = ref(false);
const switchingOrganization = ref(false);
const organizationError = ref<string | null>(null);
const platformAccess = useState<'unknown' | 'allowed' | 'denied'>('workspace-platform-access', () => 'unknown');

const isAdminRoute = computed(() => route.path === '/admin' || route.path.startsWith('/admin/'));
const showAdminLink = computed(() => isAdminRoute.value || platformAccess.value === 'allowed');
const canManageMembers = computed(() => auth.hasPermission('MANAGE_MEMBERS'));
const activeSection = computed<TournamentSection>(() => tournamentSectionForPath(route.path, route.hash));
const matchId = computed(() => matchIdFromPath(route.path));
const organizationName = computed(() => {
  const active = auth.organizations.find((organization: { id: string; name: string }) => organization.id === auth.organizationId);
  return active?.name || auth.organizations[0]?.name || t('shell.organization');
});
const tournamentLabel = computed(() => {
  if (!props.tournament) return '';
  return props.tournament.name
    || tournamentsStore.tournaments.find((candidate) => candidate.id === props.tournament?.id)?.name
    || t('shell.tournament');
});

const primaryLinks = computed(() => [
  {
    key: 'tournaments',
    label: t('shell.tournaments'),
    to: '/workspace',
     current: route.path === '/workspace'
       || route.path.startsWith('/workspace/tournaments/')
       || route.path.startsWith('/workspace/matches/'),
   },
   ...(canManageMembers.value
     ? [{ key: 'members', label: t('shell.members'), to: '/workspace/members', current: route.path === '/workspace/members' }]
     : []),
  ...(showAdminLink.value
    ? [{ key: 'administration', label: t('shell.administration'), to: '/admin', current: isAdminRoute.value }]
    : []),
]);

const tournamentLinks = computed(() => {
  const tournament = props.tournament;
  if (!tournament?.id) return [];
  const sections: Array<{ key: TournamentSection; label: string }> = [
    { key: 'summary', label: t('shell.summary') },
    { key: 'configuration', label: t('shell.configuration') },
    { key: 'calendar', label: t('shell.calendar') },
    { key: 'rosters', label: t('shell.rosters') },
    { key: 'operation', label: t('shell.operation') },
  ];
  return sections.flatMap((section) => {
    const to = tournamentSectionHref(section.key, {
      tournamentId: tournament.id,
      matchId: matchId.value,
    });
    return to ? [{ ...section, to }] : [];
  });
});

async function resolvePlatformAccess() {
  if (isAdminRoute.value || platformAccess.value !== 'unknown') return;
  try {
    const access = await request<{ allowed: boolean }>('/platform/access');
    platformAccess.value = access.allowed ? 'allowed' : 'denied';
  } catch (cause) {
    if (isUnauthorized(cause) || isForbidden(cause)) platformAccess.value = 'denied';
  }
}

async function switchOrganization(event: Event) {
  const nextOrganizationId = (event.target as HTMLSelectElement).value;
  const previousOrganizationId = auth.organizationId;
  if (!nextOrganizationId || nextOrganizationId === previousOrganizationId) return;

  switchingOrganization.value = true;
  organizationError.value = null;
  tournamentsStore.clear();
  auth.organizationId = nextOrganizationId;

  try {
    await auth.verifyWorkspace();
    if (route.path === '/workspace') {
      await tournamentsStore.load();
    } else {
      await navigateTo('/workspace');
    }
  } catch (cause) {
    if (isUnauthorized(cause) || isNotFound(cause)) {
      await auth.logout();
      await navigateTo({ path: '/login', query: { redirect: safeInternalRedirect(route.fullPath, '/workspace') } });
      return;
    }

    auth.organizationId = previousOrganizationId;
    await auth.verifyWorkspace().catch(() => undefined);
    organizationError.value = errorMessage(cause, t('shell.organizationSwitchError'));
    if (route.path === '/workspace') await tournamentsStore.load().catch(() => undefined);
  } finally {
    switchingOrganization.value = false;
  }
}

async function logout() {
  await auth.logout();
  await navigateTo('/');
}

function closeMenus() {
  mobileMenuOpen.value = false;
  accountMenuOpen.value = false;
}

async function navigateTournamentSection(event: Event) {
  const section = (event.target as HTMLSelectElement).value as TournamentSection;
  const link = tournamentLinks.value.find((candidate) => candidate.key === section);
  if (link) await navigateTo(link.to);
}

watch(() => route.fullPath, closeMenus);

onMounted(() => {
  if (auth.userId && !auth.organizations.length) void auth.loadOrganizations().catch(() => undefined);
  const currentTournament = props.tournament;
  if (currentTournament?.id && !currentTournament.name && !tournamentsStore.tournaments.length) {
    void tournamentsStore.load().catch(() => undefined);
  }
  void resolvePlatformAccess();
});
</script>

<template>
  <div class="workspace-shell-root">
    <header class="workspace-topbar">
      <div class="container workspace-topbar-inner">
        <NuxtLink to="/workspace" class="workspace-brand" aria-label="Bracket Craft">
          <span class="workspace-brand-dot" aria-hidden="true" />
          <span>BRACKET CRAFT</span>
        </NuxtLink>

        <nav class="workspace-primary-nav" :aria-label="t('shell.primaryNavigation')">
          <NuxtLink
            v-for="link in primaryLinks"
            :key="link.key"
            :to="link.to"
            class="workspace-nav-link"
            :aria-current="link.current ? 'page' : undefined"
          >{{ link.label }}</NuxtLink>
        </nav>

        <div class="workspace-desktop-controls">
          <div class="workspace-organization">
            <span class="workspace-control-label">{{ t('shell.organization') }}</span>
            <select
              v-if="auth.organizations.length > 1"
              class="workspace-organization-select"
              :value="auth.organizationId || ''"
              :disabled="switchingOrganization"
              :aria-label="t('workspace.activeOrganization')"
              @change="switchOrganization"
            >
              <option v-for="organization in auth.organizations" :key="organization.id" :value="organization.id">
                {{ organization.name }}
              </option>
            </select>
            <span v-else class="workspace-organization-name">{{ organizationName }}</span>
          </div>
          <LanguageSwitcher id="workspace-language-desktop" :inline="true" />
          <ThemeSwitcher :inline="true" />
          <div class="workspace-account">
            <button
              class="workspace-account-button"
              type="button"
              :aria-expanded="accountMenuOpen"
              aria-haspopup="menu"
              @click="accountMenuOpen = !accountMenuOpen"
              @keydown.esc="accountMenuOpen = false"
            >
              {{ t('shell.account') }} <span aria-hidden="true">v</span>
            </button>
            <div v-if="accountMenuOpen" class="workspace-account-menu" role="menu">
              <NuxtLink to="/account/google" role="menuitem" @click="accountMenuOpen = false">{{ t('google.link.title') }}</NuxtLink>
              <button type="button" role="menuitem" @click="logout">{{ t('common.logout') }}</button>
            </div>
          </div>
        </div>

        <button
          class="workspace-menu-toggle"
          type="button"
          :aria-expanded="mobileMenuOpen"
          :aria-controls="'workspace-mobile-menu'"
          @click="mobileMenuOpen = !mobileMenuOpen"
        >
          <span class="workspace-menu-icon" aria-hidden="true"><i /><i /></span>
          {{ mobileMenuOpen ? t('shell.closeMenu') : t('shell.menu') }}
        </button>
      </div>

      <div v-if="mobileMenuOpen" id="workspace-mobile-menu" class="workspace-mobile-menu">
        <div class="container workspace-mobile-menu-inner">
          <nav class="workspace-mobile-nav" :aria-label="t('shell.primaryNavigation')">
            <NuxtLink
              v-for="link in primaryLinks"
              :key="`mobile-${link.key}`"
              :to="link.to"
              class="workspace-mobile-link"
              :aria-current="link.current ? 'page' : undefined"
              @click="closeMenus"
            >{{ link.label }}</NuxtLink>
          </nav>

          <div class="workspace-mobile-controls">
            <label class="workspace-mobile-organization">
              <span>{{ t('shell.organization') }}</span>
              <select
                v-if="auth.organizations.length > 1"
                :value="auth.organizationId || ''"
                :disabled="switchingOrganization"
                :aria-label="t('workspace.activeOrganization')"
                @change="switchOrganization"
              >
                <option v-for="organization in auth.organizations" :key="organization.id" :value="organization.id">
                  {{ organization.name }}
                </option>
              </select>
              <strong v-else>{{ organizationName }}</strong>
            </label>
            <div class="workspace-mobile-preferences">
              <LanguageSwitcher id="workspace-language-mobile" :inline="true" />
              <ThemeSwitcher :inline="true" />
            </div>
            <div class="workspace-mobile-account">
              <span>{{ t('shell.account') }}</span>
              <NuxtLink to="/account/google" class="workspace-mobile-account-link">{{ t('google.link.title') }}</NuxtLink>
              <button class="workspace-mobile-logout" type="button" @click="logout">{{ t('common.logout') }}</button>
            </div>
            <p v-if="organizationError" class="workspace-organization-error" role="alert">{{ organizationError }}</p>
          </div>
        </div>
      </div>
    </header>

    <div v-if="organizationError && !mobileMenuOpen" class="container workspace-organization-error workspace-organization-error-desktop" role="alert">
      {{ organizationError }}
    </div>

    <div v-if="breadcrumbs.length || tournament" class="workspace-context container">
      <nav v-if="breadcrumbs.length" class="workspace-breadcrumbs" :aria-label="t('shell.breadcrumbs')">
        <ol>
          <li v-for="(breadcrumb, index) in breadcrumbs" :key="`${breadcrumb.label}-${index}`">
            <NuxtLink v-if="breadcrumb.to && !breadcrumb.current" :to="breadcrumb.to">{{ breadcrumb.label }}</NuxtLink>
            <span v-else :aria-current="breadcrumb.current ? 'page' : undefined">{{ breadcrumb.label }}</span>
          </li>
        </ol>
      </nav>

      <nav v-if="tournament" class="workspace-tournament-nav" :aria-label="t('shell.tournamentNavigation')">
        <div class="workspace-tournament-heading">
          <span class="workspace-tournament-parent">{{ t('shell.tournaments') }}</span>
          <strong>{{ tournamentLabel }}</strong>
        </div>
        <div class="workspace-tournament-links">
          <NuxtLink
            v-for="link in tournamentLinks"
            :key="link.key"
            :to="link.to"
            :aria-current="activeSection === link.key ? 'page' : undefined"
            :class="{ active: activeSection === link.key }"
          >{{ link.label }}</NuxtLink>
        </div>
        <select
          class="workspace-tournament-select"
          :value="activeSection"
          :aria-label="t('shell.tournamentNavigation')"
          @change="navigateTournamentSection"
        >
          <option v-for="link in tournamentLinks" :key="`select-${link.key}`" :value="link.key">{{ link.label }}</option>
        </select>
      </nav>
    </div>

    <slot />
  </div>
</template>

<style scoped>
.workspace-shell-root { min-height: 100vh; }
.workspace-topbar { position: sticky; top: 0; z-index: 40; border-bottom: 1px solid color-mix(in srgb, var(--color-muted) 16%, transparent); background: color-mix(in srgb, var(--color-canvas) 90%, transparent); backdrop-filter: blur(18px); }
.workspace-topbar-inner { display: flex; align-items: center; gap: var(--space-6); min-height: 70px; }
.workspace-brand { display: inline-flex; flex: 0 0 auto; align-items: center; gap: var(--space-2); color: var(--color-ink); font-size: var(--text-xs); font-weight: 900; letter-spacing: 0.16em; text-decoration: none; }
.workspace-brand:hover { color: var(--color-accent); }
.workspace-brand-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--color-accent); box-shadow: 0 0 18px var(--color-accent); }
.workspace-primary-nav { display: flex; align-items: center; gap: var(--space-1); }
.workspace-nav-link, .workspace-account-button { padding: var(--space-2) var(--space-3); border-radius: var(--radius-sm); color: var(--color-muted); font-size: var(--text-xs); text-decoration: none; }
.workspace-nav-link:hover, .workspace-nav-link[aria-current='page'], .workspace-account-button:hover { background: color-mix(in srgb, var(--color-accent) 8%, transparent); color: var(--color-ink); }
.workspace-nav-link[aria-current='page'] { color: var(--color-accent); }
.workspace-desktop-controls { display: flex; flex: 1 1 auto; align-items: center; justify-content: end; gap: var(--space-3); min-width: 0; }
.workspace-organization { display: flex; align-items: center; gap: var(--space-2); min-width: 0; }
.workspace-control-label { color: var(--color-muted); font-size: var(--text-2xs); letter-spacing: 0.08em; text-transform: uppercase; }
.workspace-organization-name { overflow: hidden; max-width: 150px; color: var(--color-ink); font-size: var(--text-xs); text-overflow: ellipsis; white-space: nowrap; }
.workspace-organization-select { max-width: 160px; padding: var(--space-2) var(--space-2); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: var(--color-surface); color: var(--color-ink); font: inherit; font-size: var(--text-xs); }
.workspace-organization-select:hover, .workspace-organization-select:focus { border-color: var(--color-accent); }
.workspace-account { position: relative; }
.workspace-account-button { background: transparent; color: var(--color-ink); cursor: pointer; }
.workspace-account-menu { position: absolute; top: calc(100% + 10px); right: 0; min-width: 140px; padding: var(--space-1); border: 1px solid var(--color-line); border-radius: var(--radius-md); background: var(--color-surface-raised); box-shadow: var(--shadow-deep); }
.workspace-account-menu button, .workspace-account-menu a { width: 100%; padding: var(--space-2) var(--space-2); border-radius: var(--radius-sm); background: transparent; color: var(--color-ink); text-align: left; text-decoration: none; }
.workspace-account-menu button:hover, .workspace-account-menu a:hover { background: color-mix(in srgb, var(--color-accent) 8%, transparent); color: var(--color-accent); }
.workspace-menu-toggle { display: none; align-items: center; gap: var(--space-2); margin-left: auto; padding: var(--space-2) var(--space-2); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: transparent; color: var(--color-ink); font-size: var(--text-xs); font-weight: 800; }
.workspace-menu-icon { display: grid; gap: var(--space-1); width: 14px; }
.workspace-menu-icon i { display: block; height: 1px; background: currentColor; }
.workspace-mobile-menu { border-top: 1px solid color-mix(in srgb, var(--color-muted) 12%, transparent); background: color-mix(in srgb, var(--color-surface) 98%, transparent); }
.workspace-mobile-menu-inner { display: grid; gap: var(--space-4); padding-top: var(--space-4); padding-bottom: var(--space-5); }
.workspace-mobile-nav { display: grid; gap: var(--space-1); }
.workspace-mobile-link { padding: var(--space-3) var(--space-3); border-radius: var(--radius-sm); color: var(--color-muted); font-size: var(--text-md); text-decoration: none; }
.workspace-mobile-link:hover, .workspace-mobile-link[aria-current='page'] { background: color-mix(in srgb, var(--color-accent) 8%, transparent); color: var(--color-accent); }
.workspace-mobile-controls { display: grid; gap: var(--space-3); padding-top: var(--space-3); border-top: 1px solid var(--color-line); }
.workspace-mobile-preferences { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
.workspace-mobile-preferences :deep(.language-switcher-inline label) { display: inline; }
.workspace-mobile-organization { display: grid; gap: var(--space-2); color: var(--color-muted); font-size: var(--text-xs); }
.workspace-mobile-organization span { letter-spacing: 0.08em; text-transform: uppercase; }
.workspace-mobile-organization strong { color: var(--color-ink); font-size: var(--text-md); }
.workspace-mobile-organization select { width: 100%; padding: var(--space-3); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: var(--color-canvas); color: var(--color-ink); font: inherit; }
.workspace-mobile-account { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding-top: var(--space-1); color: var(--color-muted); font-size: var(--text-xs); }
.workspace-mobile-account-link { color: var(--color-muted); font-size: var(--text-sm); text-decoration: underline; }
.workspace-mobile-account-link:hover { color: var(--color-accent); }
.workspace-mobile-logout { justify-self: start; padding: 0; background: transparent; color: var(--color-muted); font-size: var(--text-sm); text-decoration: underline; }
.workspace-mobile-logout:hover { color: var(--color-danger); }
.workspace-organization-error { margin-top: var(--space-3); padding: var(--space-2) var(--space-3); border: 1px solid var(--color-danger-border); border-radius: var(--radius-sm); color: var(--color-danger); font-size: var(--text-xs); }
.workspace-organization-error-desktop { margin-bottom: calc(-1 * var(--space-1)); }
.workspace-context { position: sticky; top: 70px; z-index: 30; padding-top: var(--space-3); background: linear-gradient(var(--color-canvas) 75%, transparent); }
:global(.workspace-shell-root [id]) { scroll-margin-top: 145px; }
.workspace-breadcrumbs { padding-bottom: var(--space-2); }
.workspace-breadcrumbs ol { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); margin: 0; padding: 0; list-style: none; color: var(--color-muted); font-size: var(--text-xs); }
.workspace-breadcrumbs li { display: inline-flex; align-items: center; gap: var(--space-2); }
.workspace-breadcrumbs li + li::before { content: '/'; color: var(--color-line); }
.workspace-breadcrumbs a { color: var(--color-muted); text-decoration: none; }
.workspace-breadcrumbs a:hover { color: var(--color-accent); }
.workspace-breadcrumbs [aria-current='page'] { color: var(--color-ink); }
.workspace-tournament-nav { display: flex; align-items: center; gap: var(--space-4); padding: var(--space-3) 0; border-top: 1px solid color-mix(in srgb, var(--color-muted) 16%, transparent); border-bottom: 1px solid color-mix(in srgb, var(--color-muted) 16%, transparent); }
.workspace-tournament-heading { display: grid; flex: 0 0 auto; gap: var(--space-1); min-width: 150px; }
.workspace-tournament-parent { color: var(--color-muted); font-size: var(--text-2xs); letter-spacing: 0.1em; text-transform: uppercase; }
.workspace-tournament-heading strong { overflow: hidden; max-width: 240px; color: var(--color-ink); font-size: var(--text-md); text-overflow: ellipsis; white-space: nowrap; }
.workspace-tournament-links { display: flex; flex: 1 1 auto; align-items: center; gap: var(--space-1); overflow-x: auto; scrollbar-width: thin; }
.workspace-tournament-links a { flex: 0 0 auto; padding: var(--space-2) var(--space-2); border-radius: var(--radius-sm); color: var(--color-muted); font-size: var(--text-xs); text-decoration: none; }
.workspace-tournament-links a:hover, .workspace-tournament-links a.active { background: color-mix(in srgb, var(--color-accent) 8%, transparent); color: var(--color-accent); }
.workspace-tournament-select { display: none; width: 100%; padding: var(--space-3) var(--space-3); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: var(--color-canvas); color: var(--color-ink); font: inherit; font-size: var(--text-sm); }
@media (max-width: 1000px) {
  .workspace-desktop-controls :deep(.language-switcher label), .workspace-desktop-controls :deep(.theme-switcher label) { display: none; }
  .workspace-topbar-inner { gap: var(--space-4); }
  .workspace-primary-nav { gap: 0; }
  .workspace-nav-link, .workspace-account-button { padding-inline: var(--space-2); }
  .workspace-control-label { display: none; }
}
@media (max-width: 760px) {
  .workspace-topbar-inner { min-height: 62px; }
  .workspace-primary-nav, .workspace-desktop-controls { display: none; }
  .workspace-menu-toggle { display: inline-flex; }
  .workspace-context { top: 62px; }
  :global(.workspace-shell-root [id]) { scroll-margin-top: 125px; }
  .workspace-tournament-nav { align-items: stretch; flex-direction: column; gap: var(--space-2); }
  .workspace-tournament-heading { min-width: 0; }
  .workspace-tournament-links { display: none; }
  .workspace-tournament-select { display: block; }
}
@media (max-width: 480px) {
  .workspace-brand { gap: var(--space-2); font-size: var(--text-2xs); letter-spacing: 0.11em; }
  .workspace-brand-dot { width: 8px; height: 8px; }
  .workspace-menu-toggle { padding-inline: var(--space-2); font-size: var(--text-2xs); }
}
</style>
