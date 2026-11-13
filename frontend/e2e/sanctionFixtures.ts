import { expect, type Page, type Route } from '@playwright/test';
import type { SanctionDetail, SanctionNotice, SanctionSource, SanctionDecision } from '../app/utils/sanctions.ts';

const uuid = (value: number) => `03400000-0000-4000-8000-${String(value).padStart(12, '0')}`;
const now = '2026-11-13T12:00:00Z';
type Actor = 'author' | 'reviewer';
const actors = { author: uuid(1), reviewer: uuid(2) };

export class SanctionFixture {
  readonly org = uuid(10); readonly otherOrg = uuid(11); readonly player = uuid(20); readonly matchId = uuid(30);
  readonly sources: SanctionSource[] = [1, 2, 3].map((index) => ({ id: uuid(100 + index), player_id: this.player, source_tournament_id: uuid(40), scope_type: 'organization', source_type: 'match_event', origin_match_id: uuid(31), matches_suspended: 3, status: 'active', reason: 'Private original sanction', created_at: now }));
  readonly cases: SanctionDetail[] = []; readonly notices: SanctionNotice[] = [];
  readonly requests: { path: string; org: string; actor: Actor; method: string }[] = [];
  authorCanView = true; authorCanSubmit = true; authorCanResolve = true; warningFails = false; saves = 0; publications = 0; lastLineup: Record<string, unknown> = {};
  private sequence = 1000;

