<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import FormField from '~/components/ui/FormField.vue';
import Surface from '~/components/ui/Surface.vue';
import { proposalSubmission, type SanctionReceipt } from '~/utils/sanctions';
const props = defineProps<{ allowed: boolean; priorCaseId?: string }>();
const emit = defineEmits<{ created: [receipt: SanctionReceipt] }>();
const { t } = useI18n(); const prefix = useId(); const api = useSanctionCases();
const { busy, error, run } = useSanctionAction();
const errorTarget = useSanctionErrorFocus(error);
const source = ref(''); const action = ref<'annul' | 'reduce'>('annul'); const duration = ref<string | number>('');
const reason = ref(''); const evidence = ref(''); const links = ref(''); const prior = ref(props.priorCaseId || '');
const receipt = ref<SanctionReceipt | null>(null);
async function submit() {
  if (busy.value || !props.allowed) return;
  const payload = proposalSubmission({ sanctionId: source.value, action: action.value, duration: duration.value, reason: reason.value, evidence: evidence.value, links: links.value, priorCaseId: prior.value });
  if (!payload) { error.value = 'sanction.error.validation'; return; }
  const result = await run({ title: t('sanction.propose'), message: t('sanction.proposalHint'), confirmLabel: t('sanction.propose') }, () => props.allowed ? api.propose(payload.id, payload.body) : Promise.resolve(undefined));
  if (result) { receipt.value = result; reason.value = ''; evidence.value = ''; links.value = ''; emit('created', result); }
}
</script>

<template>
  <Surface v-if="allowed" as="section"><h2>{{ t('sanction.propose') }}</h2><p>{{ t('sanction.proposalHint') }}</p>
    <p v-if="receipt" role="status">{{ t('sanction.receipt') }}: {{ receipt.id }}</p><p v-if="error" ref="errorTarget" tabindex="-1" role="alert">{{ t(error) }}</p>
    <form @submit.prevent="submit"><fieldset :disabled="busy">
      <FormField :for-id="`${prefix}-source`" :label="t('sanction.sanctionId')"><input :id="`${prefix}-source`" v-model="source" required></FormField>
      <FormField :for-id="`${prefix}-action`" :label="t('sanction.proposedAction')"><select :id="`${prefix}-action`" v-model="action"><option value="annul">{{ t('sanction.decision.annul') }}</option><option value="reduce">{{ t('sanction.decision.reduce') }}</option></select></FormField>
      <FormField v-if="action === 'reduce'" :for-id="`${prefix}-duration`" :label="t('sanction.newDuration')"><input :id="`${prefix}-duration`" v-model="duration" type="number" min="0" step="1" required></FormField>
      <FormField :for-id="`${prefix}-reason`" :label="t('sanction.reason')"><textarea :id="`${prefix}-reason`" v-model="reason" required /></FormField>
      <FormField :for-id="`${prefix}-evidence`" :label="t('sanction.evidenceOptional')"><textarea :id="`${prefix}-evidence`" v-model="evidence" /></FormField>
      <FormField :for-id="`${prefix}-links`" :label="t('sanction.links')" :hint="t('sanction.linksHint')" v-slot="{ ariaDescribedby }"><textarea :id="`${prefix}-links`" v-model="links" :aria-describedby="ariaDescribedby" /></FormField>
      <FormField :for-id="`${prefix}-prior`" :label="t('sanction.priorOptional')"><input :id="`${prefix}-prior`" v-model="prior"></FormField>
      <Button type="submit" :busy="busy">{{ t('sanction.propose') }}</Button>
    </fieldset></form>
  </Surface>
</template>

<style scoped>
fieldset { border: 0; padding: 0; margin: 0; display: grid; gap: var(--space-4); }
</style>
