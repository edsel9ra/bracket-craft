<script setup lang="ts">
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
  <LanguageSwitcher v-if="!isWorkspaceRoute" />
  <NuxtLoadingIndicator color="#d4f36a" :height="3" :throttle="160" />
  <NuxtPage :transition="{ name: 'page', mode: 'out-in' }" />
</template>
