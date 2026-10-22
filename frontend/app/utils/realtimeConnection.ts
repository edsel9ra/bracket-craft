/**
 * Estado visible de la conexión de tiempo real.
 *
 * `retrying` es **exclusivo del reintento manual** (RF-001): solo lo fija
 * `retry()` y solo cuando esa pulsación inicia un intento de conexión nuevo.
 * El motor y la reconexión automática no lo producen, y cualquier transición
 * (`connected`, `error`, `reconnecting`, `idle`) lo sustituye.
 */
export type RealtimeConnectionStatus =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'retrying'
  | 'error';

export interface ReconnectionInput {
  hasConnectedOnce: boolean;
  previousStatus: RealtimeConnectionStatus;
  nextStatus: RealtimeConnectionStatus;
}

/**
 * Una reconexión exige una conexión exitosa previa y una pérdida observada
 * (estado `reconnecting` o `error`) entre ambas. La conexión inicial no cuenta.
 * El estado manual `retrying` tampoco: lo produce la pulsación, que abre un
 * intento nuevo, no una pérdida del transporte.
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
