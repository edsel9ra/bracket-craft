/**
 * Asistente de reglas: pasos, errores por campo y carga completa
 * (spec 012, RF-001, RF-004, RF-005, RF-006, RF-007, RF-009).
 *
 * El módulo es puro: no lee el reloj, el entorno, el almacenamiento ni la red.
 * No valida ni serializa por su cuenta: reutiliza `validateRulesConfig`,
 * `normalizeRulesConfig` y `buildRulesRequest` de `rulesConfig.ts`, que siguen
 * siendo la única fuente de la validación y del contrato de `rules_config`.
 * Lo único que añade es la organización de esos errores por paso y por campo.
 */

import {
  DEFAULT_GAME_FORMAT,
  RULES_VALIDATION_MESSAGE_KEYS,
  buildRulesRequest,
  isGameFormat,
  normalizeRulesConfig,
  type RulesConfig,
  type RulesValidationError,
  type RulesValidationErrorCode,
} from './rulesConfig.ts';
import {
  canConfirm,
  wizardSteps,
  wizardStepStates,
  type RulesStepId,
  type WizardErrors,
  type WizardStepId,
  type WizardStepStatus,
  type WizardTranslate,
  type WizardValues,
} from './wizardModel.ts';

/** Traducción con parámetros, como la que ofrece `useI18n()`. */
export type RulesTranslate = (key: string, values?: Record<string, string | number>) => string;

/** Sección editable de `RulesEditor` que corresponde a cada paso. */
export type RulesSectionId =
  | 'scoring'
  | 'tiebreakers'
  | 'discipline'
  | 'resolution'
  | 'format'
  | 'substitutions'
  | 'registration'
  | 'overrides';

/** Orden de las secciones del editor, que es también el orden de los pasos. */
export const RULES_SECTIONS: readonly RulesSectionId[] = [
  'scoring',
  'tiebreakers',
  'discipline',
  'resolution',
  'format',
  'substitutions',
  'registration',
  'overrides',
];

/** Sección que muestra cada paso del asistente. */
export const RULES_STEP_SECTIONS: Readonly<Record<RulesStepId, RulesSectionId>> = {
  'rules.scoring': 'scoring',
  'rules.tiebreakers': 'tiebreakers',
  'rules.discipline': 'discipline',
  'rules.resolution': 'resolution',
  'rules.format': 'format',
  'rules.substitutions': 'substitutions',
  'rules.registration': 'registration',
  'rules.overrides': 'overrides',
};

/** Pasos declarados del asistente de reglas, en su orden estable. */
export const RULES_STEP_IDS: readonly RulesStepId[] = wizardSteps('rules').map(
  (step) => step.id as RulesStepId,
);

/** Sección del editor que muestra un paso. */
export function rulesSectionForStep(step: WizardStepId): RulesSectionId {
  return RULES_STEP_SECTIONS[step as RulesStepId] ?? 'scoring';
}

const STEP_LABEL_KEYS: Readonly<Record<RulesStepId, string>> = Object.fromEntries(
  wizardSteps('rules').map((step) => [step.id, step.labelKey]),
) as Record<RulesStepId, string>;

/**
 * Paso al que pertenece un camino de la configuración, o `null` cuando el error
 * no es de un campo de un paso (por ejemplo, el JSON avanzado o una clave raíz).
 */
export function rulesStepForPath(path?: string | null): RulesStepId | null {
  if (typeof path !== 'string' || !path.trim()) return null;
  const root = path.trim().split('.')[0] ?? '';
  switch (root) {
    case 'points_system':
      return 'rules.scoring';
    case 'ranking_pipeline':
      return 'rules.tiebreakers';
    case 'discipline':
      return 'rules.discipline';
    case 'stage_defaults':
      return 'rules.resolution';
    case 'game_format':
    case 'min_players_per_team':
    case 'max_players_per_team':
      return 'rules.format';
    case 'substitutions':
      return 'rules.substitutions';
    case 'roster_lock_matchday':
    case 'transfers':
      return 'rules.registration';
    case 'stage_overrides':
      return 'rules.overrides';
    default:
      return null;
  }
}

