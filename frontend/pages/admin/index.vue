<script setup lang="ts">
import { isForbidden, isUnauthorized } from '~/utils/api';

definePageMeta({ middleware: 'platform' });

interface PlatformUser {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  created_at: string;
  organization_count: number;
}

interface PlatformOrganization {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  created_at: string;
  member_count: number;
}

interface PlatformAudit {
  id: string;
  actor_email: string;
  action: string;
  target_type: string;
  target_id: string | null;
  created_at: string;
}

const auth = useAuthStore();
const { request } = useApi();
const { t, statusLabel, dateLocale, errorMessage } = useI18n();
const users = ref<PlatformUser[]>([]);
const organizations = ref<PlatformOrganization[]>([]);
const audit = ref<PlatformAudit[]>([]);
const loading = ref(true);
const savingKey = ref<string | null>(null);
const error = ref<string | null>(null);
const search = ref('');
const loadingMore = ref(false);
const hasMoreUsers = ref(false);
const hasMoreOrganizations = ref(false);
const hasMoreAudit = ref(false);
let loadGeneration = 0;
const PAGE_SIZE = 50;
const activeUserCount = computed(() => users.value.filter((user) => user.is_active).length);
const activeOrganizationCount = computed(() => organizations.value.filter((organization) => organization.is_active).length);

useHead(() => ({
  title: t('admin.title'),
  meta: [{ name: 'robots', content: 'noindex, nofollow' }],
}));

function failureMessage(cause: unknown, fallback: string): string {
  return errorMessage(cause, fallback);
}

async function load(options: { append?: boolean } = {}) {
  const append = options.append === true;
  const generation = ++loadGeneration;
  loading.value = true;
  if (!append) error.value = null;
  try {
    const query = search.value ? `&search=${encodeURIComponent(search.value)}` : '';
    const userOffset = append ? users.value.length : 0;
    const organizationOffset = append ? organizations.value.length : 0;
    const auditOffset = append ? audit.value.length : 0;
    const [userResponse, organizationResponse, auditResponse] = await Promise.all([
      request<{ items: PlatformUser[] }>(`/platform/users?limit=${PAGE_SIZE}&offset=${userOffset}${query}`),
      request<{ items: PlatformOrganization[] }>(`/platform/organizations?limit=${PAGE_SIZE}&offset=${organizationOffset}${query}`),
      request<{ items: PlatformAudit[] }>(`/platform/audit?limit=${PAGE_SIZE}&offset=${auditOffset}`),
    ]);
    if (generation !== loadGeneration) return;
    users.value = append ? [...users.value, ...userResponse.items] : userResponse.items;
    organizations.value = append ? [...organizations.value, ...organizationResponse.items] : organizationResponse.items;
    audit.value = append ? [...audit.value, ...auditResponse.items] : auditResponse.items;
    hasMoreUsers.value = userResponse.items.length === PAGE_SIZE;
    hasMoreOrganizations.value = organizationResponse.items.length === PAGE_SIZE;
    hasMoreAudit.value = auditResponse.items.length === PAGE_SIZE;
  } catch (cause) {
    if (isUnauthorized(cause)) {
      await auth.logout();
      await navigateTo({ path: '/login', query: { redirect: '/admin' } });
      return;
    }
    if (isForbidden(cause)) {
      await navigateTo({ path: '/forbidden', query: { returnTo: '/admin', resource: 'admin' } });
      return;
    }
    if (generation === loadGeneration) error.value = failureMessage(cause, t('admin.noLoad'));
  } finally {
    if (generation === loadGeneration) {
      loading.value = false;
      loadingMore.value = false;
    }
  }
}

async function loadMore() {
  if (loading.value || loadingMore.value || (!hasMoreUsers.value && !hasMoreOrganizations.value && !hasMoreAudit.value)) return;
  loadingMore.value = true;
  await load({ append: true });
}

function refresh() {
  return load();
}

async function toggleUser(user: PlatformUser) {
  await toggleStatus(`/platform/users/${user.id}/status`, user.is_active, `user:${user.id}`);
}

