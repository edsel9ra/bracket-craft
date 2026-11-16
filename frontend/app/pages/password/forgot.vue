<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import FormField from '~/components/ui/FormField.vue';
import { emailError, passwordErrorKey, type ValidationMessage } from '~/utils/passwordRecovery';

const { forgot } = usePasswordAccount();
const { t } = useI18n();
useHead(() => ({ title: `${t('password.forgot.title')} | Bracket Craft` }));

const email = ref('');
const touched = ref(false);
const pending = ref(false);
const sent = ref(false);
const failure = ref<string | null>(null);
const failureRef = ref<HTMLElement | null>(null);
const sentRef = ref<HTMLElement | null>(null);

function message(value: ValidationMessage | null): string | null {
  return value ? t(value.key, 'params' in value ? value.params : undefined) : null;
}

const fieldError = computed(() => (touched.value ? message(emailError(email.value)) : null));

async function submit() {
  touched.value = true;
  if (fieldError.value || pending.value) return;
  pending.value = true;
  failure.value = null;
  try {
    await forgot(email.value);
    // RF-001: la misma confirmación exista o no la cuenta.
    sent.value = true;
    await nextTick();
    sentRef.value?.focus();
  } catch (cause) {
    failure.value = t(passwordErrorKey(cause));
    await nextTick();
    failureRef.value?.focus();
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
      <h1>{{ t('password.forgot.title') }}</h1>

      <div v-if="sent" ref="sentRef" class="form-notice" role="status" tabindex="-1" data-testid="password-forgot-sent">
        {{ t('password.forgot.sent') }}
      </div>
      <template v-else>
        <p class="password-copy">{{ t('password.forgot.description') }}</p>
        <form class="password-form" :aria-busy="pending" novalidate @submit.prevent="submit">
          <FormField :label="t('auth.email')" :error="fieldError" for-id="password-forgot-email">
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
          <p v-if="failure" ref="failureRef" class="form-error" role="alert" tabindex="-1">{{ failure }}</p>
          <Button variant="primary" class="button-primary" type="submit" :disabled="pending">
            {{ pending ? t('common.processing') : t('password.forgot.submit') }}
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
.password-back:hover { color: var(--color-accent); }
.eyebrow { margin: 0 0 var(--space-3); color: var(--color-accent); font-size: var(--text-xs); font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; }
h1 { margin: 0; font-size: var(--text-xl); line-height: 1.05; letter-spacing: -0.05em; }
.password-copy { margin: var(--space-3) 0 0; color: var(--color-muted); line-height: 1.6; }
.password-form { display: grid; gap: var(--space-4); margin-top: var(--space-6); }
input { width: 100%; padding: var(--space-3) var(--space-4); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-canvas) 72%, transparent); color: var(--color-ink); }
input:hover { border-color: var(--color-muted); }
input:focus { border-color: var(--color-accent); box-shadow: 0 0 0 4px var(--accent-glow); }
button[type='submit'] { justify-content: center; min-height: 46px; }
.form-error { margin: 0; padding: var(--space-3); border: 1px solid var(--color-danger-border); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-danger-border) 10%, transparent); color: var(--color-danger); font-size: var(--text-md); }
.form-notice { margin-top: var(--space-5); padding: var(--space-3); border: 1px solid color-mix(in srgb, var(--color-accent) 35%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-accent) 8%, transparent); color: var(--color-ink); font-size: var(--text-md); line-height: 1.6; }
@media (max-width: 760px) { .password-card { padding: var(--space-6); } }
</style>
