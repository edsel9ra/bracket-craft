/**
 * Vista privada según capacidades independientes (spec 036, T65).
 *
 * Cada capacidad gobierna exactamente su superficie: `can_view` permite ver el
 * detalle del borrador, `can_operate` los controles, `can_close` el cierre.
 * Ninguna se hereda de otra; la UI nunca es la barrera de seguridad (el
 * servidor revalida cada lectura y comando). Sin lectura autorizada no hay
 * detalle que mostrar ni contexto que referenciar, así que los controles no se
 * ofrecen.
 */

import type { LiveCapabilities } from './matchLiveContext.ts';

export type LiveViewMode = 'hidden' | 'reader' | 'operator' | 'closer';

export interface LiveViewModel {
  mode: LiveViewMode;
  /** El detalle del borrador solo existe con `can_view`. */
  detailVisible: boolean;
  /** Controles de operación (captura, corrección, reloj, transiciones). */
  controlsEnabled: boolean;
  /** El cierre solo se ofrece con `can_close` propio. */
  closeEnabled: boolean;
}

const HIDDEN: LiveViewModel = {
  mode: 'hidden',
  detailVisible: false,
  controlsEnabled: false,
  closeEnabled: false,
};

export function deriveLiveView(capabilities: LiveCapabilities | null): LiveViewModel {
  if (capabilities === null || !capabilities.available) return HIDDEN;
  const view: LiveViewModel = {
    detailVisible: capabilities.can_view,
    controlsEnabled: capabilities.can_view && capabilities.can_operate,
    closeEnabled: capabilities.can_close,
    mode: 'hidden',
  };
  if (capabilities.can_view && capabilities.can_operate) view.mode = 'operator';
  else if (capabilities.can_close) view.mode = 'closer';
  else if (capabilities.can_view) view.mode = 'reader';
  return view;
}
