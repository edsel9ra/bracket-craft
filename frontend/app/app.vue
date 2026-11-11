<script setup lang="ts">
import ConfirmDialog from '~/components/ui/ConfirmDialog.vue';
import PublicPreferences from '~/components/PublicPreferences.vue';
import { describeTheme } from '~/utils/theme';
const { preference } = useTheme();
useHead(() => describeTheme(preference.value));
const { t } = useI18n();
const route = useRoute();
const isWorkspaceRoute = computed(() => (
  route.path === '/admin'
  || route.path.startsWith('/admin/')
  || route.path === '/workspace'
  || route.path.startsWith('/workspace/')
));
</script>

<template>
  <a class="skip-link" href="#main-content">{{ t('common.skip') }}</a>
  <nav v-if="!isWorkspaceRoute" :aria-label="t('common.preferencesNavigation')">
    <PublicPreferences />
  </nav>
  <NuxtLoadingIndicator color="var(--color-accent)" :height="3" :throttle="160" />
  <NuxtPage :transition="{ name: 'page', mode: 'out-in' }" />
  <ConfirmDialog />
</template>
