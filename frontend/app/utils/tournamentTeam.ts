/** Utilidades puras de «Equipo del torneo» (spec 049, RF-012, RF-012a). */

export const OPERATING_ROLES: readonly string[] = ['owner', 'administrator', 'operator'];

export interface TournamentTeamMember {
  organization_user_id: string;
  full_name: string;
  organization_role_code: string;
  role_code: 'tournament_operator';
  is_active: boolean;
  adds_permissions: boolean;
  assigned_at: string;
}

export interface OrganizationMember {
  organization_user_id: string;
  full_name: string;
  is_active: boolean;
  role_code: string;
}

export interface OperationAccess {
  organization_user_id: string;
  role_code: string;
  permissions: string[];
  operated_tournament_ids?: string[];
}

interface ApiFailure {
  status?: number;
  statusCode?: number;
  data?: { detail?: unknown };
}

/** Misma regla que el servidor: rol de organización, oficial asignado o operador del torneo del partido. */
export function canOperateMatch(
  access: OperationAccess | null | undefined,
  match: { tournament_id: string } | null | undefined,
  officials: ReadonlyArray<{ organization_user_id: string }>,
): boolean {
  if (!access) return false;
  if (match && access.operated_tournament_ids?.includes(match.tournament_id)) return true;
  if (!access.permissions.includes('CLOSE_MATCH_REPORT')) return false;
  if (OPERATING_ROLES.includes(access.role_code)) return true;
  return Boolean(access.organization_user_id && officials.some((official) => official.organization_user_id === access.organization_user_id));
}

const byName = <T extends { full_name: string; organization_user_id: string }>(left: T, right: T) =>
  left.full_name.localeCompare(right.full_name, 'es', { sensitivity: 'base' })
  || (left.organization_user_id < right.organization_user_id ? -1 : left.organization_user_id > right.organization_user_id ? 1 : 0);

export function sortTeam(team: readonly TournamentTeamMember[]): TournamentTeamMember[] {
  return [...team].sort(byName);
}

/** Miembros activos aún sin asignar, sin campos que no sean necesarios (nunca el correo). */
export function assignableMembers(members: readonly OrganizationMember[], team: readonly TournamentTeamMember[]): OrganizationMember[] {
  const assigned = new Set(team.map((item) => item.organization_user_id));
  return members
    .filter((item) => item.is_active && !assigned.has(item.organization_user_id))
    .map(({ organization_user_id, full_name, is_active, role_code }) => ({ organization_user_id, full_name, is_active, role_code }))
    .sort(byName);
}

const NOT_FOUND_KEYS: Record<string, string> = {
  'Torneo no encontrado': 'tournamentTeam.error.tournament',
  'Miembro no encontrado': 'tournamentTeam.error.member',
  'Asignación no encontrada': 'tournamentTeam.error.assignment',
};

export function tournamentTeamErrorKey(cause: unknown): string {
  const failure = (cause ?? {}) as ApiFailure;
  const status = Number(failure.statusCode ?? failure.status);
  if (status === 403) return 'tournamentTeam.error.forbidden';
  if (status === 404) return NOT_FOUND_KEYS[String(failure.data?.detail)] ?? 'tournamentTeam.error.tournament';
  return 'tournamentTeam.error.generic';
}
