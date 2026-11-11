import type { StageFormat } from '~/constants/stageFormats';

export interface VersionSummary {
  id: string;
  version_number: number;
  status: string;
  rules_config?: Record<string, unknown>;
}

export interface VersionDetail extends VersionSummary {
  rules_config: Record<string, unknown>;
}

export interface StageSummary {
  id: string;
  tournament_version_id: string;
  name: string;
  stage_type: StageFormat;
  stage_order: number;
  version_status: string;
}

export interface TeamSummary {
  team_id: string;
  name: string;
  short_code: string;
  status: string;
  stage_ids: string[];
  logo_url?: string | null;
  crest_url?: string | null;
}

export interface TeamCrestResponse {
  team_id: string;
  crest_url: string | null;
  logo_url: string | null;
}

export interface RosterSummary {
  roster_id: string;
  team_id: string;
  first_name: string;
  last_name: string;
  dorsal_number: number;
  age: number;
  photo_url: string | null;
  photo_consent: boolean;
  is_active: boolean;
}

export interface MatchSummary {
  id: string;
  tournament_version_id: string;
  stage_id: string;
  bracket_code: string | null;
  home_team_id: string | null;
  away_team_id: string | null;
  matchday: number | null;
  match_date: string | null;
  home_team_name: string | null;
  away_team_name: string | null;
  status: string;
  home_score: number | null;
  away_score: number | null;
}

export interface ConfigurationData {
  versions: VersionSummary[];
  stages: StageSummary[];
  teams: TeamSummary[];
  rosters: RosterSummary[];
  matches: MatchSummary[];
}

export interface SetupServices {
  auth: ReturnType<typeof useAuthStore>;
  request: ReturnType<typeof useApi>['request'];
  t: ReturnType<typeof useI18n>['t'];
  confirm: ReturnType<typeof useConfirm>['confirm'];
  tournamentId: string;
  redirectOnSessionFailure(cause: unknown): Promise<boolean>;
  failureMessage(cause: unknown, fallback: string): string;
}
