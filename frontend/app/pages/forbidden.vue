<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
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
    <Surface as="section" class="forbidden-card" aria-labelledby="forbidden-title">
      <p class="eyebrow">403</p>
      <h1 id="forbidden-title">{{ t('error.forbidden') }}</h1>
      <p>{{ t('forbidden.copy') }}</p>
      <div class="forbidden-actions">
        <Button as="NuxtLink" variant="primary" class="button-primary" :to="returnPath">{{ t('common.back') }}</Button>
        <Button variant="secondary" class="button-secondary" type="button" @click="signOut">{{ t('common.logout') }}</Button>
      </div>
    </Surface>
  </main>
</template>

<style scoped>
.forbidden-shell { display: grid; min-height: 100vh; place-items: center; padding: var(--space-5); background: radial-gradient(circle at 20% 0%, color-mix(in srgb, var(--color-accent) 10%, transparent), transparent 32rem), var(--color-canvas); }
.forbidden-card { width: min(100%, 620px); padding: var(--space-9); border: 1px solid var(--color-line); border-radius: var(--radius-lg); background: var(--color-surface); box-shadow: var(--shadow-deep); }
.forbidden-card h1 { max-width: 520px; margin: var(--space-3) 0; font-size: var(--text-display); line-height: 0.94; letter-spacing: -0.08em; }
.forbidden-card p:not(.eyebrow) { max-width: 460px; color: var(--color-muted); line-height: 1.6; }
.forbidden-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-6); }
@media (max-width: 760px) { .forbidden-card { padding: var(--space-6); } }
</style>
