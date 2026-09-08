<script setup lang="ts">
import { safeInternalRedirect } from '~/utils/navigation';

const route = useRoute();
const auth = useAuthStore();
const { t } = useI18n();
const returnPath = computed(() => {
  const resource = String(route.query.resource || '');
  const fallback = resource === 'workspace' ? '/' : resource === 'admin' ? '/workspace' : '/workspace';
  const requested = safeInternalRedirect(route.query.returnTo, fallback);
  if (resource === 'workspace' && requested.startsWith('/workspace')) return '/';
  if (resource === 'admin' && requested.startsWith('/admin')) return '/workspace';
  return requested;
});

useHead(() => ({ title: `${t('error.forbidden')} | Bracket Craft` }));

async function signOut() {
  await auth.logout();
  await navigateTo('/login');
}
</script>

<template>
  <main id="main-content" class="forbidden-shell">
    <section class="forbidden-card" aria-labelledby="forbidden-title">
      <p class="eyebrow">403</p>
      <h1 id="forbidden-title">{{ t('error.forbidden') }}</h1>
      <p>{{ t('forbidden.copy') }}</p>
      <div class="forbidden-actions">
        <NuxtLink class="button-primary" :to="returnPath">{{ t('common.back') }}</NuxtLink>
        <button class="button-secondary" type="button" @click="signOut">{{ t('common.logout') }}</button>
      </div>
    </section>
  </main>
</template>

<style scoped>
.forbidden-shell { display: grid; min-height: 100vh; place-items: center; padding: 20px; background: radial-gradient(circle at 20% 0%, rgba(212, 243, 106, 0.1), transparent 32rem), #0c0f0c; }
.forbidden-card { width: min(100%, 620px); padding: clamp(28px, 7vw, 64px); border: 1px solid var(--line); border-radius: 24px; background: var(--surface); box-shadow: var(--shadow-deep); }
.forbidden-card h1 { max-width: 520px; margin: 12px 0; font-size: clamp(2.4rem, 8vw, 5.5rem); line-height: 0.94; letter-spacing: -0.08em; }
.forbidden-card p:not(.eyebrow) { max-width: 460px; color: var(--muted); line-height: 1.6; }
.forbidden-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 28px; }
@media (max-width: 375px) { .forbidden-actions > * { width: 100%; justify-content: center; } }
</style>
