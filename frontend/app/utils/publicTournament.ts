import type { FormationCode } from '../constants/formations';
import type { StageFormat } from '../constants/stageFormats';

export interface PublicStage {
  id: string;
  name: string;
  stage_type: StageFormat;
  stage_order: number;
}

export interface PublicTournamentTeam {
  team_id: string;
  name: string;
  short_code: string;
  crest_url: string | null;
}

export interface PublicTournament {
  id: string;
  name: string;
  season: string;
  start_date: string;
  status: string;
  stages: PublicStage[];
  /** Additive list of enrolled teams (empty when the tournament has none). */
  teams?: PublicTournamentTeam[];
}

export interface PublicStanding {
  stage_id: string;
  stage_name: string;
  stage_order: number;
  group_id: string | null;
  group_name: string | null;
  team_id: string;
  team_name: string;
  short_code: string;
  played: number;
  won: number;
  drawn: number;
  lost: number;
  goals_for: number;
  goals_against: number;
  goal_difference: number;
  points: number;
  fair_play_points: number;
  rank: number;
  crest_url: string | null;
}

export interface PublicLineupPlayer {
  player_id: string;
  first_name: string;
  last_name: string;
  dorsal_number: number | null;
  role: 'starter' | 'substitute';
  position_slot: string | null;
  photo_url: string | null;
}

export interface PublicTeamLineup {
  team_id: string;
  team_name: string;
  formation_code: FormationCode | null;
  segment_number: number | null;
  crest_url: string | null;
  starters: PublicLineupPlayer[];
  substitutes: PublicLineupPlayer[];
}

export interface PublicMatchLineup {
  home: PublicTeamLineup | null;
  away: PublicTeamLineup | null;
}

export interface PublicMatch {
  rectified_at: string | null;
  id: string;
  stage_id: string;
  stage_name: string;
  stage_order: number;
  group_id: string | null;
  group_name: string | null;
  bracket_code: string | null;
  matchday: number | null;
  match_date: string | null;
  home_team_id: string | null;
  home_team_name: string | null;
  home_team_short_code: string | null;
  away_team_id: string | null;
  home_team_crest_url: string | null;
  away_team_name: string | null;
  away_team_short_code: string | null;
  away_team_crest_url: string | null;
  home_score: number | null;
  away_score: number | null;
  home_penalties: number | null;
  away_penalties: number | null;
  status: string;
  resolution_type: string | null;
  winner_team_id: string | null;
  lineup: PublicMatchLineup | null;
  home_score_regular?: number | null;
  away_score_regular?: number | null;
  // F1 (036): en `live` la lectura vigente añade reloj y provisionalidad.
  is_provisional?: true;
  clock_segment_number?: number | null;
  clock_elapsed_seconds?: number | null;
  clock_state?: 'not_started' | 'running' | 'paused';
  clock_observed_at?: string | null;
}

/**
 * Proyección cerrada del partido `suspended` (036, F1): catorce claves, sin
 * metadatos de fase, llave, fecha, escudos ni alineación. El contexto de la
 * consulta de fase/grupo vive fuera del objeto, en `PublicMatchEntry`.
 */
export interface SuspendedPublicMatch {
  id: string;
  tournament_id: string;
  home_team_id: string;
  home_team_name: string;
  away_team_id: string;
  away_team_name: string;
  status: 'suspended';
  home_score: number;
  away_score: number;
  is_provisional: true;
  clock_segment_number: number | null;
  clock_elapsed_seconds: number | null;
  clock_state: 'not_started' | 'paused';
  clock_observed_at: string;
}

export type PublicMatchState = PublicMatch | SuspendedPublicMatch;

export function isSuspendedPublicMatch(
  match: PublicMatchState | null | undefined,
): match is SuspendedPublicMatch {
  return !!match && match.status === 'suspended';
}

const SUSPENDED_CLOCK_STATES = new Set(['not_started', 'paused']);

/**
 * Valida la forma recibida sin exigir campos que el suspendido no publica:
 * un `suspended` necesita sus catorce claves; el resto conserva la forma
 * clásica. Un objeto inválido se descarta, no se rellena con campos inventados.
 */
