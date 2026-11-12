import type { Page } from '@playwright/test';
import { formationSlots } from '../app/constants/formations.ts';
import type { PublicMatch, PublicStanding, PublicTournament } from '../app/utils/publicTournament.ts';

export const uuid = (n: number) => `03100000-0000-4000-8000-${String(n).padStart(12, '0')}`;
export const leagueId = uuid(1);
export const bracketId = uuid(2);
const teamName = (n: number) => `Club Deportivo Nombre Extenso Sin Abreviar ${n}`;

function match(n: number, round: number, code: string, home: number | null, away: number | null): PublicMatch {
  const known = home !== null && away !== null;
  return {
    rectified_at: null,
    id: uuid(1000 + n), stage_id: bracketId, stage_name: 'Eliminatoria', stage_order: 2,
    group_id: null, group_name: null, bracket_code: code, matchday: round,
    match_date: '2026-11-12T18:00:00Z', home_team_id: home === null ? null : uuid(home + 100),
    away_team_id: away === null ? null : uuid(away + 100), home_team_name: home === null ? null : teamName(home),
    away_team_name: away === null ? null : teamName(away), home_team_short_code: home === null ? null : `C${home}`,
    away_team_short_code: away === null ? null : `C${away}`, home_team_crest_url: null, away_team_crest_url: null,
    home_score: known ? 2 : null, away_score: known ? 0 : null, home_penalties: null, away_penalties: null,
    status: known ? 'finished' : 'scheduled', resolution_type: known ? 'regular' : null,
    winner_team_id: known ? uuid(home + 100) : null, lineup: null,
  };
}

export function bracketMatches(size: number): PublicMatch[] {
  if (size === 5) return [match(1, 1, 'QF1', 4, 5), match(2, 2, 'SF1', 1, 4), match(3, 2, 'SF2', 2, 3), match(4, 3, 'FINAL', 1, 2)];
  const rows: PublicMatch[] = [];
  let teams: (number | null)[] = Array.from({ length: size }, (_, n) => n + 1);
  let round = 1;
  while (teams.length > 1) {
    const next: (number | null)[] = [];
    for (let i = 0; i < teams.length; i += 2) {
      const count = teams.length / 2;
      const code = count === 1 ? 'FINAL' : count === 2 ? `SF${i / 2 + 1}` : count === 4 ? `QF${i / 2 + 1}` : `R16-${i / 2 + 1}`;
      const row = match(rows.length + 1, round, code, teams[i] ?? null, teams[i + 1] ?? null);
      if (round === 1 && i === 0) { row.home_score = 3; row.resolution_type = 'walkover'; }
      if (round === 1 && i === 2) { row.status = 'scheduled'; row.winner_team_id = null; row.home_score = null; row.away_score = null; row.resolution_type = null; }
      if (round === 1 && i === 4) { row.home_score = 1; row.away_score = 1; row.home_penalties = 5; row.away_penalties = 4; row.resolution_type = 'penalties'; }
      rows.push(row); next.push(row.winner_team_id ? teams[i] ?? null : null);
    }
    teams = next; round++;
  }
  return rows;
}

