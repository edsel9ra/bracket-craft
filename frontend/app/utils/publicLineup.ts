/**
 * Funciones puras para la presentación pública de una formación táctica (spec 021).
 */

import type { FormationCode } from '../constants/formations.ts';
import { FORMATIONS_GRID, formationSlots } from '../constants/formations.ts';
import type { PublicLineupPlayer, PublicTeamLineup } from './publicTournament.ts';

export { formationSlots };

export type LineCode = 'gk' | 'def' | 'mid' | 'att';

const VALID_FORMATION_CODES: ReadonlySet<string> = new Set([
  '4-3-3',
  '4-4-2',
  '3-5-2',
  '4-2-3-1',
]);

export function isTacticalFormationValid(team: PublicTeamLineup): boolean {
  if (!team) return false;

  const code = team.formation_code;
  if (typeof code !== 'string' || !VALID_FORMATION_CODES.has(code)) return false;

  const slots = formationSlots(code as FormationCode);
  if (slots.length === 0) return false;

  const starters = Array.isArray(team.starters) ? team.starters : [];
  if (starters.length === 0) return false;
  if (starters.length !== slots.length) return false;

  const slotSet = new Set(slots);
  const occupied = new Set<string>();
  for (const player of starters) {
    const slot = player?.position_slot;
    if (typeof slot !== 'string' || slot.trim() === '') return false;
    if (!slotSet.has(slot)) return false;
    if (occupied.has(slot)) return false;
    occupied.add(slot);
  }

  if (occupied.size !== slotSet.size) return false;

  return true;
}

export function slotLine(formation: FormationCode | string, slot: string): LineCode {
  if (slot === 'GK') return 'gk';

  const grid = FORMATIONS_GRID[formation as FormationCode];
  const point = grid ? grid[slot] : undefined;
  const y = point ? point.y : 0;

  if (y >= 60) return 'def';
  if (y >= 45) return 'mid';
  return 'att';
}

export function textualFormationLines(
  team: PublicTeamLineup,
): { line: LineCode; players: PublicLineupPlayer[] }[] {
  if (!isTacticalFormationValid(team)) return [];

  const code = team.formation_code as FormationCode;
  const grid = FORMATIONS_GRID[code];

  const groups: Record<LineCode, PublicLineupPlayer[]> = {
    gk: [],
    def: [],
    mid: [],
    att: [],
  };

  for (const player of team.starters) {
    const slot = player.position_slot as string;
    const line = slotLine(code, slot);
    groups[line].push(player);
  }

  const order: LineCode[] = ['gk', 'def', 'mid', 'att'];

  const result: { line: LineCode; players: PublicLineupPlayer[] }[] = [];
  for (const line of order) {
    const players = groups[line];
    if (players.length === 0) continue;
    const sorted = [...players].sort((a, b) => {
      const xa = grid[a.position_slot as string]?.x ?? 0;
      const xb = grid[b.position_slot as string]?.x ?? 0;
      return xa - xb;
    });
    result.push({ line, players: sorted });
  }

  return result;
}

export function playerInitials(player: PublicLineupPlayer): string {
  if (!player) return '';
  const first = typeof player.first_name === 'string' ? player.first_name.trim() : '';
  const last = typeof player.last_name === 'string' ? player.last_name.trim() : '';
  const a = first ? first.charAt(0).toUpperCase() : '';
  const b = last ? last.charAt(0).toUpperCase() : '';
  return `${a}${b}`;
}
