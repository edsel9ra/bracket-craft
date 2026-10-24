<script setup lang="ts">
import { googleCallbackDestination } from '~/utils/googleAuth';

// Sin middleware: el retorno del proveedor llega sin sesión visible para SSR
// (la cookie vive en el origen de la API); esta página la rehidrata en cliente.
definePageMeta({ middleware: [] });

const auth = useAuthStore();
const route = useRoute();
const { t } = useI18n();

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
    <section class="callback-card">
      <p class="eyebrow">Bracket Craft</p>
      <h1>{{ t('auth.workspaceAccess') }}</h1>
      <p class="callback-status" role="status" aria-live="polite">
        {{ t('google.waiting') }}
      </p>
    </section>
  </main>
</template>

<style scoped>
.callback-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 28px;
  background: radial-gradient(circle at 20% 0%, rgba(212, 243, 106, 0.1), transparent 32rem), #0c0f0c;
}
.callback-card {
  width: min(100%, 460px);
  padding: clamp(28px, 6vw, 48px);
  border: 1px solid var(--line);
  border-radius: 24px;
  background: linear-gradient(145deg, rgba(32, 37, 30, 0.96), rgba(21, 24, 20, 0.98));
  box-shadow: var(--shadow-deep);
}
.eyebrow {
  margin: 0 0 12px;
  color: var(--accent);
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}
h1 { margin: 0; font-size: clamp(2rem, 7vw, 3.2rem); line-height: 1; letter-spacing: -0.06em; }
.callback-status { margin: 18px 0 0; color: var(--muted); line-height: 1.6; }
</style>
