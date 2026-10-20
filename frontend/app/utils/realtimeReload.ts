export const INITIALIZATION_GRACE_MS = 1500;
export const RECONNECT_JOIN_GRACE_MS = 1500;
export const PUBLIC_FIRST_PAGE_OFFSET = 0;

export type ReloadConsumer = 'workspace' | 'public';
export type ReloadTrigger = 'event' | 'reconnect' | 'resync-join' | 'resync-gap';
export type ReloadAction = 'none' | 'initial' | 'reload';

export type GraceScheduler = (callback: () => void, delayMs: number) => unknown;
export type GraceCancel = (handle: unknown) => void;

export function resyncTrigger(reason: string): ReloadTrigger {
  return reason === 'JOIN' ? 'resync-join' : 'resync-gap';
}

export function shouldPollPublicRealtime(status: string): boolean {
  return status !== 'connected';
}

export interface InitializationState {
  initialized: boolean;
  initializedWithJoin: boolean;
}

export interface ReloadDecision {
  action: ReloadAction;
  resetPagination: boolean;
}

export interface ReloadDecisionInput extends InitializationState {
  consumer: ReloadConsumer;
  trigger: ReloadTrigger;
}

/**
 * Política de recarga por consumidor. `initial` completa la carga inicial con
 * el primer `JOIN` sin lanzar una segunda petición; `reload` pide recargar.
 */
export function decideReload({
  consumer,
  trigger,
  initialized,
  initializedWithJoin,
}: ReloadDecisionInput): ReloadDecision {
  if (trigger === 'resync-gap') {
    return { action: 'reload', resetPagination: true };
  }

  if (trigger === 'reconnect') {
    return consumer === 'workspace'
      ? { action: 'reload', resetPagination: false }
      : { action: 'none', resetPagination: false };
  }

  if (trigger === 'resync-join') {
    if (!initialized) return { action: 'initial', resetPagination: false };
    // La gracia cerró la ventana sin JOIN: el primer JOIN posterior completa
    // la inicialización una sola vez.
    if (!initializedWithJoin) return { action: 'reload', resetPagination: false };
    return consumer === 'workspace'
      ? { action: 'reload', resetPagination: false }
      : { action: 'none', resetPagination: false };
  }

  return { action: 'reload', resetPagination: false };
}

export interface InitializationTracker extends InitializationState {
  /** La gracia venció sin JOIN: la carga HTTP ya cerró la inicialización. */
  close(): void;
  /** El primer JOIN completa la inicialización con la carga ya hecha. */
  acceptJoin(): void;
  /** Socket lógico nuevo o desconexión explícita. */
  reset(): void;
}

export function createInitializationTracker(): InitializationTracker {
  let initialized = false;
  let initializedWithJoin = false;

  return {
    get initialized() {
      return initialized;
    },
    get initializedWithJoin() {
      return initializedWithJoin;
    },
    close() {
      initialized = true;
    },
    acceptJoin() {
      initialized = true;
      initializedWithJoin = true;
    },
    reset() {
      initialized = false;
      initializedWithJoin = false;
    },
  };
}

export interface InitializationWindow extends InitializationTracker {
  /** Arranca la gracia; se llama al intentar conectar, no al recibir `connected`. */
  start(): void;
}

/**
 * Ventana de inicialización con gracia: si el socket no conecta o el JOIN no
 * llega, la ventana se cierra y el primer JOIN posterior completa la carga.
 */
export function createInitializationWindow(
  schedule: GraceScheduler,
  cancel: GraceCancel,
  delayMs = INITIALIZATION_GRACE_MS,
): InitializationWindow {
  const tracker = createInitializationTracker();
  let timer: unknown = null;

  function clearTimer() {
    if (timer !== null) {
      cancel(timer);
      timer = null;
    }
  }

  return {
    get initialized() {
      return tracker.initialized;
    },
    get initializedWithJoin() {
      return tracker.initializedWithJoin;
    },
    start() {
      clearTimer();
      if (tracker.initialized) return;
      timer = schedule(() => {
        timer = null;
        tracker.close();
      }, delayMs);
    },
    close() {
      clearTimer();
      tracker.close();
    },
    acceptJoin() {
      clearTimer();
      tracker.acceptJoin();
    },
    reset() {
      clearTimer();
      tracker.reset();
    },
  };
}

