import { createConfirmQueue, singleFlightConfirm, type ConfirmOptions, type ConfirmRequest } from '~/utils/confirmQueue';

const queues = new WeakMap<object, ReturnType<typeof createConfirmQueue>>();

export function useConfirm(options: { singleFlight?: boolean } = {}) {
  const app = useNuxtApp();
  const router = useRouter();
  const active = useState<ConfirmRequest | null>('confirm', () => null);
  let queue = queues.get(app);
  if (!queue) {
    const created = createConfirmQueue((request) => { active.value = request; });
    queue = created;
    queues.set(app, queue);
    if (import.meta.client) {
      router.beforeEach(() => { created.cancelAll(); });
    }
  }
  const currentQueue = queue;
  const confirm = (options: ConfirmOptions): Promise<boolean> => import.meta.client ? currentQueue.confirm(options) : Promise.resolve(false);
  return {
    active: readonly(active),
    confirm: options.singleFlight ? singleFlightConfirm(confirm) : confirm,
    settle: (value: boolean, id: number) => currentQueue.settle(value, id),
    cancelAll: () => currentQueue.cancelAll(),
  };
}
