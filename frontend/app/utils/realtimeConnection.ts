export type RealtimeConnectionStatus = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'error';

export interface ReconnectionInput {
  hasConnectedOnce: boolean;
  previousStatus: RealtimeConnectionStatus;
  nextStatus: RealtimeConnectionStatus;
}

/**
 * Una reconexión exige una conexión exitosa previa y una pérdida observada
 * (estado `reconnecting` o `error`) entre ambas. La conexión inicial no cuenta.
 */
export function isReconnection({
  hasConnectedOnce,
  previousStatus,
  nextStatus,
}: ReconnectionInput): boolean {
  if (!hasConnectedOnce || nextStatus !== 'connected') return false;
  return previousStatus === 'reconnecting' || previousStatus === 'error';
}

export interface SocketSessionInput {
  hasSocket: boolean;
  previousScopeKey: string | null;
  nextScopeKey: string;
  publicScope: boolean;
  previousSessionVersion: number;
  sessionVersion: number;
}

/**
 * Un socket lógico nuevo (y, con él, el vaciado de la ventana de
 * deduplicación) solo es necesario si no había socket, cambia el alcance o,
 * en organización, cambia la versión de sesión. El auto-reconnect no lo pide.
 */
export function needsNewSocketSession({
  hasSocket,
  previousScopeKey,
  nextScopeKey,
  publicScope,
  previousSessionVersion,
  sessionVersion,
}: SocketSessionInput): boolean {
  if (!hasSocket) return true;
  if (previousScopeKey !== nextScopeKey) return true;
  return !publicScope && previousSessionVersion !== sessionVersion;
}
