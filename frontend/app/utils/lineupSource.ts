/**
 * Derivación pura de la fuente de precarga de formaciones entre segmentos
 * (spec 028, RF-001, RF-002, RF-006, RF-009, RF-010, RF-014).
 *
 * A partir de `tactical_lineups` (todos los segmentos del partido) y de los
 * `rosters`, y del `segment_id` seleccionado, devuelve, por equipo, la
 * formación y las asignaciones de rol/posición a precargar, o `null` si el
 * segmento seleccionado ya tiene formación persistida para ese equipo (RF-002)
 * o no existe ninguna fuente (RF-006).
 *
 * Es pura: no lee el reloj, la red, el almacenamiento ni el entorno, así que
 * las mismas entradas dan siempre el mismo resultado (RNF-004).
 */

export type LineupRole = 'starter' | 'substitute';

/** Fila de `tactical_lineups` tal como la publica la operación. */
export interface TacticalLineupRow {
  readonly segment_id: string;
  readonly segment_number: number;
  readonly team_id: string;
  readonly formation_code: string;
  readonly is_public?: boolean;
  readonly published_at?: string | null;
  readonly player_id: string | null;
  readonly is_starter: boolean;
  readonly position_slot: string | null;
  readonly first_name?: string | null;
  readonly last_name?: string | null;
}

/** Entrada de roster tal como la publica la operación. */
export interface RosterEntry {
  readonly roster_id: string;
  readonly player_id: string;
  readonly team_id: string;
}

/** Fuente de precarga para un equipo. */
export interface LineupSource {
  readonly source_segment_id: string;
  readonly formation_code: string;
  readonly roles: Record<string, LineupRole | ''>;
  readonly positions: Record<string, string | null>;
}

/** Mapa `team_id -> LineupSource | null`. */
export type LineupSourceByTeam = Record<string, LineupSource | null>;

/**
 * Deriva la fuente de precarga por equipo.
 *
 * - Si el segmento seleccionado ya tiene formación persistida para un equipo,
 *   devuelve `null` para ese equipo (RF-002, RF-010).
 * - Si no existe ninguna fuente para un equipo, devuelve `null` (RF-006).
 * - En otro caso, copia desde el segmento de menor número con formación
 *   persistida para ese equipo: `formation_code` y, por snapshot, rol/posición.
 *   Los rosters del equipo no presentes en la fuente se inicializan con rol
 *   vacío y posición nula.
 */
export function deriveLineupSource(
  tacticalLineups: ReadonlyArray<TacticalLineupRow>,
  rosters: ReadonlyArray<RosterEntry>,
  selectedSegmentId: string,
): LineupSourceByTeam {
  const result: LineupSourceByTeam = {};

  const teams = new Set<string>();
  for (const roster of rosters) {
    if (roster && typeof roster.team_id === 'string' && roster.team_id) teams.add(roster.team_id);
  }
  for (const row of tacticalLineups) {
    if (row && typeof row.team_id === 'string' && row.team_id) teams.add(row.team_id);
  }

  for (const teamId of teams) {
    const selectedRows = (tacticalLineups || []).filter(
      (row) => row && row.team_id === teamId && row.segment_id === selectedSegmentId,
    );
    if (selectedRows.length > 0) {
      result[teamId] = null;
      continue;
    }

    const teamRows = (tacticalLineups || []).filter((row) => row && row.team_id === teamId);
    if (teamRows.length === 0) {
      result[teamId] = null;
      continue;
    }

    // Agrupa por segmento y elige el de menor segment_number.
    const bySegment = new Map<string, { number: number; rows: TacticalLineupRow[] }>();
    for (const row of teamRows) {
      const seg = row.segment_id;
      if (!bySegment.has(seg)) {
        bySegment.set(seg, {
          number: Number.isFinite(row.segment_number) ? row.segment_number : 0,
          rows: [],
        });
      }
      const entry = bySegment.get(seg)!;
      entry.rows.push(row);
      if (Number.isFinite(row.segment_number) && row.segment_number < entry.number) {
        entry.number = row.segment_number;
      }
    }

    let sourceSegId: string | null = null;
    let sourceNumber = Infinity;
    for (const [seg, info] of bySegment) {
      if (info.number < sourceNumber) {
        sourceNumber = info.number;
        sourceSegId = seg;
      }
    }
    if (sourceSegId === null) {
      result[teamId] = null;
      continue;
    }

    const sourceRows = bySegment.get(sourceSegId)!.rows;

    let formationCode = '';
    for (const row of sourceRows) {
      if (row.formation_code) {
        formationCode = row.formation_code;
        break;
      }
    }

    const teamRosters = (rosters || []).filter((r) => r && r.team_id === teamId);
    const roles: Record<string, LineupRole | ''> = {};
    const positions: Record<string, string | null> = {};
    for (const roster of teamRosters) {
      roles[roster.roster_id] = '';
      positions[roster.roster_id] = null;
    }

    for (const row of sourceRows) {
      if (!row.player_id) continue;
      const roster = teamRosters.find((r) => r.player_id === row.player_id);
      if (!roster) continue;
      roles[roster.roster_id] = row.is_starter ? 'starter' : 'substitute';
      positions[roster.roster_id] = row.position_slot ?? null;
    }

    result[teamId] = {
      source_segment_id: sourceSegId,
      formation_code: formationCode,
      roles,
      positions,
    };
  }

  return result;
}