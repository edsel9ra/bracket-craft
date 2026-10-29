/**
 * Cadena de avance de la configuración del torneo (spec 026, RF-001 a RF-004,
 * RF-007, RF-015, RF-016; ORD-4, ORD-6, ORD-9, ORD-13).
 *
 * La **acción principal** de cada sección abre la siguiente —Reglas → Equipos →
 * Fases → Calendario— y solo lo hace con un guardado **efectivo**: sin error y
 * sin trabajo pendiente. El calendario es el final de la cadena y no abre nada.
 *
 * El módulo es puro: no lee el reloj, el entorno, el almacenamiento ni la red, y
 * con las mismas entradas devuelve el mismo resultado. La página es la única que
 * ejecuta la decisión (navegar o quedarse); aquí solo se decide (D-2).
 */
import { phasesAssistantHref } from './teamsWizard.ts';

/** Las cuatro secciones del recorrido, en el orden del documento (025 RF-001). */
export type ConfigurationSection = 'rules' | 'teams' | 'stages' | 'calendar';

export interface AdvanceTarget {
  readonly path: string;
  /** Fragmento de la misma pantalla; `null` cuando el destino es otra ruta. */
  readonly hash: `#${string}` | null;
  /** El salto conserva la consulta actual, para no añadir ni retirar `?step=`. */
  readonly keepQuery: boolean;
}

export type AdvanceDecision =
  | { readonly kind: 'navigate'; readonly target: AdvanceTarget }
  | { readonly kind: 'wait'; readonly target: AdvanceTarget }
  | { readonly kind: 'stay' };

/** Sección de configuración de un torneo: la misma pantalla para Reglas, Equipos y Fases. */
function configurationPath(tournamentId: string): string {
  return `/workspace/tournaments/${tournamentId}`;
}

/** Separa ruta y fragmento de una dirección ya construida, sin reescribirla. */
function splitHref(href: string): { path: string; hash: `#${string}` | null } {
  const index = href.indexOf('#');
  if (index < 0) return { path: href, hash: null };
  return { path: href.slice(0, index), hash: href.slice(index) as `#${string}` };
}

/**
 * Destino de la acción principal de una sección (RF-001, RF-002, RF-003):
 *
 * - Reglas → Equipos: la misma pantalla con el ancla `#equipos` que ya existe.
 * - Equipos → Fases: el mismo destino que el enlace cruzado de la 025, leído de
 *   `phasesAssistantHref` para que el salto y el enlace no puedan divergir; el
 *   salto **no escribe ningún paso** en la dirección (ORD-13).
 * - Fases → Calendario: su ruta, sin consulta ni fragmento (no crea ni sortea).
 * - Calendario: `null`, porque es el final de la cadena.
 *
 * Los saltos de la misma pantalla conservan la consulta actual (RF-007).
 */
export function advanceTarget(
  section: ConfigurationSection,
  tournamentId: string,
): AdvanceTarget | null {
  switch (section) {
    case 'rules':
      return { path: configurationPath(tournamentId), hash: '#equipos', keepQuery: true };
    case 'teams': {
      const { path, hash } = splitHref(phasesAssistantHref(tournamentId));
      return { path, hash, keepQuery: true };
    }
    case 'stages':
      return { path: `${configurationPath(tournamentId)}/calendar`, hash: null, keepQuery: false };
    case 'calendar':
      return null;
  }
}

/**
 * Decisión tras un guardado o una confirmación (RF-004, RF-015):
 *
 * - Sin éxito —validación pendiente, 4xx/5xx, confirmación bloqueada o guardado
 *   parcial— la pantalla se queda y no queda ninguna salida armada.
 * - Con éxito y sin aviso de minutos, la sección siguiente se abre de inmediato.
 * - Con éxito y aviso de minutos, el salto queda **armado** esperando a que el
 *   usuario elija «Continuar» o «Quedarme» (`resolveNotice`).
 */
export function advanceAfterSave(input: {
  readonly section: ConfigurationSection;
  readonly effective: boolean;
  /** El guardado efectivo dejó el aviso de minutos. */
  readonly notice: boolean;
  readonly tournamentId: string;
}): AdvanceDecision {
  if (!input.effective) return { kind: 'stay' };
  const target = advanceTarget(input.section, input.tournamentId);
  if (!target) return { kind: 'stay' };
  return input.notice ? { kind: 'wait', target } : { kind: 'navigate', target };
}

/**
 * Resolución del salto armado por los dos controles del aviso (RF-015, ORD-9):
 * «Continuar» devuelve la navegación ya armada y «Quedarme» cancela el salto.
 * Ninguno guarda ni envía peticiones, y la decisión de entrada no se modifica.
 */
export function resolveNotice(
  decision: Extract<AdvanceDecision, { kind: 'wait' }>,
  choice: 'continue' | 'stay',
): AdvanceDecision {
  if (choice === 'continue') return { kind: 'navigate', target: decision.target };
  return { kind: 'stay' };
}

/** Los sucesos que descartan el aviso y el salto armado sin ejecutarlo (RF-016). */
const PENDING_ADVANCE_CLEARED: Readonly<
  Record<Parameters<typeof clearsPendingAdvance>[0], true>
> = {
  // Editar una regla oculta el aviso y cancela el salto.
  edit: true,
  // Un guardado nuevo recalcula el aviso desde cero, sin acumular salidas.
  save: true,
  // Un guardado fallido no deja aviso ni salto armado.
  'save-failed': true,
  // Navegar dentro de la misma página o a otra descarta el salto pendiente.
  navigation: true,
  // Cambiar de versión o de torneo descarta el salto pendiente.
  'version-change': true,
  // Recargar descarta el salto sin ejecutarlo.
  reload: true,
};

/**
 * Tabla única de invalidación de RF-016: los seis sucesos descartan el aviso y
 * el salto armado **sin ejecutarlo**. La pulsación de «Continuar» o «Quedarme»
 * no está en la tabla: su efecto lo decide `resolveNotice`.
 */
export function clearsPendingAdvance(
  event: 'edit' | 'save' | 'save-failed' | 'navigation' | 'version-change' | 'reload',
): boolean {
  return PENDING_ADVANCE_CLEARED[event];
}
