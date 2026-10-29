/**
 * Cifra de composición de una fase (spec 026, RF-010, RF-011, RF-012, RF-014;
 * ORD-5, ORD-8, ORD-14).
 *
 * Es el **único total** que leen el paso de composición y el resumen de
 * revisión del asistente de fases: los equipos **inscritos** en la fase más los
 * **seleccionados** en esta visita, contados por identificador.
 *
 * El módulo es puro: no lee el reloj, el entorno, el almacenamiento ni la red, y
 * con las mismas entradas devuelve el mismo resultado (RNF-006). Solo combina
 * dos listas que la pantalla ya cargó, así que calcularla no inscribe nada, no
 * envía ninguna petición ni cambia la API (RF-012).
 */
import { dedupeTeamIds } from './stageTeams.ts';
import { MAX_STAGE_TEAMS } from './stageWizard.ts';

export interface StageCompositionInput {
  readonly mode: 'create' | 'existing';
  readonly assignedTeamIds: readonly string[];
  readonly selectedTeamIds: readonly string[];
  /** La lista de equipos inscritos de la fase aún se está leyendo. */
  readonly loading: boolean;
}

export interface StageComposition {
  /** `false` solo en «fase existente» mientras la lista de inscritos no ha cargado. */
  readonly visible: boolean;
  readonly count: number;
  readonly overflows: boolean;
  readonly teamIds: readonly string[];
}

/**
 * Total de composición: unión **por identificador** de inscritos y
 * seleccionados, en el orden de los inscritos y después los seleccionados que
 * aún no estaban. Un equipo inscrito que vuelve a marcarse cuenta una sola vez
 * (RF-010) y la entrada no se modifica.
 */
export function stageComposition(input: StageCompositionInput): StageComposition {
  const teamIds = dedupeTeamIds([...input.assignedTeamIds, ...input.selectedTeamIds]);
  const count = teamIds.length;

  return {
    // ORD-14: en el alta no hay inscritos que cargar, así que la cifra nunca se
    // oculta; en «fase existente» no hay cifra parcial mientras carga la lista.
    visible: !(input.mode === 'existing' && input.loading),
    count,
    // ORD-8: por encima de 64 la cifra sigue siendo el total real.
    overflows: count > MAX_STAGE_TEAMS,
    teamIds,
  };
}

/**
 * Clave i18n y parámetros de la cifra: «N de 64 equipos» o, por encima del
 * máximo **por petición**, el total real sin el «de 64» (ORD-8, RF-011).
 */
export function compositionMessage(
  composition: StageComposition,
): {
  readonly key: 'stage.wizard.teamCount' | 'stage.wizard.teamCountOverflow';
  readonly params: { readonly count: number; readonly max?: number };
} {
  if (composition.overflows) {
    return {
      key: 'stage.wizard.teamCountOverflow',
      params: { count: composition.count },
    };
  }

  return {
    key: 'stage.wizard.teamCount',
    params: { count: composition.count, max: MAX_STAGE_TEAMS },
  };
}
