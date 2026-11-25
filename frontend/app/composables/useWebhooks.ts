import {
  WEBHOOK_LIMIT, normalizeWebhookUrl, orderedWebhookTypes, validateWebhookUrl, webhookErrorKey,
  type CreatedWebhook, type WebhookDelivery, type WebhookInput, type WebhookItem,
} from '~/utils/webhooks';

/** Webhooks de la organización activa (spec 047, RF-001–RF-003, RF-012). */
export function useWebhooks() {
  const { request, organizationId } = useApi();
  const auth = useAuthStore();
  const { t } = useI18n();
  const { confirm } = useConfirm({ singleFlight: true });
  const canManage = computed(() => Boolean(
    auth.hasPermission('MANAGE_WEBHOOKS') && organizationId.value && organizationId.value === auth.access?.organization_id,
  ));
  const items = ref<WebhookItem[]>([]);
  const loading = ref(false);
  const busy = ref(false);
  const error = ref('');
  const actionError = ref('');
  const notice = ref('');
  const secret = ref<string | null>(null);
  const deliveriesFor = ref<string | null>(null);
  const deliveries = ref<WebhookDelivery[]>([]);
  const deliveriesLoading = ref(false);
  const deliveriesError = ref('');
  const limitReached = computed(() => items.value.length >= WEBHOOK_LIMIT);
  let generation = 0;

  const path = (id: string, suffix = '') => `/webhooks/${encodeURIComponent(id)}${suffix}`;

  function reset() {
    generation += 1;
    items.value = []; error.value = ''; actionError.value = ''; notice.value = ''; secret.value = null;
    deliveriesFor.value = null; deliveries.value = []; deliveriesError.value = '';
    loading.value = false; busy.value = false; deliveriesLoading.value = false;
  }

  async function load() {
    if (!canManage.value) return;
    const token = generation;
    loading.value = true; error.value = '';
    try {
      const result = await request<WebhookItem[]>('/webhooks');
      if (token === generation && canManage.value) items.value = result.map(({ id, url, event_types, is_active, created_at, updated_at }) => ({ id, url, event_types, is_active, created_at, updated_at }));
    } catch (cause) {
      if (token === generation) error.value = webhookErrorKey(cause);
    } finally {
      if (token === generation) loading.value = false;
    }
  }

  async function run<T>(action: () => Promise<T>, done?: (result: T) => void): Promise<boolean> {
    if (!canManage.value || busy.value) return false;
    const token = generation;
    busy.value = true; actionError.value = ''; notice.value = '';
    try {
      const result = await action();
      if (token !== generation) return false;
      done?.(result);
      await load();
      return true;
    } catch (cause) {
      if (token === generation) actionError.value = webhookErrorKey(cause);
      return false;
    } finally {
      if (token === generation) busy.value = false;
    }
  }

  function checked(input: WebhookInput): WebhookInput | null {
    const urlError = validateWebhookUrl(input.url);
    const types = orderedWebhookTypes(input.event_types);
    actionError.value = urlError ?? (types.length ? '' : 'webhook.error.types');
    return actionError.value ? null : { url: normalizeWebhookUrl(input.url), event_types: types };
  }

  async function create(input: WebhookInput) {
    const body = checked(input);
    if (!body) return false;
    return run(() => request<CreatedWebhook>('/webhooks', { method: 'POST', body }), (result) => { secret.value = result.secret; });
  }

  async function update(id: string, input: WebhookInput) {
    const body = checked(input);
    if (!body) return false;
    return run(() => request<WebhookItem>(path(id), { method: 'PATCH', body }));
  }

  async function ask(kind: 'disable' | 'delete' | 'rotate', webhook: WebhookItem) {
    return confirm({
      title: t(`webhook.confirm.${kind}.title`),
      message: t(`webhook.confirm.${kind}.message`, { url: webhook.url }),
      confirmLabel: t(`webhook.confirm.${kind}.action`),
      tone: 'danger',
    });
  }

  async function setActive(webhook: WebhookItem, active: boolean) {
    if (!active && !(await ask('disable', webhook))) return;
    await run(() => request<WebhookItem>(path(webhook.id), { method: 'PATCH', body: { is_active: active } }));
  }

  async function remove(webhook: WebhookItem) {
    if (!(await ask('delete', webhook))) return;
    await run(() => request<null>(path(webhook.id), { method: 'DELETE' }), () => {
      if (deliveriesFor.value === webhook.id) { deliveriesFor.value = null; deliveries.value = []; }
    });
  }

  async function rotate(webhook: WebhookItem) {
    if (!(await ask('rotate', webhook))) return;
    await run(() => request<{ secret: string }>(path(webhook.id, '/rotate-secret'), { method: 'POST' }), (result) => { secret.value = result.secret; });
  }

  async function sendTest(webhook: WebhookItem) {
    await run(() => request<{ delivery_id: string }>(path(webhook.id, '/test'), { method: 'POST' }), () => { notice.value = 'webhook.testQueued'; });
  }

  async function showDeliveries(webhook: WebhookItem) {
    if (!canManage.value) return;
    const token = generation;
    deliveriesFor.value = webhook.id; deliveries.value = []; deliveriesLoading.value = true; deliveriesError.value = '';
    try {
      const result = await request<WebhookDelivery[]>(path(webhook.id, '/deliveries'));
      if (token === generation && deliveriesFor.value === webhook.id) deliveries.value = result;
    } catch (cause) {
      if (token === generation && deliveriesFor.value === webhook.id) deliveriesError.value = webhookErrorKey(cause);
    } finally {
      if (token === generation && deliveriesFor.value === webhook.id) deliveriesLoading.value = false;
    }
  }

  function dismissSecret() { secret.value = null; }

  watch(() => [organizationId.value, auth.userId, auth.access?.organization_id], () => { reset(); void load(); });
  onMounted(() => { void load(); });
  onBeforeUnmount(() => { generation += 1; secret.value = null; });

  return {
    canManage, items, loading, busy, error, actionError, notice, secret, limitReached,
    deliveriesFor, deliveries, deliveriesLoading, deliveriesError,
    load, create, update, setActive, remove, rotate, sendTest, showDeliveries, dismissSecret,
  };
}
