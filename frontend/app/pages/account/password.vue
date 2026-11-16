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
  type ValidationMessage,
} from '~/utils/passwordRecovery';

definePageMeta({ middleware: ['session'] });

const { hasPassword, change } = usePasswordAccount();
const { t } = useI18n();
useHead(() => ({ title: `${t('password.change.title')} | Bracket Craft` }));

const loading = ref(true);
const hasLocalPassword = ref(false);
const loadError = ref<string | null>(null);
const current = ref('');
const password = ref('');
const confirmation = ref('');
const touched = ref(false);
const pending = ref(false);
const failure = ref<string | null>(null);
const currentRejected = ref(false);
const changed = ref(false);
const failureRef = ref<HTMLElement | null>(null);
const changedRef = ref<HTMLElement | null>(null);

function message(value: ValidationMessage | null): string | null {
  return value ? t(value.key, 'params' in value ? value.params : undefined) : null;
}

const currentError = computed(() => {
  if (currentRejected.value) return t('password.error.CURRENT_PASSWORD_INVALID');
  return touched.value && !current.value ? t('validation.required') : null;
});
const passwordError = computed(() => (touched.value ? message(newPasswordError(password.value)) : null));
const confirmError = computed(() => (touched.value ? message(confirmationError(password.value, confirmation.value)) : null));

onMounted(async () => {
  try {
    hasLocalPassword.value = await hasPassword();
  } catch (cause) {
    loadError.value = t(passwordErrorKey(cause));
  } finally {
    loading.value = false;
  }
});

watch(current, () => { currentRejected.value = false; });

async function submit() {
  touched.value = true;
  changed.value = false;
  if (currentError.value || passwordError.value || confirmError.value || pending.value) return;
  pending.value = true;
  failure.value = null;
  try {
    await change(current.value, password.value);
    current.value = '';
    password.value = '';
    confirmation.value = '';
    touched.value = false;
    changed.value = true;
    await nextTick();
    changedRef.value?.focus();
  } catch (cause) {
    const code = passwordErrorCode(cause);
    if (code === 'CURRENT_PASSWORD_INVALID') {
      currentRejected.value = true;
      await nextTick();
      document.getElementById('password-change-current')?.focus();
      return;
    }
    if (code === 'PASSWORD_NOT_SET') hasLocalPassword.value = false;
    failure.value = t(passwordErrorKey(cause));
    await nextTick();
    failureRef.value?.focus();
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <main id="main-content" class="account-shell">
    <Surface as="section" class="account-card">
      <NuxtLink to="/workspace" class="account-back">{{ t('common.back') }}</NuxtLink>
      <p class="eyebrow">Bracket Craft</p>
      <h1>{{ t('password.change.title') }}</h1>

      <p v-if="loadError" class="form-error" role="alert">{{ loadError }}</p>
      <p v-else-if="!loading && !hasLocalPassword" class="form-notice" role="status" data-testid="password-google-only">
        {{ t('password.change.googleOnly') }}
      </p>
      <template v-else-if="!loading">
        <p class="account-copy">{{ t('password.change.description') }}</p>
        <div v-if="changed" ref="changedRef" class="form-notice" role="status" tabindex="-1" data-testid="password-changed">
          {{ t('password.change.success') }}
        </div>
        <form class="account-form" :aria-busy="pending" novalidate @submit.prevent="submit">
          <FormField :label="t('password.current')" :error="currentError" for-id="password-change-current">
            <template #default="{ id, ariaDescribedby, ariaInvalid }">
              <input
                :id="id"
                v-model="current"
                type="password"
                autocomplete="current-password"
                :maxlength="PASSWORD_MAX_LENGTH"
                :aria-describedby="ariaDescribedby"
                :aria-invalid="ariaInvalid ? true : undefined"
                required
              />
            </template>
          </FormField>
          <FormField :label="t('password.new')" :error="passwordError" for-id="password-change-new">
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
          <FormField :label="t('password.confirm')" :error="confirmError" for-id="password-change-confirm">
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
          <p class="account-hint">{{ t('password.policy', { min: PASSWORD_MIN_LENGTH, max: PASSWORD_MAX_LENGTH }) }}</p>
          <p v-if="failure" ref="failureRef" class="form-error" role="alert" tabindex="-1">{{ failure }}</p>
          <Button variant="primary" class="button-primary" type="submit" :disabled="pending">
            {{ pending ? t('common.processing') : t('password.change.submit') }}
          </Button>
        </form>
      </template>
    </Surface>
  </main>
</template>

<style scoped>
.account-shell { min-height: 100vh; display: grid; place-items: center; padding: var(--space-6); background: radial-gradient(circle at 20% 0%, color-mix(in srgb, var(--color-accent) 10%, transparent), transparent 32rem), var(--color-canvas); }
.account-card { width: min(100%, 520px); padding: var(--space-8); border: 1px solid var(--color-line); border-radius: var(--radius-lg); background: linear-gradient(145deg, color-mix(in srgb, var(--color-surface-raised) 96%, transparent), color-mix(in srgb, var(--color-surface) 98%, transparent)); box-shadow: var(--shadow-deep); }
.account-back { display: inline-block; margin-bottom: var(--space-6); color: var(--color-muted); font-size: var(--text-xs); text-decoration: underline; }
.account-back:hover { color: var(--color-accent); }
.eyebrow { margin: 0 0 var(--space-3); color: var(--color-accent); font-size: var(--text-xs); font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; }
h1 { margin: 0; font-size: var(--text-xl); line-height: 1.05; letter-spacing: -0.05em; }
.account-copy { margin: var(--space-3) 0 0; color: var(--color-muted); line-height: 1.6; }
.account-form { display: grid; gap: var(--space-4); margin-top: var(--space-6); }
.account-hint { margin: 0; color: var(--color-muted); font-size: var(--text-xs); line-height: 1.4; }
input { width: 100%; padding: var(--space-3) var(--space-4); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-canvas) 72%, transparent); color: var(--color-ink); }
input:hover { border-color: var(--color-muted); }
input:focus { border-color: var(--color-accent); box-shadow: 0 0 0 4px var(--accent-glow); }
button[type='submit'] { justify-content: center; min-height: 46px; }
.form-error { margin: var(--space-4) 0 0; padding: var(--space-3); border: 1px solid var(--color-danger-border); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-danger-border) 10%, transparent); color: var(--color-danger); font-size: var(--text-md); }
.account-form .form-error { margin: 0; }
.form-notice { margin-top: var(--space-4); padding: var(--space-3); border: 1px solid color-mix(in srgb, var(--color-accent) 35%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-accent) 8%, transparent); color: var(--color-ink); font-size: var(--text-md); line-height: 1.6; }
@media (max-width: 760px) { .account-card { padding: var(--space-6); } }
</style>
