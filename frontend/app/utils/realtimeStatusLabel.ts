import type { RealtimeConnectionStatus } from './realtimeConnection';

/**
 * Vistas que publican su estado de tiempo real con su propio texto (RF-003):
 * la página pública del torneo, el panel del Workspace y la operación del
 * partido.
 */
export type RealtimeLabelNamespace = 'public' | 'workspace' | 'match';

/**
 * Clave i18n del estado visible del tiempo real, o `null` si la vista no tiene
 * nada que anunciar (`idle` y `connecting`).
 *
 * Una sola función para las tres vistas: así la distinción entre el reintento
 * manual (`retrying`) y la reconexión automática (`reconnecting`) es la misma
 * en todas y se verifica sin navegador y en los dos idiomas (RNF-005,
 * RNF-011). La vista añade su propio respaldo cuando la clave es `null`.
 */
export function realtimeStatusLabelKey(
  status: RealtimeConnectionStatus,
  namespace: RealtimeLabelNamespace,
): string | null {
  switch (status) {
    case 'connected':
      return `${namespace}.realtimeConnected`;
    case 'reconnecting':
      return `${namespace}.realtimeReconnecting`;
    case 'retrying':
      return `${namespace}.realtimeRetrying`;
    case 'error':
      return `${namespace}.realtimeError`;
    case 'idle':
    case 'connecting':
      return null;
  }
}
