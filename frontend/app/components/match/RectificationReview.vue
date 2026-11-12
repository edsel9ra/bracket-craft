<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import FormField from '~/components/ui/FormField.vue';
import Surface from '~/components/ui/Surface.vue';
import RectificationReport from './RectificationReport.vue';
import RectificationDiff from './RectificationDiff.vue';
import { canDecide, compareReports, rectificationErrorKey, type RectificationDetail, type Preview, type ReportVersion, type PlatformAuthorization } from '~/utils/rectifications';

const props = defineProps<{ detail: RectificationDetail; memberId: string | null; canApprove: boolean; owner: boolean }>();
const emit = defineEmits<{ changed: [] }>();
const api = useMatchRectifications();
const { t, formatDateTime } = useI18n();
const { confirm } = useConfirm({ singleFlight: true });
const prefix = useId();
const reason = ref(''); const email = ref(''); const authorizationReason = ref('');
const busy = ref(false); const error = ref('');
const preview = ref<Preview | null>(null);
const current = ref<ReportVersion | null>(null);
const authorizations = ref<PlatformAuthorization[]>([]);
const decisionAllowed = computed(() => canDecide(props.detail.requested_by_member_id, props.memberId, props.canApprove, props.detail.status));
const comparison = computed(() => {
  const orderChanges = current.value ? compareReports(current.value.report, props.detail.proposed_report as unknown as Record<string, unknown>).fields.filter((field) => field.field === 'event_order') : [];
  return { ...props.detail.diff, fields: [...props.detail.diff.fields, ...orderChanges] };
});
let generation = 0;
async function load() {
  const token = ++generation;
  preview.value = null; current.value = null; authorizations.value = []; error.value = ''; reason.value = '';
  try {
    const [versions, grants] = await Promise.all([api.versions(props.detail.match_id), props.owner ? api.authorizations(props.detail.id) : Promise.resolve([])]);
    if (token !== generation) return;
    current.value = versions.sort((a, b) => a.version_number - b.version_number).at(-1) || null;
    authorizations.value = grants;
  } catch (cause) { if (token === generation) error.value = t(rectificationErrorKey(cause)); }
}
async function showPreview() {
  if (busy.value || !decisionAllowed.value) return;
  busy.value = true; error.value = ''; preview.value = null;
  const requestId = props.detail.id;
  try { const result = await api.preview(requestId); if (props.detail.id === requestId) preview.value = result; }
  catch (cause) { error.value = t(rectificationErrorKey(cause)); }
  finally { busy.value = false; }
}
async function decide(decision: 'approve' | 'reject') {
  if (busy.value || !decisionAllowed.value || !reason.value.trim() || (decision === 'approve' && !preview.value)) return;
  busy.value = true; error.value = '';
  const requestId = props.detail.id;
  try {
    if (!await confirm({ title: t(decision === 'approve' ? 'rectification.approve' : 'rectification.reject'),
      message: t(decision === 'approve' ? 'rectification.approveWarning' : 'rectification.rejectWarning'),
      confirmLabel: t(decision === 'approve' ? 'rectification.approve' : 'rectification.reject'), tone: decision === 'reject' ? 'danger' : 'primary' })) return;
    if (props.detail.id !== requestId) return;
    await api.decide(requestId, { decision, reason: reason.value.trim(), expected_base_version: preview.value?.expected_base_version ?? props.detail.base_version_number });
    preview.value = null; emit('changed');
  } catch (cause) { preview.value = null; error.value = t(rectificationErrorKey(cause)); }
  finally { busy.value = false; }
}
async function withdraw() {
  if (busy.value || props.memberId !== props.detail.requested_by_member_id || props.detail.status !== 'pending') return;
  busy.value = true; error.value = '';
  try {
    if (!await confirm({ title: t('rectification.withdraw'), message: t('rectification.withdrawWarning'), confirmLabel: t('rectification.withdraw'), tone: 'danger' })) return;
    await api.withdraw(props.detail.id); emit('changed');
  } catch (cause) { error.value = t(rectificationErrorKey(cause)); }
  finally { busy.value = false; }
}
async function grant() {
  if (busy.value || !props.owner || !email.value.trim() || !authorizationReason.value.trim()) return;
  busy.value = true; error.value = '';
  try {
    if (!await confirm({ title: t('rectification.grant'), message: t('rectification.grantWarning'), confirmLabel: t('rectification.grant') })) return;
    await api.grant(props.detail.id, { platform_admin_email: email.value.trim(), reason: authorizationReason.value.trim() });
    email.value = ''; authorizationReason.value = ''; await load();
  } catch (cause) { error.value = t(rectificationErrorKey(cause)); }
  finally { busy.value = false; }
}
async function revoke(id: string) {
  if (busy.value || !props.owner) return;
  busy.value = true; error.value = '';
  try {
    if (!await confirm({ title: t('rectification.revoke'), message: t('rectification.revokeWarning'), confirmLabel: t('rectification.revoke'), tone: 'danger' })) return;
    await api.revoke(props.detail.id, id); await load();
  } catch (cause) { error.value = t(rectificationErrorKey(cause)); }
  finally { busy.value = false; }
}
onMounted(load);
watch(() => [props.detail.id, props.detail.status, props.owner], load);
onBeforeUnmount(() => { generation++; });
</script>

