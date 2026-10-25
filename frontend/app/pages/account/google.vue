<script setup lang="ts">
import { googleErrorKey, googleLinkActionVisible, googleNoticeKey } from '~/utils/googleAuth';

definePageMeta({ middleware: ['session'] });

const auth = useAuthStore();
const route = useRoute();
const { t } = useI18n();

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
    <section class="account-card">
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
    </section>
  </main>
</template>

<style scoped>
.account-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 28px;
  background: radial-gradient(circle at 20% 0%, rgba(212, 243, 106, 0.1), transparent 32rem), #0c0f0c;
}
.account-card {
  width: min(100%, 520px);
  padding: clamp(28px, 6vw, 48px);
  border: 1px solid var(--line);
  border-radius: 24px;
  background: linear-gradient(145deg, rgba(32, 37, 30, 0.96), rgba(21, 24, 20, 0.98));
  box-shadow: var(--shadow-deep);
}
.account-back {
  display: inline-block;
  margin-bottom: 26px;
  color: var(--muted);
  font-size: 0.78rem;
  text-decoration: underline;
}
.account-back:hover { color: var(--accent); }
.eyebrow {
  margin: 0 0 12px;
  color: var(--accent);
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}
h1 { margin: 0; font-size: clamp(1.9rem, 6vw, 2.8rem); line-height: 1.05; letter-spacing: -0.05em; }
.account-copy { margin: 14px 0 0; color: var(--muted); line-height: 1.6; }
.account-state { margin: 22px 0 0; color: var(--ink); font-size: 0.9rem; }
.google-link-button { width: 100%; justify-content: center; min-height: 46px; margin-top: 18px; font-size: 0.9rem; }
.account-waiting { min-height: 1.1rem; margin: 8px 0 0; color: var(--muted); font-size: 0.78rem; }
.form-error { margin-top: 18px; padding: 12px; border: 1px solid #a45b5b; border-radius: 10px; background: rgba(164, 91, 91, 0.1); color: var(--danger); font-size: 0.85rem; }
.form-notice { margin-top: 18px; padding: 12px; border: 1px solid rgba(212, 243, 106, 0.35); border-radius: 10px; background: rgba(212, 243, 106, 0.08); color: var(--ink); font-size: 0.85rem; }
</style>
