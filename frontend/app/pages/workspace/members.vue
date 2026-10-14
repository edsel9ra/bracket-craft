<script setup lang="ts">
import { isForbidden, isNotFound, isUnauthorized } from '~/utils/api';
import { safeInternalRedirect } from '~/utils/navigation';

definePageMeta({ middleware: 'auth' });

type MemberRole = 'administrator' | 'operator' | 'referee' | 'viewer';

interface Member {
  organization_user_id: string;
  user_id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  role_code: string;
  created_at: string;
}

interface Invitation {
  id: string;
  email: string;
  role_code: MemberRole;
  expires_at: string;
  status: 'pending' | 'accepted' | 'expired' | 'revoked';
  invite_url?: string | null;
  created_at: string;
}

const auth = useAuthStore();
const route = useRoute();
const { request } = useApi();
const { t, errorMessage, dateLocale } = useI18n();
const members = ref<Member[]>([]);
const invitations = ref<Invitation[]>([]);
const loading = ref(true);
const saving = ref(false);
const pageError = ref<string | null>(null);
const actionError = ref<string | null>(null);
const generatedLink = ref<string | null>(null);
const inviteForm = reactive<{ email: string; role_code: MemberRole }>({ email: '', role_code: 'viewer' });
const roles: Array<{ value: MemberRole; label: string }> = [
  { value: 'administrator', label: 'Administrator' },
  { value: 'operator', label: 'Operator' },
  { value: 'referee', label: 'Referee' },
  { value: 'viewer', label: 'Viewer' },
];

