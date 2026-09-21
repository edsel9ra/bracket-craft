import type { FormationCode } from '../constants/formations';
import type { StageFormat } from '../constants/stageFormats';

export interface PublicStage {
  id: string;
  name: string;
  stage_type: StageFormat;
  stage_order: number;
}

export interface PublicTournament {
  id: string;
  name: string;
  season: string;
  start_date: string;
  status: string;
  stages: PublicStage[];
}

export interface PublicStanding {
  stage_id: string;
  stage_name: string;
  stage_order: number;
  group_id: string | null;
  group_name: string | null;
  team_id: string;
  team_name: string;
  short_code: string;
  played: number;
  won: number;
  drawn: number;
  lost: number;
  goals_for: number;
  goals_against: number;
  goal_difference: number;
  points: number;
  fair_play_points: number;
  rank: number;
}

export interface PublicLineupPlayer {
  player_id: string;
  first_name: string;
  last_name: string;
  dorsal_number: number | null;
  role: 'starter' | 'substitute';
  position_slot: string | null;
  photo_url: string | null;
}

export interface PublicTeamLineup {
  team_id: string;
  team_name: string;
  formation_code: FormationCode | null;
  starters: PublicLineupPlayer[];
  substitutes: PublicLineupPlayer[];
}

export interface PublicMatchLineup {
  home: PublicTeamLineup | null;
  away: PublicTeamLineup | null;
}

export interface PublicMatch {
  id: string;
  stage_id: string;
  stage_name: string;
  stage_order: number;
  group_id: string | null;
  group_name: string | null;
  bracket_code: string | null;
  matchday: number | null;
  match_date: string | null;
  home_team_id: string | null;
  home_team_name: string | null;
  home_team_short_code: string | null;
  away_team_id: string | null;
  away_team_name: string | null;
  away_team_short_code: string | null;
  home_score: number | null;
  away_score: number | null;
  home_penalties: number | null;
  away_penalties: number | null;
  status: string;
  resolution_type: string | null;
  winner_team_id: string | null;
  lineup: PublicMatchLineup | null;
}

export type PublicStagePresentation = 'standings' | 'bracket' | 'current';

export function getPublicStagePresentation(stageType: StageFormat): PublicStagePresentation {
  if (stageType === 'single_elimination') return 'bracket';
  if (stageType === 'double_elimination') return 'bracket';
  return 'standings';
}

export function sortPublicStages(stages: readonly PublicStage[]): PublicStage[] {
  return [...stages].sort((left, right) => (
    left.stage_order - right.stage_order || left.id.localeCompare(right.id)
  ));
}

export function usesCurrentDoubleEliminationFormat(stages: readonly PublicStage[]): boolean {
  return stages.length > 0 && stages.every((stage) => stage.stage_type === 'double_elimination');
}