/**
 * Clave i18n de la etiqueta del campo. Se apoya en las etiquetas que ya usa el
 * editor; los caminos dinámicos (desempates y excepciones por fase) se resuelven
 * por su sufijo.
 */
const EXACT_FIELD_LABELS: Readonly<Record<string, string>> = {
  schema_version: 'rules.field.schemaVersion',
  engine_version: 'rules.field.engineVersion',
  points_system: 'rules.pointsSection',
  'points_system.win': 'rules.winPoints',
  'points_system.draw': 'rules.drawPoints',
  'points_system.loss': 'rules.lossPoints',
  ranking_pipeline: 'rules.pipelineSection',
  substitutions: 'rules.substitutionsSection',
  'substitutions.max_per_team': 'rules.maxPerTeam',
  'substitutions.max_windows': 'rules.maxWindows',
  'substitutions.allow_reentry': 'rules.allowReentry',
  discipline: 'rules.disciplineSection',
  'discipline.yellow_card_limit': 'rules.yellowCardLimit',
  'discipline.yellow_card_suspension_matches': 'rules.yellowCardSuspensionMatches',
  'discipline.direct_red_suspension_matches': 'rules.directRedSuspensionMatches',
  'discipline.clear_yellows_on_stage_change': 'rules.clearYellowsOnStageChange',
  'discipline.fair_play_penalties': 'rules.fairPlayPenalties',
  'discipline.fair_play_penalties.yellow_card': 'rules.fairPlayYellow',
  'discipline.fair_play_penalties.double_yellow_red': 'rules.fairPlayDoubleYellow',
  'discipline.fair_play_penalties.direct_red': 'rules.fairPlayDirectRed',
  roster_lock_matchday: 'rules.rosterLockMatchday',
  transfers: 'rules.registrationSection',
  'transfers.roster_lock_matchday': 'rules.rosterLockMatchday',
  stage_defaults: 'rules.resolutionSection',
  'stage_defaults.extra_time_enabled': 'rules.extraTime',
  'stage_defaults.penalties_enabled': 'rules.penalties',
  'stage_defaults.regular_time_minutes': 'rules.regularTimeMinutes',
  'stage_defaults.extra_time_minutes': 'rules.extraTimeMinutes',
  'stage_defaults.walkover_score': 'rules.walkoverWinnerScore',
  'stage_defaults.walkover_score.winner': 'rules.walkoverWinnerScore',
  'stage_defaults.walkover_score.loser': 'rules.walkoverLoserScore',
  stage_overrides: 'rules.stageOverridesSection',
  game_format: 'rules.field.gameFormat',
  min_players_per_team: 'rules.field.minPlayers',
  max_players_per_team: 'rules.field.maxPlayers',
};

const PIPELINE_PREFIX = /^ranking_pipeline\.\d+\.(.+)$/;
const OVERRIDE_PREFIX = /^stage_overrides\.[^.]+(?:\.(.+))?$/;

