<script setup lang="ts">
import { safeEvidenceLink } from '~/utils/sanctions';
const props = defineProps<{ text?: string | null; links?: string[] }>();
const { t } = useI18n();
const safeLinks = computed(() => (props.links || []).map((raw) => ({ raw, href: safeEvidenceLink(raw) })));
</script>

<template>
  <div v-if="text || safeLinks.length" class="evidence">
    <h3>{{ t('sanction.evidence') }}</h3><p v-if="text">{{ text }}</p>
    <ul><li v-for="link in safeLinks" :key="link.raw"><a v-if="link.href" :href="link.href" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{{ link.raw }}</a><span v-else>{{ link.raw }}</span></li></ul>
  </div>
</template>

<style scoped>
.evidence { overflow-wrap: anywhere; white-space: pre-wrap; }
</style>
