import type { RealtimeConnectionStatus } from './realtimeConnection';

/**
 * Estado que puede observar el consumidor al pedir un reintento: el del
 * composable (`RealtimeConnectionStatus`) o el de un socket ya desconectado.
 */
export type RealtimeRetryStatus = RealtimeConnectionStatus | 'disconnected';

/**
 * Decide si un reintento manual debe destruir la conexión actual antes de
 * abrir una nueva.
 *
 * - `connected`: nunca. Derribar una conexión sana no es un reintento.
 * - `error` o `disconnected`: siempre, aunque exista un objeto de socket
 *   (zombi): esa conexión no se puede reutilizar y el guard de sesión
 *   devolvería temprano sin intentar nada (R18).
 * - `idle`, `connecting` o `reconnecting`: solo si no hay socket. Con un
 *   socket en curso, Socket.IO ya reintenta solo y pulsar otra vez no debe
 *   acumular conexiones ni duplicar suscripciones (RF-001).
 */
export function shouldForceReconnect(status: RealtimeRetryStatus, hasSocket: boolean): boolean {
  if (status === 'connected') return false;
  if (status === 'error' || status === 'disconnected') return true;
  return !hasSocket;
}
