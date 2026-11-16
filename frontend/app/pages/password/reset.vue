<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import FormField from '~/components/ui/FormField.vue';
import {
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  confirmationError,
  newPasswordError,
  passwordErrorCode,
  passwordErrorKey,
  resetTokenFromHash,
  urlWithoutFragment,
  type ValidationMessage,
} from '~/utils/passwordRecovery';

const auth = useAuthStore();
const { reset } = usePasswordAccount();
const { t } = useI18n();
useHead(() => ({ title: `${t('password.reset.title')} | Bracket Craft` }));

const token = ref<string | null>(null);
const ready = ref(false);
const password = ref('');
const confirmation = ref('');
const touched = ref(false);
const pending = ref(false);
const linkInvalid = ref(false);
const failure = ref<string | null>(null);
const failureRef = ref<HTMLElement | null>(null);

function message(value: ValidationMessage | null): string | null {
  return value ? t(value.key, 'params' in value ? value.params : undefined) : null;
}

const passwordError = computed(() => (touched.value ? message(newPasswordError(password.value)) : null));
const confirmError = computed(() => (touched.value ? message(confirmationError(password.value, confirmation.value)) : null));

onMounted(() => {
  // El token solo existe en el navegador: se lee y se retira del historial.
  token.value = resetTokenFromHash(window.location.hash);
  if (window.location.hash) {
    window.history.replaceState(window.history.state, '', urlWithoutFragment(window.location.pathname, window.location.search));
  }
  linkInvalid.value = !token.value;
  ready.value = true;
});

async function focusFailure() {
  await nextTick();
  failureRef.value?.focus();
}

async function submit() {
  touched.value = true;
  if (!token.value || passwordError.value || confirmError.value || pending.value) return;
  pending.value = true;
  failure.value = null;
  try {
    await reset(token.value, password.value);
    token.value = null;
    // RF-004: se cerraron todas las sesiones, también la de este navegador.
    auth.clearSession();
    await navigateTo({ path: '/login', query: { notice: 'password-reset' } });
  } catch (cause) {
    if (passwordErrorCode(cause) === 'PASSWORD_RESET_INVALID') {
      token.value = null;
      linkInvalid.value = true;
    }
    failure.value = t(passwordErrorKey(cause));
    await focusFailure();
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <main id="main-content" class="password-shell">
    <Surface as="section" class="password-card">
      <NuxtLink to="/login" class="password-back">{{ t('password.backToLogin') }}</NuxtLink>
      <p class="eyebrow">Bracket Craft</p>
      <h1>{{ t('password.reset.title') }}</h1>

      <template v-if="ready && linkInvalid">
        <p ref="failureRef" class="form-error" role="alert" tabindex="-1" data-testid="password-reset-invalid">
          {{ t('password.error.PASSWORD_RESET_INVALID') }}
        </p>
        <NuxtLink to="/password/forgot" class="password-link">{{ t('password.reset.requestNew') }}</NuxtLink>
      </template>
      <template v-else-if="ready">
        <p class="password-copy">{{ t('password.policy', { min: PASSWORD_MIN_LENGTH, max: PASSWORD_MAX_LENGTH }) }}</p>
        <form class="password-form" :aria-busy="pending" novalidate @submit.prevent="submit">
          <FormField :label="t('password.new')" :error="passwordError" for-id="password-reset-new">
            <template #default="{ id, ariaDescribedby, ariaInvalid }">
              <input
                :id="id"
                v-model="password"
                type="password"
                autocomplete="new-password"
                :maxlength="PASSWORD_MAX_LENGTH"
                :aria-describedby="ariaDescribedby"
                :aria-invalid="ariaInvalid ? true : undefined"
                required
              />
            </template>
          </FormField>
          <FormField :label="t('password.confirm')" :error="confirmError" for-id="password-reset-confirm">
            <template #default="{ id, ariaDescribedby, ariaInvalid }">
              <input
                :id="id"
                v-model="confirmation"
                type="password"
                autocomplete="new-password"
                :maxlength="PASSWORD_MAX_LENGTH"
                :aria-describedby="ariaDescribedby"
                :aria-invalid="ariaInvalid ? true : undefined"
                required
              />
            </template>
          </FormField>
          <p v-if="failure" ref="failureRef" class="form-error" role="alert" tabindex="-1">{{ failure }}</p>
          <Button variant="primary" class="button-primary" type="submit" :disabled="pending">
            {{ pending ? t('common.processing') : t('password.reset.submit') }}
          </Button>
        </form>
      </template>
    </Surface>
  </main>
</template>

<style scoped>
.password-shell { min-height: 100vh; display: grid; place-items: center; padding: var(--space-6); background: radial-gradient(circle at 20% 0%, color-mix(in srgb, var(--color-accent) 10%, transparent), transparent 32rem), var(--color-canvas); }
.password-card { width: min(100%, 500px); padding: var(--space-8); border: 1px solid var(--color-line); border-radius: var(--radius-lg); background: linear-gradient(145deg, color-mix(in srgb, var(--color-surface-raised) 96%, transparent), color-mix(in srgb, var(--color-surface) 98%, transparent)); box-shadow: var(--shadow-deep); }
.password-back { display: inline-block; margin-bottom: var(--space-6); color: var(--color-muted); font-size: var(--text-xs); text-decoration: underline; }
.password-back:hover, .password-link:hover { color: var(--color-accent); }
.password-link { display: inline-block; margin-top: var(--space-4); color: var(--color-ink); font-size: var(--text-md); text-decoration: underline; }
.eyebrow { margin: 0 0 var(--space-3); color: var(--color-accent); font-size: var(--text-xs); font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; }
h1 { margin: 0; font-size: var(--text-xl); line-height: 1.05; letter-spacing: -0.05em; }
.password-copy { margin: var(--space-3) 0 0; color: var(--color-muted); line-height: 1.6; }
.password-form { display: grid; gap: var(--space-4); margin-top: var(--space-6); }
input { width: 100%; padding: var(--space-3) var(--space-4); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-canvas) 72%, transparent); color: var(--color-ink); }
input:hover { border-color: var(--color-muted); }
input:focus { border-color: var(--color-accent); box-shadow: 0 0 0 4px var(--accent-glow); }
button[type='submit'] { justify-content: center; min-height: 46px; }
.form-error { margin: var(--space-5) 0 0; padding: var(--space-3); border: 1px solid var(--color-danger-border); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-danger-border) 10%, transparent); color: var(--color-danger); font-size: var(--text-md); }
.password-form .form-error { margin: 0; }
@media (max-width: 760px) { .password-card { padding: var(--space-6); } }
</style>