/** Clave i18n de la etiqueta legible de un camino de la configuración. */
export function rulesFieldLabelKey(path?: string | null): string {
  if (typeof path !== 'string' || !path.trim()) return 'rules.field.rulesConfig';
  const trimmed = path.trim();
  const exact = EXACT_FIELD_LABELS[trimmed];
  if (exact) return exact;

  const pipeline = PIPELINE_PREFIX.exec(trimmed);
  if (pipeline) {
    const rest = pipeline[1] ?? '';
    if (rest === 'criterion') return 'rules.criterion';
    if (rest === 'step') return 'rules.field.criterionStep';
    if (rest === 'params' || rest.startsWith('params.')) {
      return rest.endsWith('total_rounds_expected') ? 'rules.headToHeadRounds' : 'rules.parameters';
    }
    return 'rules.pipelineSection';
  }

  const override = OVERRIDE_PREFIX.exec(trimmed);
  if (override) {
    const rest = override[1];
    if (!rest) return 'rules.stageOverridesSection';
    return EXACT_FIELD_LABELS[`stage_defaults.${rest}`] ?? 'rules.field.stageOverride';
  }

  if (trimmed.startsWith('points_system.')) return 'rules.pointsSection';
  if (trimmed.startsWith('discipline.')) return 'rules.disciplineSection';
  if (trimmed.startsWith('substitutions.')) return 'rules.substitutionsSection';
  if (trimmed.startsWith('stage_defaults.')) return 'rules.resolutionSection';
  return 'rules.field.rulesConfig';
}

/** Campos del paso de formato y límites que muestran su error junto al control. */
export type RulesInlineField = 'game_format' | 'min_players_per_team' | 'max_players_per_team';

/** Identificadores estables de los mensajes asociados con `aria-describedby`. */
export const RULES_INLINE_FIELD_IDS: Readonly<Record<RulesInlineField, string>> = {
  game_format: 'rules-field-game-format-error',
  min_players_per_team: 'rules-field-min-players-error',
  max_players_per_team: 'rules-field-max-players-error',
};

/** Identificadores de las ayudas de los mismos campos y del bloque de límites. */
export const RULES_FIELD_HINT_IDS = {
  game_format: 'rules-field-game-format-hint',
  limits: 'rules-field-limits-hint',
} as const;

/** Si el camino del error se pinta junto a su control (RF-005). */
export function isInlineRulesField(path?: string | null): path is RulesInlineField {
  return typeof path === 'string' && Object.hasOwn(RULES_INLINE_FIELD_IDS, path);
}

/** Error de un campo concreto, o `null` si no tiene ninguno. */
export function inlineFieldIssue(
  issues: readonly RulesFieldIssue[],
  field: RulesInlineField,
): RulesFieldIssue | null {
  return issues.find((issue) => issue.path === field) ?? null;
}

/**
 * Problemas del resumen del paso que **no** se duplican junto al campo. El
 * resumen sigue existiendo para el resto de problemas; los de formato y
 * límites se anuncian en su control.
 */
export function summaryFieldIssues(
  issues: readonly RulesFieldIssue[],
): RulesFieldIssue[] {
  return issues.filter((issue) => !isInlineRulesField(issue.path));
}

/** Código de un problema mostrado por el asistente. */
export type RulesIssueCode = RulesValidationErrorCode | 'server_field';

/** Clave i18n del mensaje de cada código. */
export const RULES_ISSUE_MESSAGE_KEYS: Readonly<Record<RulesIssueCode, string>> = {
  ...RULES_VALIDATION_MESSAGE_KEYS,
  server_field: 'rules.error.serverField',
};

/** Un error ya organizado: campo, paso y mensaje traducible. */
export interface RulesFieldIssue {
  readonly code: RulesIssueCode;
  readonly path: string | null;
  readonly stepId: RulesStepId | null;
  readonly fieldLabelKey: string;
  readonly messageKey: string;
}

/** Convierte los errores de `validateRulesConfig` en problemas por campo. */
export function rulesIssues(
  errors: readonly RulesValidationError[] = [],
): RulesFieldIssue[] {
  return errors.map((error) => {
    const path = error.path ?? null;
    return {
      code: error.code,
      path,
      stepId: rulesStepForPath(path),
      fieldLabelKey: rulesFieldLabelKey(path),
      messageKey: RULES_VALIDATION_MESSAGE_KEYS[error.code] ?? 'rules.error.invalidObject',
    };
  });
}

function locSegments(detail: unknown): string[] {
  if (!detail || typeof detail !== 'object') return [];
  const loc = (detail as { loc?: unknown }).loc;
  if (!Array.isArray(loc)) return [];
  return loc.filter((segment): segment is string => typeof segment === 'string');
}

