import { expect, type Page, type Route } from '@playwright/test';
import type { SanctionDetail } from '../app/utils/sanctions.ts';
import { SanctionFixture, navigateFixture } from './sanctionFixtures.ts';

export class SanctionPlatformFixture extends SanctionFixture {
  readonly platformId = '03400000-0000-4000-8000-000000000003';
  readonly authorized = new Set<string>();
  readonly platformRequests: { path: string; method: string }[] = [];
  active = true; failList = false;
  constructor() {
    super();
    for (let index = 0; index < 3; index++) {
      const detail: SanctionDetail = {
        case: { id: `03400000-0000-4000-8000-00000000200${index}`, suspension_id: this.sources[index]!.id, case_type: 'appeal', status: 'pending', submitted_by_user_id: index === 2 ? this.platformId : '03400000-0000-4000-8000-000000000001', submitted_at: '2026-11-13T12:00:00Z', base_duration: 3, reason: 'Revisión privada F9', evidence_text: 'PRIVATE EVIDENCE F9', evidence_links: [], represented_player_id: this.player, represented_team_id: null, proposed_action: null, proposed_duration: null, prior_case_id: null },
        source: this.sources[index]!, projection: { original_duration: 3, effective_duration: 3, served_count: 0, remaining: 3, status: 'active', pending_effect: false }, events: [], decisions: [], resolutions: [], applications: [], serves: [], prejudice: [],
      };
      this.cases.push(detail);
    }
    this.authorized.add(this.cases[0]!.case.id);
  }
  async handlePlatform(route: Route) {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname.replace('/api/v1', ''); const method = request.method();
    const reply = (body: unknown, status = 200) => route.fulfill({ status, json: body, headers: { 'Access-Control-Allow-Origin': request.headers()['origin'] || 'http://localhost:3000', 'Access-Control-Allow-Credentials': 'true', 'Access-Control-Allow-Headers': 'Content-Type,X-Organization-ID,X-CSRF-Token', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS' } });
    if (method === 'OPTIONS') return reply({});
    this.platformRequests.push({ path, method });
    if (path === '/auth/csrf') return reply({ csrf_token: 'sanction-platform-fixture' });
    if (path === '/platform/access') return reply({ allowed: this.active });
    if (path === '/organizations') return reply([]);
    if (path === '/platform/users') return reply(this.active ? [] : { detail: 'Forbidden' }, this.active ? 200 : 403);
    if (path.startsWith('/platform/sanction-cases')) {
      if (!this.active) return reply({ detail: 'Forbidden' }, 403);
      if (path === '/platform/sanction-cases') {
        if (this.failList) return reply({ detail: 'Unavailable' }, 503);
        const rows = this.cases.filter(row => this.authorized.has(row.case.id));
        const offset = Number(url.searchParams.get('offset') || 0);
        return reply({ items: rows.slice(offset, offset + 25).map(row => ({ ...row.case, authorization_id: row.case.id, organization_id: this.org })), total: rows.length });
      }
      const target = /^\/platform\/sanction-cases\/([^/]+)(?:\/(.*))?$/.exec(path)!;
      const detail = this.authorized.has(target[1]!) ? this.cases.find(row => row.case.id === target[1]) : null;
      if (!detail) return reply({ detail: 'Not found' }, 404);
      if (!target[2]) return reply(detail);
      const canDecide = detail.case.submitted_by_user_id !== this.platformId && detail.case.status === 'pending';
      if (target[2] === 'preview') return reply({ id: detail.case.id, status: detail.case.status, expected_base_duration: 3, projection: detail.projection, can_decide: canDecide, allowed_decisions: ['maintain', 'annul', 'reduce'] });
      if (target[2] === 'decision' && method === 'POST') {
        if (!canDecide) return reply({ code: 'SANCTION_SELF_DECISION' }, 409);
        detail.case.status = 'resolved'; this.authorized.delete(detail.case.id);
        return reply({ id: detail.case.id, status: detail.case.status });
      }
    }
    return reply([]);
  }
}

export async function openPlatformFixture(page: Page, fixture: SanctionPlatformFixture) {
  await page.context().clearCookies();
  await page.context().addCookies([{ name: 'bc_user_id', value: fixture.platformId, url: new URL('/', page.url() === 'about:blank' ? 'http://localhost:3000' : page.url()).toString() }, { name: 'bc_locale', value: 'es', url: 'http://localhost:3000' }]);
  await page.route('**/api/v1/**', route => fixture.handlePlatform(route));
  await page.goto('/');
  await page.waitForFunction(() => Boolean((document.querySelector('#__nuxt') as HTMLElement & { __vue_app__?: unknown })?.__vue_app__));
  await navigateFixture(page, '/admin/sanction-cases');
  await expect(page.getByRole('heading', { name: 'Decisión excepcional de sanciones', exact: true, level: 1 })).toBeVisible();
}
