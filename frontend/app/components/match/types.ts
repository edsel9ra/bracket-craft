import { type FormationCode } from '~/constants/formations';
import { type OperationLimits, type ResolutionType } from '~/utils/matchResolution';
import { type DraftEvent as DraftEventRecord, type MatchLimits } from '~/utils/substitutions';

export type EventType = 'goal' | 'own_goal' | 'penalty_goal' | 'yellow_card' | 'red_card' | 'substitution' | 'foul';

export type RedCardType = 'direct_red' | 'double_yellow_red';

export type OfficialRole = 'main_referee' | 'assistant_referee_1' | 'assistant_referee_2' | 'fourth_official' | 'match_commissioner';

export type LineupRole = 'starter' | 'substitute';

export type SegmentStatus = 'active' | 'completed' | 'interrupted';

export type InterruptionReason = 'lighting_failure' | 'weather' | 'pitch_invasion' | 'other';

export interface MatchRecord {
  id: string;
  tournament_id: string;
  tournament_name: string;
  tournament_version_id: string;
  stage_id: string;
  stage_name: string;
  group_id: string | null;
  group_name: string | null;
  matchday: number | null;
  match_date: string | null;
  status: string;
  result_confirmed: boolean;
  version_status: string;
  home_team_id: string | null;
  home_team_name: string | null;
  home_team_short_code: string | null;
  home_team_crest_url: string | null;
  home_team_logo_url: string | null;
  away_team_id: string | null;
  away_team_name: string | null;
  away_team_short_code: string | null;
  away_team_crest_url: string | null;
  away_team_logo_url: string | null;
  home_score_regular: number | null;
  away_score_regular: number | null;
  home_score: number | null;
  away_score: number | null;
  home_penalties: number | null;
  away_penalties: number | null;
  winner_team_id: string | null;
  resolution_type: ResolutionType | null;
  rules_config?: {
    game_format?: string;
    min_players_per_team?: number | null;
    max_players_per_team?: number | null;
    stage_defaults?: {
      extra_time_enabled?: boolean;
      penalties_enabled?: boolean;
      walkover_score?: { winner: number; loser: number };
    };
  };
}

export interface Segment {
  id: string;
  segment_number: number;
  minute_start: number;
  minute_end: number | null;
  status: SegmentStatus;
}

export interface SegmentInterruption {
  id: string;
  match_id: string;
  segment_id: string;
  reason: InterruptionReason;
  minute: number;
  notes: string | null;
  created_at: string;
}

export interface Official {
  id: string;
  match_id: string;
  organization_user_id: string;
  official_role: OfficialRole;
  full_name: string;
  email: string;
}

export interface EligibleOfficial {
  organization_user_id: string;
  full_name: string;
  email: string;
}

export interface RosterEntry {
  roster_id: string;
  player_id: string;
  team_id: string;
  team_name: string;
  first_name: string;
  last_name: string;
  dorsal_number: number;
  is_active: boolean;
  match_roster_id: string | null;
  role: LineupRole | null;
  entered_minute: number | null;
  left_minute: number | null;
  is_valid: boolean | null;
}

export interface LineupEntry {
  match_roster_id: string;
  roster_id: string;
  player_id: string;
  team_id: string;
  role: LineupRole;
  entered_minute: number | null;
  left_minute: number | null;
  first_name: string;
  last_name: string;
  dorsal_number: number;
  position_slot: string | null;
}

export interface TacticalLineupRow {
  segment_id: string;
  segment_number: number;
  team_id: string;
  formation_code: FormationCode;
  is_public: boolean;
  published_at: string | null;
  player_id: string;
  is_starter: boolean;
  position_slot: string | null;
  first_name: string | null;
  last_name: string | null;
}

export interface MatchEvent {
  id: string;
  client_event_id: string;
  event_type: EventType;
  team_id: string;
  team_name: string;
  beneficiary_team_id: string | null;
  player_id: string;
  player_out_id?: string | null;
  player_in_id?: string | null;
  assist_player_id?: string | null;
  first_name: string;
  last_name: string;
  minute: number;
  added_minute: number;
  segment_id: string;
  metadata: Record<string, unknown>;
  is_voided: boolean;
}

export interface MatchOperation {
  match: MatchRecord;
  segments: Segment[];
  interruptions: SegmentInterruption[];
  officials: Official[];
  eligible_officials: EligibleOfficial[];
  rosters: RosterEntry[];
  lineup: LineupEntry[];
  tactical_lineups: TacticalLineupRow[];
  events: MatchEvent[];
  substitutions?: unknown;
  limits?: (MatchLimits & OperationLimits) | null;
  /**
   * Propuesta del siguiente segmento (spec 017, RF-015). Se declara como
   * `unknown` a propósito: la forma la valida `parseSegmentProposal` en la
   * frontera, así que una respuesta inesperada no rompe el formulario. Es
   * `null` en un partido terminal o con la versión sin publicar.
   */
  next_segment?: unknown;
}

export type DraftEvent = DraftEventRecord<EventType>;

// RNF-007: cada error del alta vive en su campo, con `aria-invalid` y
// `aria-describedby`, y se muestra en el idioma activo. Se guarda la clave y
// sus parámetros (no el texto) para que un cambio de idioma lo reescriba.
export type EventFieldKey =
  | 'event_type'
  | 'segment'
  | 'team'
  | 'player'
  | 'player_out'
  | 'player_in'
  | 'assist'
  | 'beneficiary'
  | 'red_card_type'
  | 'minute'
  | 'added_minute';

export interface EventFieldIssue {
  readonly key: string;
  readonly params?: Record<string, string | number>;
}