/**
 * Detalle de validación de un 422 tal como lo devuelve la API, si lo trae. La
 * extracción es deliberadamente estrecha: solo se usa para ubicar el campo, no
 * para mostrar el cuerpo de la respuesta.
 */
export function serverValidationDetail(cause: unknown): unknown[] | null {
  if (!cause || typeof cause !== 'object') return null;
  const data = (cause as { data?: unknown }).data;
  if (!data || typeof data !== 'object') return null;
  const detail = (data as { detail?: unknown }).detail;
  return Array.isArray(detail) ? detail : null;
}

/**
 * Mapea el detalle de validación del servidor al paso y al campo. El mensaje
 * mostrado es siempre el traducido del proyecto: nunca el `msg` del cuerpo.
 */
export function rulesServerIssues(detail: unknown): RulesFieldIssue[] {
  if (!Array.isArray(detail)) return [];
  const issues: RulesFieldIssue[] = [];
  for (const entry of detail) {
    const segments = locSegments(entry);
    const configIndex = segments.indexOf('rules_config');
    const rest = configIndex >= 0
      ? segments.slice(configIndex + 1)
      : segments.filter((segment) => !['body', 'query', 'path', 'header'].includes(segment));
    const path = rest.length ? rest.join('.') : null;
    issues.push({
      code: 'server_field',
      path,
      stepId: rulesStepForPath(path),
      fieldLabelKey: rulesFieldLabelKey(path),
      messageKey: 'rules.error.serverField',
    });
  }
  return issues;
}

/** Problemas agrupados por paso, más los que no pertenecen a ningún paso. */
export interface RulesErrorsByStep {
  readonly byStep: Readonly<Record<RulesStepId, readonly RulesFieldIssue[]>>;
  readonly global: readonly RulesFieldIssue[];
}

/** Agrupa los problemas por paso conservando el orden de entrada. */
export function rulesErrorsByStep(
  issues: readonly RulesFieldIssue[],
): RulesErrorsByStep {
  const byStep = Object.fromEntries(
    RULES_STEP_IDS.map((stepId) => [stepId, [] as RulesFieldIssue[]]),
  ) as Record<RulesStepId, RulesFieldIssue[]>;
  const global: RulesFieldIssue[] = [];

  for (const issue of issues) {
    if (issue.stepId && byStep[issue.stepId]) byStep[issue.stepId].push(issue);
    else global.push(issue);
  }

  return { byStep, global };
}

/** Errores por paso en el formato que consume el índice (`stepState`). */
export function rulesWizardErrors(
  issues: readonly RulesFieldIssue[],
): WizardErrors {
  const { byStep } = rulesErrorsByStep(issues);
  const errors: Record<string, readonly string[]> = {};
  for (const stepId of RULES_STEP_IDS) {
    const stepIssues = byStep[stepId];
    if (stepIssues.length) errors[stepId] = stepIssues.map((issue) => issue.messageKey);
  }
  return errors;
}

const isRecord = (value: unknown): value is Record<string, unknown> => (
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)
);

const isPositiveInteger = (value: unknown): value is number => (
  typeof value === 'number' && Number.isInteger(value) && value >= 1
);

const isNonNegativeInteger = (value: unknown): value is number => (
  typeof value === 'number' && Number.isInteger(value) && value >= 0
);

/**
 * Formato declarado: lee la clave de la configuración y cae a `11v11` cuando
 * falta o no pertenece al catálogo cerrado. Es puramente informativo: no
 * deriva ni acota los límites de plantilla (RF-043).
 */
export function gameFormatOf(config: unknown): string {
  const source = isRecord(config) ? config : {};
  return isGameFormat(source.game_format) ? source.game_format : DEFAULT_GAME_FORMAT;
}

