<script setup lang="ts">
import Surface from '~/components/ui/Surface.vue';
import { googleErrorKey, googleLinkActionVisible, googleNoticeKey } from '~/utils/googleAuth';

definePageMeta({ middleware: ['session'] });

const auth = useAuthStore();
const route = useRoute();
const { t } = useI18n();
useHead(() => ({ title: `${t('google.link.title')} | Bracket Craft` }));

const linked = ref(false);
const googleEnabled = ref(false);
const loading = ref(true);
const pending = ref(false);
const loadError = ref<string | null>(null);
const actionError = ref<string | null>(null);

const queryError = computed(() => {
  const raw = route.query.error;
  return typeof raw === 'string' && raw ? t(googleErrorKey(raw)) : null;
});

const successNotice = computed(() => {
  const raw = route.query.notice;
  if (typeof raw !== 'string' || !raw) return null;
  const key = googleNoticeKey(raw);
  return key ? t(key) : null;
});

const visibleError = computed(() => queryError.value || actionError.value || loadError.value);

const showLinkAction = computed(() => googleLinkActionVisible({
  enabled: googleEnabled.value,
  loading: loading.value,
  linked: linked.value,
  error: Boolean(loadError.value),
}));

function failureCode(cause: unknown): string | null {
  const data = (cause as { data?: { code?: unknown } } | undefined)?.data;
  return typeof data?.code === 'string' ? data.code : null;
}

onMounted(async () => {
  try {
    googleEnabled.value = await auth.googleStatus();
    if (!googleEnabled.value) {
      // RF-33: sin Google configurado no se ofrece ni se inicia la vinculación.
      loadError.value = t(googleErrorKey('GOOGLE_UNAVAILABLE'));
      return;
    }
    linked.value = await auth.googleLinkStatus();
  } catch (cause) {
    loadError.value = t(googleErrorKey(failureCode(cause)));
  } finally {
    loading.value = false;
  }
});

async function startLink() {
  if (pending.value || linked.value || !googleEnabled.value) return;
  pending.value = true;
  actionError.value = null;
  try {
    const authorizationUrl = await auth.linkGoogle();
    window.location.assign(authorizationUrl);
  } catch (cause) {
    actionError.value = t(googleErrorKey(failureCode(cause)));
    pending.value = false;
  }
}
</script>

<template>
  <main id="main-content" class="account-shell">
    <Surface as="section" class="account-card">
      <NuxtLink to="/workspace" class="account-back">{{ t('common.back') }}</NuxtLink>
      <p class="eyebrow">Bracket Craft</p>
      <h1>{{ t('google.link.title') }}</h1>
      <p class="account-copy">{{ t('google.link.description') }}</p>

      <p v-if="visibleError" class="form-error" role="alert">{{ visibleError }}</p>
      <p v-if="successNotice" class="form-notice" role="status">{{ successNotice }}</p>

      <p v-if="!loading && !loadError" class="account-state">
        {{ linked ? t('google.link.linked') : t('google.link.notLinked') }}
      </p>

      <button
        v-if="showLinkAction"
        class="button-secondary google-link-button"
        type="button"
        :disabled="pending"
        :aria-busy="pending ? 'true' : 'false'"
        @click="startLink"
      >
        {{ pending ? t('google.link.waiting') : t('google.link.action') }}
      </button>
      <p class="account-waiting" role="status" aria-live="polite">
        {{ pending ? t('google.link.waiting') : '' }}
      </p>
    </Surface>
  </main>
</template>

<style scoped>
.account-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: var(--space-6);
  background: radial-gradient(circle at 20% 0%, color-mix(in srgb, var(--color-accent) 10%, transparent), transparent 32rem), var(--color-canvas);
}
.account-card {
  width: min(100%, 520px);
  padding: var(--space-8);
  border: 1px solid var(--color-line);
  border-radius: var(--radius-lg);
  background: linear-gradient(145deg, color-mix(in srgb, var(--color-surface-raised) 96%, transparent), color-mix(in srgb, var(--color-surface) 98%, transparent));
  box-shadow: var(--shadow-deep);
}
.account-back {
  display: inline-block;
  margin-bottom: var(--space-6);
  color: var(--color-muted);
  font-size: var(--text-xs);
  text-decoration: underline;
}
.account-back:hover { color: var(--color-accent); }
.eyebrow {
  margin: 0 0 var(--space-3);
  color: var(--color-accent);
  font-size: var(--text-xs);
  font-weight: 800;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}
h1 { margin: 0; font-size: var(--text-xl); line-height: 1.05; letter-spacing: -0.05em; }
.account-copy { margin: var(--space-3) 0 0; color: var(--color-muted); line-height: 1.6; }
.account-state { margin: var(--space-5) 0 0; color: var(--color-ink); font-size: var(--text-md); }
.google-link-button { width: 100%; justify-content: center; min-height: 46px; margin-top: var(--space-4); font-size: var(--text-md); }
.account-waiting { min-height: 1.1rem; margin: var(--space-2) 0 0; color: var(--color-muted); font-size: var(--text-xs); }
.form-error { margin-top: var(--space-4); padding: var(--space-3); border: 1px solid var(--color-danger-border); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-danger-border) 10%, transparent); color: var(--color-danger); font-size: var(--text-md); }
.form-notice { margin-top: var(--space-4); padding: var(--space-3); border: 1px solid color-mix(in srgb, var(--color-accent) 35%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-accent) 8%, transparent); color: var(--color-ink); font-size: var(--text-md); }
@media (max-width: 760px) { .account-card { padding: var(--space-6); } }
</style>
