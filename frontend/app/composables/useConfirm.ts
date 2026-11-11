import { createConfirmQueue, type ConfirmOptions, type ConfirmRequest } from '~/utils/confirmQueue';

const queues = new WeakMap<object, ReturnType<typeof createConfirmQueue>>();

export function useConfirm() {
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
  return {
    active: readonly(active),
    confirm: (options: ConfirmOptions): Promise<boolean> => import.meta.client ? currentQueue.confirm(options) : Promise.resolve(false),
    settle: (value: boolean, id: number) => currentQueue.settle(value, id),
    cancelAll: () => currentQueue.cancelAll(),
  };
}
