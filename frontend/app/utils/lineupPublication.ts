/**
 * Formaciones publicadas que retiraría un guardado (spec 045, RF-003).
 *
 * Aplica la misma definición que el servidor (DA-2): la alineación de un equipo
 * es su formación y, por jugador convocado, su rol y su posición; los minutos y
 * el orden no cuentan. Solo anticipa el resultado con el estado cargado: el
 * servidor decide al guardar (RF-008).
 */

export interface PublicationRow {
  readonly team_id: string;
  readonly formation_code: string;
  readonly is_public?: boolean;
  readonly player_id: string | null;
  readonly is_starter: boolean;
  readonly position_slot: string | null;
}

export interface EditorLineupEntry {
  readonly roster_id: string;
  readonly role: string;
  readonly position_slot: string | null;
}

export interface PublicationRoster {
  readonly roster_id: string;
  readonly player_id: string;
  readonly team_id: string;
}

function signature(formation: string, players: string[]): string {
  return JSON.stringify([formation, [...players].sort()]);
}

function player(playerId: string, role: string, positionSlot: string | null): string {
  return `${playerId}|${role}|${positionSlot ?? ''}`;
}

/** Equipos publicados cuya alineación cambia o desaparece, en orden de aparición. */
export function withdrawnPublicTeams(
  rows: readonly PublicationRow[],
  formations: Readonly<Record<string, string>>,
  entries: readonly EditorLineupEntry[],
  rosters: readonly PublicationRoster[],
): string[] {
  const storedFormation = new Map<string, string>();
  const storedPlayers = new Map<string, string[]>();
  const publicTeams: string[] = [];
  for (const row of rows) {
    storedFormation.set(row.team_id, row.formation_code);
    if (row.is_public && !publicTeams.includes(row.team_id)) publicTeams.push(row.team_id);
    if (row.player_id) {
      const players = storedPlayers.get(row.team_id) ?? [];
      players.push(player(row.player_id, row.is_starter ? 'starter' : 'substitute', row.position_slot));
      storedPlayers.set(row.team_id, players);
    }
  }
  const rosterById = new Map(rosters.map((roster) => [roster.roster_id, roster]));
  const editorPlayers = new Map<string, string[]>();
  for (const entry of entries) {
    const roster = rosterById.get(entry.roster_id);
    if (!roster) continue;
    const players = editorPlayers.get(roster.team_id) ?? [];
    players.push(player(roster.player_id, entry.role, entry.position_slot));
    editorPlayers.set(roster.team_id, players);
  }
  return publicTeams.filter((teamId) => {
    const formation = formations[teamId];
    if (!formation) return true;
    return signature(storedFormation.get(teamId) ?? '', storedPlayers.get(teamId) ?? [])
      !== signature(formation, editorPlayers.get(teamId) ?? []);
  });
}
