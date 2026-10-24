export const RULES_SCHEMA_VERSION = '3.3.0';
export const SUPPORTED_RULES_SCHEMA_VERSIONS = ['3.2.0', '3.3.0'] as const;
export const RULES_ENGINE_VERSION = '2026.1';

export const DEFAULT_REGULAR_TIME_MINUTES = 90;
export const DEFAULT_EXTRA_TIME_MINUTES = 120;

/**
 * RF-042: closed declarative catalog of the game format. `11v11` preserves the
 * compatibility of a configuration that does not declare it yet.
 */
export const GAME_FORMAT_OPTIONS = ['5v5', '7v7', '9v9', '11v11'] as const;
export type GameFormat = (typeof GAME_FORMAT_OPTIONS)[number];
export const DEFAULT_GAME_FORMAT: GameFormat = '11v11';

/** RF-044: 0 means "no limit"; the key may also be absent in an old config. */
export const DEFAULT_PLAYERS_PER_TEAM = 0;

export const RANKING_CRITERIA = [
  'points',
  'head_to_head',
  'goal_difference',
  'goals_for',
  'goals_against',
  'fair_play_points',
  'random_draw',
] as const;

export type RankingCriterion = (typeof RANKING_CRITERIA)[number];

export interface RankingPipelineItem {
  step: number;
  criterion: RankingCriterion;
  params: Record<string, unknown>;
}

export interface PointsSystem {
  win: number;
  draw: number;
  loss: number;
}

export interface SubstitutionRules {
  max_per_team: number;
  max_windows: number;
  allow_reentry: boolean;
}

export interface DisciplineRules {
  yellow_card_limit: number;
  yellow_card_suspension_matches: number;
  direct_red_suspension_matches: number;
  clear_yellows_on_stage_change: boolean;
  fair_play_penalties: {
    yellow_card: number;
    double_yellow_red: number;
    direct_red: number;
  };
}

export interface WalkoverScore {
  winner: number;
  loser: number;
}

export interface StageResolutionRules {
  extra_time_enabled: boolean;
  penalties_enabled: boolean;
  regular_time_minutes: number;
  extra_time_minutes?: number;
  walkover_score: WalkoverScore;
}

export type StageOverride = Partial<StageResolutionRules> & {
  walkover_score?: WalkoverScore;
};

export interface EffectiveStageRules {
  extra_time_enabled: boolean;
  penalties_enabled: boolean;
  regular_time_minutes: number;
  extra_time_minutes: number;
  walkover_score: WalkoverScore;
}

export interface RulesConfig {
  schema_version: string;
  engine_version: string;
  game_format: GameFormat;
  min_players_per_team: number;
  max_players_per_team: number;
  points_system: PointsSystem;
  ranking_pipeline: RankingPipelineItem[];
  substitutions: SubstitutionRules;
  discipline: DisciplineRules;
  roster_lock_matchday: number | null;
  stage_defaults: StageResolutionRules;
  stage_overrides: Record<string, StageOverride>;
}

export interface RulesValidationError {
  code: RulesValidationErrorCode;
  path?: string;
}

export type RulesValidationErrorCode =
  | 'invalid_object'
  | 'schema_version'
  | 'engine_version'
  | 'unknown_property'
  | 'pipeline_required'
  | 'pipeline_item'
  | 'pipeline_step'
  | 'pipeline_criterion'
  | 'pipeline_params'
  | 'pipeline_duplicate'
  | 'pipeline_points_first'
  | 'pipeline_random_last'
  | 'head_to_head_rounds'
  | 'points_field'
  | 'integer_field'
  | 'boolean_field'
  | 'walkover_score'
  | 'minutes_pair'
  | 'game_format'
  | 'roster_limits_pair'
  | 'section'
  | 'invalid_json';