export type ReconnectJoinOutcome = 'reconnect' | 'handled' | 'none';

export interface ReconnectJoinController {
  readonly waiting: boolean;
  /** Pérdida de conexión observada: se espera el JOIN de la reconexión. */
  arm(): void;
  /** Conexión restablecida: programa el respaldo único si el JOIN no llega. */
  scheduleFallback(): void;
  acceptJoin(): ReconnectJoinOutcome;
  reset(): void;
}

/**
 * Una recarga por reconexión, disparada por el JOIN posterior. El respaldo se
 * programa al reconectar y se cancela al procesar el JOIN; si vence, se
 * ejecuta una sola vez y el JOIN tardío se ignora.
 */
export function createReconnectJoinController(
  onFallback: () => void,
  schedule: GraceScheduler,
  cancel: GraceCancel,
  delayMs = RECONNECT_JOIN_GRACE_MS,
): ReconnectJoinController {
  let waiting = false;
  let handled = false;
  let timer: unknown = null;

  function clearTimer() {
    if (timer !== null) {
      cancel(timer);
      timer = null;
    }
  }

  return {
    get waiting() {
      return waiting;
    },
    arm() {
      clearTimer();
      waiting = true;
      handled = false;
    },
    scheduleFallback() {
      if (!waiting) return;
      clearTimer();
      timer = schedule(() => {
        timer = null;
        if (!waiting) return;
        waiting = false;
        handled = true;
        onFallback();
      }, delayMs);
    },
    acceptJoin() {
      if (waiting) {
        clearTimer();
        waiting = false;
        handled = true;
        return 'reconnect';
      }
      if (handled) {
        handled = false;
        return 'handled';
      }
      return 'none';
    },
    reset() {
      clearTimer();
      waiting = false;
      handled = false;
    },
  };
}

export interface ReloadRequestOptions {
  resetPagination?: boolean;
}

export interface PageSlice<T> {
  items: T[];
  hasMore: boolean;
}

/** Reemplaza la lista con la primera página y descarta las adicionales. */
export function firstPageSlice<T>(page: readonly T[], pageSize: number): PageSlice<T> {
  return { items: [...page], hasMore: page.length === pageSize };
}

export function appendedPageSlice<T>(
  current: readonly T[],
  page: readonly T[],
  pageSize: number,
): PageSlice<T> {
  return { items: [...current, ...page], hasMore: page.length === pageSize };
}

export interface RequestGeneration {
  next(): number;
  isCurrent(generation: number): boolean;
}

/** Invalida respuestas de páginas que quedaron obsoletas tras una recarga. */
export function createRequestGeneration(): RequestGeneration {
  let current = 0;
  return {
    next() {
      current += 1;
      return current;
    },
    isCurrent(generation) {
      return generation === current;
    },
  };
}

export interface ReloadCoordinator {
  request(options?: ReloadRequestOptions): Promise<void>;
  readonly inFlight: boolean;
}

/**
 * Coordina una recarga en curso y una única trailing; el reset de paginación
 * es acumulativo. Un fallo se delega al consumidor y no programa reintentos.
 */
export function createReloadCoordinator(
  run: (options: { resetPagination: boolean }) => Promise<void>,
): ReloadCoordinator {
  let current: Promise<void> | null = null;
  let pending = false;
  let pendingReset = false;

  async function flush() {
    do {
      pending = false;
      const resetPagination = pendingReset;
      pendingReset = false;
      try {
        await run({ resetPagination });
      } catch {
        // El consumidor conserva sus datos y su estado; sin reintento automático.
      }
    } while (pending);
  }

  return {
    request(options = {}) {
      if (options.resetPagination) pendingReset = true;
      if (current) {
        pending = true;
        return current;
      }
      current = flush().finally(() => {
        current = null;
      });
      return current;
    },
    get inFlight() {
      return current !== null;
    },
  };
}
