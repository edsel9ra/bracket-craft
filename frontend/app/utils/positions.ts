/**
 * Única fuente de los nombres cortos de las posiciones (RF-027, RF-028).
 *
 * El **código** es el valor contractual: es lo que viaja a la API y a la base
 * de datos y no se localiza. Solo se localiza lo que se muestra, y cada uno de
 * los 23 códigos del catálogo cerrado de formaciones declara aquí su **clave
 * i18n** estable (`positions.<CODE>`) y el lado que ocupa (`left`, `right` o
 * `null`). Este archivo no contiene ningún texto traducible: los catálogos es/en
 * viven solo en `composables/useI18n.ts`.
 *
 * `positionLabel` es pura: recibe el código y el traductor existente (`t`) y no
 * toca DOM, almacenamiento ni reloj. Si el código no está en el catálogo —o su
 * clave no existe en el idioma activo— devuelve el código recibido tal cual,
 * sin inventar texto ni devolver una etiqueta vacía.
 */

export type PositionSide = 'left' | 'right' | null;

export interface PositionDefinition {
  readonly key: string;
  readonly side: PositionSide;
}

export type PositionCode =
  | 'GK'
  | 'CB'
  | 'LCB'
  | 'RCB'
  | 'LB'
  | 'RB'
  | 'LWB'
  | 'RWB'
  | 'CDM_L'
  | 'CDM_R'
  | 'CM'
  | 'CM_L'
  | 'CM_R'
  | 'LCM'
  | 'RCM'
  | 'LM'
  | 'RM'
  | 'CAM'
  | 'LW'
  | 'RW'
  | 'ST'
  | 'ST_L'
  | 'ST_R';

/** Los 23 códigos del catálogo cerrado, en el orden del apéndice C. */
export const POSITION_CODES: readonly PositionCode[] = [
  'GK',
  'CB',
  'LCB',
  'RCB',
  'LB',
  'RB',
  'LWB',
  'RWB',
  'CDM_L',
  'CDM_R',
  'CM',
  'CM_L',
  'CM_R',
  'LCM',
  'RCM',
  'LM',
  'RM',
  'CAM',
  'LW',
  'RW',
  'ST',
  'ST_L',
  'ST_R',
];

export const POSITION_DEFINITIONS: Record<PositionCode, PositionDefinition> = {
  GK: { key: 'positions.GK', side: null },
  CB: { key: 'positions.CB', side: null },
  LCB: { key: 'positions.LCB', side: 'left' },
  RCB: { key: 'positions.RCB', side: 'right' },
  LB: { key: 'positions.LB', side: 'left' },
  RB: { key: 'positions.RB', side: 'right' },
  LWB: { key: 'positions.LWB', side: 'left' },
  RWB: { key: 'positions.RWB', side: 'right' },
  CDM_L: { key: 'positions.CDM_L', side: 'left' },
  CDM_R: { key: 'positions.CDM_R', side: 'right' },
  CM: { key: 'positions.CM', side: null },
  CM_L: { key: 'positions.CM_L', side: 'left' },
  CM_R: { key: 'positions.CM_R', side: 'right' },
  LCM: { key: 'positions.LCM', side: 'left' },
  RCM: { key: 'positions.RCM', side: 'right' },
  LM: { key: 'positions.LM', side: 'left' },
  RM: { key: 'positions.RM', side: 'right' },
  CAM: { key: 'positions.CAM', side: null },
  LW: { key: 'positions.LW', side: 'left' },
  RW: { key: 'positions.RW', side: 'right' },
  ST: { key: 'positions.ST', side: null },
  ST_L: { key: 'positions.ST_L', side: 'left' },
  ST_R: { key: 'positions.ST_R', side: 'right' },
};

/** Traductor existente (`t` de `useI18n`): clave i18n → texto del idioma activo. */
export type PositionTranslator = (key: string) => string;

function definitionOf(code: string | null | undefined): PositionDefinition | null {
  if (typeof code !== 'string') return null;
  const candidate = code.trim();
  if (!candidate) return null;
  return Object.prototype.hasOwnProperty.call(POSITION_DEFINITIONS, candidate)
    ? POSITION_DEFINITIONS[candidate as PositionCode]
    : null;
}

/**
 * Clave i18n de un código conocido; el propio código si es desconocido y una
 * cadena vacía si no hay código. Así `t(positionKey(code))` nunca inventa texto.
 */
export function positionKey(code: string | null | undefined): string {
  if (typeof code !== 'string') return '';
  const definition = definitionOf(code);
  if (definition) return definition.key;
  return code.trim() ? code : '';
}

/** Lado que declara el código; `null` si no declara ninguno o es desconocido. */
export function positionSide(code: string | null | undefined): PositionSide {
  return definitionOf(code)?.side ?? null;
}

/**
 * Nombre corto localizado a través del traductor existente. Un código
 * desconocido o una clave ausente se muestran tal cual (RF-028).
 *
 * `t()` devuelve la propia clave cuando no existe en el catálogo; en ese caso
 * esta función devuelve el código recibido, no la clave interna.
 */
export function positionLabel(
  code: string | null | undefined,
  translate: PositionTranslator,
): string {
  if (typeof code !== 'string') return '';
  const definition = definitionOf(code);
  if (!definition) return code.trim() ? code : '';
  const label = translate(definition.key);
  return label && label !== definition.key ? label : code;
}