export const RULES_VALIDATION_MESSAGE_KEYS: Record<RulesValidationErrorCode, string> = {
  invalid_object: 'rules.error.invalidObject',
  schema_version: 'rules.error.schemaVersion',
  engine_version: 'rules.error.engineVersion',
  unknown_property: 'rules.error.unknownProperty',
  pipeline_required: 'rules.error.pipelineRequired',
  pipeline_item: 'rules.error.pipelineItem',
  pipeline_step: 'rules.error.pipelineStep',
  pipeline_criterion: 'rules.error.pipelineCriterion',
  pipeline_params: 'rules.error.pipelineParams',
  pipeline_duplicate: 'rules.error.pipelineDuplicate',
  pipeline_points_first: 'rules.error.pipelinePointsFirst',
  pipeline_random_last: 'rules.error.pipelineRandomLast',
  head_to_head_rounds: 'rules.error.headToHeadRounds',
  points_field: 'rules.error.pointsField',
  integer_field: 'rules.error.integerField',
  boolean_field: 'rules.error.booleanField',
  walkover_score: 'rules.error.walkoverScore',
  minutes_pair: 'rules.error.minutesPair',
  game_format: 'rules.error.gameFormat',
  roster_limits_pair: 'rules.error.rosterLimitsPair',
  section: 'rules.error.section',
  invalid_json: 'rules.error.invalidJson',
};

export const DEFAULT_RULES_CONFIG: RulesConfig = {
  schema_version: RULES_SCHEMA_VERSION,
  engine_version: RULES_ENGINE_VERSION,
  game_format: DEFAULT_GAME_FORMAT,
  min_players_per_team: DEFAULT_PLAYERS_PER_TEAM,
  max_players_per_team: DEFAULT_PLAYERS_PER_TEAM,
  points_system: { win: 3, draw: 1, loss: 0 },
  ranking_pipeline: [
    { step: 1, criterion: 'points', params: {} },
    { step: 2, criterion: 'head_to_head', params: { total_rounds_expected: 1 } },
    { step: 3, criterion: 'goal_difference', params: {} },
    { step: 4, criterion: 'goals_for', params: {} },
    { step: 5, criterion: 'fair_play_points', params: {} },
  ],
  substitutions: { max_per_team: 5, max_windows: 3, allow_reentry: false },
  discipline: {
    yellow_card_limit: 3,
    yellow_card_suspension_matches: 1,
    direct_red_suspension_matches: 1,
    clear_yellows_on_stage_change: true,
    fair_play_penalties: { yellow_card: 1, double_yellow_red: 3, direct_red: 3 },
  },
  roster_lock_matchday: null,
  stage_defaults: {
    extra_time_enabled: false,
    penalties_enabled: false,
    regular_time_minutes: DEFAULT_REGULAR_TIME_MINUTES,
    extra_time_minutes: DEFAULT_EXTRA_TIME_MINUTES,
    walkover_score: { winner: 3, loser: 0 },
  },
  stage_overrides: {},
};

const RULES_PROPERTY_NAMES = [
  'schema_version',
  'engine_version',
  'game_format',
  'min_players_per_team',
  'max_players_per_team',
  'points_system',
  'ranking_pipeline',
  'substitutions',
  'discipline',
  'roster_lock_matchday',
  'transfers',
  'stage_defaults',
  'stage_overrides',
] as const;

const isRecord = (value: unknown): value is Record<string, any> => (
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)
);

const isInteger = (value: unknown): value is number => typeof value === 'number' && Number.isInteger(value);
const isNonNegativeInteger = (value: unknown): value is number => isInteger(value) && value >= 0;
const isPositiveInteger = (value: unknown): value is number => isInteger(value) && value >= 1;

export function isRankingCriterion(value: unknown): value is RankingCriterion {
  return typeof value === 'string' && (RANKING_CRITERIA as readonly string[]).includes(value);
}

/** Whether the value belongs to the closed game-format catalog (RF-042). */
export function isGameFormat(value: unknown): value is GameFormat {
  return typeof value === 'string' && (GAME_FORMAT_OPTIONS as readonly string[]).includes(value);
}

