<script setup lang="ts">
import Surface from '~/components/ui/Surface.vue';
import { googleCallbackDestination } from '~/utils/googleAuth';

// Sin middleware: el retorno del proveedor llega sin sesión visible para SSR
// (la cookie vive en el origen de la API); esta página la rehidrata en cliente.
definePageMeta({ middleware: [] });

const auth = useAuthStore();
const route = useRoute();
const { t } = useI18n();
useHead(() => ({ title: `${t('common.login')} | Bracket Craft` }));

function landingDestination(): string {
  // `next` solo se usa tras validarlo: nunca se renderiza ni se navega en crudo.
  const explicit = googleCallbackDestination(route.query.next, '');
  if (explicit) return explicit;
  return auth.organizationId ? '/workspace' : '/organization';
}

onMounted(async () => {
  try {
    const session = await auth.restoreSession();
    if (!session) {
      await navigateTo(
        { path: '/login', query: { error: 'GOOGLE_STATE_INVALID' } },
        { replace: true },
      );
      return;
    }
    // `replace`: el retorno no deja una entrada extra en el historial (D-4).
    await navigateTo(landingDestination(), { replace: true });
  } catch {
    await navigateTo(
      { path: '/login', query: { error: 'GOOGLE_UNAVAILABLE' } },
      { replace: true },
    );
  }
});
</script>

<template>
  <main id="main-content" class="callback-shell">
    <Surface as="section" class="callback-card">
      <p class="eyebrow">Bracket Craft</p>
      <h1>{{ t('auth.workspaceAccess') }}</h1>
      <p class="callback-status" role="status" aria-live="polite">
        {{ t('google.waiting') }}
      </p>
    </Surface>
  </main>
</template>

<style scoped>
.callback-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: var(--space-6);
  background: radial-gradient(circle at 20% 0%, color-mix(in srgb, var(--color-accent) 10%, transparent), transparent 32rem), var(--color-canvas);
}
.callback-card {
  width: min(100%, 460px);
  padding: var(--space-8);
  border: 1px solid var(--color-line);
  border-radius: var(--radius-lg);
  background: linear-gradient(145deg, color-mix(in srgb, var(--color-surface-raised) 96%, transparent), color-mix(in srgb, var(--color-surface) 98%, transparent));
  box-shadow: var(--shadow-deep);
}
.eyebrow {
  margin: 0 0 var(--space-3);
  color: var(--color-accent);
  font-size: var(--text-xs);
  font-weight: 800;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}
h1 { margin: 0; font-size: var(--text-xl); line-height: 1; letter-spacing: -0.06em; }
.callback-status { margin: var(--space-4) 0 0; color: var(--color-muted); line-height: 1.6; }
@media (max-width: 760px) { .callback-card { padding: var(--space-6); } }
</style>
