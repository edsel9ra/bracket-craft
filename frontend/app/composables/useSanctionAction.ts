import type { ConfirmOptions } from '~/utils/confirmQueue';
import { sanctionErrorKey } from '~/utils/sanctions';

export function useSanctionAction() {
  const { organizationId } = useApi();
  const auth = useAuthStore();
  const { confirm, cancelAll } = useConfirm({ singleFlight: true });
  const busy = ref(false); const error = ref('');
  let generation = 0;
  function reset() { generation++; busy.value = false; error.value = ''; cancelAll(); }
  watch(() => [organizationId.value, auth.userId, auth.access?.permissions.join(','), auth.access?.role_code], reset, { flush: 'sync' });
  onBeforeUnmount(reset);
  async function run<T>(options: ConfirmOptions, operation: () => Promise<T>): Promise<T | undefined> {
    if (busy.value || !organizationId.value || !auth.userId) return;
    const token = generation;
    busy.value = true; error.value = '';
    try {
      if (!await confirm(options) || token !== generation) return;
      const result = await operation();
      return token === generation ? result : undefined;
    } catch (cause) { if (token === generation) error.value = sanctionErrorKey(cause); }
    finally { if (token === generation) busy.value = false; }
  }
  return { busy, error, run };
}