/**
 * La advertencia de formato se muestra cuando la modalidad declarada no es
 * `11v11`, porque la planilla soportada es de once (RF-043). Nunca bloquea.
 */
export function formatWarns(format: unknown): boolean {
  return gameFormatOf({ game_format: format }) !== DEFAULT_GAME_FORMAT;
}

function optionalLimit(value: unknown): number | undefined {
  return isNonNegativeInteger(value) ? value : undefined;
}

/**
 * Valores del asistente derivados de la configuración (RF-006). Un paso
 * obligatorio está completo cuando sus campos obligatorios tienen valor; los
 * opcionales quedan sin valor cuando la configuración no los trae.
 */
export function rulesWizardValues(config: unknown): WizardValues {
  const source = isRecord(config) ? config : {};
  const pipeline = source.ranking_pipeline;
  const overrides = source.stage_overrides;
  return {
    scoring: isRecord(source.points_system) ? source.points_system : undefined,
    tiebreakers: Array.isArray(pipeline) && pipeline.length > 0 ? pipeline : undefined,
    discipline: isRecord(source.discipline) ? source.discipline : undefined,
    resolution: isRecord(source.stage_defaults) ? source.stage_defaults : undefined,
    gameFormat: gameFormatOf(source),
    minPlayers: optionalLimit(source.min_players_per_team),
    maxPlayers: optionalLimit(source.max_players_per_team),
    substitutions: isRecord(source.substitutions) ? source.substitutions : undefined,
    registration: isPositiveInteger(source.roster_lock_matchday)
      ? source.roster_lock_matchday
      : undefined,
    overrides: isRecord(overrides) && Object.keys(overrides).length ? overrides : undefined,
  };
}

const identity: WizardTranslate = (key) => key;

/** Estado de cada paso del asistente para el índice (RF-006). */
export function rulesWizardStatuses(
  config: unknown,
  t: WizardTranslate = identity,
  issues: readonly RulesFieldIssue[] = [],
): WizardStepStatus[] {
  return wizardStepStates('rules', t, rulesWizardValues(config), rulesWizardErrors(issues));
}

/** Resultado de intentar confirmar el asistente y enviar la configuración. */
export interface RulesSaveCheck {
  readonly ok: boolean;
  readonly blockedBy: WizardStepId[];
  readonly issues: readonly RulesFieldIssue[];
  readonly global: readonly RulesFieldIssue[];
}

/**
 * Confirmación (RF-005, RF-006, RF-007, RF-009): exige los pasos obligatorios
 * completos, ningún paso con error y ningún problema global (JSON avanzado o un
 * rechazo del servidor sin campo reconocible). No modifica la configuración.
 */
export function checkRulesSave(
  config: unknown,
  issues: readonly RulesFieldIssue[] = [],
  t: WizardTranslate = identity,
): RulesSaveCheck {
  const { global } = rulesErrorsByStep(issues);
  const confirmation = canConfirm('rules', rulesWizardStatuses(config, t, issues));
  return {
    ok: confirmation.ok && global.length === 0,
    blockedBy: confirmation.blockedBy,
    issues,
    global,
  };
}

/** Mensaje completo de un problema: paso, campo y motivo, en el idioma activo. */
export function describeRulesIssue(issue: RulesFieldIssue, t: RulesTranslate): string {
  const stepLabel = issue.stepId
    ? t(STEP_LABEL_KEYS[issue.stepId] ?? 'rules.wizardTitle')
    : t('rules.field.rulesConfig');
  return t('rules.error.fieldInStep', {
    step: stepLabel,
    field: t(issue.fieldLabelKey),
    message: t(issue.messageKey),
  });
}

/**
 * Cuerpo enviado al guardar: la configuración completa de la versión, con las
 * claves requeridas presentes aunque estén vacías (RF-009).
 */
export function buildRulesPayload(config: RulesConfig): { rules_config: Record<string, unknown> } {
  return buildRulesRequest(normalizeRulesConfig(config));
}
