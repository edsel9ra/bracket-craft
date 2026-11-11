<script setup lang="ts">
defineProps<{ setupChecks: { label: string; detail: string; valid: boolean }[] }>();
const { t } = useI18n();
</script>

<template>
<div class="setup-checklist" :aria-label="t('setup.operationalChecklist')">
           <div class="checklist-heading"><div><p class="eyebrow">{{ t('setup.beforePublish') }}</p><h2>{{ t('setup.operationalChecklist') }}</h2></div><span class="muted-note">{{ t('setup.rosterNote') }}</span></div>
           <div class="checklist-items"><div v-for="check in setupChecks" :key="check.label" class="check-item" :class="{ valid: check.valid }"><span aria-hidden="true">{{ check.valid ? '✓' : '!' }}</span><strong>{{ check.label }}</strong><small>{{ check.detail }}</small></div></div>
         </div>
</template>

<style scoped>
.setup-checklist { display: grid; gap: var(--space-4); margin-bottom: var(--space-6); padding: var(--space-5); border: 1px solid color-mix(in srgb, var(--color-accent) 24%, transparent); border-radius: var(--radius-lg); background: color-mix(in srgb, var(--color-accent) 4%, transparent); }
.checklist-heading { display: flex; align-items: end; justify-content: space-between; gap: var(--space-5); }
.checklist-heading h2 { margin: 0; font-size: var(--text-lg); letter-spacing: -0.05em; }
.checklist-items { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: var(--space-2); }
.check-item { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: var(--space-1) var(--space-2); min-width: 0; padding: var(--space-3); border: 1px solid var(--color-line); border-radius: var(--radius-md); color: var(--color-muted); }
.check-item > span { display: grid; grid-row: span 2; width: 20px; height: 20px; place-items: center; border-radius: 50%; background: color-mix(in srgb, var(--color-danger) 10%, transparent); color: var(--color-danger); font-size: var(--text-xs); font-weight: 900; }
.check-item strong { overflow: hidden; color: var(--color-ink); font-size: var(--text-xs); text-overflow: ellipsis; white-space: nowrap; }
.check-item small { color: var(--color-muted); font-size: var(--text-2xs); }
.check-item.valid { border-color: color-mix(in srgb, var(--color-accent) 28%, transparent); }
.check-item.valid > span { background: color-mix(in srgb, var(--color-accent) 16%, transparent); color: var(--color-accent); }
@media (max-width: 1000px) { .checklist-items { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 480px) { .checklist-heading { align-items: stretch; flex-direction: column; } .checklist-items { grid-template-columns: 1fr; } }
</style>
