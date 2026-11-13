<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import FormField from '~/components/ui/FormField.vue';
import { authorizationState, sanctionErrorKey, type SanctionAuthorization } from '~/utils/sanctions';
const props = withDefaults(defineProps<{ owner: boolean; caseId: string; pending?: boolean }>(), { pending: true });
const { t, formatDateTime } = useI18n(); const prefix = useId(); const api = useSanctionCases();
const { busy, error, run } = useSanctionAction();
const rows = ref<SanctionAuthorization[]>([]); const loading = ref(false); const email = ref(''); const reason = ref('');
let generation = 0;
async function load() {
  const token = ++generation; rows.value = []; error.value = ''; loading.value = false;
  if (!props.owner) return;
  loading.value = true;
  try { const value = await api.authorizations(props.caseId); if (token === generation) rows.value = value; }
  catch (cause) { if (token === generation) error.value = sanctionErrorKey(cause); }
  finally { if (token === generation) loading.value = false; }
}
watch(() => [props.caseId, props.owner], load, { flush: 'sync' });
onMounted(load); onBeforeUnmount(() => { generation++; });
async function grant() {
  if (!props.owner || !props.pending || busy.value) return;
  if (!reason.value.trim() || !email.value.trim()) { error.value = 'sanction.error.validation'; return; }
  const id = props.caseId; const body = { platform_admin_email: email.value.trim(), reason: reason.value.trim() };
  const result = await run({ title: t('sanction.grant'), message: t('sanction.authorizationHint'), confirmLabel: t('sanction.grant') }, () => props.owner ? api.grant(id, body) : Promise.resolve(undefined));
  if (result) { reason.value = ''; email.value = ''; await load(); }
}
async function revoke(scope: SanctionAuthorization) {
  if (!props.owner || !props.pending || scope.revoked_at || scope.consumed_at || busy.value) return;
  const id = props.caseId;
  const result = await run({ title: t('sanction.revoke'), message: t('sanction.authorizationHint'), confirmLabel: t('sanction.revoke'), tone: 'danger' }, () => props.owner ? api.revoke(id, scope.id) : Promise.resolve(undefined));
  if (result) await load();
}
</script>

<template>
  <section v-if="owner"><h3>{{ t('sanction.authorizations') }}</h3><p>{{ t('sanction.authorizationHint') }}</p>
    <p v-if="loading" role="status">{{ t('common.loading') }}</p><p v-if="error" role="alert">{{ t(error) }} <Button variant="secondary" :disabled="busy || loading" @click="load">{{ t('common.retry') }}</Button></p>
    <p v-if="!loading && !error && !rows.length">{{ t('sanction.noAuthorizations') }}</p>
    <ul><li v-for="scope in rows" :key="scope.id">{{ scope.platform_admin_user_id }} · {{ scope.reason }} · {{ formatDateTime(scope.granted_at) }} · {{ t(authorizationState(scope)) }} <Button v-if="pending && !scope.revoked_at && !scope.consumed_at" variant="danger" :busy="busy" @click="revoke(scope)">{{ t('sanction.revoke') }}</Button></li></ul>
    <form v-if="pending" @submit.prevent="grant"><fieldset :disabled="busy || loading">
      <FormField :for-id="`${prefix}-email`" :label="t('sanction.platformEmail')"><input :id="`${prefix}-email`" v-model="email" type="email" required></FormField>
      <FormField :for-id="`${prefix}-reason`" :label="t('sanction.reason')"><textarea :id="`${prefix}-reason`" v-model="reason" required /></FormField>
      <Button type="submit" :busy="busy">{{ t('sanction.grant') }}</Button>
    </fieldset></form>
  </section>
</template>

<style scoped>
fieldset { border: 0; padding: 0; margin: 0; display: grid; gap: var(--space-4); }
li { overflow-wrap: anywhere; margin-block: var(--space-3); }
</style>
