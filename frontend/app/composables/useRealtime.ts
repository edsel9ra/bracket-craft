import { io, type Socket } from 'socket.io-client';

import { normalizeOrganizationId, normalizeUuid } from '~/utils/validation';

export type RealtimeEventName = 'MATCH_CLOSED' | 'MATCH_UPDATED' | 'STANDINGS_UPDATED';
export type RealtimeStatus = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'error';

export interface RealtimeHandlers {
  onMatchClosed?: (payload: unknown) => void;
  onMatchUpdated?: (payload: unknown) => void;
  onStandingsUpdated?: (payload: unknown) => void;
  onEvent?: (event: string, payload: unknown) => void;
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

  function handlersFrom(input?: HandlerInput): RealtimeHandlers {
    if (typeof input === 'function') return { onMatchClosed: input };
    return input || {};
  }

  function setStatus(nextStatus: RealtimeStatus, nextError: string | null = null) {
    status.value = nextStatus;
    error.value = nextError;
  }

  function connect(input?: HandlerInput, options?: ConnectionOptions) {
    if (input !== undefined) activeHandlers = handlersFrom(input);
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
      socket
      && connectedScopeKey === scopeKey
      && (scopeKey.startsWith('public:') || connectedSessionVersion === auth.sessionVersion)
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

    socket.on('connect', () => setStatus('connected'));
    socket.on('disconnect', (reason) => {
      if (manuallyDisconnected) return;
      setStatus('reconnecting', reason || null);
    });
    socket.on('connect_error', (cause) => {
      const message = cause instanceof Error ? cause.message : String(cause);
      setStatus('error', message);
      activeHandlers.onError?.(cause);
    });
    socket.io.on('reconnect_attempt', () => setStatus('reconnecting'));
    socket.io.on('reconnect', () => setStatus('connected'));
    socket.io.on('reconnect_failed', () => setStatus('error', 'reconnect_failed'));

    // The server may add new event names. Unknown events are intentionally ignored.
    socket.onAny((event: string, payload: unknown) => {
      activeHandlers.onEvent?.(event, payload);
      if (event === 'MATCH_CLOSED') activeHandlers.onMatchClosed?.(payload);
      if (event === 'MATCH_UPDATED') activeHandlers.onMatchUpdated?.(payload);
      if (event === 'STANDINGS_UPDATED') activeHandlers.onStandingsUpdated?.(payload);
    });
  }

  function disconnect(clearRequestedScope = true) {
    manuallyDisconnected = true;
    socket?.disconnect();
    socket = null;
    connectedScopeKey = null;
    connectedSessionVersion = -1;
    if (clearRequestedScope) requestedPublicTournamentId = null;
    setStatus('idle');
  }

  const stopSessionWatch = watch(
    [() => organizationId.value, () => auth.userId, () => auth.sessionVersion],
    () => connect(activeHandlers),
  );
  onScopeDispose(() => {
    stopSessionWatch();
    disconnect();
  });

  return { connect, disconnect, status, error };
}