export function publicContract(size = 8) {
  const tournament: PublicTournament = {
    id: uuid(0), name: 'Torneo público 031', season: '2026', start_date: '2026-11-01', status: 'published',
    stages: [
      { id: leagueId, name: 'Liga', stage_type: 'round_robin', stage_order: 1 },
      { id: bracketId, name: 'Eliminatoria', stage_type: 'single_elimination', stage_order: 2 },
    ],
    teams: Array.from({ length: 53 }, (_, n) => ({ team_id: uuid(n + 101), name: teamName(n + 1), short_code: `C${n + 1}`, crest_url: null })),
  };
  const standings: PublicStanding[] = [1, 2].map(n => ({
    stage_id: leagueId, stage_name: 'Liga', stage_order: 1, group_id: null, group_name: null,
    team_id: uuid(n + 100), team_name: teamName(n), short_code: `C${n}`, played: 1, won: 0, drawn: 1, lost: 0,
    goals_for: 1, goals_against: 1, goal_difference: 0, points: 1, fair_play_points: 0, rank: 1, crest_url: null,
  }));
  const published = match(100, 1, '', 1, 2);
  Object.assign(published, { stage_id: leagueId, stage_name: 'Liga', stage_order: 1, bracket_code: null, home_score: 1, away_score: 1, home_penalties: 5, away_penalties: 4, resolution_type: 'penalties' });
  published.lineup = { home: {
    team_id: uuid(101), team_name: teamName(1), formation_code: '4-4-2', segment_number: 2, crest_url: null,
    starters: formationSlots('4-4-2').map((slot, i) => ({ player_id: uuid(3000 + i), first_name: 'Nombre', last_name: `Publicado ${i}`, dorsal_number: i + 1, role: 'starter', position_slot: slot, photo_url: null })), substitutes: [],
  }, away: null };
  const players = Array.from({ length: 53 }, (_, i) => ({ rank: i < 2 ? 1 : i + 1, player_id: uuid(2000 + i), first_name: 'Global', last_name: `Apellido Extenso ${i}`, team_id: uuid(101), team_name: teamName(1), goals: i < 2 ? 53 : 53 - i, yellow_cards: 0, red_cards: 0, clean_sheets: 0, matches_played: 2, photo_url: i === 0 ? '/031-missing-photo.png' : null }));
  const teams = Array.from({ length: 53 }, (_, i) => ({ rank: i < 2 ? 1 : i + 1, team_id: uuid(101 + i), team_name: teamName(i + 1), short_code: `C${i + 1}`, crest_url: null, goals_for: i < 2 ? 53 : 53 - i, goals_against: 0, clean_sheets: 1, fair_play_points: 0 }));
  return { tournament, standings, matches: [published, ...bracketMatches(size)], players, teams };
}

export async function installPublicContract(page: Page, size = 8) {
  const data = publicContract(size);
  const state = { mode: 'normal' as 'normal' | 'empty' | 'error', hold: false, release: () => {} };
  const requests: { method: string; path: string; scope: string | null; offset: number }[] = [];
  await page.route('**/031-missing-photo.png', route => route.fulfill({ status: 404 }));
  await page.route('**/api/v1/tournaments/public**', async route => {
    const request = route.request();
    if (request.method() === 'OPTIONS') return route.continue();
    const url = new URL(request.url());
    const endpoint = url.pathname.split('/').at(-1)!;
    const scope = url.searchParams.get('stage_id');
    const offset = Number(url.searchParams.get('offset') ?? 0);
    requests.push({ method: request.method(), path: url.pathname, scope, offset });
    const headers = { 'Access-Control-Allow-Origin': request.headers()['origin'] ?? '*', 'Access-Control-Allow-Credentials': 'true' };
    const stats = endpoint === 'player-stats' || endpoint === 'team-stats';
    if (stats && state.hold && offset === 50) await new Promise<void>(resolve => { state.release = resolve; });
    if (state.mode === 'error' && stats) return route.fulfill({ status: 503, headers, json: { detail: 'Servicio no disponible' } });
    let body: unknown;
    if (stats) {
      const rows = endpoint === 'player-stats' ? data.players : data.teams;
      body = state.mode === 'empty' || scope === bracketId ? [] : (scope ? rows.slice(0, 3) : rows).slice(offset, offset + 50);
    } else if (endpoint === 'standings') body = scope === bracketId ? [] : data.standings;
    else if (endpoint === 'matches') body = data.matches.filter(row => !scope || row.stage_id === scope);
    else if (endpoint === 'public') body = [data.tournament];
    else body = { ...data.tournament, id: endpoint };
    await route.fulfill({ headers, json: body });
  });
  return { data, state, requests };
}
