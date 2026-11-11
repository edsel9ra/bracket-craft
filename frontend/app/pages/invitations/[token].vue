<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import FormField from '~/components/ui/FormField.vue';
import { isNotFound, isUnauthorized } from '~/utils/api';
import { roleKey, type AssignableRoleCode } from '~/utils/labels';
import { safeInternalRedirect } from '~/utils/navigation';

interface InvitationPreview {
  invitation_id: string;
  organization_id: string;
  organization_name: string;
  email: string;
  role_code: AssignableRoleCode;
  expires_at: string;
  status: 'pending' | 'accepted' | 'expired' | 'revoked';
  requires_login: boolean;
}

interface AcceptResponse {
  user_id: string;
  organization_id: string;
  organization_user_id: string;
  role_code: string;
  created_user: boolean;
}

const route = useRoute();
const auth = useAuthStore();
const { request } = useApi();
const { t, errorMessage, formatDateTime } = useI18n();
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
  return formatDateTime(value);
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
    <Surface as="section" class="invitation-card">
      <NuxtLink to="/" class="invitation-brand">BRACKET CRAFT</NuxtLink>
      <div v-if="loading" class="invitation-state" role="status">{{ t('common.loading') }}</div>
      <div v-else-if="error" class="invitation-state form-error" role="alert">{{ error }}</div>
      <template v-else-if="preview">
        <p class="eyebrow">{{ t('invitation.eyebrow') }}</p>
        <h1>{{ t('invitation.headline') }}</h1>
        <p class="invitation-copy">{{ t('invitation.copy', { organization: preview.organization_name }) }}</p>
        <dl class="invitation-details">
          <div><dt>{{ t('invitation.email') }}</dt><dd>{{ preview.email }}</dd></div>
          <div><dt>{{ t('invitation.role') }}</dt><dd>{{ t(roleKey(preview.role_code)) }}</dd></div>
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
            <FormField :label="t('invitation.fullName')" for-id="invitation-full-name">
              <template #default="{ id, ariaDescribedby }">
                <input :id="id" v-model="fullName" type="text" autocomplete="name" minlength="2" maxlength="100" required :aria-describedby="ariaDescribedby" />
              </template>
            </FormField>
            <FormField :label="t('invitation.password')" for-id="invitation-password">
              <template #default="{ id, ariaDescribedby }">
                <input :id="id" v-model="password" type="password" autocomplete="new-password" minlength="8" maxlength="128" required :aria-describedby="ariaDescribedby" />
              </template>
            </FormField>
          </template>
          <p v-if="error" class="form-error" role="alert">{{ error }}</p>
          <Button variant="primary" class="button-primary invitation-action" type="submit" :disabled="submitting || !canAccept">{{ submitting ? t('common.processing') : t('invitation.accept') }}</Button>
        </form>
      </template>
    </Surface>
  </main>
</template>

<style scoped>
/* RF-006/VI-1: el titular mantiene la composición fluida de la tarjeta. */
.invitation-shell { display: grid; min-height: 100vh; place-items: center; padding: var(--space-6); background: radial-gradient(circle at 20% 0%, color-mix(in srgb, var(--color-accent) 10%, transparent), transparent 32rem), var(--color-canvas); }
.invitation-card { width: min(100%, 540px); padding: var(--space-8); border: 1px solid var(--color-line); border-radius: var(--radius-xl); background: linear-gradient(145deg, color-mix(in srgb, var(--color-surface-raised) 96%, transparent), color-mix(in srgb, var(--color-surface) 98%, transparent)); box-shadow: var(--shadow-deep); }
.invitation-brand { color: var(--color-ink); font-size: var(--text-xs); font-weight: 900; letter-spacing: 0.16em; text-decoration: none; }
.invitation-brand:hover { color: var(--color-accent); }
.eyebrow { margin: var(--space-9) 0 var(--space-3); color: var(--color-accent); font-size: var(--text-xs); font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; }
h1 { margin: 0; font-size: clamp(2.5rem, 8vw, 4.8rem); line-height: 0.94; letter-spacing: -0.08em; }
.invitation-copy, .field-hint { color: var(--color-muted); line-height: 1.6; }
.invitation-details { display: grid; gap: var(--space-2); margin: var(--space-6) 0; padding: var(--space-4); border: 1px solid var(--color-line); border-radius: var(--radius-md); }
.invitation-details div { display: flex; justify-content: space-between; gap: var(--space-4); }
dt { color: var(--color-muted); font-size: var(--text-xs); } dd { margin: 0; color: var(--color-ink); font-size: var(--text-sm); text-align: right; }
.invitation-form { display: grid; gap: var(--space-4); margin-top: var(--space-5); }
label { display: grid; gap: var(--space-2); color: var(--color-muted); font-size: var(--text-sm); }
input { width: 100%; padding: var(--space-3) var(--space-4); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-canvas) 72%, transparent); color: var(--color-ink); }
input:focus { border-color: var(--color-accent); box-shadow: 0 0 0 4px var(--accent-glow); outline: none; }
.invitation-action { display: inline-flex; justify-content: center; width: 100%; margin-top: var(--space-2); min-height: 46px; text-decoration: none; }
.form-error { padding: var(--space-3); border: 1px solid var(--color-danger-border); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-danger-border) 10%, transparent); color: var(--color-danger); font-size: var(--text-md); }
.invitation-state { margin-top: var(--space-8); color: var(--color-muted); }
@media (max-width: 480px) { .invitation-shell { padding: var(--space-4); } .invitation-card { padding: var(--space-6) var(--space-5); } .invitation-details div { align-items: start; flex-direction: column; gap: var(--space-1); } dd { text-align: left; } }
</style>