/** Declared format, falling back to `11v11` for an absent or unknown value. */
export function normalizeGameFormat(value: unknown): GameFormat {
  return isGameFormat(value) ? value : DEFAULT_GAME_FORMAT;
}

/**
 * Reads a limit field as typed by the user (RF-044). An empty value means
 * "no limit" and normalizes to `0` when leaving the field. Negative, decimal or
 * non-numeric values return `null` so the entered value is kept and the field
 * shows its validation message instead of being silently clamped.
 */
export function readRosterLimitInput(value: unknown): number | null {
  if (value === null || value === undefined) return 0;
  if (typeof value === 'number') {
    return Number.isInteger(value) && value >= 0 ? value : null;
  }
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return 0;
  if (!/^\d+$/.test(trimmed)) return null;
  const parsed = Number(trimmed);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

/** Configuration value of a limit: a non-negative integer, or `0` (RF-044). */
export function normalizeRosterLimit(value: unknown): number {
  return isNonNegativeInteger(value) ? value : DEFAULT_PLAYERS_PER_TEAM;
}

export function cloneRulesConfig<T>(config: T): T {
  return JSON.parse(JSON.stringify(config)) as T;
}

function normalizeNonNegativeInteger(value: unknown, fallback: number): number {
  return isNonNegativeInteger(value) ? value : fallback;
}

function normalizePositiveInteger(value: unknown, fallback: number): number {
  return isPositiveInteger(value) ? value : fallback;
}

function normalizeBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function normalizeWalkoverScore(value: unknown, fallback: WalkoverScore): WalkoverScore {
  const source = isRecord(value) ? value : {};
  return {
    winner: normalizeNonNegativeInteger(source.winner, fallback.winner),
    loser: normalizeNonNegativeInteger(source.loser, fallback.loser),
  };
}

function normalizeStageDefaults(value: unknown): StageResolutionRules {
  const source = isRecord(value) ? value : {};
  const fallback = DEFAULT_RULES_CONFIG.stage_defaults;
  const extraTimeEnabled = normalizeBoolean(source.extra_time_enabled, fallback.extra_time_enabled);
  const regular = isInteger(source.regular_time_minutes)
    ? source.regular_time_minutes
    : DEFAULT_REGULAR_TIME_MINUTES;
  const extra = isInteger(source.extra_time_minutes)
    ? source.extra_time_minutes
    : (extraTimeEnabled && regular < DEFAULT_EXTRA_TIME_MINUTES ? DEFAULT_EXTRA_TIME_MINUTES : undefined);

  return {
    extra_time_enabled: extraTimeEnabled,
    penalties_enabled: normalizeBoolean(source.penalties_enabled, fallback.penalties_enabled),
    regular_time_minutes: regular,
    ...(extra === undefined ? {} : { extra_time_minutes: extra }),
    walkover_score: normalizeWalkoverScore(source.walkover_score, fallback.walkover_score),
  };
}

function normalizePipeline(value: unknown): RankingPipelineItem[] {
  if (!Array.isArray(value)) return cloneRulesConfig(DEFAULT_RULES_CONFIG.ranking_pipeline);
  const candidates = value.flatMap((item) => {
    if (!isRecord(item) || !isRankingCriterion(item.criterion)) return [];
    return [{
      step: isPositiveInteger(item.step) ? item.step : 0,
      criterion: item.criterion,
      params: isRecord(item.params) ? cloneRulesConfig(item.params) : {},
    }];
  });
  const pipeline = recalculatePipeline(candidates);
  return pipeline.length ? pipeline : cloneRulesConfig(DEFAULT_RULES_CONFIG.ranking_pipeline);
}

function normalizeStageOverrides(value: unknown): Record<string, StageOverride> {
  if (!isRecord(value)) return {};
  const overrides: Record<string, StageOverride> = {};
  for (const [stageId, rawOverride] of Object.entries(value)) {
    if (!isRecord(rawOverride)) continue;
    const override: StageOverride = {};
    if (typeof rawOverride.extra_time_enabled === 'boolean') override.extra_time_enabled = rawOverride.extra_time_enabled;
    if (typeof rawOverride.penalties_enabled === 'boolean') override.penalties_enabled = rawOverride.penalties_enabled;
    if (isInteger(rawOverride.regular_time_minutes)) override.regular_time_minutes = rawOverride.regular_time_minutes;
    if (isInteger(rawOverride.extra_time_minutes)) override.extra_time_minutes = rawOverride.extra_time_minutes;
    if (isRecord(rawOverride.walkover_score)) {
      override.walkover_score = normalizeWalkoverScore(rawOverride.walkover_score, DEFAULT_RULES_CONFIG.stage_defaults.walkover_score);
    }
    overrides[stageId] = override;
  }
  return overrides;
}

function reportUnknownProperties(
  value: Record<string, any>,
  allowed: readonly string[],
  path: string,
  errors: RulesValidationError[],
) {
  for (const key of Object.keys(value)) {
    if (!allowed.includes(key)) errors.push({ code: 'unknown_property', path: `${path}.${key}` });
  }
}

export function normalizeRosterLockMatchday(value: unknown): number | null {
  return isPositiveInteger(value) ? value : null;
}

export function normalizeRulesConfig(value: unknown): RulesConfig {
  const source = isRecord(value) ? value : {};
  const points = isRecord(source.points_system) ? source.points_system : {};
  const substitutions = isRecord(source.substitutions) ? source.substitutions : {};
  const discipline = isRecord(source.discipline) ? source.discipline : {};
  const fairPlay = isRecord(discipline.fair_play_penalties) ? discipline.fair_play_penalties : {};
  const transfers = isRecord(source.transfers) ? source.transfers : {};
  const rosterLockMatchday = normalizeRosterLockMatchday(source.roster_lock_matchday)
    ?? normalizeRosterLockMatchday(transfers.roster_lock_matchday);

  return {
    schema_version: RULES_SCHEMA_VERSION,
    engine_version: typeof source.engine_version === 'string' ? source.engine_version : RULES_ENGINE_VERSION,
    game_format: normalizeGameFormat(source.game_format),
    min_players_per_team: normalizeRosterLimit(source.min_players_per_team),
    max_players_per_team: normalizeRosterLimit(source.max_players_per_team),
    points_system: {
      win: normalizeNonNegativeInteger(points.win, DEFAULT_RULES_CONFIG.points_system.win),
      draw: normalizeNonNegativeInteger(points.draw, DEFAULT_RULES_CONFIG.points_system.draw),
      loss: normalizeNonNegativeInteger(points.loss, DEFAULT_RULES_CONFIG.points_system.loss),
    },
    ranking_pipeline: normalizePipeline(source.ranking_pipeline),
    substitutions: {
      max_per_team: normalizeNonNegativeInteger(substitutions.max_per_team, DEFAULT_RULES_CONFIG.substitutions.max_per_team),
      max_windows: normalizeNonNegativeInteger(substitutions.max_windows, DEFAULT_RULES_CONFIG.substitutions.max_windows),
      allow_reentry: normalizeBoolean(substitutions.allow_reentry, DEFAULT_RULES_CONFIG.substitutions.allow_reentry),
    },
    discipline: {
      yellow_card_limit: normalizePositiveInteger(discipline.yellow_card_limit, DEFAULT_RULES_CONFIG.discipline.yellow_card_limit),
      yellow_card_suspension_matches: normalizePositiveInteger(
        discipline.yellow_card_suspension_matches,
        DEFAULT_RULES_CONFIG.discipline.yellow_card_suspension_matches,
      ),
      direct_red_suspension_matches: normalizePositiveInteger(
        discipline.direct_red_suspension_matches,
        DEFAULT_RULES_CONFIG.discipline.direct_red_suspension_matches,
      ),
      clear_yellows_on_stage_change: normalizeBoolean(
        discipline.clear_yellows_on_stage_change,
        DEFAULT_RULES_CONFIG.discipline.clear_yellows_on_stage_change,
      ),
      fair_play_penalties: {
        yellow_card: normalizeNonNegativeInteger(fairPlay.yellow_card, DEFAULT_RULES_CONFIG.discipline.fair_play_penalties.yellow_card),
        double_yellow_red: normalizeNonNegativeInteger(
          fairPlay.double_yellow_red,
          DEFAULT_RULES_CONFIG.discipline.fair_play_penalties.double_yellow_red,
        ),
        direct_red: normalizeNonNegativeInteger(fairPlay.direct_red, DEFAULT_RULES_CONFIG.discipline.fair_play_penalties.direct_red),
      },
    },
    roster_lock_matchday: rosterLockMatchday,
    stage_defaults: normalizeStageDefaults(source.stage_defaults),
    stage_overrides: normalizeStageOverrides(source.stage_overrides),
  };
}

export function effectiveStageRules(config: RulesConfig, stageId?: string | null): EffectiveStageRules {
  const defaults = config.stage_defaults;
  const override = stageId ? config.stage_overrides?.[stageId] : undefined;
  return {
    extra_time_enabled: override?.extra_time_enabled ?? defaults.extra_time_enabled,
    penalties_enabled: override?.penalties_enabled ?? defaults.penalties_enabled,
    regular_time_minutes: override?.regular_time_minutes ?? defaults.regular_time_minutes ?? DEFAULT_REGULAR_TIME_MINUTES,
    extra_time_minutes: override?.extra_time_minutes ?? defaults.extra_time_minutes ?? DEFAULT_EXTRA_TIME_MINUTES,
    walkover_score: override?.walkover_score ?? defaults.walkover_score,
  };
}

export function removeDuplicateCriteria(
  pipeline: ReadonlyArray<Partial<RankingPipelineItem> & { criterion: RankingCriterion }>,
): RankingPipelineItem[] {
  const seen = new Set<RankingCriterion>();
  return pipeline.flatMap((item) => {
    if (seen.has(item.criterion)) return [];
    seen.add(item.criterion);
    return [{
      step: isPositiveInteger(item.step) ? item.step : 0,
      criterion: item.criterion,
      params: isRecord(item.params) ? cloneRulesConfig(item.params) : {},
    }];
  });
}

export function recalculatePipeline(
  pipeline: ReadonlyArray<Partial<RankingPipelineItem> & { criterion: RankingCriterion }>,
): RankingPipelineItem[] {
  return removeDuplicateCriteria(pipeline).map((item, index) => ({ ...item, step: index + 1 }));
}

export function validateRulesConfig(value: unknown): RulesValidationError[] {
  if (!isRecord(value)) return [{ code: 'invalid_object' }];
  const errors: RulesValidationError[] = [];

  for (const key of Object.keys(value)) {
    if (!(RULES_PROPERTY_NAMES as readonly string[]).includes(key)) errors.push({ code: 'unknown_property', path: key });
  }
  if (!(SUPPORTED_RULES_SCHEMA_VERSIONS as readonly unknown[]).includes(value.schema_version)) {
    errors.push({ code: 'schema_version', path: 'schema_version' });
  }
  if (value.engine_version !== RULES_ENGINE_VERSION) errors.push({ code: 'engine_version', path: 'engine_version' });

  // RF-042: absent means the compatible default; a declared value must be in
  // the closed catalog.
  if (value.game_format !== undefined && !isGameFormat(value.game_format)) {
    errors.push({ code: 'game_format', path: 'game_format' });
  }

  // RF-044: optional non-negative integers; absent means "no limit".
  for (const field of ['min_players_per_team', 'max_players_per_team'] as const) {
    if (value[field] !== undefined && !isNonNegativeInteger(value[field])) {
      errors.push({ code: 'integer_field', path: field });
    }
  }
  const minPlayers = isNonNegativeInteger(value.min_players_per_team) ? value.min_players_per_team : 0;
  const maxPlayers = isNonNegativeInteger(value.max_players_per_team) ? value.max_players_per_team : 0;
  // The pair is only constrained when both declare a limit. The format never
  // takes part in this rule (RF-043).
  if (minPlayers > 0 && maxPlayers > 0 && minPlayers > maxPlayers) {
    errors.push({ code: 'roster_limits_pair', path: 'max_players_per_team' });
  }

  const rosterLockMatchday = value.roster_lock_matchday === '' ? null : value.roster_lock_matchday;
  if (rosterLockMatchday !== undefined
    && rosterLockMatchday !== null
    && !isPositiveInteger(rosterLockMatchday)) {
    errors.push({ code: 'integer_field', path: 'roster_lock_matchday' });
  }

  const points = value.points_system;
  if (!isRecord(points)) {
    errors.push({ code: 'section', path: 'points_system' });
  } else {
    reportUnknownProperties(points, ['win', 'draw', 'loss'], 'points_system', errors);
    for (const field of ['win', 'draw', 'loss']) {
      if (!isNonNegativeInteger(points[field])) errors.push({ code: 'points_field', path: `points_system.${field}` });
    }
  }

  const pipeline = value.ranking_pipeline;
  if (!Array.isArray(pipeline) || pipeline.length < 1) {
    errors.push({ code: 'pipeline_required', path: 'ranking_pipeline' });
  } else {
    const criteria: string[] = [];
    pipeline.forEach((item, index) => {
      if (!isRecord(item)) {
        errors.push({ code: 'pipeline_item', path: `ranking_pipeline.${index}` });
        return;
      }
      reportUnknownProperties(item, ['step', 'criterion', 'params'], `ranking_pipeline.${index}`, errors);
      if (!isPositiveInteger(item.step) || item.step !== index + 1) errors.push({ code: 'pipeline_step', path: `ranking_pipeline.${index}.step` });
      if (!isRankingCriterion(item.criterion)) {
        errors.push({ code: 'pipeline_criterion', path: `ranking_pipeline.${index}.criterion` });
      } else {
        if (criteria.includes(item.criterion)) errors.push({ code: 'pipeline_duplicate', path: `ranking_pipeline.${index}.criterion` });
        criteria.push(item.criterion);
        if (index === 0 && item.criterion !== 'points') errors.push({ code: 'pipeline_points_first', path: 'ranking_pipeline' });
        if (item.criterion === 'random_draw' && index !== pipeline.length - 1) errors.push({ code: 'pipeline_random_last', path: `ranking_pipeline.${index}.criterion` });
        if (item.criterion === 'head_to_head') {
          const rounds = isRecord(item.params) ? item.params.total_rounds_expected : undefined;
          if (!isInteger(rounds) || ![1, 2].includes(rounds)) errors.push({ code: 'head_to_head_rounds', path: `ranking_pipeline.${index}.params.total_rounds_expected` });
        }
      }
      if (!isRecord(item.params)) errors.push({ code: 'pipeline_params', path: `ranking_pipeline.${index}.params` });
    });
  }

  const substitutions = value.substitutions;
  if (substitutions !== undefined) {
    if (!isRecord(substitutions)) {
      errors.push({ code: 'section', path: 'substitutions' });
    } else {
      reportUnknownProperties(substitutions, ['max_per_team', 'max_windows', 'allow_reentry'], 'substitutions', errors);
      for (const field of ['max_per_team', 'max_windows']) {
        if (!isNonNegativeInteger(substitutions[field])) errors.push({ code: 'integer_field', path: `substitutions.${field}` });
      }
      if (typeof substitutions.allow_reentry !== 'boolean') errors.push({ code: 'boolean_field', path: 'substitutions.allow_reentry' });
    }
  }

  const discipline = value.discipline;
  if (!isRecord(discipline)) {
    errors.push({ code: 'section', path: 'discipline' });
  } else {
    reportUnknownProperties(
      discipline,
      ['yellow_card_limit', 'yellow_card_suspension_matches', 'direct_red_suspension_matches', 'clear_yellows_on_stage_change', 'fair_play_penalties'],
      'discipline',
      errors,
    );
    for (const field of ['yellow_card_limit', 'yellow_card_suspension_matches', 'direct_red_suspension_matches']) {
      if (!isPositiveInteger(discipline[field])) errors.push({ code: 'integer_field', path: `discipline.${field}` });
    }
    if (typeof discipline.clear_yellows_on_stage_change !== 'boolean') errors.push({ code: 'boolean_field', path: 'discipline.clear_yellows_on_stage_change' });
    const fairPlay = discipline.fair_play_penalties;
    if (!isRecord(fairPlay)) {
      errors.push({ code: 'section', path: 'discipline.fair_play_penalties' });
    } else {
      reportUnknownProperties(fairPlay, ['yellow_card', 'double_yellow_red', 'direct_red'], 'discipline.fair_play_penalties', errors);
      for (const field of ['yellow_card', 'double_yellow_red', 'direct_red']) {
        if (!isNonNegativeInteger(fairPlay[field])) errors.push({ code: 'integer_field', path: `discipline.fair_play_penalties.${field}` });
      }
    }
  }

  // Deprecated block: accepted and ignored. It is never emitted again.
  if (value.transfers !== undefined && !isRecord(value.transfers)) {
    errors.push({ code: 'section', path: 'transfers' });
  }

  validateStageResolutionSection(value.stage_defaults, 'stage_defaults', errors);
  const overrides = value.stage_overrides;
  if (!isRecord(overrides)) {
    errors.push({ code: 'section', path: 'stage_overrides' });
  } else {
    for (const [stageId, override] of Object.entries(overrides)) {
      if (!isRecord(override)) {
        errors.push({ code: 'section', path: `stage_overrides.${stageId}` });
        continue;
      }
      reportUnknownProperties(override, STAGE_RESOLUTION_PROPERTIES, `stage_overrides.${stageId}`, errors);
      if ('extra_time_enabled' in override && typeof override.extra_time_enabled !== 'boolean') errors.push({ code: 'boolean_field', path: `stage_overrides.${stageId}.extra_time_enabled` });
      if ('penalties_enabled' in override && typeof override.penalties_enabled !== 'boolean') errors.push({ code: 'boolean_field', path: `stage_overrides.${stageId}.penalties_enabled` });
      validateMinutesFields(override, `stage_overrides.${stageId}`, errors);
      validateOverrideMinutes(value.stage_defaults, override, `stage_overrides.${stageId}`, errors);
      if ('walkover_score' in override) validateWalkoverScore(override.walkover_score, `stage_overrides.${stageId}.walkover_score`, errors);
    }
  }

  return errors;
}

function validateWalkoverScore(value: unknown, path: string, errors: RulesValidationError[]) {
  if (!isRecord(value) || !isNonNegativeInteger(value.winner) || !isNonNegativeInteger(value.loser)) {
    errors.push({ code: 'walkover_score', path });
    return;
  }
  reportUnknownProperties(value, ['winner', 'loser'], path, errors);
}

const STAGE_RESOLUTION_PROPERTIES = [
  'extra_time_enabled',
  'penalties_enabled',
  'regular_time_minutes',
  'extra_time_minutes',
  'walkover_score',
] as const;

function isRegularMinutes(value: unknown): value is number {
  return isInteger(value) && value >= 1 && value <= 179;
}

function declaredMinutes(
  value: Record<string, any>,
  fallback: { enabled: boolean; regular: number; extra: number },
): { enabled: boolean; regular: number; extra: number } {
  return {
    enabled: typeof value.extra_time_enabled === 'boolean' ? value.extra_time_enabled : fallback.enabled,
    regular: isInteger(value.regular_time_minutes) ? value.regular_time_minutes : fallback.regular,
    extra: isInteger(value.extra_time_minutes) ? value.extra_time_minutes : fallback.extra,
  };
}

function validateMinutesFields(value: Record<string, any>, path: string, errors: RulesValidationError[]) {
  if ('regular_time_minutes' in value && !isRegularMinutes(value.regular_time_minutes)) {
    errors.push({ code: 'integer_field', path: `${path}.regular_time_minutes` });
  }
  if ('extra_time_minutes' in value && !isInteger(value.extra_time_minutes)) {
    errors.push({ code: 'integer_field', path: `${path}.extra_time_minutes` });
  }
}

function validateMinutesPair(
  minutes: { enabled: boolean; regular: number; extra: number },
  path: string,
  errors: RulesValidationError[],
) {
  if (!minutes.enabled) return;
  if (!(minutes.regular < minutes.extra && minutes.extra <= 180)) {
    errors.push({ code: 'minutes_pair', path: `${path}.extra_time_minutes` });
  }
}

function baseMinutes(stageDefaults: unknown) {
  const value = isRecord(stageDefaults) ? stageDefaults : {};
  return {
    enabled: value.extra_time_enabled === true,
    regular: isRegularMinutes(value.regular_time_minutes) ? value.regular_time_minutes : DEFAULT_REGULAR_TIME_MINUTES,
    extra: isInteger(value.extra_time_minutes) ? value.extra_time_minutes : DEFAULT_EXTRA_TIME_MINUTES,
  };
}

function validateOverrideMinutes(
  stageDefaults: unknown,
  override: Record<string, any>,
  path: string,
  errors: RulesValidationError[],
) {
  const merged = declaredMinutes(override, baseMinutes(stageDefaults));
  const regularIsValid = !('regular_time_minutes' in override) || isRegularMinutes(override.regular_time_minutes);
  const extraIsValid = !('extra_time_minutes' in override) || isInteger(override.extra_time_minutes);
  if (regularIsValid && extraIsValid) validateMinutesPair(merged, path, errors);
}

function validateStageResolutionSection(value: unknown, path: string, errors: RulesValidationError[]) {
  if (!isRecord(value)) {
    errors.push({ code: 'section', path });
    return;
  }
  reportUnknownProperties(value, STAGE_RESOLUTION_PROPERTIES, path, errors);
  if (typeof value.extra_time_enabled !== 'boolean') errors.push({ code: 'boolean_field', path: `${path}.extra_time_enabled` });
  if (typeof value.penalties_enabled !== 'boolean') errors.push({ code: 'boolean_field', path: `${path}.penalties_enabled` });
  validateMinutesFields(value, path, errors);
  const regularIsValid = !('regular_time_minutes' in value) || isRegularMinutes(value.regular_time_minutes);
  const extraIsValid = !('extra_time_minutes' in value) || isInteger(value.extra_time_minutes);
  if (regularIsValid && extraIsValid) {
    validateMinutesPair(declaredMinutes(value, baseMinutes(value)), path, errors);
  }
  validateWalkoverScore(value.walkover_score, `${path}.walkover_score`, errors);
}

export interface ParsedRulesConfig {
  config: RulesConfig | null;
  errors: RulesValidationError[];
}

export function parseRulesConfigJson(value: string): ParsedRulesConfig {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    return { config: null, errors: [{ code: 'invalid_json' }] };
  }
  const errors = validateRulesConfig(parsed);
  return errors.length
    ? { config: null, errors }
    : { config: normalizeRulesConfig(parsed), errors: [] };
}

export function serializeRulesConfig(config: RulesConfig): string {
  return JSON.stringify(cloneRulesConfig(config), null, 2);
}

export function buildRulesRequest(config: RulesConfig): { rules_config: Record<string, unknown> } {
  return { rules_config: normalizeRulesConfig(config) as unknown as Record<string, unknown> };
}