async function toggleOrganization(organization: PlatformOrganization) {
  await toggleStatus(
    `/platform/organizations/${organization.id}/status`,
    organization.is_active,
    `organization:${organization.id}`,
  );
}

async function toggleStatus(path: string, currentValue: boolean, key: string) {
  if (currentValue && import.meta.client && !window.confirm(t('admin.confirmDeactivate'))) return;
  savingKey.value = key;
  error.value = null;
  try {
    await request(path, { method: 'PATCH', body: { is_active: !currentValue } });
    await load();
  } catch (cause) {
    if (isUnauthorized(cause)) {
      await auth.logout();
      await navigateTo({ path: '/login', query: { redirect: '/admin' } });
      return;
    }
    if (isForbidden(cause)) {
      await navigateTo({ path: '/forbidden', query: { returnTo: '/admin', resource: 'admin' } });
      return;
    }
    error.value = failureMessage(cause, t('admin.noUpdate'));
  } finally {
    savingKey.value = null;
  }
}

async function logoutAndGoHome() {
  await auth.logout();
  await navigateTo('/');
}

await load();
</script>

<template>
  <main id="main-content" class="admin-shell">
    <header class="container admin-topbar">
      <NuxtLink to="/" class="brand-mark">BRACKET CRAFT</NuxtLink>
      <div class="topbar-actions">
         <NuxtLink to="/workspace" class="button-secondary">{{ t('home.workspace') }}</NuxtLink>
         <button class="button-secondary" type="button" @click="logoutAndGoHome">{{ t('common.logout') }}</button>
      </div>
    </header>

    <section class="container admin-hero">
      <div class="hero-line">
         <p class="eyebrow">{{ t('admin.platformControl') }}</p>
         <span class="admin-status"><span aria-hidden="true" /> {{ t('admin.auditActive') }}</span>
      </div>
       <h1>{{ t('admin.headline') }}</h1>
       <p class="admin-copy">{{ t('admin.copy') }}</p>
    </section>

    <section class="container admin-content">
       <div class="admin-metrics" :aria-label="t('admin.platformControl')">
          <article class="metric-card"><span>{{ t('admin.activeUsers') }}</span><strong>{{ activeUserCount }}</strong><small>{{ t('admin.visibleRecords', { count: users.length }) }}</small></article>
          <article class="metric-card"><span>{{ t('admin.activeOrganizations') }}</span><strong>{{ activeOrganizationCount }}</strong><small>{{ t('admin.visibleRecords', { count: organizations.length }) }}</small></article>
         <article class="metric-card metric-card-accent"><span>{{ t('admin.recentEvents') }}</span><strong>{{ audit.length }}</strong><small>{{ t('admin.visibleActions') }}</small></article>
      </div>
      <div class="admin-toolbar">
        <label>
           {{ t('admin.search') }}
            <input v-model="search" type="search" maxlength="100" :placeholder="t('admin.searchPlaceholder')" @keyup.enter="refresh" />
          </label>
          <button class="button-primary" type="button" :disabled="loading" @click="refresh">{{ t('common.refresh') }}</button>
        </div>
        <div v-if="error" class="form-error" role="alert"><span>{{ error }}</span><button class="button-secondary" type="button" @click="refresh">{{ t('common.retry') }}</button></div>
       <div v-if="loading" class="empty-state" role="status">{{ t('common.loading') }}</div>
      <template v-else>
        <div class="admin-grid">
          <section class="panel">
            <div class="panel-heading">
              <div>
                 <p class="eyebrow">{{ t('admin.identity') }}</p>
                 <h2>{{ t('admin.users') }}</h2>
              </div>
              <span class="muted">{{ users.length }}</span>
            </div>
            <Transition name="content-fade" mode="out-in">
               <div v-if="!users.length" key="empty-users" class="empty-state compact">{{ t('admin.noUsers') }}</div>
              <TransitionGroup v-else name="card-list" tag="div" class="resource-list">
              <article v-for="user in users" :key="user.id" class="resource-row">
                <div>
                  <strong>{{ user.full_name }}</strong>
                   <small>{{ user.email }} · {{ t('admin.organizationsCount', { count: user.organization_count }) }}</small>
                </div>
                <button
                   class="status-button"
                   type="button"
                   :aria-pressed="user.is_active"
                  :disabled="savingKey === `user:${user.id}`"
                  @click="toggleUser(user)"
                >
                   {{ user.is_active ? t('admin.active') : t('admin.blocked') }}
                </button>
              </article>
               </TransitionGroup>
             </Transition>
             <button v-if="hasMoreUsers" class="button-secondary load-more" type="button" :disabled="loading" @click="loadMore">{{ loadingMore ? t('common.loading') : t('admin.loadMore') }}</button>
           </section>

          <section class="panel">
            <div class="panel-heading">
              <div>
                 <p class="eyebrow">{{ t('admin.tenants') }}</p>
                 <h2>{{ t('admin.organizations') }}</h2>
              </div>
              <span class="muted">{{ organizations.length }}</span>
            </div>
            <Transition name="content-fade" mode="out-in">
               <div v-if="!organizations.length" key="empty-organizations" class="empty-state compact">{{ t('admin.noOrganizations') }}</div>
              <TransitionGroup v-else name="card-list" tag="div" class="resource-list">
              <article v-for="organization in organizations" :key="organization.id" class="resource-row">
                <div>
                  <strong>{{ organization.name }}</strong>
                   <small>{{ organization.slug }} · {{ t('admin.membersCount', { count: organization.member_count }) }}</small>
                </div>
                <button
                   class="status-button"
                   type="button"
                   :aria-pressed="organization.is_active"
                  :disabled="savingKey === `organization:${organization.id}`"
                  @click="toggleOrganization(organization)"
                >
                   {{ organization.is_active ? t('admin.organizationActive') : t('admin.organizationSuspended') }}
                </button>
              </article>
               </TransitionGroup>
             </Transition>
             <button v-if="hasMoreOrganizations" class="button-secondary load-more" type="button" :disabled="loading" @click="loadMore">{{ loadingMore ? t('common.loading') : t('admin.loadMore') }}</button>
           </section>
        </div>

        <section class="panel audit-panel">
          <div class="panel-heading">
            <div>
               <p class="eyebrow">{{ t('admin.traceability') }}</p>
               <h2>{{ t('admin.activity') }}</h2>
            </div>
          </div>
          <Transition name="content-fade" mode="out-in">
             <div v-if="!audit.length" key="empty-audit" class="empty-state compact">{{ t('admin.noActions') }}</div>
            <TransitionGroup v-else name="card-list" tag="div" class="audit-list">
            <div v-for="entry in audit" :key="entry.id" class="audit-row">
              <strong>{{ entry.action }}</strong>
              <span>{{ entry.actor_email }} · {{ entry.target_type }}</span>
               <time :datetime="entry.created_at">{{ new Date(entry.created_at).toLocaleString(dateLocale) }}</time>
            </div>
             </TransitionGroup>
           </Transition>
           <button v-if="hasMoreAudit" class="button-secondary load-more" type="button" :disabled="loading" @click="loadMore">{{ loadingMore ? t('common.loading') : t('admin.loadMore') }}</button>
         </section>
      </template>
    </section>
  </main>
