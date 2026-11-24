export type GameFormat = '5v5' | '7v7' | '9v9' | '11v11';

export const DEFAULT_GAME_FORMAT: GameFormat = '11v11';

// Spec 044 (RF-001): mismo catálogo cerrado que backend/app/modules/rule_contract.py.
export const FORMATIONS_BY_GAME_FORMAT = {
  '5v5': ['1-2-1', '2-1-1', '2-2'],
  '7v7': ['2-3-1', '3-2-1', '3-1-2'],
  '9v9': ['3-3-2', '3-4-1', '4-3-1'],
  '11v11': ['4-3-3', '4-4-2', '3-5-2', '4-2-3-1'],
} as const satisfies Record<GameFormat, readonly string[]>;

export type FormationCode = (typeof FORMATIONS_BY_GAME_FORMAT)[GameFormat][number];

export interface FormationPoint {
  x: number;
  y: number;
}

export const FORMATION_OPTIONS: FormationCode[] = [...FORMATIONS_BY_GAME_FORMAT['11v11']];

export const FORMATIONS_GRID: Record<FormationCode, Record<string, FormationPoint>> = {
  '4-3-3': {
    GK: { x: 50, y: 88 }, LB: { x: 15, y: 70 }, LCB: { x: 38, y: 73 }, RCB: { x: 62, y: 73 }, RB: { x: 85, y: 70 },
    CM_L: { x: 29, y: 50 }, CM: { x: 50, y: 54 }, CM_R: { x: 71, y: 50 }, LW: { x: 20, y: 23 }, ST: { x: 50, y: 17 }, RW: { x: 80, y: 23 },
  },
  '4-4-2': {
    GK: { x: 50, y: 88 }, LB: { x: 15, y: 70 }, LCB: { x: 38, y: 73 }, RCB: { x: 62, y: 73 }, RB: { x: 85, y: 70 },
    LM: { x: 17, y: 47 }, LCM: { x: 38, y: 50 }, RCM: { x: 62, y: 50 }, RM: { x: 83, y: 47 }, ST_L: { x: 39, y: 20 }, ST_R: { x: 61, y: 20 },
  },
  '3-5-2': {
    GK: { x: 50, y: 88 }, LCB: { x: 27, y: 73 }, CB: { x: 50, y: 75 }, RCB: { x: 73, y: 73 }, LWB: { x: 12, y: 48 },
    LCM: { x: 31, y: 51 }, CM: { x: 50, y: 54 }, RCM: { x: 69, y: 51 }, RWB: { x: 88, y: 48 }, ST_L: { x: 39, y: 20 }, ST_R: { x: 61, y: 20 },
  },
  '4-2-3-1': {
    GK: { x: 50, y: 88 }, LB: { x: 15, y: 70 }, LCB: { x: 38, y: 73 }, RCB: { x: 62, y: 73 }, RB: { x: 85, y: 70 },
    CDM_L: { x: 39, y: 57 }, CDM_R: { x: 61, y: 57 }, LW: { x: 20, y: 33 }, CAM: { x: 50, y: 35 }, RW: { x: 80, y: 33 }, ST: { x: 50, y: 17 },
  },
  '1-2-1': {
    GK: { x: 50, y: 88 }, CB: { x: 50, y: 70 }, LM: { x: 22, y: 48 }, RM: { x: 78, y: 48 }, ST: { x: 50, y: 20 },
  },
  '2-1-1': {
    GK: { x: 50, y: 88 }, LCB: { x: 32, y: 70 }, RCB: { x: 68, y: 70 }, CM: { x: 50, y: 50 }, ST: { x: 50, y: 20 },
  },
  '2-2': {
    GK: { x: 50, y: 88 }, LCB: { x: 32, y: 70 }, RCB: { x: 68, y: 70 }, ST_L: { x: 35, y: 25 }, ST_R: { x: 65, y: 25 },
  },
  '2-3-1': {
    GK: { x: 50, y: 88 }, LCB: { x: 32, y: 72 }, RCB: { x: 68, y: 72 },
    LM: { x: 18, y: 48 }, CM: { x: 50, y: 52 }, RM: { x: 82, y: 48 }, ST: { x: 50, y: 20 },
  },
  '3-2-1': {
    GK: { x: 50, y: 88 }, LCB: { x: 24, y: 72 }, CB: { x: 50, y: 74 }, RCB: { x: 76, y: 72 },
    LCM: { x: 35, y: 50 }, RCM: { x: 65, y: 50 }, ST: { x: 50, y: 20 },
  },
  '3-1-2': {
    GK: { x: 50, y: 88 }, LCB: { x: 24, y: 72 }, CB: { x: 50, y: 74 }, RCB: { x: 76, y: 72 },
    CM: { x: 50, y: 52 }, ST_L: { x: 35, y: 22 }, ST_R: { x: 65, y: 22 },
  },
  '3-3-2': {
    GK: { x: 50, y: 88 }, LCB: { x: 24, y: 72 }, CB: { x: 50, y: 74 }, RCB: { x: 76, y: 72 },
    LM: { x: 18, y: 48 }, CM: { x: 50, y: 52 }, RM: { x: 82, y: 48 }, ST_L: { x: 38, y: 20 }, ST_R: { x: 62, y: 20 },
  },
  '3-4-1': {
    GK: { x: 50, y: 88 }, LCB: { x: 24, y: 72 }, CB: { x: 50, y: 74 }, RCB: { x: 76, y: 72 },
    LM: { x: 14, y: 48 }, LCM: { x: 38, y: 51 }, RCM: { x: 62, y: 51 }, RM: { x: 86, y: 48 }, ST: { x: 50, y: 20 },
  },
  '4-3-1': {
    GK: { x: 50, y: 88 }, LB: { x: 15, y: 70 }, LCB: { x: 38, y: 73 }, RCB: { x: 62, y: 73 }, RB: { x: 85, y: 70 },
    CM_L: { x: 29, y: 50 }, CM: { x: 50, y: 54 }, CM_R: { x: 71, y: 50 }, ST: { x: 50, y: 20 },
  },
};

const GAME_FORMAT_BY_FORMATION: ReadonlyMap<string, GameFormat> = new Map(
  (Object.entries(FORMATIONS_BY_GAME_FORMAT) as [GameFormat, readonly FormationCode[]][]).flatMap(
    ([format, codes]) => codes.map((code) => [code, format] as const),
  ),
);

export function isGameFormat(value: unknown): value is GameFormat {
  return typeof value === 'string' && Object.hasOwn(FORMATIONS_BY_GAME_FORMAT, value);
}

/** Formaciones de una modalidad; ausente o desconocida se lee como 11v11 (spec 044). */
export function formationOptionsFor(format: string | null | undefined): FormationCode[] {
  return [...FORMATIONS_BY_GAME_FORMAT[isGameFormat(format) ? format : DEFAULT_GAME_FORMAT]];
}

export function formationGameFormat(code: string | null | undefined): GameFormat | null {
  return (code && GAME_FORMAT_BY_FORMATION.get(code)) || null;
}

export function formationSlots(formation: FormationCode | ''): string[] {
  return formation ? Object.keys(FORMATIONS_GRID[formation]) : [];
}
