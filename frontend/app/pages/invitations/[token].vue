<script setup lang="ts">
import { isNotFound, isUnauthorized } from '~/utils/api';
import { safeInternalRedirect } from '~/utils/navigation';

interface InvitationPreview {
  invitation_id: string;
  organization_id: string;
  organization_name: string;
  email: string;
  role_code: 'administrator' | 'operator' | 'referee' | 'viewer';
  expires_at: string;
  status: 'pending' | 'accepted' | 'expired' | 'revoked';
  requires_login: boolean;
}

interface AcceptResponse {
  access_token?: string | null;
  token_type: string;
  user_id: string;
  organization_id: string;
  organization_user_id: string;
  role_code: string;
  created_user: boolean;
}

const route = useRoute();
const auth = useAuthStore();
const { request } = useApi();
const { t, errorMessage, dateLocale } = useI18n();
const token = encodeURIComponent(String(route.params.token));
const preview = ref<InvitationPreview | null>(null);
const loading = ref(true);
const submitting = ref(false);
const error = ref<string | null>(null);
const fullName = ref('');
const password = ref('');

useHead(() => ({
  title: `${t('invitation.title')} | Bracket Craft`,
  meta: [{ name: 'robots', content: 'noindex, nofollow' }],
}));

const loginRedirect = computed(() => `/invitations/${encodeURIComponent(String(route.params.token))}`);
const canAccept = computed(() => Boolean(preview.value?.status === 'pending' && (!preview.value.requires_login ? fullName.value.trim() && password.value : auth.userId)));

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(dateLocale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

async function loadPreview() {
  try {
    preview.value = await request<InvitationPreview>(`/invitations/${token}`);
  } catch (cause) {
    error.value = errorMessage(cause, t('invitation.invalid'));
  } finally {
    loading.value = false;
  }
}

async function accept() {
  if (!preview.value || !canAccept.value) return;
  submitting.value = true;
  error.value = null;
  try {
    const result = await request<AcceptResponse>(`/invitations/${token}/accept`, {
      method: 'POST',
      body: {
        password: preview.value.requires_login ? null : password.value,
        full_name: preview.value.requires_login ? null : fullName.value,
      },
    });
    await auth.adoptSession({
      user_id: result.user_id,
      organization_id: result.organization_id,
      access_token: result.access_token,
      token_type: result.token_type,
    });
    await navigateTo('/workspace');
  } catch (cause) {
    if (isUnauthorized(cause)) {
      await navigateTo({ path: '/login', query: { redirect: safeInternalRedirect(loginRedirect.value, '/') } });
      return;
    }
    error.value = errorMessage(cause, t('invitation.noAccept'));
  } finally {
    submitting.value = false;
  }
}

await loadPreview();
</script>

<template>
  <main id="main-content" class="invitation-shell">
    <section class="invitation-card">
      <NuxtLink to="/" class="invitation-brand">BRACKET CRAFT</NuxtLink>
      <div v-if="loading" class="invitation-state" role="status">{{ t('common.loading') }}</div>
      <div v-else-if="error" class="invitation-state form-error" role="alert">{{ error }}</div>
      <template v-else-if="preview">
        <p class="eyebrow">{{ t('invitation.eyebrow') }}</p>
        <h1>{{ t('invitation.headline') }}</h1>
        <p class="invitation-copy">{{ t('invitation.copy', { organization: preview.organization_name }) }}</p>
        <dl class="invitation-details">
          <div><dt>{{ t('invitation.email') }}</dt><dd>{{ preview.email }}</dd></div>
          <div><dt>{{ t('invitation.role') }}</dt><dd>{{ preview.role_code }}</dd></div>
          <div><dt>{{ t('invitation.expires') }}</dt><dd>{{ formatDate(preview.expires_at) }}</dd></div>
        </dl>
        <div v-if="preview.status !== 'pending'" class="form-error" role="alert">{{ t('invitation.unavailable') }}</div>
        <template v-else-if="preview.requires_login && !auth.userId">
          <p class="field-hint">{{ t('invitation.existingAccount') }}</p>
          <NuxtLink class="button-primary invitation-action" :to="{ path: '/login', query: { redirect: loginRedirect } }">{{ t('invitation.login') }}</NuxtLink>
        </template>
        <form v-else class="invitation-form" @submit.prevent="accept">
          <p v-if="preview.requires_login" class="field-hint">{{ t('invitation.confirmAccount') }}</p>
          <template v-else>
            <label>{{ t('invitation.fullName') }}<input v-model="fullName" type="text" autocomplete="name" minlength="2" maxlength="100" required /></label>
            <label>{{ t('invitation.password') }}<input v-model="password" type="password" autocomplete="new-password" minlength="8" maxlength="128" required /></label>
          </template>
          <p v-if="error" class="form-error" role="alert">{{ error }}</p>
          <button class="button-primary invitation-action" type="submit" :disabled="submitting || !canAccept">{{ submitting ? t('common.processing') : t('invitation.accept') }}</button>
        </form>
      </template>
    </section>
  </main>
</template>

<style scoped>
.invitation-shell { display: grid; min-height: 100vh; place-items: center; padding: 28px; background: radial-gradient(circle at 20% 0%, rgba(212, 243, 106, 0.1), transparent 32rem), #0c0f0c; }
.invitation-card { width: min(100%, 540px); padding: clamp(28px, 6vw, 56px); border: 1px solid var(--line); border-radius: 28px; background: linear-gradient(145deg, rgba(32, 37, 30, 0.96), rgba(21, 24, 20, 0.98)); box-shadow: var(--shadow-deep); }
.invitation-brand { color: var(--ink); font-size: 0.78rem; font-weight: 900; letter-spacing: 0.16em; text-decoration: none; }
.invitation-brand:hover { color: var(--accent); }
.eyebrow { margin: 62px 0 12px; color: var(--accent); font-size: 0.72rem; font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; }
h1 { margin: 0; font-size: clamp(2.5rem, 8vw, 4.8rem); line-height: 0.94; letter-spacing: -0.08em; }
.invitation-copy, .field-hint { color: var(--muted); line-height: 1.6; }
.invitation-details { display: grid; gap: 10px; margin: 26px 0; padding: 16px; border: 1px solid var(--line); border-radius: 13px; }
.invitation-details div { display: flex; justify-content: space-between; gap: 16px; }
dt { color: var(--muted); font-size: 0.75rem; } dd { margin: 0; color: var(--ink); font-size: 0.8rem; text-align: right; }
.invitation-form { display: grid; gap: 15px; margin-top: 22px; }
label { display: grid; gap: 7px; color: var(--muted); font-size: 0.82rem; }
input { width: 100%; padding: 0.82rem 0.9rem; border: 1px solid var(--line); border-radius: 10px; background: rgba(12, 15, 12, 0.72); color: var(--ink); }
input:focus { border-color: var(--accent); box-shadow: 0 0 0 4px var(--accent-glow); outline: none; }
.invitation-action { display: inline-flex; justify-content: center; width: 100%; margin-top: 8px; min-height: 46px; text-decoration: none; }
.form-error { padding: 12px; border: 1px solid #a45b5b; border-radius: 10px; background: rgba(164, 91, 91, 0.1); color: var(--danger); font-size: 0.85rem; }
.invitation-state { margin-top: 42px; color: var(--muted); }
@media (max-width: 480px) { .invitation-shell { padding: 16px; } .invitation-card { padding: 25px 20px; } .invitation-details div { align-items: start; flex-direction: column; gap: 4px; } dd { text-align: left; } }
</style>