<template>
  <Surface as="section">
    <h2>{{ t('rectification.review') }}</h2>
    <p>{{ t('rectification.requester') }}: {{ detail.requested_by_user_id }} · {{ formatDateTime(detail.requested_at) }}</p>
    <p>{{ t('rectification.reason') }}: {{ detail.reason }}</p><p>{{ t('rectification.evidence') }}: {{ detail.evidence }}</p>
    <p>{{ t(`rectification.status.${detail.status}`) }}</p>
    <p v-if="error" role="alert">{{ error }} <Button variant="secondary" :disabled="busy" @click="load">{{ t('common.retry') }}</Button></p>
    <details v-if="current"><summary>{{ t('rectification.current') }} · {{ current.version_number }}</summary><RectificationReport :report="current.report" /></details>
    <details><summary>{{ t('rectification.proposal') }}</summary><RectificationReport :report="detail.proposed_report as unknown as Record<string, unknown>" /></details>
    <RectificationDiff :diff="comparison" />
    <template v-if="decisionAllowed">
      <Button variant="secondary" :busy="busy" @click="showPreview">{{ t('rectification.preview') }}</Button>
      <section v-if="preview" :aria-label="t('rectification.effects')">
        <h3>{{ t('rectification.effects') }} · {{ t('rectification.version') }} {{ preview.expected_base_version }}</h3>
        <p>{{ t('rectification.previewHint') }}</p><p v-if="!preview.effects.length">{{ t('rectification.noEffects') }}</p>
        <details v-for="(effect, index) in preview.effects" :key="index"><summary>{{ t(`rectification.effect.${effect.effect_type || effect.type}`) }}</summary><pre>{{ JSON.stringify(effect, null, 2) }}</pre></details>
      </section>
      <FormField :for-id="`${prefix}-decision`" :label="t('rectification.decisionReason')"><textarea :id="`${prefix}-decision`" v-model="reason" required /></FormField>
      <div class="actions"><Button :disabled="!preview || !reason.trim()" :busy="busy" @click="decide('approve')">{{ t('rectification.approve') }}</Button><Button variant="danger" :disabled="!reason.trim()" :busy="busy" @click="decide('reject')">{{ t('rectification.reject') }}</Button></div>
    </template>
    <Button v-if="detail.status === 'pending' && memberId === detail.requested_by_member_id" variant="danger" :busy="busy" @click="withdraw">{{ t('rectification.withdraw') }}</Button>
    <section v-if="owner">
      <h3>{{ t('rectification.authorizations') }}</h3>
      <p v-if="!authorizations.length">{{ t('rectification.noAuthorizations') }}</p>
      <ul><li v-for="authorization in authorizations" :key="authorization.id">{{ authorization.platform_admin_user_id }} · {{ authorization.reason }} · {{ t(authorization.consumed_at ? 'rectification.consumed' : authorization.revoked_at ? 'rectification.revoked' : 'rectification.authorized') }} <Button v-if="!authorization.revoked_at && !authorization.consumed_at && detail.status === 'pending'" variant="danger" :busy="busy" @click="revoke(authorization.id)">{{ t('rectification.revoke') }}</Button></li></ul>
      <form v-if="detail.status === 'pending'" @submit.prevent="grant">
        <FormField :for-id="`${prefix}-email`" :label="t('rectification.platformEmail')"><input :id="`${prefix}-email`" v-model="email" type="email" required></FormField>
        <FormField :for-id="`${prefix}-grant`" :label="t('rectification.reason')"><textarea :id="`${prefix}-grant`" v-model="authorizationReason" required /></FormField>
        <Button type="submit" :busy="busy">{{ t('rectification.grant') }}</Button>
      </form>
    </section>
  </Surface>
</template>

<style scoped>
.actions { display: flex; flex-wrap: wrap; gap: var(--space-3); margin-block: var(--space-4); }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: var(--text-sm); }
li { overflow-wrap: anywhere; margin-block: var(--space-3); }
</style>
