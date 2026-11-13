export type CaseStatus = 'pending' | 'resolved' | 'withdrawn' | 'closed_by_rectification';
export type CaseType = 'appeal' | 'administrative_proposal';
export type SanctionDecision = 'maintain' | 'annul' | 'reduce' | 'approve' | 'reject';
export interface SanctionPage<T> { items: T[]; total: number }
export interface Pagination { limit?: number; offset?: number }
export interface CaseFilters extends Pagination { status?: CaseStatus; case_type?: CaseType }
export interface SanctionFilters extends Pagination { status?: 'active' | 'served' | 'cancelled' | 'appealed'; scope_type?: 'tournament' | 'organization'; player_id?: string; source_tournament_id?: string }
export interface Evidence { reason: string; evidence_text?: string | null; evidence_links?: string[] }
export interface AppealBody extends Evidence { represented_player_id?: string | null; represented_team_id?: string | null; prior_case_id?: string | null }
export interface ProposalBody extends Evidence { proposed_action: 'annul' | 'reduce'; proposed_duration?: number | null; prior_case_id?: string | null }
export interface DecisionBody extends Evidence { decision: SanctionDecision; expected_base_duration: number; after_duration?: number | null; prejudice_records?: { match_id: string; reason: string }[] }
export interface SanctionReceipt { id: string; status: CaseStatus }
export interface SanctionCase extends SanctionReceipt { suspension_id: string; case_type: CaseType; submitted_by_user_id: string; submitted_at: string }
export interface FullSanctionCase extends SanctionCase, Evidence { base_duration: number; proposed_action: 'annul' | 'reduce' | null; proposed_duration: number | null; represented_player_id: string | null; represented_team_id: string | null; prior_case_id: string | null }
export interface SanctionSource { id: string; player_id: string; source_tournament_id: string; scope_type: 'tournament' | 'organization'; source_type: string; origin_match_id: string | null; matches_suspended: number; status: string; reason: string; created_at: string }
export interface SanctionProjection { original_duration: number; effective_duration: number; served_count: number; remaining: number; status: string; pending_effect: boolean }
export interface SanctionRow { source: SanctionSource; projection: SanctionProjection }
export interface SanctionEvent extends Evidence { id: string; event_type: 'submitted' | 'withdrawn' | 'closed_by_rectification' | 'affected_by_rectification'; actor_user_id: string; created_at: string; rectification_version_id: string | null }
export interface DecisionRecord extends DecisionBody { id: string; decided_by_user_id: string; decided_as: string; before_duration: number; created_at: string }
export interface SanctionResolution { id: string; case_id: string; action: 'annul' | 'reduce'; original_duration: number; before_duration: number; new_duration: number | null; served_count: number; is_declarative: boolean; created_at: string; excluded: boolean }
export interface SanctionApplication { id: string; resolution_id: string; match_id: string; effective_at: string; before_status: string; after_status: string }
export interface SanctionServe { id: string; match_id: string; is_voided: boolean; created_at: string }
export interface SanctionDetail { case: FullSanctionCase; source: SanctionSource; projection: SanctionProjection; events: SanctionEvent[]; decisions: DecisionRecord[]; prejudice: { id: string; match_id: string | null; reason: string; created_at: string }[]; resolutions: SanctionResolution[]; applications: SanctionApplication[]; serves: SanctionServe[] }
export interface SanctionPreview { id: string; status: CaseStatus; projection: SanctionProjection; expected_base_duration: number; allowed_decisions: SanctionDecision[]; can_decide: boolean }
export interface SanctionAuthorization { id: string; case_id: string; platform_admin_user_id: string; reason: string; granted_at: string; revoked_at: string | null; consumed_at: string | null }
export interface AuthorizationBody { platform_admin_email: string; reason: string }
export interface SanctionNotice { id: string; case_id: string; notification_type: string; reason: string; created_at: string; decision: SanctionDecision | null }
export interface SuspensionWarning { player_id: string; remaining: number }

export function sanctionQuery(filters: CaseFilters | SanctionFilters | Pagination = {}): string {
  const allowed = new Set(['status', 'case_type', 'limit', 'offset', 'scope_type', 'player_id', 'source_tournament_id']);
  const entries = Object.entries(filters).filter(([key, value]) => allowed.has(key) && value !== undefined && value !== '');
  return entries.length ? `?${new URLSearchParams(entries.map(([key, value]) => [key, String(value)]))}` : '';
}

export function sanctionAccess(permissions: string[], role: string | undefined) {
  return { view: permissions.includes('VIEW_SANCTION_CASES'), submit: permissions.includes('SUBMIT_SANCTION_APPEALS'), resolve: permissions.includes('RESOLVE_SANCTION_CASES'), owner: role === 'owner' };
}

export function canDecideSanction(author: string, actor: string | null, permission: boolean, status: string): boolean {
  return Boolean(actor && actor !== author && permission && status === 'pending');
}

export function sanctionErrorKey(cause: unknown): string {
  const failure = cause as { status?: number; statusCode?: number; data?: { code?: string } };
  const code = failure?.data?.code;
  if (['SANCTION_CASE_CONFLICT', 'SANCTION_SELF_DECISION', 'SANCTION_STALE_BASE', 'SANCTION_CASE_NOT_PENDING', 'SANCTION_INVALID_STATE'].includes(code || '')) return `sanction.error.${code}`;
  const status = failure?.statusCode || failure?.status;
  return `sanction.error.${status === 403 ? 'forbidden' : status === 404 ? 'notFound' : status === 409 ? 'conflict' : status === 422 ? 'validation' : 'generic'}`;
}

export function safeEvidenceLink(value: string): string | null {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
