export const RULES_SCHEMA_VERSION = '3.2.0';
export const RULES_ENGINE_VERSION = '2026.1';

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

export interface TransferRules {
  allow_mid_season_transfers: boolean;
  same_matchday_participation_allowed: boolean;
  roster_lock_matchday: number | null;
}

export interface WalkoverScore {
  winner: number;
  loser: number;
}

export interface StageResolutionRules {
  extra_time_enabled: boolean;
  penalties_enabled: boolean;
  walkover_score: WalkoverScore;
}

export type StageOverride = Partial<StageResolutionRules> & {
  walkover_score?: WalkoverScore;
};

export interface RulesConfig {
  schema_version: string;
  engine_version: string;
  points_system: PointsSystem;
  ranking_pipeline: RankingPipelineItem[];
  substitutions: SubstitutionRules;
  discipline: DisciplineRules;
  transfers: TransferRules;
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
  section: 'rules.error.section',
  invalid_json: 'rules.error.invalidJson',
};

export const DEFAULT_RULES_CONFIG: RulesConfig = {
  schema_version: RULES_SCHEMA_VERSION,
  engine_version: RULES_ENGINE_VERSION,
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
  transfers: {
    allow_mid_season_transfers: true,
    same_matchday_participation_allowed: false,
    roster_lock_matchday: null,
  },
  stage_defaults: {
    extra_time_enabled: false,
    penalties_enabled: false,
    walkover_score: { winner: 3, loser: 0 },
  },
  stage_overrides: {},
};

const RULES_PROPERTY_NAMES = [
  'schema_version',
  'engine_version',
  'points_system',
  'ranking_pipeline',
  'substitutions',
  'discipline',
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

export function cloneRulesConfig<T>(config: T): T {
  return JSON.parse(JSON.stringify(config)) as T;
}

function normalizeNonNegativeInteger(value: unknown, fallback: number): number {
  return isNonNegativeInteger(value) ? value : fallback;
}

function normalizePositiveInteger(value: unknown, fallback: number): number {
  return isPositiveInteger(value) ? value : fallback;
}

function normalizeNullablePositiveInteger(value: unknown, fallback: number | null): number | null {
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

export function normalizeRulesConfig(value: unknown): RulesConfig {
  const source = isRecord(value) ? value : {};
  const points = isRecord(source.points_system) ? source.points_system : {};
  const substitutions = isRecord(source.substitutions) ? source.substitutions : {};
  const discipline = isRecord(source.discipline) ? source.discipline : {};
  const fairPlay = isRecord(discipline.fair_play_penalties) ? discipline.fair_play_penalties : {};
  const transfers = isRecord(source.transfers) ? source.transfers : {};
  const stageDefaults = isRecord(source.stage_defaults) ? source.stage_defaults : {};

  return {
    schema_version: typeof source.schema_version === 'string' ? source.schema_version : RULES_SCHEMA_VERSION,
    engine_version: typeof source.engine_version === 'string' ? source.engine_version : RULES_ENGINE_VERSION,
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
    transfers: {
      allow_mid_season_transfers: normalizeBoolean(
        transfers.allow_mid_season_transfers,
        DEFAULT_RULES_CONFIG.transfers.allow_mid_season_transfers,
      ),
      same_matchday_participation_allowed: normalizeBoolean(
        transfers.same_matchday_participation_allowed,
        DEFAULT_RULES_CONFIG.transfers.same_matchday_participation_allowed,
      ),
      roster_lock_matchday: normalizeNullablePositiveInteger(
        transfers.roster_lock_matchday,
        DEFAULT_RULES_CONFIG.transfers.roster_lock_matchday,
      ),
    },
    stage_defaults: {
      extra_time_enabled: normalizeBoolean(stageDefaults.extra_time_enabled, DEFAULT_RULES_CONFIG.stage_defaults.extra_time_enabled),
      penalties_enabled: normalizeBoolean(stageDefaults.penalties_enabled, DEFAULT_RULES_CONFIG.stage_defaults.penalties_enabled),
      walkover_score: normalizeWalkoverScore(stageDefaults.walkover_score, DEFAULT_RULES_CONFIG.stage_defaults.walkover_score),
    },
    stage_overrides: normalizeStageOverrides(source.stage_overrides),
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
  if (value.schema_version !== RULES_SCHEMA_VERSION) errors.push({ code: 'schema_version', path: 'schema_version' });
  if (value.engine_version !== RULES_ENGINE_VERSION) errors.push({ code: 'engine_version', path: 'engine_version' });

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
  if (!isRecord(substitutions)) {
    errors.push({ code: 'section', path: 'substitutions' });
  } else {
    reportUnknownProperties(substitutions, ['max_per_team', 'max_windows', 'allow_reentry'], 'substitutions', errors);
    for (const field of ['max_per_team', 'max_windows']) {
      if (!isNonNegativeInteger(substitutions[field])) errors.push({ code: 'integer_field', path: `substitutions.${field}` });
    }
    if (typeof substitutions.allow_reentry !== 'boolean') errors.push({ code: 'boolean_field', path: 'substitutions.allow_reentry' });
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

  const transfers = value.transfers;
  if (!isRecord(transfers)) {
    errors.push({ code: 'section', path: 'transfers' });
  } else {
    reportUnknownProperties(
      transfers,
      ['allow_mid_season_transfers', 'same_matchday_participation_allowed', 'roster_lock_matchday'],
      'transfers',
      errors,
    );
    for (const field of ['allow_mid_season_transfers', 'same_matchday_participation_allowed']) {
      if (typeof transfers[field] !== 'boolean') errors.push({ code: 'boolean_field', path: `transfers.${field}` });
    }
    if (transfers.roster_lock_matchday !== null && !isPositiveInteger(transfers.roster_lock_matchday)) {
      errors.push({ code: 'integer_field', path: 'transfers.roster_lock_matchday' });
    }
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
      reportUnknownProperties(override, ['extra_time_enabled', 'penalties_enabled', 'walkover_score'], `stage_overrides.${stageId}`, errors);
      if ('extra_time_enabled' in override && typeof override.extra_time_enabled !== 'boolean') errors.push({ code: 'boolean_field', path: `stage_overrides.${stageId}.extra_time_enabled` });
      if ('penalties_enabled' in override && typeof override.penalties_enabled !== 'boolean') errors.push({ code: 'boolean_field', path: `stage_overrides.${stageId}.penalties_enabled` });
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

function validateStageResolutionSection(value: unknown, path: string, errors: RulesValidationError[]) {
  if (!isRecord(value)) {
    errors.push({ code: 'section', path });
    return;
  }
  reportUnknownProperties(value, ['extra_time_enabled', 'penalties_enabled', 'walkover_score'], path, errors);
  if (typeof value.extra_time_enabled !== 'boolean') errors.push({ code: 'boolean_field', path: `${path}.extra_time_enabled` });
  if (typeof value.penalties_enabled !== 'boolean') errors.push({ code: 'boolean_field', path: `${path}.penalties_enabled` });
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
  return { rules_config: cloneRulesConfig(config) as unknown as Record<string, unknown> };
}
