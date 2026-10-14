<script setup lang="ts">
const props = withDefaults(defineProps<{ inline?: boolean }>(), { inline: false });

const { locale, t, setLocale } = useI18n();

useHead(() => ({
  htmlAttrs: { lang: locale.value },
}));
</script>

<template>
  <div class="language-switcher" :class="{ 'language-switcher-inline': props.inline }">
    <label for="language-select">{{ t('language.label') }}</label>
    <select id="language-select" :value="locale" :aria-label="t('language.label')" @change="setLocale(($event.target as HTMLSelectElement).value as 'es' | 'en')">
      <option value="es">{{ t('language.es') }}</option>
      <option value="en">{{ t('language.en') }}</option>
    </select>
  </div>
</template>

<style scoped>
.language-switcher { position: fixed; right: 20px; bottom: 20px; z-index: 30; display: flex; align-items: center; gap: 8px; padding: 7px 9px 7px 11px; border: 1px solid var(--line); border-radius: 999px; background: rgba(21, 24, 20, 0.94); box-shadow: 0 12px 30px rgba(0, 0, 0, 0.25); backdrop-filter: blur(14px); }
.language-switcher-inline { position: static; right: auto; bottom: auto; z-index: auto; padding: 5px 7px 5px 9px; box-shadow: none; backdrop-filter: none; }
.language-switcher label { color: var(--muted); font-size: 0.68rem; letter-spacing: 0.08em; text-transform: uppercase; }
.language-switcher select { padding: 0.28rem 0.35rem; border: 0; background: transparent; color: var(--accent); font: inherit; font-size: 0.74rem; font-weight: 800; cursor: pointer; }
.language-switcher select:focus { outline: 2px solid var(--accent); outline-offset: 2px; box-shadow: none; }
@media (max-width: 520px) { .language-switcher { right: 12px; bottom: 12px; } .language-switcher label { display: none; } }
</style>
