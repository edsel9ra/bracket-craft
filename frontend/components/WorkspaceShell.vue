<script setup lang="ts">
import { isForbidden, isNotFound, isUnauthorized } from '~/utils/api';
import { safeInternalRedirect } from '~/utils/navigation';

export type WorkspaceSection = 'summary' | 'configuration' | 'calendar' | 'teams' | 'rosters' | 'operation';

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
  activeSection?: WorkspaceSection;
}>(), {
  breadcrumbs: () => [],
  tournament: null,
  activeSection: 'summary',
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
const canManageTournaments = computed(() => auth.hasPermission('MANAGE_TOURNAMENTS'));
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
  if (!props.tournament?.id) return [];
  const base = `/workspace/tournaments/${props.tournament.id}`;
  return [
    { key: 'summary' as WorkspaceSection, label: t('shell.summary'), to: `${base}#resumen` },
    ...(canManageTournaments.value
      ? [{ key: 'configuration' as WorkspaceSection, label: t('shell.configuration'), to: `${base}#configuracion` }]
      : []),
    { key: 'calendar' as WorkspaceSection, label: t('shell.calendar'), to: `${base}#calendario` },
    { key: 'teams' as WorkspaceSection, label: t('shell.teams'), to: `${base}#equipos` },
    { key: 'rosters' as WorkspaceSection, label: t('shell.rosters'), to: `${base}#plantillas` },
    {
      key: 'operation' as WorkspaceSection,
      label: t('shell.operation'),
      to: route.path.startsWith('/workspace/matches/') ? `${route.path}#operacion` : `${base}#operacion`,
    },
  ];
});

