<template>
  <p v-if="message" class="field-error" role="alert" :id="id">{{ message }}</p>
</template>

<script setup lang="ts">
defineProps<{
  message?: string | null;
  id?: string;
}>();
</script>