</template>

<style scoped>
.admin-shell { min-height: 100vh; background: radial-gradient(circle at 88% 4%, rgba(212, 243, 106, 0.1), transparent 30rem), #0c0f0c; }
.admin-topbar { display: flex; justify-content: space-between; align-items: center; padding: 24px 0; }
.brand-mark { color: var(--ink); font-size: 0.78rem; font-weight: 900; letter-spacing: 0.16em; text-decoration: none; }
.brand-mark:hover { color: var(--accent); }
.topbar-actions { display: flex; gap: 12px; }
.admin-hero { padding: 9vh 0 7vh; animation: rise-in 700ms var(--ease-out) both; }
.hero-line { display: flex; align-items: center; gap: 18px; }
.admin-status { display: inline-flex; align-items: center; gap: 7px; color: var(--muted); font-size: 0.7rem; letter-spacing: 0.1em; text-transform: uppercase; }
.admin-status span { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 12px var(--accent); }
.admin-hero h1 { max-width: 900px; margin: 14px 0; font-size: clamp(3rem, 8vw, 7rem); line-height: 0.9; letter-spacing: -0.08em; }
.admin-copy { max-width: 560px; color: var(--muted); font-size: 1.1rem; line-height: 1.6; }
.admin-content { padding-bottom: 80px; }
.admin-metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 26px; }
.metric-card { display: grid; gap: 7px; min-height: 130px; padding: 18px; border: 1px solid var(--line); border-radius: 18px; background: linear-gradient(145deg, var(--surface-raised), var(--surface)); }
.metric-card span, .metric-card small { color: var(--muted); font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase; }
.metric-card strong { font-size: 2.5rem; line-height: 1; letter-spacing: -0.08em; }
.metric-card-accent { border-color: rgba(212, 243, 106, 0.36); }
.admin-toolbar { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin-bottom: 20px; }
label { display: grid; gap: 7px; width: min(100%, 460px); color: var(--muted); font-size: 0.82rem; }
input { width: 100%; padding: 0.82rem 0.9rem; border: 1px solid var(--line); border-radius: 10px; background: #0c0f0c; color: var(--ink); }
input:focus { border-color: var(--accent); box-shadow: 0 0 0 4px var(--accent-glow); }
.admin-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.panel { min-width: 0; padding: 22px; border: 1px solid var(--line); border-radius: 20px; background: linear-gradient(145deg, rgba(32, 37, 30, 0.9), rgba(21, 24, 20, 0.94)); box-shadow: 0 18px 50px rgba(0, 0, 0, 0.12); }
.panel-heading { display: flex; justify-content: space-between; align-items: end; gap: 16px; margin-bottom: 20px; }
.panel-heading h2 { margin: 7px 0 0; font-size: 1.8rem; letter-spacing: -0.06em; }
.eyebrow { margin: 0; color: var(--accent); font-size: 0.7rem; font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; }
.muted, .empty-state { color: var(--muted); }
.empty-state { padding: 20px; border: 1px dashed var(--line); border-radius: 14px; }
.empty-state.compact { padding: 16px; }
.form-error { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 20px; padding: 12px; border: 1px solid #a45b5b; border-radius: 10px; color: #ffb0a8; }
.resource-list, .audit-list { display: grid; gap: 10px; }
.resource-list, .audit-list { position: relative; }
.resource-row, .audit-row { display: flex; justify-content: space-between; align-items: center; gap: 14px; padding: 13px 0; border-top: 1px solid rgba(166, 170, 159, 0.14); }
.resource-row:first-child, .audit-row:first-child { border-top: 0; }
.resource-row small { display: block; margin-top: 4px; color: var(--muted); font-size: 0.72rem; }
.status-button { flex: 0 0 auto; padding: 0.55rem 0.7rem; border: 1px solid var(--line); border-radius: 999px; background: transparent; color: var(--accent); font-size: 0.72rem; font-weight: 800; }
.status-button:hover:not(:disabled) { border-color: var(--accent); background: var(--accent-glow); transform: translateY(-2px); }
.status-button:disabled { cursor: wait; opacity: 0.5; }
.audit-panel { margin-top: 16px; }
.load-more { display: block; margin: 16px auto 0; }
.audit-row { align-items: baseline; font-size: 0.82rem; }
.audit-row span, .audit-row time { color: var(--muted); }
@media (max-width: 800px) {
  .container { width: min(100% - 28px, 620px); }
  .admin-metrics { grid-template-columns: 1fr; }
  .admin-grid { grid-template-columns: 1fr; }
  .admin-toolbar { align-items: stretch; flex-direction: column; }
}
@media (max-width: 560px) {
  .admin-topbar, .topbar-actions { align-items: start; flex-direction: column; }
  .resource-row, .audit-row { align-items: start; flex-direction: column; }
  .form-error { align-items: stretch; flex-direction: column; }
}
@media (max-width: 375px) {
  .admin-topbar, .topbar-actions { align-items: stretch; }
  .topbar-actions > * { justify-content: center; text-align: center; }
}
</style>
