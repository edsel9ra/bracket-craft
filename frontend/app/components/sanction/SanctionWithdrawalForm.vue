<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import FormField from '~/components/ui/FormField.vue';
import { canWithdrawSanction, evidencePayload, isSanctionConflictKey, type SanctionCase } from '~/utils/sanctions';
const props = defineProps<{ case: Pick<SanctionCase, 'id' | 'status' | 'case_type' | 'submitted_by_user_id'>; userId: string | null; submitPermission: boolean; resolvePermission: boolean }>();
const emit = defineEmits<{ changed: [notice?: string] }>();
const { t } = useI18n(); const prefix = useId(); const api = useSanctionCases();
const { busy, error, run } = useSanctionAction();
const allowed = computed(() => canWithdrawSanction(props.case, props.userId, props.submitPermission, props.resolvePermission));
const reason = ref(''); const evidence = ref(''); const links = ref('');
async function submit() {
  if (!allowed.value || busy.value) return;
  const body = evidencePayload(reason.value, evidence.value, links.value);
  if (!body) { error.value = 'sanction.error.validation'; return; }
  const id = props.case.id;
  const result = await run({ title: t('sanction.withdraw'), message: t('sanction.withdrawHint'), confirmLabel: t('sanction.withdraw'), tone: 'danger' }, () => allowed.value ? api.withdraw(id, body) : Promise.resolve(undefined));
  if (result) emit('changed', 'sanction.stateUpdated');
  else if (isSanctionConflictKey(error.value)) emit('changed', error.value);
}
</script>

<template>
  <section v-if="allowed"><h3>{{ t('sanction.withdraw') }}</h3><p>{{ t('sanction.withdrawHint') }}</p><p v-if="error" role="alert">{{ t(error) }}</p>
    <form @submit.prevent="submit"><fieldset :disabled="busy">
      <FormField :for-id="`${prefix}-reason`" :label="t('sanction.reason')"><textarea :id="`${prefix}-reason`" v-model="reason" required /></FormField>
      <FormField :for-id="`${prefix}-evidence`" :label="t('sanction.evidenceOptional')"><textarea :id="`${prefix}-evidence`" v-model="evidence" /></FormField>
      <FormField :for-id="`${prefix}-links`" :label="t('sanction.links')"><textarea :id="`${prefix}-links`" v-model="links" /></FormField>
      <Button type="submit" variant="danger" :busy="busy">{{ t('sanction.withdraw') }}</Button>
    </fieldset></form>
  </section>
</template>

<style scoped>
fieldset { border: 0; padding: 0; margin: 0; display: grid; gap: var(--space-4); }
</style>