  notice(reason: string) { this.notices.push({ id: uuid(++this.sequence), case_id: this.cases[0]!.case.id, notification_type: 'decision', reason, created_at: now, decision: 'annul' }); }
  rectify(id: string) {
    const detail = this.cases.find((item) => item.case.id === id)!; detail.case.status = 'closed_by_rectification';
    detail.events.push({ id: uuid(++this.sequence), event_type: 'closed_by_rectification', reason: 'Rectificación 033', evidence_links: [], actor_user_id: actors.reviewer, created_at: now, rectification_version_id: uuid(90) });
  }
  apply(id: string) {
    const detail = this.cases.find((item) => item.case.id === id)!;
    detail.projection = { ...detail.projection, effective_duration: 0, remaining: 0, pending_effect: false, status: 'cancelled' };
    detail.applications.push({ id: uuid(++this.sequence), resolution_id: detail.resolutions[0]!.id, match_id: this.matchId, effective_at: now, before_status: 'active', after_status: 'cancelled' });
  }
  private operation() {
    const team = uuid(50); const segment = uuid(60); const roster = uuid(70);
    return {
      match: { id: this.matchId, tournament_id: uuid(40), tournament_name: 'Torneo 034', tournament_version_id: uuid(41), stage_id: uuid(42), stage_name: 'Fase 034', group_id: null, group_name: null, matchday: 2, match_date: now, status: 'live', result_confirmed: false, version_status: 'published', home_team_id: team, home_team_name: 'Local', home_team_short_code: 'LOC', home_team_crest_url: null, home_team_logo_url: null, away_team_id: uuid(51), away_team_name: 'Visitante', away_team_short_code: 'VIS', away_team_crest_url: null, away_team_logo_url: null, home_score_regular: null, away_score_regular: null, home_score: null, away_score: null, home_penalties: null, away_penalties: null, winner_team_id: null, resolution_type: null, rules_config: { game_format: '5v5' } },
      segments: [{ id: segment, segment_number: 1, minute_start: 0, minute_end: null, status: 'active' }], interruptions: [], officials: [], eligible_officials: [], events: [], next_segment: null,
      rosters: [{ roster_id: roster, player_id: this.player, team_id: team, team_name: 'Local', first_name: 'Jugador', last_name: '034', dorsal_number: 1, is_active: true, match_roster_id: uuid(71), role: 'starter', entered_minute: 0, left_minute: null, is_valid: true }],
      lineup: [{ match_roster_id: uuid(71), roster_id: roster, player_id: this.player, team_id: team, role: 'starter', entered_minute: 0, left_minute: null, first_name: 'Jugador', last_name: '034', dorsal_number: 1, position_slot: 'GK' }],
      tactical_lineups: [{ segment_id: segment, segment_number: 1, team_id: team, formation_code: '4-3-3', is_public: this.publications > 0, published_at: null, player_id: this.player, is_starter: true, position_slot: 'GK', first_name: 'Jugador', last_name: '034' }],
    };
  }
  async handle(route: Route, actor: Actor) {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname.replace('/api/v1', ''); const method = request.method();
    const org = request.headers()['x-organization-id'] || '';
    const reply = (body: unknown, status = 200) => route.fulfill({ status, json: body, headers: { 'Access-Control-Allow-Origin': request.headers()['origin'] || 'http://localhost:3000', 'Access-Control-Allow-Credentials': 'true', 'Access-Control-Allow-Headers': 'Content-Type,X-Organization-ID,X-CSRF-Token', 'Access-Control-Allow-Methods': 'GET,POST,PATCH,PUT,DELETE,OPTIONS' } });
    if (method === 'OPTIONS') return reply({});
    this.requests.push({ path, org, actor, method });
    const summary = (id: string) => ({ id, name: id === this.org ? 'Organización A' : 'Organización B', slug: id === this.org ? 'org-a' : 'org-b', organization_user_id: uuid(80) });
    const permissions = ['CLOSE_MATCH_REPORT', ...((actor !== 'author' || this.authorCanSubmit) ? ['SUBMIT_SANCTION_APPEALS'] : []), ...((actor !== 'author' || this.authorCanResolve) ? ['RESOLVE_SANCTION_CASES'] : []), ...((actor !== 'author' || this.authorCanView) ? ['VIEW_SANCTION_CASES'] : [])];
    if (path === '/auth/csrf') return reply({ csrf_token: 'sanction-fixture-csrf' });
    if (path === '/organizations') return reply([summary(this.org), summary(this.otherOrg)]);
    if (path === '/organizations/current') return reply(summary(org));
    if (path === '/organizations/current/access') return reply({ organization_id: org, organization_user_id: uuid(80), user_id: actors[actor], role_code: actor === 'author' ? 'owner' : 'administrator', permissions });
    if (path === '/platform/access') return reply({ allowed: false });
    if (path === '/tournaments') return reply([]);
    if (path === `/tournaments/${uuid(40)}`) return reply({ id: uuid(40), name: 'Torneo 034' });
    if (path === '/sanction-notifications') return reply({ items: org === this.org ? this.notices : [] });
    if (path === '/sanctions') return reply({ items: org === this.org ? this.sources.map((source) => ({ source, projection: { original_duration: 3, effective_duration: 3, served_count: 0, remaining: 3, status: 'active', pending_effect: false } })) : [], total: org === this.org ? this.sources.length : 0 });
    if (path === '/sanction-cases') {
      const status = url.searchParams.get('status'); const type = url.searchParams.get('case_type');
      const cases = org === this.org ? this.cases.filter((item) => (!status || item.case.status === status) && (!type || item.case.case_type === type)) : [];
      return reply({ items: cases.map((item) => item.case), total: cases.length });
    }
    if (path === `/matches/${this.matchId}/operation`) return reply(this.operation());
    if (path.endsWith('/suspension-warnings')) return this.warningFails ? reply({ detail: 'Unavailable' }, 403) : reply([{ player_id: this.player, remaining: 3 }]);
    if (path.endsWith('/lineup') && method === 'PUT') { this.saves++; this.lastLineup = request.postDataJSON() as Record<string, unknown>; return reply({}); }
    if (path.endsWith('/lineup/publication') && method === 'PATCH') { this.publications++; return reply({}); }
    const submit = /^\/sanctions\/([^/]+)\/(appeals|administrative-proposals)$/.exec(path);
    if (submit && method === 'POST' && org === this.org) {
      const body = request.postDataJSON() as Record<string, unknown>; const source = this.sources.find((row) => row.id === submit[1])!;
      const detail: SanctionDetail = { case: { id: uuid(++this.sequence), status: 'pending', suspension_id: source.id, case_type: submit[2] === 'appeals' ? 'appeal' : 'administrative_proposal', submitted_by_user_id: actors[actor], submitted_at: now, base_duration: 3, reason: String(body.reason), evidence_text: typeof body.evidence_text === 'string' ? body.evidence_text : null, evidence_links: (body.evidence_links || []) as string[], proposed_action: body.proposed_action as 'annul' | 'reduce' || null, proposed_duration: typeof body.proposed_duration === 'number' ? body.proposed_duration : null, represented_player_id: body.represented_player_id as string || null, represented_team_id: body.represented_team_id as string || null, prior_case_id: body.prior_case_id as string || null }, source, projection: { original_duration: 3, effective_duration: 3, served_count: 0, remaining: 3, status: 'active', pending_effect: false }, events: [], decisions: [], prejudice: [], resolutions: [], applications: [], serves: [] };
      this.cases.push(detail); return reply({ id: detail.case.id, status: detail.case.status }, 201);
    }
    const target = /^\/sanction-cases\/([^/]+)(?:\/(.*))?$/.exec(path);
    if (target) {
      const detail = org === this.org ? this.cases.find((item) => item.case.id === target[1]) : undefined;
      if (!detail) return reply({ detail: 'Not found' }, 404);
      if (!target[2]) return reply(detail);
      if (target[2] === 'platform-authorizations') return reply([]);
      if (target[2] === 'preview') return reply({ id: detail.case.id, status: detail.case.status, expected_base_duration: 3, projection: detail.projection, can_decide: actors[actor] !== detail.case.submitted_by_user_id, allowed_decisions: detail.case.case_type === 'appeal' ? ['maintain', 'annul', 'reduce'] : ['approve', 'reject'] });
      const body = request.postDataJSON() as Record<string, unknown>;
      if (target[2] === 'withdraw') {
        if (detail.case.status !== 'pending') return reply({ code: 'SANCTION_CASE_NOT_PENDING' }, 409);
        if (actors[actor] !== detail.case.submitted_by_user_id) return reply({ code: 'SANCTION_INVALID_STATE' }, 409);
        detail.case.status = 'withdrawn'; return reply({ id: detail.case.id, status: 'withdrawn' });
      }
      if (target[2] === 'decision') {
        if (actors[actor] === detail.case.submitted_by_user_id) return reply({ code: 'SANCTION_SELF_DECISION' }, 409);
        detail.case.status = 'resolved'; const decision = body.decision as SanctionDecision;
        detail.decisions.push({ id: uuid(++this.sequence), decision, reason: String(body.reason), expected_base_duration: 3, before_duration: 3, decided_by_user_id: actors[actor], decided_as: 'organization_member', created_at: now });
        if (['annul', 'reduce', 'approve'].includes(decision)) {
          const action = decision === 'approve' ? detail.case.proposed_action! : decision as 'annul' | 'reduce';
          detail.resolutions.push({ id: uuid(++this.sequence), case_id: detail.case.id, action, original_duration: 3, before_duration: 3, new_duration: action === 'reduce' ? Number(body.after_duration ?? detail.case.proposed_duration) : null, served_count: 0, is_declarative: false, created_at: now, excluded: false });
          detail.projection.pending_effect = true;
        }
        this.notice(String(body.reason)); return reply({ id: detail.case.id, status: 'resolved' });
      }
    }
    return reply([]);
  }
}

export async function navigateFixture(page: Page, path: string) {
  await page.evaluate(async path => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__: { config: { globalProperties: { $router: { push: (path: string) => Promise<unknown> } } } } };
    await root.__vue_app__.config.globalProperties.$router.push(path);
  }, path);
}

export async function openFixture(page: Page, fixture: SanctionFixture, actor: Actor) {
  await page.context().addCookies([{ name: 'bc_user_id', value: actors[actor], url: 'http://localhost:3000' }, { name: 'bc_organization_id', value: fixture.org, url: 'http://localhost:3000' }]);
  await page.route('**/api/v1/**', route => fixture.handle(route, actor));
  await page.goto('/');
  await page.waitForFunction(() => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__?: { config: { globalProperties: { $nuxt: { isHydrating: boolean } } } } };
    return root?.__vue_app__?.config.globalProperties.$nuxt.isHydrating === false;
  });
  await navigateFixture(page, '/workspace/sanctions');
  await expect(page.getByRole('heading', { name: 'Expedientes de sanciones', exact: true, level: 1 })).toBeVisible();
}
