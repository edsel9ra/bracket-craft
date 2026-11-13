<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import FormField from '~/components/ui/FormField.vue';
import { canDecideSanction, decisionSubmission, isSanctionConflictKey, sanctionErrorKey, type SanctionCase, type SanctionDecision, type SanctionPreview } from '~/utils/sanctions';
const props = defineProps<{ case: Pick<SanctionCase, 'id' | 'status' | 'submitted_by_user_id'>; userId: string | null; canResolve: boolean }>();
const emit = defineEmits<{ changed: [notice?: string] }>();
const { t } = useI18n(); const prefix = useId(); const api = useSanctionCases();
const { busy, error, run } = useSanctionAction();
const allowed = computed(() => canDecideSanction(props.case.submitted_by_user_id, props.userId, props.canResolve, props.case.status));
const preview = ref<SanctionPreview | null>(null); const previewBusy = ref(false);
const decision = ref<SanctionDecision>('maintain'); const duration = ref(''); const reason = ref(''); const evidence = ref(''); const links = ref('');
const prejudice = ref<{ match_id: string; reason: string }[]>([]);
let generation = 0;
watch(() => props.case, () => { generation++; preview.value = null; }, { flush: 'sync' });
onBeforeUnmount(() => { generation++; });
async function loadPreview() {
  if (!allowed.value || previewBusy.value || busy.value) return;
  const token = ++generation; preview.value = null; previewBusy.value = true; error.value = '';
  try {
    const value = await api.preview(props.case.id);
    if (token === generation) { preview.value = value; decision.value = value.allowed_decisions[0] || 'maintain'; }
  } catch (cause) { if (token === generation) error.value = sanctionErrorKey(cause); }
  finally { if (token === generation) previewBusy.value = false; }
}
async function submit() {
  if (!allowed.value || !preview.value || busy.value) return;
  const body = decisionSubmission(preview.value, { decision: decision.value, duration: duration.value, reason: reason.value, evidence: evidence.value, links: links.value, prejudice: prejudice.value });
  if (!body) { error.value = 'sanction.error.validation'; return; }
  const id = props.case.id;
  const result = await run({ title: t('sanction.decide'), message: t('sanction.decisionHint'), confirmLabel: t('sanction.decide'), tone: 'danger' }, () => allowed.value ? api.decide(id, body) : Promise.resolve(undefined));
  if (result) emit('changed', 'sanction.stateUpdated');
  else if (isSanctionConflictKey(error.value)) { preview.value = null; emit('changed', error.value); }
}
</script>

<template>
  <section v-if="allowed">
    <h3>{{ t('sanction.decide') }}</h3><p>{{ t('sanction.decisionHint') }}</p>
    <p v-if="error" role="alert">{{ t(error) }}</p>
    <Button variant="secondary" :busy="previewBusy" :disabled="busy" @click="loadPreview">{{ t('sanction.preview') }}</Button>
    <form v-if="preview && preview.can_decide" @submit.prevent="submit"><fieldset :disabled="busy || previewBusy">
      <p role="status">{{ t('sanction.baseDuration') }}: {{ preview.expected_base_duration }} · {{ t('sanction.effective') }}: {{ preview.projection.effective_duration }} · {{ t('sanction.served') }}: {{ preview.projection.served_count }}</p>
      <FormField :for-id="`${prefix}-decision`" :label="t('sanction.decide')"><select :id="`${prefix}-decision`" v-model="decision"><option v-for="value in preview.allowed_decisions" :key="value" :value="value">{{ t(`sanction.decision.${value}`) }}</option></select></FormField>
      <FormField v-if="decision === 'reduce'" :for-id="`${prefix}-duration`" :label="t('sanction.newDuration')"><input :id="`${prefix}-duration`" v-model="duration" type="number" min="0" :max="preview.expected_base_duration - 1" step="1" required></FormField>
      <FormField :for-id="`${prefix}-reason`" :label="t('sanction.reason')"><textarea :id="`${prefix}-reason`" v-model="reason" required /></FormField>
      <FormField :for-id="`${prefix}-evidence`" :label="t('sanction.evidenceOptional')"><textarea :id="`${prefix}-evidence`" v-model="evidence" /></FormField>
      <FormField :for-id="`${prefix}-links`" :label="t('sanction.links')"><textarea :id="`${prefix}-links`" v-model="links" /></FormField>
      <fieldset v-for="(record, index) in prejudice" :key="index"><legend>{{ t('sanction.prejudice') }} {{ index + 1 }}</legend><FormField :for-id="`${prefix}-match-${index}`" :label="t('sanction.matchId')"><input :id="`${prefix}-match-${index}`" v-model="record.match_id" required></FormField><FormField :for-id="`${prefix}-prejudice-${index}`" :label="t('sanction.reason')"><textarea :id="`${prefix}-prejudice-${index}`" v-model="record.reason" required /></FormField><Button variant="ghost" @click="prejudice.splice(index, 1)">{{ t('sanction.removeRecord') }}</Button></fieldset>
      <Button variant="secondary" :disabled="prejudice.length >= 100" @click="prejudice.push({ match_id: '', reason: '' })">{{ t('sanction.addPrejudice') }}</Button>
      <Button type="submit" :busy="busy">{{ t('sanction.decide') }}</Button>
    </fieldset></form>
  </section>
</template>

<style scoped>
fieldset { border: 0; padding: 0; margin: 0; display: grid; gap: var(--space-4); }
</style>
