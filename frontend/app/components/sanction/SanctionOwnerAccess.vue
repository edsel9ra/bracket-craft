<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import FormField from '~/components/ui/FormField.vue';
import Surface from '~/components/ui/Surface.vue';
import SanctionAuthorizations from './SanctionAuthorizations.vue';
import { normalizeUuid } from '~/utils/validation';
defineProps<{ owner: boolean }>();
const { t } = useI18n(); const prefix = useId(); const input = ref(''); const selected = ref(''); const error = ref(false);
function select() { const value = normalizeUuid(input.value); error.value = !value; selected.value = value || ''; }
</script>

<template>
  <Surface v-if="owner" as="section"><h2>{{ t('sanction.authorizations') }}</h2><p>{{ t('sanction.ownerHint') }}</p>
    <form @submit.prevent="select"><FormField :for-id="`${prefix}-case`" :label="t('sanction.caseId')" :error="error ? t('sanction.error.validation') : ''" v-slot="{ ariaDescribedby }"><input :id="`${prefix}-case`" v-model="input" :aria-describedby="ariaDescribedby" :aria-invalid="error" required></FormField><Button type="submit">{{ t('sanction.loadAuthorizations') }}</Button></form>
    <SanctionAuthorizations v-if="selected" :key="selected" :owner="owner" :case-id="selected" />
  </Surface>
</template>
