<script setup lang="ts">
import { isForbidden, isNotFound, isUnauthorized } from '~/utils/api';
import {
  beginInvitationOperation,
  invitationActionAriaKey,
  invitationActionConfirmKey,
  invitationActionErrorKey,
  invitationActionLabelKey,
  invitationActionsFor,
  invitationControlsDisabled,
  type InvitationAction,
  type InvitationOperation,
} from '~/utils/invitationActions';
import { invitationConflictCode, invitationConflictMessageKey } from '~/utils/invitationErrors';
import {
  ASSIGNABLE_ROLE_CODES,
  invitationStatusLabelKey,
  isAssignableRole,
  memberStatusLabelKey,
  roleKey,
  type AssignableRoleCode,
} from '~/utils/labels';
import { safeInternalRedirect } from '~/utils/navigation';
import { buildInviteMemberBody } from '~/utils/requestBodies';

definePageMeta({ middleware: 'auth' });

type MemberRole = AssignableRoleCode;

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
const { t, errorMessage, formatDateTime } = useI18n();
const members = ref<Member[]>([]);
const invitations = ref<Invitation[]>([]);
const loading = ref(true);
const saving = ref(false);
const invitationOperation = ref<InvitationOperation>('idle');
const pageError = ref<string | null>(null);
const actionError = ref<string | null>(null);
const generatedLink = ref<string | null>(null);
const inviteForm = reactive<{ email: string; role_code: MemberRole }>({ email: '', role_code: 'viewer' });
/** Los roles editables salen de la fuente única; `owner` no está entre ellos (RF-025). */
const assignableRoles = ASSIGNABLE_ROLE_CODES;

/** Estado de operación de invitaciones por acción; `saving` solo gobierna el directorio. */
const OPERATION_BY_ACTION: Record<InvitationAction, InvitationOperation> = {
  resend: 'resending',
  reopen: 'reopening',
  revoke: 'revoking',
};

/** Revocar conserva su confirmación de siempre; reabrir añade la suya (RF-006). */
const REVOKE_CONFIRM_KEY = 'members.confirmRevoke';

const isCreatingInvitation = computed(() => invitationOperation.value === 'creating');

useHead({
  title: () => `${t('members.title')} | Bracket Craft`,
  meta: [{ name: 'robots', content: 'noindex, nofollow' }],
});

