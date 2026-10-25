<script setup lang="ts">
/**
 * Escudo de un equipo con sustituto de iniciales (spec 014, T14).
 *
 * La precedencia la decide `crestSource` (el `logo_url` heredado solo se ve en
 * el Workspace) y la imagen tiene el nombre del equipo como texto alternativo.
 * Si la imagen no carga se muestran las iniciales con el mismo nombre
 * accesible: no se pide un enlace nuevo ni se reintenta la carga. Un cambio de
 * prop (una nueva carga) sí vuelve a intentar la imagen nueva.
 */
import { crestSource, teamInitials, type CrestSurface } from '~/utils/teamCrest';

interface TeamIdentity {
  name: string;
  short_code?: string | null;
  shortCode?: string | null;
}

const props = withDefaults(defineProps<{
  team: TeamIdentity;
  crestUrl?: string | null;
  logoUrl?: string | null;
  surface?: CrestSurface;
}>(), {
  crestUrl: null,
  logoUrl: null,
  surface: 'workspace',
});

const { t } = useI18n();
const imageFailed = ref(false);

const source = computed(() => {
  if (imageFailed.value) {
    return 'initials' as const;
  }
  return crestSource({
    crestUrl: props.crestUrl,
    logoUrl: props.logoUrl,
    surface: props.surface,
  });
});

const alt = computed(() => t('crest.alt', { team: props.team.name }));
const initials = computed(() =>
  teamInitials(props.team.name, props.team.short_code ?? props.team.shortCode ?? ''),
);
const src = computed(() =>
  source.value === 'crest'
    ? props.crestUrl
    : source.value === 'logo'
      ? props.logoUrl
      : null,
);

// Una imagen nueva (otra URL) merece un intento; el mismo enlace no se repite.
watch(
  () => [props.crestUrl, props.logoUrl],
  () => {
    imageFailed.value = false;
  },
);
</script>

<template>
  <img
    v-if="src"
    class="team-crest"
    :src="src"
    :alt="alt"
    loading="lazy"
    decoding="async"
    @error="imageFailed = true"
  >
  <span
    v-else
    class="team-crest team-crest--initials"
    role="img"
    :aria-label="alt"
  >{{ initials }}</span>
</template>

<style scoped>
.team-crest {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 50%;
  object-fit: contain;
  background: rgba(255, 255, 255, 0.06);
}

.team-crest--initials {
  border: 1px solid rgba(255, 255, 255, 0.18);
  color: #f5f7fb;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
</style>
