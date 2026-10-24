<script setup lang="ts">
import { organizationCreationErrorKey } from '~/utils/organizationCreation';
import { safeInternalRedirect } from '~/utils/navigation';

definePageMeta({ middleware: ['session'] });

const auth = useAuthStore();
const route = useRoute();
const { t } = useI18n();

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
  submitting.value = true;
  errorMessage.value = null;
  notice.value = null;
  try {
    await auth.createOrganization({ name: name.value.trim(), slug: normalizedSlug.value });
    // El destino llegó validado (`?next=`): una sola navegación con reemplazo.
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
    <section class="organization-card">
      <p class="eyebrow">Bracket Craft</p>
      <h1 id="organization-title" ref="titleElement" tabindex="-1">{{ t('organization.title') }}</h1>
      <p class="organization-copy">{{ t('organization.description') }}</p>

      <p v-if="errorMessage" id="organization-error" class="form-error" role="alert">
        {{ errorMessage }}
      </p>
      <p v-if="notice" class="form-notice" role="status" aria-live="polite">{{ notice }}</p>

      <form class="organization-form" :aria-busy="submitting" @submit.prevent="submit">
        <label>
          {{ t('organization.name') }}
          <input
            v-model="name"
            type="text"
            autocomplete="organization"
            minlength="2"
            maxlength="100"
            required
            :aria-invalid="errorMessage ? 'true' : undefined"
            :aria-describedby="errorMessage ? 'organization-error' : undefined"
          />
        </label>
        <label>
          {{ t('organization.slug') }}
          <input
            id="organization-slug"
            :value="slug"
            type="text"
            pattern="[a-z0-9\-]+"
            minlength="2"
            maxlength="100"
            autocomplete="off"
            autocapitalize="none"
            spellcheck="false"
            required
            :aria-invalid="errorMessage ? 'true' : undefined"
            :aria-describedby="errorMessage ? 'organization-error organization-slug-help' : 'organization-slug-help'"
            @input="onSlugInput"
          />
          <small id="organization-slug-help" class="field-help">{{ t('organization.slugHelp') }}</small>
        </label>

        <button class="button-primary" type="submit" :disabled="submitting">
          {{ submitting ? t('organization.creating') : t('organization.create') }}
        </button>
      </form>

      <button class="button-secondary organization-skip" type="button" @click="notNow">
        {{ t('organization.notNow') }}
      </button>
    </section>
  </main>
</template>

<style scoped>
.organization-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 28px;
  background: radial-gradient(circle at 20% 0%, rgba(212, 243, 106, 0.1), transparent 32rem), #0c0f0c;
}
.organization-card {
  width: min(100%, 540px);
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
h1 { margin: 0; font-size: clamp(1.9rem, 6vw, 2.8rem); line-height: 1.05; letter-spacing: -0.05em; }
h1:focus { outline: none; }
.organization-copy { margin: 14px 0 0; color: var(--muted); line-height: 1.6; }
.organization-form { display: grid; gap: 16px; margin-top: 24px; }
label { display: grid; gap: 7px; color: var(--muted); font-size: 0.82rem; }
input { width: 100%; padding: 0.82rem 0.9rem; border: 1px solid var(--line); border-radius: 10px; background: rgba(12, 15, 12, 0.72); color: var(--ink); }
input:hover { border-color: var(--muted); }
input:focus { border-color: var(--accent); box-shadow: 0 0 0 4px var(--accent-glow); }
.field-help { color: var(--muted); font-size: 0.75rem; line-height: 1.4; }
button[type='submit'] { justify-content: center; margin-top: 4px; min-height: 46px; }
button:disabled { cursor: wait; opacity: 0.6; }
.organization-skip { width: 100%; justify-content: center; min-height: 44px; margin-top: 14px; font-size: 0.88rem; }
.form-error { margin-top: 18px; padding: 12px; border: 1px solid #a45b5b; border-radius: 10px; background: rgba(164, 91, 91, 0.1); color: var(--danger); font-size: 0.85rem; }
.form-notice { margin-top: 18px; padding: 12px; border: 1px solid rgba(212, 243, 106, 0.35); border-radius: 10px; background: rgba(212, 243, 106, 0.08); color: var(--ink); font-size: 0.85rem; }
</style>