function formatDate(value: string): string {
  return formatDateTime(value);
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

async function fetchLists(): Promise<[Member[], Invitation[]]> {
  await auth.loadAccess();
  return Promise.all([
    request<Member[]>('/organizations/members'),
    request<Invitation[]>('/organizations/invitations'),
  ]);
}

async function loadData() {
  loading.value = true;
  pageError.value = null;
  try {
    const [memberRows, invitationRows] = await fetchLists();
    members.value = memberRows;
    invitations.value = invitationRows;
  } catch (cause) {
    if (!(await redirectOnSessionFailure(cause))) pageError.value = errorMessage(cause, t('members.noLoad'));
  } finally {
    loading.value = false;
  }
}

/**
 * Recarga las listas tras una petición de invitación fallida: el servidor pudo escribir
 * antes de fallar (un 502 al enviar el correo llega **después** del commit) y la lista debe
 * reflejar el estado real (RF-007). No toca `loading`, `pageError`, `actionError` ni
 * `generatedLink`: si la recarga falla se conserva lo mostrado, el mensaje y el enlace.
 */
async function refreshInvitationLists() {
  try {
    const [memberRows, invitationRows] = await fetchLists();
    members.value = memberRows;
    invitations.value = invitationRows;
  } catch (cause) {
    await redirectOnSessionFailure(cause);
  }
}

/** El 409 trae un `code` estable; el catálogo del idioma activo lo traduce (RF-007). */
function invitationErrorMessage(cause: unknown, fallbackKey: string): string {
  const key = invitationConflictMessageKey(invitationConflictCode(cause));
  if (key) return t(key);
  return errorMessage(cause, t(fallbackKey));
}

async function inviteMember() {
  const operation = beginInvitationOperation(invitationOperation.value, 'creating');
  if (operation === null) return;
  invitationOperation.value = operation;
  actionError.value = null;
  generatedLink.value = null;
  try {
    const invitation = await request<Invitation>('/organizations/invitations', {
      method: 'POST',
      body: buildInviteMemberBody(inviteForm),
    });
    generatedLink.value = invitation.invite_url || null;
    inviteForm.email = '';
    await loadData();
  } catch (cause) {
    if (!(await redirectOnSessionFailure(cause))) {
      actionError.value = invitationErrorMessage(cause, 'members.noInvite');
      await refreshInvitationLists();
    }
  } finally {
    invitationOperation.value = 'idle';
  }
}

/** Un solo punto de entrada por activación: la compuerta evita la doble petición (RF-006). */
async function runInvitationAction(action: InvitationAction, invitation: Invitation) {
  const confirmKey = invitationActionConfirmKey(action) ?? (action === 'revoke' ? REVOKE_CONFIRM_KEY : null);
  if (confirmKey && import.meta.client && !window.confirm(t(confirmKey))) return;
  const operation = beginInvitationOperation(invitationOperation.value, OPERATION_BY_ACTION[action]);
  if (operation === null) return;
  invitationOperation.value = operation;
  actionError.value = null;
  try {
    if (action === 'revoke') {
      await request(`/organizations/invitations/${invitation.id}`, { method: 'DELETE' });
    } else {
      const path = action === 'reopen'
        ? `/organizations/invitations/${invitation.id}/reopen`
        : `/organizations/invitations/${invitation.id}/resend`;
      const updated = await request<Invitation>(path, { method: 'POST' });
      Object.assign(invitation, updated);
      generatedLink.value = updated.invite_url || null;
    }
    await loadData();
  } catch (cause) {
    if (!(await redirectOnSessionFailure(cause))) {
      actionError.value = invitationErrorMessage(cause, invitationActionErrorKey(action));
      await refreshInvitationLists();
    }
  } finally {
    invitationOperation.value = 'idle';
  }
}

/** Etiqueta accesible con rol y fecha de vencimiento: nunca el correo completo (RF-005). */
function invitationAria(action: InvitationAction, invitation: Invitation): string {
  return t(invitationActionAriaKey(action), {
    role: t(roleKey(invitation.role_code)),
    date: formatDate(invitation.expires_at),
  });
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
            <form class="panel" :aria-busy="invitationControlsDisabled(invitationOperation)" @submit.prevent="inviteMember">
              <div>
                <p class="eyebrow">{{ t('members.inviteEyebrow') }}</p>
                <h2>{{ t('members.inviteTitle') }}</h2>
              </div>
              <label>{{ t('members.email') }}<input v-model="inviteForm.email" type="email" autocomplete="email" required /></label>
              <label>{{ t('members.role') }}<select v-model="inviteForm.role_code"><option v-for="role in assignableRoles" :key="role" :value="role">{{ t(roleKey(role)) }}</option></select></label>
              <p class="field-hint">{{ t('members.expiryHint') }}</p>
              <button class="button-primary" type="submit" :disabled="invitationControlsDisabled(invitationOperation)">{{ isCreatingInvitation ? t('common.processing') : t('members.invite') }}</button>
              <div v-if="generatedLink" class="generated-link" role="status">
                <strong>{{ t('members.generatedLink') }}</strong>
                <input :value="generatedLink" readonly :aria-label="t('members.generatedLinkAria')" />
                <button class="button-secondary" type="button" @click="copyLink">{{ t('members.copyLink') }}</button>
              </div>
            </form>

            <section class="panel">
              <div class="panel-heading"><div><p class="eyebrow">{{ t('members.pendingEyebrow') }}</p><h2>{{ t('members.invitations') }}</h2></div><span class="muted-note">{{ invitations.length }}</span></div>
              <ul v-if="invitations.length" class="resource-list">
                <li v-for="invitation in invitations" :key="invitation.id">
                  <div><strong>{{ invitation.email }}</strong><small>{{ t(roleKey(invitation.role_code)) }} · {{ t(invitationStatusLabelKey(invitation.status)) }} · {{ formatDate(invitation.expires_at) }}</small></div>
                  <div class="row-actions">
                    <button v-for="action in invitationActionsFor(invitation.status)" :key="action" class="text-button" :class="{ danger: action === 'revoke' }" type="button" :disabled="invitationControlsDisabled(invitationOperation)" :aria-label="invitationAria(action, invitation)" @click="runInvitationAction(action, invitation)">{{ t(invitationActionLabelKey(action)) }}</button>
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
                        <option v-if="!isAssignableRole(member.role_code)" :value="member.role_code">{{ t(roleKey(member.role_code)) }}</option>
                        <option v-for="role in assignableRoles" :key="role" :value="role">{{ t(roleKey(role)) }}</option>
                      </select>
                    </td>
                    <td><span class="status-tag" :class="{ inactive: !member.is_active }">{{ t(memberStatusLabelKey(member.is_active ? 'active' : 'inactive')) }}</span></td>
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
