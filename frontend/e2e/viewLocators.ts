/**
 * Localizadores de la región del tiempo real (RNF-005, RF-003).
 *
 * Las tres vistas publican su estado de conexión en un `role="status"`, pero no
 * son los únicos: el panel del Workspace anuncia la carga de sus datos y la
 * operación del partido anuncia el borrador local y la vista previa de
 * sustituciones con el mismo rol. Por eso ni el estado ni el control se buscan
 * por nombre suelto en toda la página:
 *
 * - El **estado** se acota a los elementos de estado cuyo texto es exactamente
 *   uno de los cuatro textos visibles del namespace de la vista («conectado»,
 *   «reconectando», «reintentando» o «error»), en el idioma fijado de la
 *   corrida. Un `role="status"` con otro texto no entra en la observación.
 * - El **control «Reintentar»** se busca solo dentro del contenedor que alberga
 *   ese estado (su elemento padre en las tres vistas) y por nombre accesible
 *   exacto. Así no se confunde con los botones «Reintentar» de los bloques de
 *   error de datos, que viven en `role="alert"` fuera de ese contenedor.
 *
 * No se usan clases ni atributos de maquetación: el ancla es el texto visible y
 * el nombre accesible del control.
 */

import type { Locator, Page } from '@playwright/test';

import {
  E2E_LABELS,
  REALTIME_STATUS_TEXT,
  labelText,
  type VisibleRealtimeStatus,
} from './labels.ts';
import type { ViewDefinition } from './observations.ts';

const VISIBLE_STATUSES: readonly VisibleRealtimeStatus[] = [
  'connected',
  'reconnecting',
  'retrying',
  'error',
];

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Alternancia de los textos de estado de la vista. Es lo que distingue el
 * estado del tiempo real del resto de `role="status"` de la misma página.
 */
export function realtimeStatusPattern(view: ViewDefinition): RegExp {
  const entries = REALTIME_STATUS_TEXT[view.namespace];
  return new RegExp(VISIBLE_STATUSES.map((status) => escapeRegExp(labelText(entries[status]))).join('|'));
}

/** El `role="status"` del tiempo real de la vista, acotado por su texto. */
export function realtimeStatusRegion(page: Page, view: ViewDefinition): Locator {
  return page.locator('[role="status"]').filter({ hasText: realtimeStatusPattern(view) });
}

/**
 * Botón del reintento manual: mismo contenedor que el estado del tiempo real y
 * nombre accesible exacto en el idioma fijado. Los «Reintentar» de los errores
 * de datos quedan fuera del contenedor y no compiten con este.
 */
export function realtimeRetryControl(page: Page, view: ViewDefinition): Locator {
  return realtimeStatusRegion(page, view)
    .locator('xpath=..')
    .getByRole('button', { name: labelText(E2E_LABELS.retry), exact: true });
}

/**
 * Textos de los elementos de estado del tiempo real, leídos de la interfaz. Si
 * la vista no anuncia nada (estado `idle`/`connecting`), devuelve una lista
 * vacía en lugar de leer textos de otros estados de la página.
 */
export function readRealtimeStatusTexts(page: Page, view: ViewDefinition): Promise<string[]> {
  return realtimeStatusRegion(page, view).evaluateAll((elements) =>
    elements
      .map((element) => (element.textContent ?? '').trim())
      .filter((text) => text.length > 0),
  );
}
