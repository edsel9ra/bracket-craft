<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import FormField from '~/components/ui/FormField.vue';
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
const { t, statusLabel, formatDateTime, errorMessage } = useI18n();
const { confirm } = useConfirm({ singleFlight: true });
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
  if (currentValue && import.meta.client && !(await confirm({ title: t('confirm.deactivate.title'), message: t('admin.confirmDeactivate'), confirmLabel: t('confirm.deactivate.action'), tone: 'danger' }))) return;
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

await load();
</script>

<template>
  <WorkspaceShell :breadcrumbs="[{ label: t('shell.administration'), current: true }]">
   <main id="main-content" class="admin-shell">
    <section class="container admin-hero">
      <div class="hero-line">
         <p class="eyebrow">{{ t('admin.platformControl') }}</p>
         <span class="admin-status"><span aria-hidden="true" /> {{ t('admin.auditActive') }}</span>
      </div>
       <h1>{{ t('admin.headline') }}</h1>
       <p class="admin-copy">{{ t('admin.copy') }}</p>
       <Button as="NuxtLink" to="/admin/rectifications" variant="secondary">{{ t('rectification.platformTitle') }}</Button>
       <Button as="NuxtLink" to="/admin/sanction-cases" variant="secondary">{{ t('sanction.platformTitle') }}</Button>
    </section>

    <section class="container admin-content">
       <div class="admin-metrics" :aria-label="t('admin.platformControl')">
          <Surface as="article" class="metric-card"><span>{{ t('admin.activeUsers') }}</span><strong>{{ activeUserCount }}</strong><small>{{ t('admin.visibleRecords', { count: users.length }) }}</small></Surface>
          <Surface as="article" class="metric-card"><span>{{ t('admin.activeOrganizations') }}</span><strong>{{ activeOrganizationCount }}</strong><small>{{ t('admin.visibleRecords', { count: organizations.length }) }}</small></Surface>
         <Surface as="article" class="metric-card metric-card-accent"><span>{{ t('admin.recentEvents') }}</span><strong>{{ audit.length }}</strong><small>{{ t('admin.visibleActions') }}</small></Surface>
      </div>
      <div class="admin-toolbar">
        <FormField :label="t('admin.search')" for-id="admin-search">
          <template #default="{ id, ariaDescribedby }">
            <input :id="id" v-model="search" type="search" maxlength="100" :placeholder="t('admin.searchPlaceholder')" :aria-describedby="ariaDescribedby" @keyup.enter="refresh" />
          </template>
        </FormField>
        <Button variant="primary" class="button-primary" type="button" :disabled="loading" @click="refresh">{{ t('common.refresh') }}</Button>
      </div>
        <div v-if="error" class="form-error" role="alert"><span>{{ error }}</span><Button variant="secondary" class="button-secondary" type="button" @click="refresh">{{ t('common.retry') }}</Button></div>
       <div v-if="loading" class="empty-state" role="status">{{ t('common.loading') }}</div>
      <template v-else>
        <div class="admin-grid">
          <Surface as="section" class="panel">
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
             <Button variant="secondary" v-if="hasMoreUsers" class="button-secondary load-more" type="button" :disabled="loading" @click="loadMore">{{ loadingMore ? t('common.loading') : t('admin.loadMore') }}</Button>
           </Surface>

          <Surface as="section" class="panel">
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
             <Button variant="secondary" v-if="hasMoreOrganizations" class="button-secondary load-more" type="button" :disabled="loading" @click="loadMore">{{ loadingMore ? t('common.loading') : t('admin.loadMore') }}</Button>
           </Surface>
        </div>

        <Surface as="section" class="panel audit-panel">
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
               <time :datetime="entry.created_at">{{ formatDateTime(entry.created_at) }}</time>
            </div>
             </TransitionGroup>
           </Transition>
           <Button variant="secondary" v-if="hasMoreAudit" class="button-secondary load-more" type="button" :disabled="loading" @click="loadMore">{{ loadingMore ? t('common.loading') : t('admin.loadMore') }}</Button>
         </Surface>
      </template>
    </section>
   </main>
  </WorkspaceShell>
</template>

