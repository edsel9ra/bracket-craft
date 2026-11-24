import { NOTIFICATION_PAGE_SIZE, notificationErrorKey, notificationQuery, type NotificationItem, type NotificationPage } from '~/utils/notifications';

function useNotificationScope() {
  const { request, organizationId } = useApi();
  const auth = useAuthStore();
  const active = () => Boolean(auth.userId && organizationId.value && organizationId.value === auth.access?.organization_id);
  const identity = () => [organizationId.value, auth.userId, auth.access?.organization_id];
  return { request, active, identity };
}

/** Número de avisos sin leer de la organización activa, compartido entre el Workspace y la bandeja. */
export function useNotificationUnread() {
  const { request, active, identity } = useNotificationScope();
  const count = useState<number | null>('notification-unread', () => null);
  let generation = 0;
  async function refresh() {
    const token = ++generation;
    if (!active()) { count.value = null; return; }
    try {
      const page = await request<NotificationPage>(`/notifications${notificationQuery({ limit: 1, offset: 0 })}`);
      if (token === generation) count.value = page.unread_count;
    } catch { if (token === generation) count.value = null; }
  }
  watch(identity, () => { count.value = null; void refresh(); }, { flush: 'sync' });
  return { count, refresh };
}

export function useNotifications() {
  const { request, active, identity } = useNotificationScope();
  const unreadCount = useState<number | null>('notification-unread', () => null);
  const items = ref<NotificationItem[]>([]);
  const total = ref(0);
  const offset = ref(0);
  const loading = ref(false);
  const busy = ref(false);
  const error = ref('');
  const actionError = ref('');
  let generation = 0;

  function clear() {
    generation++;
    items.value = []; total.value = 0; error.value = ''; actionError.value = ''; loading.value = false; busy.value = false;
  }

  async function load() {
    clear();
    if (!active()) { unreadCount.value = null; return; }
    const token = generation; loading.value = true;
    try {
      const page = await request<NotificationPage>(`/notifications${notificationQuery({ limit: NOTIFICATION_PAGE_SIZE, offset: offset.value })}`);
      if (token !== generation) return;
      items.value = page.items; total.value = page.total; unreadCount.value = page.unread_count;
    } catch (cause) { if (token === generation) error.value = notificationErrorKey(cause); }
    finally { if (token === generation) loading.value = false; }
  }

  async function command(path: string) {
    if (busy.value || !active()) return;
    const token = generation; busy.value = true; actionError.value = '';
    try {
      await request(path, { method: 'POST' });
      if (token === generation) await load();
    } catch (cause) {
      if (token === generation) { actionError.value = notificationErrorKey(cause); busy.value = false; }
    }
  }

  function page(value: number) { offset.value = Math.max(0, value); void load(); }
  const markRead = (id: string) => command(`/notifications/${encodeURIComponent(id)}/read`);
  const markAllRead = () => command('/notifications/read-all');

  watch(identity, () => { offset.value = 0; void load(); }, { flush: 'sync' });
  onMounted(load);
  onBeforeUnmount(clear);
  return {
    items, unreadCount, total, offset, loading, busy, error, actionError,
    canNext: computed(() => offset.value + items.value.length < total.value),
    load, page, markRead, markAllRead,
  };
}