export function normalizePublicMatchState(value: unknown): PublicMatchState | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  if (raw.status === 'suspended') {
    for (const key of [
      'id', 'tournament_id', 'home_team_id', 'home_team_name',
      'away_team_id', 'away_team_name',
    ] as const) {
      if (typeof raw[key] !== 'string' || !(raw[key] as string)) return null;
    }
    if (typeof raw.home_score !== 'number' || typeof raw.away_score !== 'number') return null;
    if (raw.is_provisional !== true) return null;
    if (typeof raw.clock_state !== 'string' || !SUSPENDED_CLOCK_STATES.has(raw.clock_state)) return null;
    if (raw.clock_segment_number !== null && typeof raw.clock_segment_number !== 'number') return null;
    if (raw.clock_elapsed_seconds !== null && typeof raw.clock_elapsed_seconds !== 'number') return null;
    if (typeof raw.clock_observed_at !== 'string') return null;
    return value as SuspendedPublicMatch;
  }
  if (typeof raw.id !== 'string' || typeof raw.status !== 'string') return null;
  return value as PublicMatch;
}

export function normalizePublicMatchPage(value: unknown): PublicMatchState[] {
  if (!Array.isArray(value)) return [];
  const matches: PublicMatchState[] = [];
  for (const item of value) {
    const match = normalizePublicMatchState(item);
    if (match) matches.push(match);
  }
  return matches;
}

/**
 * Entrada de la lista de partidos: el contexto de fase/grupo procede de la
 * consulta que lo trajo —nunca de campos fabricados sobre el objeto— y se
 * conserva al cambiar de estado, así la misma tarjeta no se duplica ni desaparece.
 */
export interface PublicMatchEntry {
  match: PublicMatchState;
  stageId: string | null;
  groupId: string | null;
}

/**
 * Fusiona una página consultada con las entradas vigentes: un `id` ya presente
 * reemplaza su dato en la posición que ocupaba (cambio de estado sin duplicar);
 * los nuevos se anexan con el contexto de la consulta que los trajo.
 */
export function mergeMatchEntries(
  existing: readonly PublicMatchEntry[],
  page: readonly PublicMatchState[],
  stageId: string | null,
  groupId: string | null,
): PublicMatchEntry[] {
  const entries = existing.map((entry) => ({ ...entry }));
  const indexById = new Map(entries.map((entry, index) => [entry.match.id, index]));
  for (const match of page) {
    const index = indexById.get(match.id);
    // El clásico publica su fase y grupo; el suspendido solo conserva el
    // contexto de la consulta que lo trajo (o el que ya tenía).
    const context = isSuspendedPublicMatch(match)
      ? { stageId, groupId }
      : { stageId: match.stage_id, groupId: match.group_id };
    if (index === undefined) {
      indexById.set(match.id, entries.length);
      entries.push({ match, ...context });
    } else {
      const entry = entries[index]!;
      entries[index] = {
        match,
        stageId: isSuspendedPublicMatch(match) ? entry.stageId : match.stage_id,
        groupId: isSuspendedPublicMatch(match) ? entry.groupId : match.group_id,
      };
    }
  }
  return entries;
}

export function matchEntriesForStage(
  entries: readonly PublicMatchEntry[],
  stageId: string,
): PublicMatchState[] {
  return entries.filter((entry) => entry.stageId === stageId).map((entry) => entry.match);
}

export function matchEntriesForGroup(
  entries: readonly PublicMatchEntry[],
  stageId: string,
  groupId: string | null | undefined,
): PublicMatchState[] {
  return entries
    .filter((entry) => {
      if (entry.stageId !== stageId) return false;
      if (groupId != null) return entry.groupId === groupId;
      return true;
    })
    .map((entry) => entry.match);
}

/** El suspendido no publica llave de eliminatoria: nunca entra al bracket. */
export function bracketEligibleMatches(
  matches: readonly PublicMatchState[],
): PublicMatch[] {
  return matches.filter(
    (match): match is PublicMatch => !isSuspendedPublicMatch(match),
  );
}

