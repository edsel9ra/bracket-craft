import { io, type Socket } from 'socket.io-client';

import { isReconnection, needsNewSocketSession, type RealtimeConnectionStatus } from '~/utils/realtimeConnection';
import { createEventDeduplicator } from '~/utils/realtimeDedup';
import {
  createRealtimeDispatcher,
  parseResyncPayload,
  RESYNC_EVENT,
  type ResyncPayload,
} from '~/utils/realtimeDispatch';
import { createInitializationWindow, createReconnectJoinController } from '~/utils/realtimeReload';
import { shouldForceReconnect } from '~/utils/realtimeRetry';
import { normalizeOrganizationId, normalizeUuid } from '~/utils/validation';

export type RealtimeEventName = 'MATCH_CLOSED' | 'MATCH_UPDATED' | 'STANDINGS_UPDATED';
export type RealtimeStatus = RealtimeConnectionStatus;

export interface RealtimeHandlers {
  onMatchClosed?: (payload: unknown) => void;
  onMatchUpdated?: (payload: unknown) => void;
  onStandingsUpdated?: (payload: unknown) => void;
  onEvent?: (event: string, payload: unknown) => void;
  onReconnect?: () => void;
  onResync?: (payload: ResyncPayload) => void;
  onError?: (cause: unknown) => void;
}

type HandlerInput = RealtimeHandlers | (() => void);
type ConnectionOptions = { tournamentId?: string };

