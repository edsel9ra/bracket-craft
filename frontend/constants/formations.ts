export type FormationCode = '4-3-3' | '4-4-2' | '3-5-2' | '4-2-3-1';

export interface FormationPoint {
  x: number;
  y: number;
}

export const FORMATION_OPTIONS: FormationCode[] = ['4-3-3', '4-4-2', '3-5-2', '4-2-3-1'];

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
};

export function formationSlots(formation: FormationCode | ''): string[] {
  return formation ? Object.keys(FORMATIONS_GRID[formation]) : [];
}

export function positionLabel(position: string): string {
  return position.replace('_', ' ');
}
