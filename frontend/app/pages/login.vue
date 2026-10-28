<script setup lang="ts">
import FormField from '~/components/ui/FormField.vue';
import { googleErrorKey } from '~/utils/googleAuth';
import { safeInternalRedirect } from '~/utils/navigation';

const auth = useAuthStore();
const route = useRoute();
const { request } = useApi();
const { t } = useI18n();
const isRegister = ref(route.query.mode === 'register');
const email = ref('');
const password = ref('');
const formTouched = ref(false);
const emailError = computed(() => formTouched.value && !email.value.trim() ? t('validation.required') : (formTouched.value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim()) ? t('validation.email') : null));
const passwordError = computed(() => formTouched.value && !password.value ? t('validation.required') : (formTouched.value && isRegister.value && password.value.length < 8 ? t('validation.minLength', { min: 8 }) : null));
const fullName = ref('');
const organizationName = ref('');
const organizationSlug = ref('');

// RF-1: la opción de Google solo se muestra si el servidor la tiene configurada.
// Se consulta durante el renderizado en servidor para no parpadear.
const { data: googleEnabled } = await useAsyncData(
  'auth-google-status',
  () => auth.googleStatus(),
  { default: () => false },
);
const googlePending = ref(false);
const googleError = ref<string | null>(null);
const googleStatusId = 'google-status';

const queryError = computed(() => {
  const raw = route.query.error;
  return typeof raw === 'string' && raw ? t(googleErrorKey(raw)) : null;
});

/**
 * Solo se reenvía un `redirect` interno y presente: si falta, el backend aplica
 * su destino por defecto (`/organization` sin organización, `/workspace` con
 * ella) en vez de forzar `/workspace`.
 */
const googleRedirect = computed(() => {
  const raw = route.query.redirect;
  if (typeof raw !== 'string' || !raw) return null;
  return safeInternalRedirect(raw, '') || null;
});

const needsOrganization = computed(() => Boolean(auth.userId && !auth.organizationId));

function failureCode(cause: unknown): string | null {
  const data = (cause as { data?: { code?: unknown } } | undefined)?.data;
  return typeof data?.code === 'string' ? data.code : null;
}

function normalizeOrganizationSlug(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 100);
}

function onOrganizationSlugInput(event: Event) {
  const input = event.target as HTMLInputElement;
  organizationSlug.value = normalizeOrganizationSlug(input.value);
}

useHead(() => ({
  title: isRegister.value ? `${t('auth.newOrganization')} | Bracket Craft` : `${t('common.login')} | Bracket Craft`,
}));

const redirectPath = computed(() => {
  return safeInternalRedirect(route.query.redirect, '/workspace');
});

async function startGoogle() {
  if (googlePending.value) return;
  googlePending.value = true;
  googleError.value = null;
  try {
    const authorizationUrl = await auth.startGoogleAuthorization('login', googleRedirect.value);
    window.location.assign(authorizationUrl);
  } catch (cause) {
    googleError.value = t(googleErrorKey(failureCode(cause)));
    googlePending.value = false;
  }
}

async function submit() {
  formTouched.value = true;
  if (emailError.value || passwordError.value) return;
  try {
    if (isRegister.value) {
      await auth.register({
        email: email.value,
        password: password.value,
        full_name: fullName.value,
        organization_name: organizationName.value,
        organization_slug: normalizeOrganizationSlug(organizationSlug.value),
      });
    } else {
      await auth.login(email.value, password.value);
    }
  } catch {
    return;
  }

  if (auth.organizationId || redirectPath.value.startsWith('/invitations/')) {
    await navigateTo(redirectPath.value);
  } else {
    try {
      await request('/platform/users?limit=1');
      await navigateTo('/admin');
    } catch {
      auth.error = t('auth.noActiveOrganization');
    }
  }
}
</script>

