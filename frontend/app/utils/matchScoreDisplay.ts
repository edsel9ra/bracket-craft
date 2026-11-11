export interface ScoreDisplayInput {
  status: string;
  segments: readonly { minute_start: number }[];
  score: { home: number | null; away: number | null };
  resolution?: string | null;
}

export function matchScoreDisplay(input: ScoreDisplayInput) {
  const final = ['finished', 'administrative_resolution', 'cancelled'].includes(input.status);
  const kind = final ? 'final' : input.segments.length ? 'live' : 'pending';
  return {
    kind,
    home: kind === 'pending' ? null : input.score.home ?? 0,
    away: kind === 'pending' ? null : input.score.away ?? 0,
    labelKey: kind === 'pending' ? 'match.scorePending' : kind === 'final' ? 'match.scoreFinal' : 'match.scoreLive',
  } as const;
}
