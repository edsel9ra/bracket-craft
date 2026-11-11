<script setup lang="ts">
/**
 * Advertencia declarativa de formato (spec 012, RF-043).
 *
 * La planilla soportada es de once. Cuando el formato declarado no es `11v11`
 * se avisa en el paso de reglas, en el resumen de configuración y en la
 * operación/planilla, siempre con un texto traducido. La advertencia es
 * puramente informativa: no deshabilita controles ni bloquea ninguna acción.
 */
import { formatWarns } from '~/utils/rulesWizard';

const props = withDefaults(defineProps<{
  format?: string | null;
  /** Clave i18n del aviso de la superficie que lo muestra. */
  messageKey?: string;
}>(), {
  format: null,
  messageKey: 'format.notice.rules',
});

const { t } = useI18n();
const visible = computed(() => formatWarns(props.format));
</script>

<template>
  <p v-if="visible" class="format-warning" role="status">
    {{ t(messageKey) }}
  </p>
</template>

<style scoped>
.format-warning {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid color-mix(in srgb, var(--color-warning) 35%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-warning) 8%, transparent);
  color: var(--color-warning);
  font-size: var(--text-xs);
  line-height: 1.45;
}
</style>