<style scoped>
/* RF-006: hero proporcional a la ventana y cifras de métricas de 2.5rem ajustadas a sus tarjetas. */
.admin-shell { min-height: 100vh; background: radial-gradient(circle at 88% 4%, color-mix(in srgb, var(--color-accent) 10%, transparent), transparent 30rem), var(--color-canvas); }
.admin-hero { padding: 4vh 0 4vh; animation: rise-in 700ms var(--ease-out) both; }
.hero-line { display: flex; align-items: center; gap: var(--space-4); }
.admin-status { display: inline-flex; align-items: center; gap: var(--space-2); color: var(--color-muted); font-size: var(--text-2xs); letter-spacing: 0.1em; text-transform: uppercase; }
.admin-status span { width: 7px; height: 7px; border-radius: 50%; background: var(--color-accent); box-shadow: 0 0 12px var(--color-accent); }
.admin-hero h1 { max-width: 900px; margin: var(--space-3) 0; font-size: var(--text-display); line-height: 0.92; letter-spacing: -0.08em; }
.admin-copy { max-width: 560px; color: var(--color-muted); font-size: var(--text-base); line-height: 1.6; }
.admin-content { padding-bottom: var(--space-10); }
.admin-metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-3); margin-bottom: var(--space-6); }
.metric-card { display: grid; gap: var(--space-2); min-height: 130px; padding: var(--space-4); border: 1px solid var(--color-line); border-radius: var(--radius-lg); background: linear-gradient(145deg, var(--color-surface-raised), var(--color-surface)); }
.metric-card span, .metric-card small { color: var(--color-muted); font-size: var(--text-xs); letter-spacing: 0.08em; text-transform: uppercase; }
.metric-card strong { font-size: 2.5rem; line-height: 1; letter-spacing: -0.08em; }
.metric-card-accent { border-color: color-mix(in srgb, var(--color-accent) 36%, transparent); }
.admin-toolbar { display: flex; align-items: end; justify-content: space-between; gap: var(--space-4); margin-bottom: var(--space-5); }
label { display: grid; gap: var(--space-2); width: min(100%, 460px); color: var(--color-muted); font-size: var(--text-sm); }
input { width: 100%; padding: var(--space-3) var(--space-4); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: var(--color-canvas); color: var(--color-ink); }
input:focus { border-color: var(--color-accent); box-shadow: 0 0 0 4px var(--accent-glow); }
.admin-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-4); }
.panel { min-width: 0; padding: var(--space-5); border: 1px solid var(--color-line); border-radius: var(--radius-lg); background: linear-gradient(145deg, color-mix(in srgb, var(--color-surface-raised) 90%, transparent), color-mix(in srgb, var(--color-surface) 94%, transparent)); box-shadow: 0 18px 50px color-mix(in srgb, var(--color-shadow) 12%, transparent); }
.panel-heading { display: flex; justify-content: space-between; align-items: end; gap: var(--space-4); margin-bottom: var(--space-5); }
.panel-heading h2 { margin: var(--space-2) 0 0; font-size: var(--text-xl); letter-spacing: -0.06em; }
.eyebrow { margin: 0; color: var(--color-accent); font-size: var(--text-2xs); font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; }
.muted, .empty-state { color: var(--color-muted); }
.empty-state { padding: var(--space-5); border: 1px dashed var(--color-line); border-radius: var(--radius-md); }
.empty-state.compact { padding: var(--space-4); }
.form-error { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-5); padding: var(--space-3); border: 1px solid var(--color-danger-border); border-radius: var(--radius-sm); color: var(--color-danger); }
.resource-list, .audit-list { display: grid; gap: var(--space-2); }
.resource-list, .audit-list { position: relative; }
.resource-row, .audit-row { display: flex; justify-content: space-between; align-items: center; gap: var(--space-3); padding: var(--space-3) 0; border-top: 1px solid color-mix(in srgb, var(--color-muted) 14%, transparent); }
.resource-row:first-child, .audit-row:first-child { border-top: 0; }
.resource-row small { display: block; margin-top: var(--space-1); color: var(--color-muted); font-size: var(--text-xs); }
.status-button { flex: 0 0 auto; padding: var(--space-2) var(--space-3); border: 1px solid var(--color-line); border-radius: var(--radius-pill); background: transparent; color: var(--color-accent); font-size: var(--text-xs); font-weight: 800; }
.status-button:hover:not(:disabled) { border-color: var(--color-accent); background: var(--accent-glow); transform: translateY(-2px); }
.status-button:disabled { cursor: wait; opacity: 0.5; }
.audit-panel { margin-top: var(--space-4); }
.load-more { display: block; margin: var(--space-4) auto 0; }
.audit-row { align-items: baseline; font-size: var(--text-sm); }
.audit-row span, .audit-row time { color: var(--color-muted); }
@media (max-width: 760px) {
  .container { width: min(100% - 28px, 620px); }
  .admin-metrics { grid-template-columns: 1fr; }
  .admin-grid { grid-template-columns: 1fr; }
  .admin-toolbar { align-items: stretch; flex-direction: column; }
}
@media (max-width: 480px) {
  .resource-row, .audit-row { align-items: start; flex-direction: column; }
  .form-error { align-items: stretch; flex-direction: column; }
}
:root[data-theme="light"] .status-button:disabled { opacity: 1; }
@media (prefers-color-scheme: light) {
  :root[data-theme="system"] .status-button:disabled { opacity: 1; }
}
</style>