/** Marcador/reloj del suspendido: detenido o sin iniciar, siempre provisional. */
export function formatSuspendedClock(match: SuspendedPublicMatch): string | null {
  const seconds = match.clock_elapsed_seconds;
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return null;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`;
}

export type PublicStagePresentation = 'standings' | 'bracket' | 'current';

export function getPublicStagePresentation(stageType: StageFormat): PublicStagePresentation {
  if (stageType === 'single_elimination') return 'bracket';
  if (stageType === 'double_elimination') return 'bracket';
  return 'standings';
}

export function sortPublicStages(stages: readonly PublicStage[]): PublicStage[] {
  return [...stages].sort((left, right) => (
    left.stage_order - right.stage_order || left.id.localeCompare(right.id)
  ));
}

export function usesCurrentDoubleEliminationFormat(stages: readonly PublicStage[]): boolean {
  return stages.length > 0 && stages.every((stage) => stage.stage_type === 'double_elimination');
}

export interface PublicGroup {
  groupId: string | null;
  groupName: string | null;
}

export interface PublicSelection {
  stageId: string | null;
  groupId: string | null;
}

function isStanding(value: unknown): value is PublicStanding {
  return typeof value === 'object' && value !== null
    && 'stage_id' in (value as Record<string, unknown>)
    && 'group_id' in (value as Record<string, unknown>);
}

/**
 * Normaliza la selección de fase y grupo a partir de la dirección.
 * Acepta tanto (stages, stageParam, groupParam) como
 * (stages, standings, stageParam, groupParam) para poder validar el grupo.
 */
export function normalizePublicSelection(
  stages: readonly PublicStage[] | null | undefined,
  second: unknown,
  third?: unknown,
  fourth?: unknown,
): PublicSelection {
  const sorted = sortPublicStages(stages ?? []);
  if (sorted.length === 0) return { stageId: null, groupId: null };

  let standings: readonly PublicStanding[] | null = null;
  let stageParam: string | null | undefined;
  let groupParam: string | null | undefined;
  if (Array.isArray(second) && (second.length === 0 || isStanding(second[0]))) {
    standings = second as readonly PublicStanding[];
    stageParam = third as string | null | undefined;
    groupParam = fourth as string | null | undefined;
  } else {
    stageParam = second as string | null | undefined;
    groupParam = third as string | null | undefined;
  }

  const stageIds = new Set(sorted.map((stage) => stage.id));
  const stageId = stageParam != null && stageIds.has(stageParam)
    ? stageParam
    : (sorted[0] as PublicStage).id;

  // Cuando la fase se restaura a la primera (inválida), se descarta el grupo.
  const stageWasInvalid = !(stageParam != null && stageIds.has(stageParam));
  if (stageWasInvalid) return { stageId, groupId: null };

  if (groupParam == null) return { stageId, groupId: null };

  if (standings && standings.length > 0) {
    const groups = groupsOfStage(standings, stageId);
    const groupIds = new Set(groups.map((group) => group.groupId));
    if (!groupIds.has(groupParam)) return { stageId, groupId: null };
  }

  return { stageId, groupId: groupParam };
}

export interface PublicStatsScope {
  stageId: string | null;
  groupId: string | null;
}

/**
 * Resuelve el ámbito de las tablas de estadísticas públicas (spec 022, RF-021).
 *
 * El valor por defecto es el **torneo completo**: sin `stage_id` ni `group_id`
 * y sin preseleccionar la primera fase. Una fase solo entra en el ámbito cuando
 * el usuario la elige, y un grupo solo vale dentro de una fase elegida: sin
 * fase, el grupo se descarta aunque llegue en la dirección.
 */
export function resolvePublicStatsScope(
  stages: readonly PublicStage[] | null | undefined,
  stageParam: string | null | undefined,
  groupParam?: string | null | undefined,
  standings?: readonly PublicStanding[] | null,
): PublicStatsScope {
  const stageIds = new Set(sortPublicStages(stages ?? []).map((stage) => stage.id));
  const stageId = stageParam != null && stageIds.has(stageParam) ? stageParam : null;
  if (stageId === null) return { stageId: null, groupId: null };

  if (groupParam == null || groupParam === '') return { stageId, groupId: null };

  if (standings && standings.length > 0) {
    const groupIds = new Set(groupsOfStage(standings, stageId).map((group) => group.groupId));
    if (!groupIds.has(groupParam)) return { stageId, groupId: null };
  }

  return { stageId, groupId: groupParam };
}

export function groupsOfStage(
  standings: readonly PublicStanding[],
  stageId: string,
): PublicGroup[] {
  const groups: PublicGroup[] = [];
  const seen = new Set<string | null>();
  for (const standing of standings) {
    if (standing.stage_id !== stageId) continue;
    const key = standing.group_id;
    if (seen.has(key)) continue;
    seen.add(key);
    groups.push({ groupId: standing.group_id, groupName: standing.group_name });
  }
  return groups;
}

export function standingsForGroup(
  standings: readonly PublicStanding[],
  stageId: string,
  groupId: string | null | undefined,
): PublicStanding[] {
  return standings.filter((standing) => {
    if (standing.stage_id !== stageId) return false;
    if (groupId != null) return standing.group_id === groupId;
    return true;
  });
}

export function matchesForGroup(
  matches: readonly PublicMatch[],
  stageId: string,
  groupId: string | null | undefined,
): PublicMatch[] {
  return matches.filter((match) => {
    if (match.stage_id !== stageId) return false;
    if (groupId != null) return match.group_id === groupId;
    return true;
  });
}

export function resolveMatchOutcomeLabel(match: PublicMatch | null | undefined): (
  | 'walkover'
  | 'penalties'
  | 'extra_time'
  | 'administrative'
  | null
) {
  if (!match) return null;

  const resolutionType = match.resolution_type;
  if (resolutionType === 'walkover') return 'walkover';
  if (resolutionType === 'administrative') return 'administrative';
  if (resolutionType === 'penalties') return 'penalties';
  if (resolutionType === 'extra_time') return 'extra_time';

  if (match.home_penalties != null && match.away_penalties != null) return 'penalties';

  const regularHome = match.home_score_regular;
  const regularAway = match.away_score_regular;
  const finalHome = match.home_score;
  const finalAway = match.away_score;
  if (
    regularHome != null && regularAway != null &&
    finalHome != null && finalAway != null &&
    (regularHome !== finalHome || regularAway !== finalAway)
  ) {
    return 'extra_time';
  }

  if (match.status === 'administrative_resolution') return 'administrative';

  return null;
}

export function combinationKey(
  stageId: string | null | undefined,
  groupId: string | null | undefined,
): string {
  return `${stageId ?? ''}:${groupId ?? ''}`;
}

export interface CombinationPaginationEntry {
  offset: number;
  hasMore: boolean;
}

function readCombinationEntry(pagination: unknown, key: string): unknown {
  if (pagination instanceof Map) return (pagination as Map<string, unknown>).get(key);
  if (pagination && typeof pagination === 'object') {
    const record = pagination as Record<string, unknown>;
    if (key in record) return record[key];
  }
  return undefined;
}

export function hasMoreForCombination(pagination: unknown, key: string): boolean {
  const entry = readCombinationEntry(pagination, key);
  if (typeof entry === 'boolean') return entry;
  if (entry && typeof entry === 'object') {
    const value = (entry as { hasMore?: unknown }).hasMore;
    if (typeof value === 'boolean') return value;
  }
  return false;
}

export function nextOffsetForCombination(...args: unknown[]): number {
  const first = args[0];
  if (typeof first === 'number') {
    const pageSize = typeof args[1] === 'number' ? (args[1] as number) : 0;
    return first + pageSize;
  }
  const key = args[1];
  if (typeof key !== 'string') return 0;
  const entry = readCombinationEntry(first, key);
  if (typeof entry === 'number') return entry;
  if (entry && typeof entry === 'object') {
    const obj = entry as { offset?: unknown; nextOffset?: unknown };
    if (typeof obj.offset === 'number') return obj.offset;
    if (typeof obj.nextOffset === 'number') return obj.nextOffset;
  }
  return 0;
}