<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import FormField from '~/components/ui/FormField.vue';
import { organizationCreationErrorKey } from '~/utils/organizationCreation';
import { safeInternalRedirect } from '~/utils/navigation';

definePageMeta({ middleware: ['session'] });

const auth = useAuthStore();
const route = useRoute();
const { t } = useI18n();
useHead(() => ({ title: `${t('organization.title')} | Bracket Craft` }));

const destination = computed(() => safeInternalRedirect(route.query.next, '/workspace'));

// Una sesión que ya tiene organización no ve el formulario: va a su destino.
if (auth.organizationId) {
  await navigateTo(destination.value, { replace: true });
}

const name = ref('');
const slug = ref('');
const submitting = ref(false);
const errorMessage = ref<string | null>(null);
const notice = ref<string | null>(null);
const titleElement = ref<HTMLElement | null>(null);

const normalizedSlug = computed(() => normalizeOrganizationSlug(slug.value));

const formTouched = ref(false);
const nameError = computed(() => formTouched.value && !name.value.trim() ? t('validation.required') : null);
const slugError = computed(() => formTouched.value && !slug.value.trim() ? t('validation.required') : (formTouched.value && normalizedSlug.value.length < 2 ? t('validation.minLength', { min: 2 }) : null));

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

function onSlugInput(event: Event) {
  const input = event.target as HTMLInputElement;
  slug.value = normalizeOrganizationSlug(input.value);
}

function failureCode(cause: unknown): string | null {
  const data = (cause as { data?: { code?: unknown } } | undefined)?.data;
  return typeof data?.code === 'string' ? data.code : null;
}

function failureStatus(cause: unknown): number | null {
  const failure = cause as { status?: unknown; statusCode?: unknown } | undefined;
  const candidate = failure?.status ?? failure?.statusCode;
  return typeof candidate === 'number' ? candidate : null;
}

async function submit() {
  if (submitting.value) return;
  formTouched.value = true;
  if (nameError.value || slugError.value) return;
  submitting.value = true;
  errorMessage.value = null;
  notice.value = null;
  try {
    await auth.createOrganization({ name: name.value.trim(), slug: normalizedSlug.value });
    // El destino llegó validado (`?next=`): una sola navegación con reemplazo.
    formTouched.value = false;
    await navigateTo(destination.value, { replace: true });
  } catch (cause) {
    const key = organizationCreationErrorKey(failureCode(cause), failureStatus(cause));
    errorMessage.value = t(key);
    if (key === 'organization.alreadyExists') {
      // Otra pestaña o una sesión anterior ya la creó: se recarga el estado sin
      // romper la página ni pedir de nuevo el acceso con Google.
      try {
        await auth.loadOrganizations();
      } catch {
        // Sin conexión se mantiene el mensaje y la sesión.
      }
      if (auth.organizationId) {
        await navigateTo(destination.value, { replace: true });
      }
    }
    submitting.value = false;
  }
}

function notNow() {
  // La sesión se conserva; el Workspace exige organización, así que el aviso se
  // muestra aquí y la persona puede retomarlo cuando quiera.
  notice.value = t('auth.noActiveOrganization');
}

onMounted(() => {
  titleElement.value?.focus();
});
</script>

<template>
  <main id="main-content" class="organization-shell">
    <Surface as="section" class="organization-card">
      <p class="eyebrow">Bracket Craft</p>
      <h1 id="organization-title" ref="titleElement" tabindex="-1">{{ t('organization.title') }}</h1>
      <p class="organization-copy">{{ t('organization.description') }}</p>

      <p v-if="errorMessage" id="organization-error" class="field-error" role="alert">
        {{ errorMessage }}
      </p>
      <p v-if="notice" class="form-notice" role="status" aria-live="polite">{{ notice }}</p>

      <form class="organization-form" :aria-busy="submitting" novalidate @submit.prevent="submit">
        <FormField :label="t('organization.name')" :error="nameError || errorMessage" for-id="organization-name">
          <template #default="{ id, ariaDescribedby, ariaInvalid }">
            <input
              :id="id"
              v-model="name"
              type="text"
              autocomplete="organization"
              minlength="2"
              maxlength="100"
              required
              :aria-invalid="ariaInvalid ? true : undefined"
              :aria-describedby="ariaDescribedby"
            />
          </template>
        </FormField>
        <FormField :label="t('organization.slug')" :error="slugError || errorMessage" for-id="organization-slug" :hint="t('organization.slugHelp')">
          <template #default="{ id, ariaDescribedby, ariaInvalid }">
            <input
              :id="id"
              :value="slug"
              type="text"
              pattern="[a-z0-9\-]+"
              minlength="2"
              maxlength="100"
              autocomplete="off"
              autocapitalize="none"
              spellcheck="false"
              required
              :aria-invalid="ariaInvalid ? true : undefined"
              :aria-describedby="ariaDescribedby"
              @input="onSlugInput"
            />
          </template>
        </FormField>

        <Button variant="primary" class="button-primary" type="submit" :disabled="submitting">
          {{ submitting ? t('organization.creating') : t('organization.create') }}
        </Button>
      </form>

      <Button variant="secondary" class="button-secondary organization-skip" type="button" @click="notNow">
        {{ t('organization.notNow') }}
      </Button>
    </Surface>
  </main>
</template>

<style scoped>
.organization-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: var(--space-6);
  background: radial-gradient(circle at 20% 0%, color-mix(in srgb, var(--color-accent) 10%, transparent), transparent 32rem), var(--color-canvas);
}
.organization-card {
  width: min(100%, 540px);
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
h1 { margin: 0; font-size: var(--text-xl); line-height: 1.05; letter-spacing: -0.05em; }
h1:focus { outline: none; }
.organization-copy { margin: var(--space-3) 0 0; color: var(--color-muted); line-height: 1.6; }
.organization-form { display: grid; gap: var(--space-4); margin-top: var(--space-6); }
label { display: grid; gap: var(--space-2); color: var(--color-muted); font-size: var(--text-sm); }
input { width: 100%; padding: var(--space-3) var(--space-4); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-canvas) 72%, transparent); color: var(--color-ink); }
input:hover { border-color: var(--color-muted); }
input:focus { border-color: var(--color-accent); box-shadow: 0 0 0 4px var(--accent-glow); }
.field-help { color: var(--color-muted); font-size: var(--text-xs); line-height: 1.4; }
button[type='submit'] { justify-content: center; margin-top: var(--space-1); min-height: 46px; }
button:disabled { cursor: wait; opacity: 0.6; }
.organization-skip { width: 100%; justify-content: center; min-height: 44px; margin-top: var(--space-3); font-size: var(--text-md); }
.form-error { margin-top: var(--space-4); padding: var(--space-3); border: 1px solid var(--color-danger-border); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-danger-border) 10%, transparent); color: var(--color-danger); font-size: var(--text-md); }
.form-notice { margin-top: var(--space-4); padding: var(--space-3); border: 1px solid color-mix(in srgb, var(--color-accent) 35%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-accent) 8%, transparent); color: var(--color-ink); font-size: var(--text-md); }
@media (max-width: 760px) { .organization-card { padding: var(--space-6); } }
:root[data-theme="light"] button:disabled { opacity: 1; }
@media (prefers-color-scheme: light) {
  :root[data-theme="system"] button:disabled { opacity: 1; }
}
</style>