<template>
  <main id="main-content" class="auth-shell">
    <section class="auth-card">
      <NuxtLink to="/" class="auth-brand">BRACKET CRAFT</NuxtLink>
       <p class="eyebrow">{{ isRegister ? t('auth.newOrganization') : t('auth.workspaceAccess') }}</p>
       <h1>{{ isRegister ? t('auth.registerHeadline') : t('auth.loginHeadline') }}</h1>
       <p class="auth-copy">
         {{ isRegister ? t('auth.registerCopy') : t('auth.loginCopy') }}
      </p>

      <div v-if="googleEnabled" class="google-access">
        <button
          class="button-secondary auth-secondary-action google-button"
          type="button"
          :disabled="googlePending"
          :aria-busy="googlePending ? 'true' : 'false'"
          @click="startGoogle"
        >
          {{ googlePending ? t('google.waiting') : t('google.continue') }}
        </button>
        <p id="google-status" class="google-status" role="status" aria-live="polite">
          {{ googlePending ? t('google.waiting') : '' }}
        </p>
      </div>

      <form class="auth-form" :aria-busy="auth.loading" novalidate @submit.prevent="submit">
        <FormField :label="t('auth.email')" :error="emailError || auth.error" for-id="auth-email">
          <template #default="{ id, ariaDescribedby, ariaInvalid }">
            <input
              :id="id"
              v-model="email"
              type="email"
              autocomplete="email"
              :aria-describedby="ariaDescribedby"
              :aria-invalid="ariaInvalid ? true : undefined"
              required
            />
          </template>
        </FormField>
        <FormField :label="t('auth.password')" :error="passwordError || auth.error" for-id="auth-password">
          <template #default="{ id, ariaDescribedby, ariaInvalid }">
            <input
              :id="id"
              v-model="password"
              type="password"
              :autocomplete="isRegister ? 'new-password' : 'current-password'"
              :minlength="isRegister ? 8 : 1"
              :aria-describedby="ariaDescribedby"
              :aria-invalid="ariaInvalid ? true : undefined"
              required
            />
          </template>
        </FormField>
        <Transition name="panel-reveal" mode="out-in">
          <div v-if="isRegister" key="register-fields" class="register-fields">
            <label>
               {{ t('auth.fullName') }}
              <input v-model="fullName" type="text" autocomplete="name" minlength="2" required />
            </label>
            <label>
               {{ t('auth.organizationName') }}
              <input v-model="organizationName" type="text" minlength="2" required />
            </label>
            <label>
               {{ t('auth.organizationSlug') }}
              <input
                id="organization-slug"
                v-model="organizationSlug"
                @input="onOrganizationSlugInput"
                type="text"
                pattern="[a-z0-9\-]+"
                minlength="2"
                maxlength="100"
                autocomplete="off"
                autocapitalize="none"
                spellcheck="false"
                aria-describedby="organization-slug-help"
                required
              />
              <small id="organization-slug-help" class="field-help">
                 {{ t('auth.slugHelp') }}
              </small>
            </label>
          </div>
        </Transition>
        <div v-if="queryError || googleError || auth.error" id="auth-error" class="field-error" role="alert">
          {{ queryError || googleError || auth.error }}
        </div>
        <button class="button-primary" type="submit" :disabled="auth.loading">
           {{ auth.loading ? t('common.processing') : isRegister ? t('auth.createAccount') : t('auth.login') }}
        </button>
      </form>

       <div class="auth-secondary-actions">
         <NuxtLink v-if="needsOrganization" to="/organization" class="button-secondary auth-secondary-action">
            {{ t('organization.create') }}
         </NuxtLink>
         <button class="button-secondary auth-secondary-action mode-toggle" type="button" @click="isRegister = !isRegister; auth.error = null">
            {{ isRegister ? t('auth.haveAccount') : t('auth.createNewAccount') }}
         </button>
         <NuxtLink to="/" class="button-secondary auth-secondary-action back-link">{{ t('auth.backHome') }}</NuxtLink>
       </div>
    </section>
  </main>
</template>

<style scoped>
.auth-shell { position: relative; min-height: 100vh; display: grid; place-items: center; overflow: hidden; padding: 28px; background: radial-gradient(circle at 20% 0%, rgba(212, 243, 106, 0.1), transparent 32rem), #0c0f0c; }
.auth-shell::before, .auth-shell::after { position: absolute; border: 1px solid rgba(212, 243, 106, 0.12); border-radius: 50%; content: ''; pointer-events: none; }
.auth-shell::before { width: 38rem; height: 38rem; right: -20rem; top: -18rem; }
.auth-shell::after { width: 20rem; height: 20rem; left: -12rem; bottom: -10rem; background: rgba(212, 243, 106, 0.03); }
.auth-card { position: relative; z-index: 1; width: min(100%, 500px); padding: clamp(28px, 6vw, 56px); border: 1px solid var(--line); border-radius: 28px; background: linear-gradient(145deg, rgba(32, 37, 30, 0.96), rgba(21, 24, 20, 0.98)); box-shadow: var(--shadow-deep); }
.auth-brand { color: var(--ink); font-size: 0.78rem; font-weight: 900; letter-spacing: 0.16em; text-decoration: none; }
.auth-brand:hover { color: var(--accent); }
.eyebrow { margin: 62px 0 12px; color: var(--accent); font-size: 0.72rem; font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; }
h1 { margin: 0; font-size: clamp(2.4rem, 8vw, 4.6rem); line-height: 0.95; letter-spacing: -0.07em; }
.auth-copy { color: var(--muted); line-height: 1.6; }
.auth-form { display: grid; gap: 16px; margin-top: 28px; }
.google-access { display: grid; gap: 6px; margin-top: 24px; }
.google-button { width: 100%; justify-content: center; min-height: 46px; font-size: 0.9rem; }
.google-status { min-height: 1.1rem; margin: 0; color: var(--muted); font-size: 0.78rem; }
.register-fields { display: grid; gap: 16px; }
label { display: grid; gap: 7px; color: var(--muted); font-size: 0.82rem; }
input { width: 100%; padding: 0.82rem 0.9rem; border: 1px solid var(--line); border-radius: 10px; background: rgba(12, 15, 12, 0.72); color: var(--ink); }
input:hover { border-color: var(--muted); }
input:focus { border-color: var(--accent); box-shadow: 0 0 0 4px var(--accent-glow); }
.field-help { color: var(--muted); font-size: 0.75rem; line-height: 1.4; }
button[type='submit'] { justify-content: center; margin-top: 8px; min-height: 46px; }
button:disabled { cursor: wait; opacity: 0.6; }
.form-error { padding: 12px; border: 1px solid #a45b5b; border-radius: 10px; background: rgba(164, 91, 91, 0.1); color: var(--danger); font-size: 0.85rem; }
 .auth-secondary-actions { display: grid; gap: 10px; margin-top: 18px; }
 .auth-secondary-action { width: 100%; justify-content: center; min-height: 44px; font-size: 0.88rem; }
 .back-link { text-decoration: none; }
</style>
