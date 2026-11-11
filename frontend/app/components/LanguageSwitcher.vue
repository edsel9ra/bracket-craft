<script setup lang="ts">
const props = withDefaults(defineProps<{ inline?: boolean; id?: string }>(), { inline: false, id: 'language-select' });

const { locale, t, setLocale } = useI18n();

useHead(() => ({
  htmlAttrs: { lang: locale.value },
}));
</script>

<template>
  <div class="language-switcher" :class="{ 'language-switcher-inline': props.inline }">
    <label :for="props.id">{{ t('language.label') }}</label>
    <select :id="props.id" :value="locale" :aria-label="t('language.label')" @change="setLocale(($event.target as HTMLSelectElement).value as 'es' | 'en')">
      <option value="es">{{ t('language.es') }}</option>
      <option value="en">{{ t('language.en') }}</option>
    </select>
  </div>
</template>

<style scoped>
.language-switcher { position: fixed; right: 20px; bottom: 20px; z-index: 30; display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3); border: 1px solid var(--color-line); border-radius: var(--radius-pill); background: color-mix(in srgb, var(--color-surface) 94%, transparent); box-shadow: 0 12px 30px color-mix(in srgb, var(--color-shadow) 25%, transparent); backdrop-filter: blur(14px); }
.language-switcher-inline { position: static; right: auto; bottom: auto; z-index: auto; padding: var(--space-1) var(--space-2) var(--space-1) var(--space-2); box-shadow: none; backdrop-filter: none; }
.language-switcher label { color: var(--color-muted); font-size: var(--text-2xs); letter-spacing: 0.08em; text-transform: uppercase; }
.language-switcher select { padding: var(--space-1) var(--space-1); border: 0; background: transparent; color: var(--color-accent); font: inherit; font-size: var(--text-xs); font-weight: 800; cursor: pointer; }
.language-switcher select:focus { outline: 2px solid var(--color-accent); outline-offset: 2px; box-shadow: none; }
@media (max-width: 480px) { .language-switcher { right: 12px; bottom: 12px; } .language-switcher label { display: none; } }
</style>
