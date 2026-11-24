import { notificationErrorKey, orderedPreferences, type NotificationPreference } from '~/utils/notifications';

export function useNotificationPreferences() {
  const { request, organizationId } = useApi();
  const auth = useAuthStore();
  const items = ref<NotificationPreference[]>([]);
  const stored = ref('');
  const loading = ref(false);
  const saving = ref(false);
  const saved = ref(false);
  const error = ref('');
  let generation = 0;
  const active = () => Boolean(auth.userId && organizationId.value && organizationId.value === auth.access?.organization_id);
  const signature = (value: readonly NotificationPreference[]) => JSON.stringify(value.map((item) => item.enabled));

  function apply(value: readonly NotificationPreference[]) {
    items.value = orderedPreferences(value); stored.value = signature(items.value);
  }

  function clear() {
    generation++;
    items.value = []; stored.value = ''; loading.value = false; saving.value = false; saved.value = false; error.value = '';
  }

  async function load() {
    clear();
    if (!active()) return;
    const token = generation; loading.value = true;
    try {
      const result = await request<{ items: NotificationPreference[] }>('/notification-preferences');
      if (token === generation) apply(result.items);
    } catch (cause) { if (token === generation) error.value = notificationErrorKey(cause); }
    finally { if (token === generation) loading.value = false; }
  }

  async function save() {
    if (saving.value || !active() || items.value.length === 0) return;
    const token = generation; saving.value = true; saved.value = false; error.value = '';
    try {
      const body = { items: orderedPreferences(items.value) };
      const result = await request<{ items: NotificationPreference[] }>('/notification-preferences', { method: 'PUT', body });
      if (token === generation) { apply(result.items); saved.value = true; }
    } catch (cause) { if (token === generation) error.value = notificationErrorKey(cause); }
    finally { if (token === generation) saving.value = false; }
  }

  watch(() => [organizationId.value, auth.userId, auth.access?.organization_id], () => { void load(); }, { flush: 'sync' });
  onMounted(load);
  onBeforeUnmount(clear);
  return { items, loading, saving, saved, error, dirty: computed(() => items.value.length > 0 && signature(items.value) !== stored.value), load, save };
}
