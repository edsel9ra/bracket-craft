<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import RectificationReport from './RectificationReport.vue';
import RectificationEditor from './RectificationEditor.vue';
import RectificationDiff from './RectificationDiff.vue';
import { compareReports, rectificationErrorKey, type ReportVersion } from '~/utils/rectifications';
import { isForbidden, isNotFound, isUnauthorized } from '~/utils/api';

const props = defineProps<{ matchId: string; canRequest?: boolean; refreshKey?: object }>();
const api = useMatchRectifications();
const { t, formatDateTime } = useI18n();
const versions = ref<ReportVersion[]>([]);
const selected = ref(1);
const editing = ref(false);
const loading = ref(false);
const error = ref('');
let generation = 0;
let pendingReload = false;
const current = computed(() => versions.value.at(-1));
const visible = computed(() => versions.value.find((row) => row.version_number === selected.value));
const comparison = computed(() => current.value && visible.value && current.value !== visible.value ? compareReports(visible.value.report, current.value.report) : null);
async function load() {
  const token = ++generation;
  pendingReload = false;
  loading.value = true; error.value = ''; editing.value = false;
  try {
    const result = await api.versions(props.matchId);
    if (token !== generation) return;
    versions.value = result.sort((a, b) => a.version_number - b.version_number);
    selected.value = current.value?.version_number || 1;
  } catch (cause) {
    if (token === generation) {
      if (isUnauthorized(cause) || isForbidden(cause) || isNotFound(cause)) versions.value = [];
      error.value = t(rectificationErrorKey(cause));
    }
  }
  finally { if (token === generation) loading.value = false; }
}
onMounted(load);
watch(() => props.matchId, () => { versions.value = []; void load(); }, { flush: 'sync' });
watch(() => props.refreshKey, () => {
  generation++;
  if (editing.value) {
    pendingReload = true;
    loading.value = false;
  } else void load();
}, { flush: 'sync' });
watch(editing, (active) => {
  if (active && loading.value) {
    generation++;
    loading.value = false;
    pendingReload = true;
  } else if (!active && pendingReload) void load();
}, { flush: 'sync' });
onBeforeUnmount(() => { generation++; pendingReload = false; });
</script>

<template>
  <Surface as="section">
    <h2>{{ t('rectification.versions') }}</h2>
    <Button variant="secondary" :busy="loading" @click="load">{{ t('common.refresh') }}</Button>
    <p v-if="loading" role="status">{{ t('common.loading') }}</p>
    <p v-else-if="error" role="alert">{{ error }} <Button variant="secondary" @click="load">{{ t('common.retry') }}</Button></p>
    <p v-else-if="!versions.length" role="status">{{ t('rectification.noVersions') }}</p>
    <template v-if="visible">
      <label class="field">{{ t('rectification.version') }}<select v-model="selected"><option v-for="version in versions" :key="version.version_number" :value="version.version_number">{{ version.version_number }} · {{ version.version_number === current?.version_number ? t('rectification.current') : t('rectification.historical') }}</option></select></label>
      <p>{{ visible.published_at ? formatDateTime(visible.published_at) : t('rectification.original') }} · {{ visible.published_by_user_id || '—' }}</p>
      <p>{{ visible.reason }}</p><p v-if="visible.evidence">{{ t('rectification.evidence') }}: {{ visible.evidence }}</p>
      <RectificationReport :report="visible.report" />
      <RectificationDiff v-if="comparison" :diff="comparison" />
      <Button v-if="canRequest && current && !editing" @click="editing = true">{{ t('rectification.request') }}</Button>
      <Button as="NuxtLink" to="/workspace/rectifications" variant="secondary">{{ t('rectification.inbox') }}</Button>
      <RectificationEditor v-if="editing && current" :match-id="matchId" :version="current" @submitted="editing = false" @cancel="editing = false" />
    </template>
  </Surface>
</template>