export function useRealtime() {
  const config = useRuntimeConfig();
  const auth = useAuthStore();
  const cookieOptions = { sameSite: 'lax' as const, secure: !import.meta.dev };
  const organizationId = useCookie<string | null>('bc_organization_id', cookieOptions);
  if (organizationId.value && !normalizeOrganizationId(organizationId.value)) organizationId.value = null;

  const status = ref<RealtimeStatus>('idle');
  const error = ref<string | null>(null);
  let socket: Socket | null = null;
  let connectedScopeKey: string | null = null;
  let connectedSessionVersion = -1;
  let requestedPublicTournamentId: string | null = null;
  let activeHandlers: RealtimeHandlers = {};
  let manuallyDisconnected = false;
  // Una ventana por socket lógico; solo se vacía al abrir otro socket o
  // desconectar, nunca en el auto-reconnect de Socket.IO.
  const dedupe = createEventDeduplicator();
  let dispatch = createRealtimeDispatcher({ dedupe, handlers: activeHandlers });
  const scheduleGrace = (callback: () => void, delayMs: number) => setTimeout(callback, delayMs);
  const cancelGrace = (handle: unknown) => clearTimeout(handle as ReturnType<typeof setTimeout>);
  const initialization = createInitializationWindow(scheduleGrace, cancelGrace);
  const reconnectJoin = createReconnectJoinController(
    () => activeHandlers.onReconnect?.(),
    scheduleGrace,
    cancelGrace,
  );
  let hasConnectedOnce = false;
  let sawConnectionLoss = false;

  function handlersFrom(input?: HandlerInput): RealtimeHandlers {
    if (typeof input === 'function') return { onMatchClosed: input };
    return input || {};
  }

  function setStatus(nextStatus: RealtimeStatus, nextError: string | null = null) {
    status.value = nextStatus;
    error.value = nextError;
  }

  function noteConnectionLoss() {
    const firstLoss = !sawConnectionLoss;
    sawConnectionLoss = true;
    if (firstLoss && hasConnectedOnce) reconnectJoin.arm();
  }

  function connect(input?: HandlerInput, options?: ConnectionOptions) {
    if (input !== undefined) {
      activeHandlers = handlersFrom(input);
      dispatch = createRealtimeDispatcher({ dedupe, handlers: activeHandlers });
    }
    if (options !== undefined) requestedPublicTournamentId = normalizeUuid(options.tournamentId);
    if (import.meta.server) return;

    const validOrganizationId = normalizeOrganizationId(organizationId.value);
    const validPublicTournamentId = normalizeUuid(requestedPublicTournamentId);
    const usePublicScope = Boolean(validPublicTournamentId);
    if (!usePublicScope && (!auth.userId || !validOrganizationId)) {
      disconnect();
      return;
    }
    const scopeKey = usePublicScope
      ? `public:${validPublicTournamentId}`
      : `organization:${validOrganizationId}`;

    if (
      !needsNewSocketSession({
        hasSocket: socket !== null,
        previousScopeKey: connectedScopeKey,
        nextScopeKey: scopeKey,
        publicScope: scopeKey.startsWith('public:'),
        previousSessionVersion: connectedSessionVersion,
        sessionVersion: auth.sessionVersion,
      })
    ) {
      return;
    }

    disconnect(false);
    manuallyDisconnected = false;
    connectedScopeKey = scopeKey;
    connectedSessionVersion = auth.sessionVersion;
    setStatus('connecting');

    socket = io(config.public.socketBase, {
      auth: usePublicScope
        ? { tournament_id: validPublicTournamentId }
        : { organization_id: validOrganizationId },
      withCredentials: true,
      reconnection: true,
      reconnectionAttempts: Infinity,
      timeout: 10_000,
    });

    // La ventana de inicialización empieza con el intento de conexión: si el
    // socket no conecta o el JOIN no llega, la gracia la cierra con la carga
    // HTTP ya hecha.
    initialization.start();

    socket.on('connect', () => {
      const reconnected = isReconnection({
        hasConnectedOnce,
        previousStatus: sawConnectionLoss ? 'reconnecting' : status.value,
        nextStatus: 'connected',
      });
      setStatus('connected');
      hasConnectedOnce = true;
      sawConnectionLoss = false;
      if (reconnected) reconnectJoin.scheduleFallback();
    });
    socket.on('disconnect', (reason) => {
      if (manuallyDisconnected) return;
      noteConnectionLoss();
      setStatus('reconnecting', reason || null);
    });
    socket.on('connect_error', (cause) => {
      noteConnectionLoss();
      const message = cause instanceof Error ? cause.message : String(cause);
      setStatus('error', message);
      activeHandlers.onError?.(cause);
    });
    socket.io.on('reconnect_attempt', () => setStatus('reconnecting'));
    socket.io.on('reconnect', () => setStatus('connected'));
    socket.io.on('reconnect_failed', () => setStatus('error', 'reconnect_failed'));

    // Único punto de despacho: deduplica antes de invocar cualquier handler y
    // separa RESYNC de los eventos de dominio. El JOIN cancelado por el
    // respaldo de reconexión no vuelve a disparar la recarga del consumidor.
    socket.onAny((event: string, payload: unknown) => {
      const resync = event === RESYNC_EVENT ? parseResyncPayload(payload) : null;
      if (resync?.reason === 'JOIN') {
        const outcome = reconnectJoin.acceptJoin();
        if (outcome === 'handled' && activeHandlers.onReconnect) {
          // La recarga de respaldo ya se hizo: el JOIN tardío se absorbe.
          initialization.acceptJoin();
          return;
        }
        dispatch(event, payload);
        initialization.acceptJoin();
        return;
      }
      dispatch(event, payload);
    });
  }

  function disconnect(clearRequestedScope = true) {
    manuallyDisconnected = true;
    dedupe.reset();
    reconnectJoin.reset();
    initialization.reset();
    hasConnectedOnce = false;
    sawConnectionLoss = false;
    socket?.disconnect();
    socket = null;
    connectedScopeKey = null;
    connectedSessionVersion = -1;
    if (clearRequestedScope) requestedPublicTournamentId = null;
    setStatus('idle');
  }

  /**
   * Reintento manual (R18): si la conexión actual no se puede reutilizar,
   * cierra el intento anterior antes de abrir uno nuevo. `disconnect(false)`
   * conserva el alcance solicitado y `activeHandlers` sobrevive al cierre, de
   * modo que el socket nuevo se suscribe con los mismos handlers. Con un
   * socket en curso o conectado el guard de `connect()` evita duplicarlo.
   */
  function retry() {
    if (shouldForceReconnect(status.value, socket !== null)) {
      disconnect(false);
    }
    connect(activeHandlers);
  }

  const stopSessionWatch = watch(
    [() => organizationId.value, () => auth.userId, () => auth.sessionVersion],
    () => connect(activeHandlers),
  );
  onScopeDispose(() => {
    stopSessionWatch();
    disconnect();
  });

  return { connect, disconnect, retry, status, error, initialization };
}
