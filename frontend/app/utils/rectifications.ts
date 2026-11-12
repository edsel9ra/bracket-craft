import type { DraftEvent, MatchOperation } from '../components/match/types';
import type { ResolutionType } from './matchResolution.ts';

export interface ReportProposal {
  resolution_type: ResolutionType;
  reason?: string | null;
  home_score_regular?: number | null;
  away_score_regular?: number | null;
  home_score?: number | null;
  away_score?: number | null;
  home_penalties?: number | null;
  away_penalties?: number | null;
  winner_team_id?: string | null;
  events: DraftEvent[];
}
export interface ReportVersion {
  match_id: string;
  version_number: number;
  published_at: string | null;
  published_by_user_id: string | null;
  reason: string | null;
  evidence: string | null;
  report: Record<string, unknown>;
}
export interface FieldDifference { field: string; before: unknown; after: unknown }
export interface ReportDifference {
  fields: FieldDifference[];
  events: { added: Record<string, unknown>[]; removed: Record<string, unknown>[]; changed: { client_event_id: string; fields: FieldDifference[] }[] };
}
export interface Rectification {
  id: string;
  match_id: string;
  base_version_number: number;
  proposed_report: ReportProposal;
  reason: string;
  evidence: string | null;
  requested_by_user_id: string;
  requested_by_member_id: string;
  requested_at: string;
  status: 'pending' | 'rejected' | 'withdrawn' | 'published';
}
export interface RectificationDetail extends Rectification { diff: ReportDifference }
export interface Preview { version: ReportVersion; effects: Record<string, unknown>[]; expected_base_version: number }
export interface PlatformAuthorization { id: string; platform_admin_user_id: string; reason: string; granted_at: string; revoked_at: string | null; consumed_at: string | null }
export interface CompetitiveImpact { id: string; match_id: string; version_id: string; status: 'open' | 'closed'; reason: string | null; affected_items: Record<string, unknown>[]; created_at: string; closed_at: string | null; resolution: 'keep_as_played' | null }
export interface Page<T> { items: T[]; total: number; limit: number; offset: number }
export interface InboxFilters { status?: string; tournament_id?: string; limit?: number; offset?: number }
export type { MatchOperation };

export function inboxQuery(filters: InboxFilters = {}): string {
  const entries = Object.entries(filters).filter(([, value]) => value !== undefined && value !== '');
  return entries.length ? `?${new URLSearchParams(entries.map(([key, value]) => [key, String(value)]))}` : '';
}

export function canDecide(requester: string, member: string | null, permission: boolean, status: string): boolean {
  return Boolean(member && member !== requester && permission && status === 'pending');
}

export function rectificationErrorKey(cause: unknown): string {
  const failure = cause as { status?: number; statusCode?: number; data?: { code?: string; detail?: { code?: string } } };
  const rawCode = failure?.data?.code || failure?.data?.detail?.code;
  const code = typeof rawCode === 'string' ? rawCode.replace(/^RECTIFICATION_/, '') : null;
  if (code === 'STALE' || code === 'SELF_APPROVAL' || code === 'COMPETITIVE_IMPACT_OPEN') return `rectification.error.${code}`;
  const status = failure?.statusCode || failure?.status;
  return status === 403 ? 'rectification.error.forbidden' : status === 409 ? 'rectification.error.conflict' : status === 404 ? 'rectification.error.notFound' : 'rectification.error.generic';
}

export const SCORE_FIELDS = ['home_score_regular', 'away_score_regular', 'home_score', 'away_score', 'home_penalties', 'away_penalties'] as const;
export const RECTIFICATION_RESOLUTION_LABEL_KEYS = { regular: 'match.regularTime', extra_time: 'match.overtime', penalties: 'match.penaltyShootout', walkover: 'match.walkover', administrative: 'match.administrative' } as const;
export const EVENT_LABEL_KEYS = { goal: 'event.goal', own_goal: 'event.ownGoal', penalty_goal: 'event.penaltyGoal', yellow_card: 'event.yellowCard', red_card: 'event.redCard', substitution: 'event.substitution', foul: 'event.foul' } as const;

export function reportProposal(report: Record<string, unknown>): ReportProposal {
  const resolution = report.resolution_type as ResolutionType;
  const source = Array.isArray(report.events) ? report.events as Record<string, unknown>[] : [];
  const eventFields = ['client_event_id', 'event_type', 'team_id', 'beneficiary_team_id', 'player_id', 'minute', 'added_minute', 'segment_id', 'assist_player_id', 'player_out_id', 'player_in_id', 'metadata'];
  const events = source.filter((row) => !row.is_voided).map((row) => ({
    ...Object.fromEntries(eventFields.map((key) => [key, row[key] ?? (key === 'metadata' ? {} : null)])),
    client_event_id: typeof row.client_event_id === 'string' ? row.client_event_id.toLowerCase() : row.client_event_id,
  })) as unknown as DraftEvent[];
  return { resolution_type: resolution, reason: (report.resolution_reason ?? report.reason ?? null) as string | null,
    winner_team_id: report.winner_team_id as string | null, events,
    ...(resolution === 'walkover' ? {} : Object.fromEntries(SCORE_FIELDS.map((key) => [key, report[key] === '' ? null : report[key] ?? null]))),
  };
}

export function compareReports(before: Record<string, unknown>, after: Record<string, unknown>): ReportDifference {
  const left = reportProposal(before); const right = reportProposal(after);
  const fields: FieldDifference[] = [];
  const fieldValue = (report: Record<string, unknown>, key: string) => key === 'reason' ? report.resolution_reason ?? report.reason ?? null : report[key] ?? null;
  for (const key of ['resolution_type', 'reason', 'winner_team_id', ...SCORE_FIELDS] as const) {
    const oldValue = fieldValue(before, key); const newValue = fieldValue(after, key);
    if (JSON.stringify(oldValue) !== JSON.stringify(newValue)) fields.push({ field: key, before: oldValue, after: newValue });
  }
  const ids = (report: ReportProposal) => report.events.map((event) => event.client_event_id);
  if (JSON.stringify(ids(left)) !== JSON.stringify(ids(right))) fields.push({ field: 'event_order', before: ids(left), after: ids(right) });
  const oldEvents = new Map(left.events.map((event) => [event.client_event_id, event]));
  const newEvents = new Map(right.events.map((event) => [event.client_event_id, event]));
  const added = right.events.filter((event) => !oldEvents.has(event.client_event_id));
  const removed = left.events.filter((event) => !newEvents.has(event.client_event_id));
  const changed: ReportDifference['events']['changed'] = [];
  for (const event of right.events) {
    const original = oldEvents.get(event.client_event_id);
    if (!original) continue;
    const changes = (Object.keys(event) as (keyof DraftEvent)[]).filter((key) => JSON.stringify(original[key] ?? null) !== JSON.stringify(event[key] ?? null))
      .map((key) => ({ field: key, before: original[key] ?? null, after: event[key] ?? null }));
    if (changes.length) changed.push({ client_event_id: event.client_event_id, fields: changes });
  }
  return { fields, events: { added: added as unknown as Record<string, unknown>[], removed: removed as unknown as Record<string, unknown>[], changed } };
}
