import type { PublicMatch } from './publicTournament.ts';

export interface PublicBracketRound {
  key: string;
  stageId: string;
  groupId: string | null;
  matchday: number | null;
  matches: PublicMatch[];
}

export interface PublicAdvance {
  sourceId: string;
  targetId: string;
  teamId: string;
  side: 'home' | 'away';
}

function roundNumber(value: number | null): number | null {
  return Number.isInteger(value) && value !== null && value > 0 ? value : null;
}

function partitionKey(match: PublicMatch): string {
  return JSON.stringify([match.stage_id, match.group_id]);
}

export function groupPublicRounds(matches: readonly PublicMatch[]): PublicBracketRound[] {
  const partitions = new Map<string, Map<number | null, PublicBracketRound>>();
  const seen = new Set<string>();
  for (const match of matches) {
    if (seen.has(match.id)) continue;
    seen.add(match.id);
    const partition = partitionKey(match);
    const grouped = partitions.get(partition) ?? new Map<number | null, PublicBracketRound>();
    const matchday = roundNumber(match.matchday);
    const round = grouped.get(matchday) ?? {
      key: JSON.stringify([match.stage_id, match.group_id, matchday]),
      stageId: match.stage_id, groupId: match.group_id, matchday, matches: [],
    };
    round.matches.push(match);
    grouped.set(matchday, round);
    partitions.set(partition, grouped);
  }
  return [...partitions.values()].flatMap(grouped => [...grouped.values()]
    .sort((a, b) => (a.matchday ?? Infinity) - (b.matchday ?? Infinity)));
}

export function inferPublicAdvances(matches: readonly PublicMatch[]): PublicAdvance[] {
  const fingerprints = new Map<string, string>();
  const conflicts = new Set<string>();
  const uniqueRecords = new Map<string, PublicMatch>();
  for (const match of matches) {
    const fingerprint = JSON.stringify(match);
    if (fingerprints.has(match.id) && fingerprints.get(match.id) !== fingerprint) conflicts.add(match.id);
    fingerprints.set(match.id, fingerprint);
    uniqueRecords.set(fingerprint, match);
  }
  const records = [...uniqueRecords.values()];
  const edges: PublicAdvance[] = [];
  for (const round of groupPublicRounds(matches)) {
    if (round.matchday === null || !round.stageId) continue;
    const sameScope = (m: PublicMatch) => m.stage_id === round.stageId && m.group_id === round.groupId;
    const left = records.filter(m => sameScope(m) && m.matchday === round.matchday);
    const right = records.filter(m => sameScope(m) && m.matchday === round.matchday! + 1);
    for (const source of left) {
      const team = source.winner_team_id;
      if (!team || !source.id || conflicts.has(source.id)) continue;
      if ([source.home_team_id, source.away_team_id].filter(id => id === team).length !== 1) continue;
      if (left.filter(m => m.winner_team_id === team).length !== 1) continue;
      const targets = right.flatMap(m => (['home', 'away'] as const)
        .filter(side => m[`${side}_team_id`] === team).map(side => ({ match: m, side })));
      if (targets.length !== 1) continue;
      const target = targets[0]!;
      if (!target.match.id || source.id === target.match.id || conflicts.has(target.match.id)) continue;
      edges.push({ sourceId: source.id, targetId: target.match.id, teamId: team, side: target.side });
    }
  }
  return edges;
}

export function publicRoundLabel(round: PublicBracketRound): { key: string; value?: number } {
  const family = (code: string | null): string | null => {
    if (code === 'FINAL') return 'public.final';
    if (code && /^SF[12]$/.test(code)) return 'public.semifinals';
    if (code && /^QF[1-4]$/.test(code)) return 'public.quarterfinals';
    if (code && /^R16-[1-8]$/.test(code)) return 'public.roundOf16';
    return null;
  };
  const names = round.matches.map(match => family(match.bracket_code));
  const key = names[0];
  if (key && names.every(name => name === key)) return { key };
  return round.matchday === null ? { key: 'public.bracket' } : { key: 'public.round', value: round.matchday };
}
