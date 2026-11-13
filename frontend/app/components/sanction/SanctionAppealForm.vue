<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import FormField from '~/components/ui/FormField.vue';
import Surface from '~/components/ui/Surface.vue';
import { appealSubmission, type SanctionReceipt } from '~/utils/sanctions';
const props = defineProps<{ allowed: boolean; sanctionId?: string; playerId?: string; priorCaseId?: string }>();
const emit = defineEmits<{ created: [receipt: SanctionReceipt] }>();
const { t } = useI18n();
const api = useSanctionCases();
const { busy, error, run } = useSanctionAction();
const prefix = useId();
const source = ref(props.sanctionId || ''); const represented = ref(props.playerId || '');
const representation = ref<'player' | 'team'>('player');
const reason = ref(''); const evidence = ref(''); const links = ref(''); const prior = ref(props.priorCaseId || '');
const receipt = ref<SanctionReceipt | null>(null);
watch(representation, () => { represented.value = ''; });
async function submit() {
  if (busy.value || !props.allowed) return;
  const payload = appealSubmission({ sanctionId: source.value, representation: representation.value, representedId: represented.value, reason: reason.value, evidence: evidence.value, links: links.value, priorCaseId: prior.value });
  if (!payload) { error.value = 'sanction.error.validation'; return; }
  const result = await run({ title: t('sanction.appeal'), message: t('sanction.separation'), confirmLabel: t('sanction.appeal') }, () => props.allowed ? api.appeal(payload.id, payload.body) : Promise.resolve(undefined));
  if (result) { receipt.value = result; reason.value = ''; evidence.value = ''; links.value = ''; emit('created', result); }
}
</script>

<template>
  <Surface v-if="allowed" as="section">
    <h2>{{ t('sanction.appeal') }}</h2><p>{{ t('sanction.noExpiry') }}</p><p>{{ t('sanction.representationHint') }}</p>
    <p v-if="receipt" role="status">{{ t('sanction.receipt') }}: {{ receipt.id }} · {{ t(`sanction.status.${receipt.status}`) }}</p>
    <p v-if="error" role="alert">{{ t(error) }}</p>
    <form @submit.prevent="submit"><fieldset :disabled="busy">
      <FormField :for-id="`${prefix}-source`" :label="t('sanction.sanctionId')"><input :id="`${prefix}-source`" v-model="source" required></FormField>
      <FormField :for-id="`${prefix}-representation`" :label="t('sanction.representation')"><select :id="`${prefix}-representation`" v-model="representation"><option value="player">{{ t('sanction.player') }}</option><option value="team">{{ t('sanction.team') }}</option></select></FormField>
      <FormField :for-id="`${prefix}-represented`" :label="t('sanction.representedId')"><input :id="`${prefix}-represented`" v-model="represented" required></FormField>
      <FormField :for-id="`${prefix}-reason`" :label="t('sanction.reason')"><textarea :id="`${prefix}-reason`" v-model="reason" required /></FormField>
      <FormField :for-id="`${prefix}-evidence`" :label="t('sanction.evidenceOptional')"><textarea :id="`${prefix}-evidence`" v-model="evidence" /></FormField>
      <FormField :for-id="`${prefix}-links`" :label="t('sanction.links')" :hint="t('sanction.linksHint')" v-slot="{ ariaDescribedby }"><textarea :id="`${prefix}-links`" v-model="links" :aria-describedby="ariaDescribedby" /></FormField>
      <FormField :for-id="`${prefix}-prior`" :label="t('sanction.priorOptional')"><input :id="`${prefix}-prior`" v-model="prior"></FormField>
      <Button type="submit" :busy="busy">{{ t('sanction.appeal') }}</Button>
    </fieldset></form>
  </Surface>
</template>

<style scoped>
fieldset { border: 0; padding: 0; margin: 0; display: grid; gap: var(--space-4); }
</style>
