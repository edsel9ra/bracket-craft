/** Utilidades puras de la auditoría organizacional (spec 041). */

export const AUDIT_ACTIONS = [
  'CLOSE_MATCH_REPORT', 'ADMINISTRATIVE_MATCH_RESOLUTION', 'INTERRUPT_MATCH_SEGMENT', 'MATCH_LIVE_COMMAND',
  'SAVE_MATCH_LINEUP', 'PUBLISH_MATCH_LINEUP', 'UNPUBLISH_MATCH_LINEUP', 'ASSIGN_MATCH_OFFICIAL',
  'REMOVE_MATCH_OFFICIAL', 'REQUEST_MATCH_REPORT_RECTIFICATION', 'DECIDE_MATCH_REPORT_RECTIFICATION',
  'GRANT_RECTIFICATION_AUTHORIZATION', 'REVOKE_RECTIFICATION_AUTHORIZATION', 'DECIDE_SANCTION_CASE',
  'GRANT_SANCTION_AUTHORIZATION', 'REVOKE_SANCTION_AUTHORIZATION', 'OPEN_COMPETITIVE_IMPACT',
  'CLOSE_COMPETITIVE_IMPACT', 'CHANGE_MEMBER_ROLE', 'SET_MEMBER_ACTIVE', 'ACCEPT_INVITATION', 'REOPEN_INVITATION',
  'SET_TEAM_CREST', 'REMOVE_TEAM_CREST', 'STAGE_SLOTS_RESOLVED', 'CREATE_WEBHOOK', 'UPDATE_WEBHOOK',
  'SET_WEBHOOK_ACTIVE', 'ROTATE_WEBHOOK_SECRET', 'DELETE_WEBHOOK',
] as const;

export const AUDIT_ENTITIES = [
  'matches', 'sanction_cases', 'competitive_impact_procedures', 'organization_users',
  'organization_invitations', 'teams', 'stage_slot_resolutions', 'organization_webhooks',
] as const;

export const AUDIT_PAGE_SIZE = 50;

export type AuditAction = typeof AUDIT_ACTIONS[number];
export type AuditValue = string | number | boolean;

export interface AuditDetail { key: string; value: AuditValue }
export interface AuditActor { kind: 'member' | 'platform'; member_id: string | null; name: string | null }
export interface AuditEntry {
  id: string;
  performed_at: string;
  action: string;
  cataloged: boolean;
  entity_type: string;
  entity_id: string;
  entity_available: boolean;
  actor: AuditActor;
  details: AuditDetail[] | null;
}
export interface AuditPage { items: AuditEntry[]; total: number; limit: number; offset: number }
export interface AuditActorOption { member_id: string; name: string }
export interface AuditFilters { actions: AuditAction[]; actor: string; from: string; to: string; page: number }
export type AuditRouteQuery = Record<string, string | null | undefined | (string | null)[]>;

const isAction = (value: string): value is AuditAction => (AUDIT_ACTIONS as readonly string[]).includes(value);
const first = (value: AuditRouteQuery[string]) => (Array.isArray(value) ? value[0] : value) ?? '';

export function auditActionLabelKey(action: string): string {
  return isAction(action) ? `audit.action.${action}` : 'audit.action.unknown';
}

export function auditEntityLabelKey(entity: string): string {
  return (AUDIT_ENTITIES as readonly string[]).includes(entity) ? `audit.entity.${entity}` : 'audit.entity.unknown';
}

/** Inicio o fin (inclusivo) del día local `YYYY-MM-DD`, en UTC ISO; `null` si la fecha no existe. */
export function dayBoundUtc(value: string, bound: 'start' | 'end'): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const [year, month, day] = [Number(match[1]), Number(match[2]) - 1, Number(match[3])];
  const start = new Date(year, month, day);
  if (start.getFullYear() !== year || start.getMonth() !== month || start.getDate() !== day) return null;
  if (bound === 'start') return start.toISOString();
  return new Date(new Date(year, month, day + 1).getTime() - 1).toISOString();
}

export function filtersFromQuery(query: AuditRouteQuery): AuditFilters {
  const raw = query.action;
  const actions = [...new Set((Array.isArray(raw) ? raw : raw ? [raw] : []).filter((value): value is string => Boolean(value)))]
    .filter(isAction).sort();
  const date = (value: string) => (dayBoundUtc(value, 'start') ? value : '');
  const page = Number.parseInt(first(query.page), 10);
  return {
    actions, actor: first(query.actor), from: date(first(query.from)), to: date(first(query.to)),
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

export function filtersToQuery(filters: AuditFilters): Record<string, string | string[]> {
  const query: Record<string, string | string[]> = {};
  if (filters.actions.length) query.action = [...filters.actions];
  if (filters.actor) query.actor = filters.actor;
  if (filters.from) query.from = filters.from;
  if (filters.to) query.to = filters.to;
  if (filters.page > 1) query.page = String(filters.page);
  return query;
}

export function auditQuery(filters: AuditFilters): string {
  const params = new URLSearchParams();
  for (const action of filters.actions) params.append('action', action);
  if (filters.actor) params.set('actor_member_id', filters.actor);
  const from = dayBoundUtc(filters.from, 'start');
  const to = dayBoundUtc(filters.to, 'end');
  if (from) params.set('from', from);
  if (to) params.set('to', to);
  params.set('limit', String(AUDIT_PAGE_SIZE));
  params.set('offset', String((Math.max(1, filters.page) - 1) * AUDIT_PAGE_SIZE));
  return `?${params}`;
}

export function auditEntityLink(
  entry: Pick<AuditEntry, 'entity_type' | 'entity_id' | 'entity_available'>, permissions: readonly string[],
): string | null {
  if (!entry.entity_available) return null;
  if (entry.entity_type === 'matches') return `/workspace/matches/${entry.entity_id}`;
  if (entry.entity_type === 'sanction_cases' && permissions.includes('VIEW_SANCTION_CASES')) {
    return `/workspace/sanctions?case=${entry.entity_id}`;
  }
  return null;
}

export function formatAuditValue(value: AuditValue, t: (key: string) => string, number: (value: number) => string): string {
  if (typeof value === 'boolean') return t(`audit.value.${value}`);
  if (typeof value === 'number') return number(value);
  return value;
}

export function auditErrorKey(cause: unknown): string {
  const failure = cause as { status?: number; statusCode?: number } | null;
  return (failure?.statusCode || failure?.status) === 403 ? 'audit.error.forbidden' : 'audit.error.generic';
}

export function auditActorLabel(actor: AuditActor, t: (key: string) => string): string {
  if (actor.kind === 'platform') return t('audit.actor.platform');
  return actor.name || t('audit.actor.unknown');
}
