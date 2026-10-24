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
  padding: 10px 12px;
  border: 1px solid rgba(255, 203, 122, 0.35);
  border-radius: 9px;
  background: rgba(255, 203, 122, 0.08);
  color: #ffcb7a;
  font-size: 0.78rem;
  line-height: 1.45;
}
</style>
