<script setup lang="ts">
const props = withDefaults(defineProps<{ inline?: boolean }>(), { inline: false });
const id = useId();
const { t } = useI18n();
const { preference, setTheme } = useTheme();
const choices = ['dark', 'light', 'system'] as const;
</script>

<template>
  <div class="theme-switcher" :class="{ 'theme-switcher-inline': props.inline }">
    <label :for="id">{{ t('theme.label') }}</label>
    <select :id="id" :value="preference" :aria-label="t('theme.label')" @change="setTheme(($event.target as HTMLSelectElement).value)">
      <option v-for="choice in choices" :key="choice" :value="choice" :selected="preference === choice">{{ t(`theme.${choice}`) }}</option>
    </select>
  </div>
</template>

<style scoped>
.theme-switcher { display: flex; flex: 0 0 auto; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3); border: 1px solid var(--color-line); border-radius: var(--radius-pill); background: color-mix(in srgb, var(--color-surface) 94%, transparent); }
.theme-switcher-inline { padding: var(--space-1) var(--space-2); }
.theme-switcher label { color: var(--color-muted); font-size: var(--text-2xs); letter-spacing: 0.08em; text-transform: uppercase; }
.theme-switcher select { padding: var(--space-1); border: 0; background: transparent; color: var(--color-accent); font: inherit; font-size: var(--text-xs); font-weight: 800; cursor: pointer; }
.theme-switcher select:focus { outline: 2px solid var(--color-accent); outline-offset: 2px; box-shadow: none; }
</style>