async function resolvePlatformAccess() {
  if (isAdminRoute.value || platformAccess.value !== 'unknown') return;
  try {
    await request('/platform/users?limit=1');
    platformAccess.value = 'allowed';
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
  const section = (event.target as HTMLSelectElement).value as WorkspaceSection;
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
          <LanguageSwitcher :inline="true" />
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
            <LanguageSwitcher :inline="true" />
            <div class="workspace-mobile-account">
              <span>{{ t('shell.account') }}</span>
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
.workspace-topbar { position: sticky; top: 0; z-index: 40; border-bottom: 1px solid rgba(166, 170, 159, 0.16); background: rgba(12, 15, 12, 0.9); backdrop-filter: blur(18px); }
.workspace-topbar-inner { display: flex; align-items: center; gap: 28px; min-height: 70px; }
.workspace-brand { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 9px; color: var(--ink); font-size: 0.78rem; font-weight: 900; letter-spacing: 0.16em; text-decoration: none; }
.workspace-brand:hover { color: var(--accent); }
.workspace-brand-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 18px var(--accent); }
.workspace-primary-nav { display: flex; align-items: center; gap: 4px; }
.workspace-nav-link, .workspace-account-button { padding: 9px 11px; border-radius: 8px; color: var(--muted); font-size: 0.78rem; text-decoration: none; }
.workspace-nav-link:hover, .workspace-nav-link[aria-current='page'], .workspace-account-button:hover { background: rgba(212, 243, 106, 0.08); color: var(--ink); }
.workspace-nav-link[aria-current='page'] { color: var(--accent); }
.workspace-desktop-controls { display: flex; flex: 1 1 auto; align-items: center; justify-content: end; gap: 14px; min-width: 0; }
.workspace-organization { display: flex; align-items: center; gap: 7px; min-width: 0; }
.workspace-control-label { color: var(--muted); font-size: 0.68rem; letter-spacing: 0.08em; text-transform: uppercase; }
.workspace-organization-name { overflow: hidden; max-width: 150px; color: var(--ink); font-size: 0.78rem; text-overflow: ellipsis; white-space: nowrap; }
.workspace-organization-select { max-width: 160px; padding: 0.48rem 0.62rem; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--ink); font: inherit; font-size: 0.76rem; }
.workspace-organization-select:hover, .workspace-organization-select:focus { border-color: var(--accent); }
.workspace-account { position: relative; }
.workspace-account-button { background: transparent; color: var(--ink); cursor: pointer; }
.workspace-account-menu { position: absolute; top: calc(100% + 10px); right: 0; min-width: 140px; padding: 6px; border: 1px solid var(--line); border-radius: 12px; background: var(--surface-raised); box-shadow: var(--shadow-deep); }
.workspace-account-menu button { width: 100%; padding: 9px 10px; border-radius: 7px; background: transparent; color: var(--ink); text-align: left; }
.workspace-account-menu button:hover { background: rgba(212, 243, 106, 0.08); color: var(--accent); }
.workspace-menu-toggle { display: none; align-items: center; gap: 8px; margin-left: auto; padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; background: transparent; color: var(--ink); font-size: 0.75rem; font-weight: 800; }
.workspace-menu-icon { display: grid; gap: 4px; width: 14px; }
.workspace-menu-icon i { display: block; height: 1px; background: currentColor; }
.workspace-mobile-menu { border-top: 1px solid rgba(166, 170, 159, 0.12); background: rgba(21, 24, 20, 0.98); }
.workspace-mobile-menu-inner { display: grid; gap: 18px; padding-top: 18px; padding-bottom: 20px; }
.workspace-mobile-nav { display: grid; gap: 4px; }
.workspace-mobile-link { padding: 11px 12px; border-radius: 9px; color: var(--muted); font-size: 0.9rem; text-decoration: none; }
.workspace-mobile-link:hover, .workspace-mobile-link[aria-current='page'] { background: rgba(212, 243, 106, 0.08); color: var(--accent); }
.workspace-mobile-controls { display: grid; gap: 12px; padding-top: 14px; border-top: 1px solid var(--line); }
.workspace-mobile-organization { display: grid; gap: 7px; color: var(--muted); font-size: 0.75rem; }
.workspace-mobile-organization span { letter-spacing: 0.08em; text-transform: uppercase; }
.workspace-mobile-organization strong { color: var(--ink); font-size: 0.86rem; }
.workspace-mobile-organization select { width: 100%; padding: 0.75rem; border: 1px solid var(--line); border-radius: 9px; background: #0c0f0c; color: var(--ink); font: inherit; }
.workspace-mobile-account { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 4px; color: var(--muted); font-size: 0.75rem; }
.workspace-mobile-logout { justify-self: start; padding: 0; background: transparent; color: var(--muted); font-size: 0.8rem; text-decoration: underline; }
.workspace-mobile-logout:hover { color: var(--danger); }
.workspace-organization-error { margin-top: 12px; padding: 10px 12px; border: 1px solid #a45b5b; border-radius: 9px; color: var(--danger); font-size: 0.78rem; }
.workspace-organization-error-desktop { margin-bottom: -2px; }
.workspace-context { position: sticky; top: 70px; z-index: 30; padding-top: 12px; background: linear-gradient(#0c0f0c 75%, transparent); }
:global(.workspace-shell-root [id]) { scroll-margin-top: 145px; }
.workspace-breadcrumbs { padding-bottom: 10px; }
.workspace-breadcrumbs ol { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin: 0; padding: 0; list-style: none; color: var(--muted); font-size: 0.74rem; }
.workspace-breadcrumbs li { display: inline-flex; align-items: center; gap: 7px; }
.workspace-breadcrumbs li + li::before { content: '/'; color: var(--line); }
.workspace-breadcrumbs a { color: var(--muted); text-decoration: none; }
.workspace-breadcrumbs a:hover { color: var(--accent); }
.workspace-breadcrumbs [aria-current='page'] { color: var(--ink); }
.workspace-tournament-nav { display: flex; align-items: center; gap: 18px; padding: 12px 0; border-top: 1px solid rgba(166, 170, 159, 0.16); border-bottom: 1px solid rgba(166, 170, 159, 0.16); }
.workspace-tournament-heading { display: grid; flex: 0 0 auto; gap: 3px; min-width: 150px; }
.workspace-tournament-parent { color: var(--muted); font-size: 0.66rem; letter-spacing: 0.1em; text-transform: uppercase; }
.workspace-tournament-heading strong { overflow: hidden; max-width: 240px; color: var(--ink); font-size: 0.9rem; text-overflow: ellipsis; white-space: nowrap; }
.workspace-tournament-links { display: flex; flex: 1 1 auto; align-items: center; gap: 3px; overflow-x: auto; scrollbar-width: thin; }
.workspace-tournament-links a { flex: 0 0 auto; padding: 8px 9px; border-radius: 7px; color: var(--muted); font-size: 0.76rem; text-decoration: none; }
.workspace-tournament-links a:hover, .workspace-tournament-links a.active { background: rgba(212, 243, 106, 0.08); color: var(--accent); }
.workspace-tournament-select { display: none; width: 100%; padding: 0.72rem 0.8rem; border: 1px solid var(--line); border-radius: 9px; background: #0c0f0c; color: var(--ink); font: inherit; font-size: 0.8rem; }
@media (max-width: 1000px) {
  .workspace-topbar-inner { gap: 16px; }
  .workspace-primary-nav { gap: 0; }
  .workspace-nav-link, .workspace-account-button { padding-inline: 8px; }
  .workspace-control-label { display: none; }
}
@media (max-width: 800px) {
  .workspace-topbar-inner { min-height: 62px; }
  .workspace-primary-nav, .workspace-desktop-controls { display: none; }
  .workspace-menu-toggle { display: inline-flex; }
  .workspace-context { top: 62px; }
  :global(.workspace-shell-root [id]) { scroll-margin-top: 125px; }
  .workspace-tournament-nav { align-items: stretch; flex-direction: column; gap: 10px; }
  .workspace-tournament-heading { min-width: 0; }
  .workspace-tournament-links { display: none; }
  .workspace-tournament-select { display: block; }
}
@media (max-width: 420px) {
  .workspace-brand { gap: 7px; font-size: 0.68rem; letter-spacing: 0.11em; }
  .workspace-brand-dot { width: 8px; height: 8px; }
  .workspace-menu-toggle { padding-inline: 8px; font-size: 0.7rem; }
}
</style>
