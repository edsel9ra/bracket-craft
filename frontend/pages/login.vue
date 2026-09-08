<script setup lang="ts">
import { safeInternalRedirect } from '~/utils/navigation';

const auth = useAuthStore();
const route = useRoute();
const { request } = useApi();
const { t } = useI18n();
const isRegister = ref(route.query.mode === 'register');
const email = ref('');
const password = ref('');
const fullName = ref('');
const organizationName = ref('');
const organizationSlug = ref('');

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

async function submit() {
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

  if (auth.organizationId) {
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

      <form class="auth-form" :aria-busy="auth.loading" @submit.prevent="submit">
        <label>
           {{ t('auth.email') }}
           <input
             v-model="email"
             type="email"
             autocomplete="email"
             :aria-describedby="auth.error ? 'auth-error' : undefined"
             :aria-invalid="auth.error ? 'true' : undefined"
             required
           />
        </label>
        <label>
           {{ t('auth.password') }}
           <input
             v-model="password"
             type="password"
             :autocomplete="isRegister ? 'new-password' : 'current-password'"
             :minlength="isRegister ? 8 : 1"
             :aria-describedby="auth.error ? 'auth-error' : undefined"
             :aria-invalid="auth.error ? 'true' : undefined"
             required
           />
        </label>
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
        <div v-if="auth.error" id="auth-error" class="form-error" role="alert">{{ auth.error }}</div>
        <button class="button-primary" type="submit" :disabled="auth.loading">
           {{ auth.loading ? t('common.processing') : isRegister ? t('auth.createAccount') : t('auth.login') }}
        </button>
      </form>

       <div class="auth-secondary-actions">
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
