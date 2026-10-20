export interface StageTeamSummary {
  team_id: string;
  name: string;
  short_code: string;
}

export interface StageTeamsResponse {
  stage_id: string;
  version_id: string;
  assigned: StageTeamSummary[];
  unassigned: StageTeamSummary[];
}

export interface StageTeamAssignmentResponse {
  stage_id: string;
  version_id: string;
  team_ids: string[];
  assigned: string[];
  already_assigned: string[];
}

export type StageTeamAction =
  | 'assigned'
  | 'already_assigned'
  | 'removed'
  | 'forbidden'
  | 'not_found'
  | 'conflict'
  | 'invalid'
  | 'error';

function compareText(left: string, right: string): number {
  const a = left.toLocaleLowerCase();
  const b = right.toLocaleLowerCase();
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}

function isString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

/** Deduplicates ids while preserving the first occurrence order. */
export function dedupeTeamIds(ids: readonly string[]): string[] {
  return Array.from(new Set(ids));
}

export function normalizeStageTeamSummary(value: unknown): StageTeamSummary | null {
  if (!value || typeof value !== 'object') return null;
  const record = value as Record<string, unknown>;
  if (!isString(record.team_id) || !isString(record.name) || !isString(record.short_code)) {
    return null;
  }
  return {
    team_id: record.team_id,
    name: record.name,
    short_code: record.short_code,
  };
}

export function sortStageTeams(teams: readonly StageTeamSummary[]): StageTeamSummary[] {
  return [...teams].sort((left, right) => (
    compareText(left.name, right.name)
    || compareText(left.short_code, right.short_code)
    || compareText(left.team_id, right.team_id)
  ));
}

/**
 * Normalizes a GET response: drops malformed rows, deduplicates by team_id,
 * moves any team present in both arrays to `assigned`, and sorts both lists.
 */
export function normalizeStageTeamsResponse(value: unknown): StageTeamsResponse | null {
  if (!value || typeof value !== 'object') return null;
  const record = value as Record<string, unknown>;
  if (!isString(record.stage_id) || !isString(record.version_id)) return null;
  if (!Array.isArray(record.assigned) || !Array.isArray(record.unassigned)) return null;

  const assignedById = new Map<string, StageTeamSummary>();
  for (const item of record.assigned) {
    const team = normalizeStageTeamSummary(item);
    if (team) assignedById.set(team.team_id, team);
  }
  const unassignedById = new Map<string, StageTeamSummary>();
  for (const item of record.unassigned) {
    const team = normalizeStageTeamSummary(item);
    if (team && !assignedById.has(team.team_id)) unassignedById.set(team.team_id, team);
  }

  return {
    stage_id: record.stage_id,
    version_id: record.version_id,
    assigned: sortStageTeams([...assignedById.values()]),
    unassigned: sortStageTeams([...unassignedById.values()]),
  };
}

/** Teams that can still be selected for the stage. */
export function availableStageTeams(
  response: StageTeamsResponse | null | undefined,
): StageTeamSummary[] {
  return response ? sortStageTeams(response.unassigned) : [];
}

/** Keeps only ids still available, deduplicated, preserving the request order. */
export function pruneStageTeamSelection(
  selection: readonly string[],
  available: readonly StageTeamSummary[],
): string[] {
  const allowed = new Set(available.map((team) => team.team_id));
  return dedupeTeamIds(selection).filter((teamId) => allowed.has(teamId));
}

/** Maps the HTTP status of POST/DELETE to a UI outcome. */
export function stageTeamActionFromStatus(status: number): StageTeamAction {
  switch (status) {
    case 201:
      return 'assigned';
    case 200:
      return 'already_assigned';
    case 204:
      return 'removed';
    case 400:
    case 422:
      return 'invalid';
    case 403:
      return 'forbidden';
    case 404:
      return 'not_found';
    case 409:
      return 'conflict';
    default:
      return 'error';
  }
}

export function normalizeAssignmentResponse(
  value: unknown,
): StageTeamAssignmentResponse | null {
  if (!value || typeof value !== 'object') return null;
  const record = value as Record<string, unknown>;
  if (!isString(record.stage_id) || !isString(record.version_id)) return null;
  const arrays = ['team_ids', 'assigned', 'already_assigned'] as const;
  for (const key of arrays) {
    if (!Array.isArray(record[key]) || !record[key].every((item) => isString(item))) {
      return null;
    }
  }
  return {
    stage_id: record.stage_id,
    version_id: record.version_id,
    team_ids: dedupeTeamIds(record.team_ids as string[]),
    assigned: dedupeTeamIds(record.assigned as string[]),
    already_assigned: dedupeTeamIds(record.already_assigned as string[]),
  };
}

/** An assignment is "new" when the server reports at least one inserted team. */
export function assignmentOutcome(
  response: StageTeamAssignmentResponse | null | undefined,
): 'assigned' | 'already_assigned' {
  return response && response.assigned.length > 0 ? 'assigned' : 'already_assigned';
}
