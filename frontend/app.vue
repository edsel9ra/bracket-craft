<script setup lang="ts">
const { t } = useI18n();
</script>

<template>
  <a class="skip-link" href="#main-content">{{ t('common.skip') }}</a>
  <LanguageSwitcher />
  <NuxtLoadingIndicator color="#d4f36a" :height="3" :throttle="160" />
  <NuxtPage :transition="{ name: 'page', mode: 'out-in' }" />
</template>