useHead({
  title: () => `${t('members.title')} | Bracket Craft`,
  meta: [{ name: 'robots', content: 'noindex, nofollow' }],
});

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(dateLocale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

async function redirectOnSessionFailure(cause: unknown): Promise<boolean> {
  if (isUnauthorized(cause) || isNotFound(cause)) {
    await auth.logout();
    await navigateTo({ path: '/login', query: { redirect: safeInternalRedirect(route.fullPath, '/workspace') } });
    return true;
  }
  if (isForbidden(cause)) {
    await navigateTo({ path: '/forbidden', query: { returnTo: '/workspace/members', resource: 'workspace' } });
    return true;
  }
  return false;
}

async function loadData() {
  loading.value = true;
  pageError.value = null;
  try {
    await auth.loadAccess();
    const [memberRows, invitationRows] = await Promise.all([
      request<Member[]>('/organizations/members'),
      request<Invitation[]>('/organizations/invitations'),
    ]);
    members.value = memberRows;
    invitations.value = invitationRows;
  } catch (cause) {
    if (!(await redirectOnSessionFailure(cause))) pageError.value = errorMessage(cause, t('members.noLoad'));
  } finally {
    loading.value = false;
  }
}

async function inviteMember() {
  saving.value = true;
  actionError.value = null;
  generatedLink.value = null;
  try {
    const invitation = await request<Invitation>('/organizations/invitations', {
      method: 'POST',
      body: { ...inviteForm },
    });
    generatedLink.value = invitation.invite_url || null;
    inviteForm.email = '';
    await loadData();
  } catch (cause) {
    if (!(await redirectOnSessionFailure(cause))) actionError.value = errorMessage(cause, t('members.noInvite'));
  } finally {
    saving.value = false;
  }
}

async function resendInvitation(invitation: Invitation) {
  saving.value = true;
  actionError.value = null;
  try {
    const updated = await request<Invitation>(`/organizations/invitations/${invitation.id}/resend`, { method: 'POST' });
    generatedLink.value = updated.invite_url || null;
    await loadData();
  } catch (cause) {
    if (!(await redirectOnSessionFailure(cause))) actionError.value = errorMessage(cause, t('members.noResend'));
  } finally {
    saving.value = false;
  }
}

async function revokeInvitation(invitation: Invitation) {
  if (import.meta.client && !window.confirm(t('members.confirmRevoke'))) return;
  saving.value = true;
  actionError.value = null;
  try {
    await request(`/organizations/invitations/${invitation.id}`, { method: 'DELETE' });
    await loadData();
  } catch (cause) {
    if (!(await redirectOnSessionFailure(cause))) actionError.value = errorMessage(cause, t('members.noRevoke'));
  } finally {
    saving.value = false;
  }
}

async function changeRole(member: Member, event: Event) {
  const role_code = (event.target as HTMLSelectElement).value as MemberRole;
  if (member.role_code === 'owner' || member.role_code === role_code) return;
  saving.value = true;
  actionError.value = null;
  try {
    const updated = await request<Member>(`/organizations/members/${member.organization_user_id}/role`, {
      method: 'PATCH',
      body: { role_code },
    });
    Object.assign(member, updated);
  } catch (cause) {
    if (!(await redirectOnSessionFailure(cause))) actionError.value = errorMessage(cause, t('members.noRoleChange'));
  } finally {
    saving.value = false;
  }
}

async function toggleMember(member: Member) {
  saving.value = true;
  actionError.value = null;
  try {
    const updated = await request<Member>(`/organizations/members/${member.organization_user_id}/status`, {
      method: 'PATCH',
      body: { is_active: !member.is_active },
    });
    Object.assign(member, updated);
  } catch (cause) {
    if (!(await redirectOnSessionFailure(cause))) actionError.value = errorMessage(cause, t('members.noStatusChange'));
  } finally {
    saving.value = false;
  }
}

async function copyLink() {
  if (generatedLink.value && import.meta.client && navigator.clipboard) {
    await navigator.clipboard.writeText(generatedLink.value);
  }
}

await loadData();
</script>

<template>
  <WorkspaceShell :breadcrumbs="[{ label: t('members.title'), current: true }]">
    <main id="main-content" class="members-shell">
      <section class="container members-hero">
        <p class="eyebrow">{{ t('members.eyebrow') }}</p>
        <h1>{{ t('members.headline') }}</h1>
        <p>{{ t('members.copy') }}</p>
      </section>

      <section class="container members-content">
        <div v-if="loading" class="empty-state" role="status">{{ t('common.loading') }}</div>
        <div v-else-if="pageError" class="form-error" role="alert">{{ pageError }}</div>
        <template v-else>
          <div class="members-grid">
            <form class="panel" :aria-busy="saving" @submit.prevent="inviteMember">
              <div>
                <p class="eyebrow">{{ t('members.inviteEyebrow') }}</p>
                <h2>{{ t('members.inviteTitle') }}</h2>
              </div>
              <label>{{ t('members.email') }}<input v-model="inviteForm.email" type="email" autocomplete="email" required /></label>
              <label>{{ t('members.role') }}<select v-model="inviteForm.role_code"><option v-for="role in roles" :key="role.value" :value="role.value">{{ role.label }}</option></select></label>
              <p class="field-hint">{{ t('members.expiryHint') }}</p>
              <button class="button-primary" type="submit" :disabled="saving">{{ saving ? t('common.processing') : t('members.invite') }}</button>
              <div v-if="generatedLink" class="generated-link" role="status">
                <strong>{{ t('members.generatedLink') }}</strong>
                <input :value="generatedLink" readonly aria-label="Invitation link" />
                <button class="button-secondary" type="button" @click="copyLink">{{ t('members.copyLink') }}</button>
              </div>
            </form>

            <section class="panel">
              <div class="panel-heading"><div><p class="eyebrow">{{ t('members.pendingEyebrow') }}</p><h2>{{ t('members.invitations') }}</h2></div><span class="muted-note">{{ invitations.length }}</span></div>
              <ul v-if="invitations.length" class="resource-list">
                <li v-for="invitation in invitations" :key="invitation.id">
                  <div><strong>{{ invitation.email }}</strong><small>{{ invitation.role_code }} · {{ invitation.status }} · {{ formatDate(invitation.expires_at) }}</small></div>
                  <div class="row-actions">
                    <button v-if="invitation.status !== 'accepted'" class="text-button" type="button" :disabled="saving" @click="resendInvitation(invitation)">{{ t('members.resend') }}</button>
                    <button v-if="invitation.status === 'pending'" class="text-button danger" type="button" :disabled="saving" @click="revokeInvitation(invitation)">{{ t('members.revoke') }}</button>
                  </div>
                </li>
              </ul>
              <p v-else class="muted-note">{{ t('members.noInvitations') }}</p>
            </section>
          </div>

          <div v-if="actionError" class="form-error" role="alert">{{ actionError }}</div>

          <section class="panel members-panel">
            <div class="panel-heading"><div><p class="eyebrow">{{ t('members.directoryEyebrow') }}</p><h2>{{ t('members.directory') }}</h2></div><span class="muted-note">{{ members.length }}</span></div>
            <div class="member-table-wrap">
              <table class="member-table">
                <thead><tr><th>{{ t('members.person') }}</th><th>{{ t('members.role') }}</th><th>{{ t('members.status') }}</th><th>{{ t('members.actions') }}</th></tr></thead>
                <tbody>
                  <tr v-for="member in members" :key="member.organization_user_id">
                    <td><strong>{{ member.full_name }}</strong><small>{{ member.email }}</small></td>
                    <td>
                      <select :value="member.role_code" :disabled="member.role_code === 'owner' || saving" @change="changeRole(member, $event)">
                        <option v-if="member.role_code === 'owner'" value="owner">Owner</option>
                        <option v-for="role in roles" :key="role.value" :value="role.value">{{ role.label }}</option>
                      </select>
                    </td>
                    <td><span class="status-tag" :class="{ inactive: !member.is_active }">{{ member.is_active ? t('members.active') : t('members.inactive') }}</span></td>
                    <td><button class="text-button" type="button" :disabled="saving" @click="toggleMember(member)">{{ member.is_active ? t('members.deactivate') : t('members.activate') }}</button></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </template>
      </section>
    </main>
  </WorkspaceShell>
</template>

<style scoped>
.members-shell { min-height: 100vh; background: radial-gradient(circle at 90% 8%, rgba(212, 243, 106, 0.08), transparent 28rem), #0c0f0c; }
.members-hero { padding: 5vh 0 4vh; }
.members-hero h1 { max-width: 760px; margin: 12px 0; font-size: clamp(2.7rem, 7vw, 5.7rem); line-height: 0.92; letter-spacing: -0.08em; }
.members-hero p:last-child { max-width: 560px; color: var(--muted); font-size: 1.05rem; line-height: 1.6; }
.members-content { display: grid; gap: 18px; padding-bottom: 90px; }
.members-grid { display: grid; grid-template-columns: minmax(280px, 0.8fr) minmax(0, 1.2fr); gap: 18px; align-items: start; }
.panel { display: grid; align-content: start; gap: 15px; min-width: 0; padding: 22px; border: 1px solid var(--line); border-radius: 20px; background: linear-gradient(145deg, rgba(32, 37, 30, 0.9), rgba(21, 24, 20, 0.94)); box-shadow: 0 18px 50px rgba(0, 0, 0, 0.12); }
.panel h2 { margin: 0; font-size: 1.5rem; letter-spacing: -0.05em; }
.panel-heading { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
label { display: grid; gap: 7px; color: var(--muted); font-size: 0.8rem; }
input, select { min-width: 0; padding: 0.78rem 0.85rem; border: 1px solid var(--line); border-radius: 9px; background: #0c0f0c; color: var(--ink); font: inherit; }
input:focus, select:focus { border-color: var(--accent); box-shadow: 0 0 0 4px var(--accent-glow); outline: none; }
.field-hint, .muted-note { color: var(--muted); font-size: 0.76rem; line-height: 1.5; }
.generated-link { display: grid; gap: 8px; padding-top: 12px; border-top: 1px solid var(--line); }
.generated-link input { font-size: 0.7rem; }
.resource-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.resource-list li { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 0; border-top: 1px solid var(--line); }
.resource-list li > div:first-child { display: grid; gap: 4px; min-width: 0; }
.resource-list small, .member-table small { display: block; overflow: hidden; color: var(--muted); font-size: 0.7rem; text-overflow: ellipsis; white-space: nowrap; }
.row-actions { display: flex; flex-wrap: wrap; justify-content: end; gap: 9px; }
.text-button { padding: 3px 0; background: transparent; color: var(--muted); font-size: 0.75rem; }
.text-button:hover:not(:disabled) { color: var(--accent); }
.text-button.danger:hover:not(:disabled) { color: var(--danger); }
.form-error, .empty-state { padding: 17px; border: 1px solid #a45b5b; border-radius: 12px; color: var(--danger); }
.empty-state { border-style: dashed; border-color: var(--line); color: var(--muted); }
.member-table-wrap { overflow-x: auto; }
.member-table { width: 100%; border-collapse: collapse; min-width: 650px; }
.member-table th { padding: 0 12px 11px; color: var(--muted); font-size: 0.67rem; letter-spacing: 0.08em; text-align: left; text-transform: uppercase; }
.member-table td { padding: 13px 12px; border-top: 1px solid var(--line); color: var(--ink); font-size: 0.82rem; }
.member-table td:first-child { display: grid; gap: 4px; }
.member-table select { padding: 0.55rem 0.62rem; font-size: 0.75rem; }
.status-tag { color: var(--accent); font-size: 0.7rem; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; }
.status-tag.inactive { color: var(--danger); }
@media (max-width: 800px) { .members-grid { grid-template-columns: 1fr; } .members-hero, .members-content { width: min(100% - 28px, 620px); } }
@media (max-width: 480px) { .panel { padding: 17px; } .resource-list li { align-items: start; flex-direction: column; } .row-actions { justify-content: start; } }
</style>
