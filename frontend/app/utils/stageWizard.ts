/**
 * Asistente de fases: identificación, composición opcional y revisión, y la
 * secuencia **no atómica** de creación e inscripción (spec 012, RF-002, RF-006,
 * RF-010; AT-1).
 *
 * El módulo es puro: no lee el reloj, el entorno, el almacenamiento ni la red.
 * La secuencia se describe como un plan de pasos que el componente ejecuta con
 * `useApi()`; el reintento se planifica **sin** el paso de creación, de modo que
 * la fase creada no pueda duplicarse.
 */

import { STAGE_FORMATS, type StageFormat } from '../constants/stageFormats.ts';
import { getApiStatus } from './api.ts';
import { dedupeTeamIds, normalizeAssignmentResponse } from './stageTeams.ts';
import {
  canConfirm,
  wizardStepStates,
  type ConfirmResult,
  type PhasesStepId,
  type WizardErrors,
  type WizardStepStatus,
  type WizardTranslate,
  type WizardValues,
} from './wizardModel.ts';

/** Tope del contrato de inscripción (`AssignStageTeamsRequest`). */
export const MAX_STAGE_TEAMS = 64;
export const STAGE_NAME_MIN_LENGTH = 2;
export const STAGE_NAME_MAX_LENGTH = 50;

const IDENTITY_STEP: PhasesStepId = 'phases.identity';
const COMPOSITION_STEP: PhasesStepId = 'phases.composition';

const STAGE_FORMAT_VALUES: readonly string[] = STAGE_FORMATS.map((format) => format.value);

/** Valores editables del asistente, tal como llegan del formulario. */
export interface StageWizardValues {
  readonly name?: unknown;
  readonly stageOrder?: unknown;
  readonly stageType?: unknown;
  readonly teamIds?: unknown;
}

/** Un problema de validación ya ubicado en su paso y en su campo. */
export interface StageIssue {
  readonly stepId: PhasesStepId;
  readonly field: 'name' | 'stageOrder' | 'stageType' | 'teamIds';
  readonly messageKey: string;
}

/** Identidad normalizada de la fase. */
export interface StageIdentity {
  readonly name: string;
  readonly stageOrder: number;
  readonly stageType: string;
}

/** Fase ya creada del borrador, con lo mínimo que el asistente necesita. */
export interface StageOptionLike {
  readonly id: string;
  readonly name: string;
  readonly stage_type: string;
  readonly stage_order: number;
  readonly tournament_version_id?: string;
}

const identity: WizardTranslate = (key) => key;

export function normalizeStageName(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

/** Orden de fase: entero ≥ 1, escrito como número o como dígitos. */
export function normalizeStageOrder(value: unknown): number | null {
  if (typeof value === 'number') {
    return Number.isInteger(value) && value >= 1 ? value : null;
  }
  if (typeof value === 'string' && /^\d+$/.test(value.trim())) {
    const parsed = Number(value.trim());
    return parsed >= 1 ? parsed : null;
  }
  return null;
}

/** Formato de fase del catálogo cerrado, o `null` si no pertenece a él. */
export function normalizeStageType(value: unknown): StageFormat | null {
  if (typeof value !== 'string') return null;
  const candidate = value.trim();
  return STAGE_FORMAT_VALUES.includes(candidate) ? (candidate as StageFormat) : null;
}

/** Equipos elegidos, sin vacíos y sin duplicados, en el orden de selección. */
export function normalizeStageTeamIds(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return dedupeTeamIds(
    value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
      .map((item) => item.trim()),
  );
}

/** Todos los problemas del asistente, en el orden de los pasos. */
export function validateStageValues(values: StageWizardValues): StageIssue[] {
  const issues: StageIssue[] = [];

  const name = normalizeStageName(values.name);
  if (name.length < STAGE_NAME_MIN_LENGTH || name.length > STAGE_NAME_MAX_LENGTH) {
    issues.push({ stepId: IDENTITY_STEP, field: 'name', messageKey: 'stage.wizard.error.name' });
  }
  if (normalizeStageOrder(values.stageOrder) === null) {
    issues.push({ stepId: IDENTITY_STEP, field: 'stageOrder', messageKey: 'stage.wizard.error.stageOrder' });
  }
  if (normalizeStageType(values.stageType) === null) {
    issues.push({ stepId: IDENTITY_STEP, field: 'stageType', messageKey: 'stage.wizard.error.stageType' });
  }
  if (normalizeStageTeamIds(values.teamIds).length > MAX_STAGE_TEAMS) {
    issues.push({ stepId: COMPOSITION_STEP, field: 'teamIds', messageKey: 'stage.wizard.error.teamLimit' });
  }

  return issues;
}

/** Valores del modelo de pasos: la composición vacía queda como paso omitido. */
export function stageWizardValues(values: StageWizardValues): WizardValues {
  const teamIds = normalizeStageTeamIds(values.teamIds);
  const order = normalizeStageOrder(values.stageOrder);
  const type = normalizeStageType(values.stageType);
  return {
    name: normalizeStageName(values.name) || undefined,
    stageOrder: order ?? undefined,
    stageType: type ?? undefined,
    teamIds,
  };
}

/** Errores por paso en el formato que consume el índice (`stepState`). */
export function stageWizardErrors(issues: readonly StageIssue[]): WizardErrors {
  const errors: Record<string, readonly string[]> = {};
  for (const issue of issues) {
    errors[issue.stepId] = [...(errors[issue.stepId] ?? []), issue.messageKey];
  }
  return errors;
}

/** Estado de cada paso del asistente para el índice (RF-006). */
export function stageWizardStatuses(
  values: StageWizardValues,
  issues: readonly StageIssue[] = [],
  t: WizardTranslate = identity,
): WizardStepStatus[] {
  return wizardStepStates('phases', t, stageWizardValues(values), stageWizardErrors(issues));
}

/** Confirmación: identificación y revisión completas; composición opcional (RF-006). */
export function stageConfirmation(
  values: StageWizardValues,
  issues: readonly StageIssue[] = [],
  t: WizardTranslate = identity,
): ConfirmResult {
  return canConfirm('phases', stageWizardStatuses(values, issues, t));
}

/** Cuerpo exacto de `POST /stages` (contrato actual del servidor). */
export function buildStageBody(input: {
  readonly versionId: string;
  readonly values: StageWizardValues;
}): Record<string, unknown> {
  return {
    version_id: input.versionId,
    name: normalizeStageName(input.values.name),
    stage_type: normalizeStageType(input.values.stageType) ?? normalizeStageName(input.values.stageType),
    stage_order: normalizeStageOrder(input.values.stageOrder) ?? 1,
  };
}

export function stagesPath(tournamentId: string): string {
  return `/tournaments/${tournamentId}/stages`;
}

export function stageTeamsPath(tournamentId: string, stageId: string): string {
  return `/tournaments/${tournamentId}/stages/${stageId}/teams`;
}

export function stageTeamPath(tournamentId: string, stageId: string, teamId: string): string {
  return `/tournaments/${tournamentId}/stages/${stageId}/teams/${teamId}`;
}

/** Un paso del plan: crear la fase o inscribir equipos en ella. */
export type StagePlanStep =
  | {
    readonly kind: 'create_stage';
    readonly body: Record<string, unknown>;
  }
  | {
    readonly kind: 'assign_teams';
    /** `null` mientras la fase no existe: es la que acaba de crear el paso anterior. */
    readonly stageId: string | null;
    readonly teamIds: string[];
  };

/**
 * Plan de creación (RF-010, AT-1): primero la fase, después la inscripción. Sin
 * equipos elegidos solo se crea la fase.
 */
export interface StageCreationPlan {
  readonly mode: 'create' | 'retry';
  readonly steps: readonly StagePlanStep[];
}

export function planStageCreation(input: {
  readonly versionId: string;
  readonly values: StageWizardValues;
}): StageCreationPlan {
  const teamIds = normalizeStageTeamIds(input.values.teamIds);
  const steps: StagePlanStep[] = [{ kind: 'create_stage', body: buildStageBody(input) }];
  if (teamIds.length) steps.push({ kind: 'assign_teams', stageId: null, teamIds });
  return { mode: 'create', steps };
}

/**
 * Plan de reintento (RF-010): **solo** la inscripción sobre la fase ya creada.
 * No contiene ningún paso de creación, así que reintentar no puede duplicarla.
 */
export function planStageRetry(input: {
  readonly stageId: string;
  readonly teamIds: readonly string[];
}): StageCreationPlan {
  const teamIds = normalizeStageTeamIds(input.teamIds);
  return {
    mode: 'retry',
    steps: teamIds.length ? [{ kind: 'assign_teams', stageId: input.stageId, teamIds }] : [],
  };
}

/** Resultado de una creación o inscripción, con lo que quedó pendiente. */
export type StageSaveStatus = 'created' | 'partial' | 'existing';

export interface StageSaveResult {
  readonly status: StageSaveStatus;
  readonly stageId: string | null;
  /** Equipos seleccionados que no quedaron inscritos y se pueden reintentar. */
  readonly pendingTeamIds: string[];
  readonly messageKey: string;
  readonly canRetry: boolean;
  /** Solo cuando no se sabe si la fase llegó a crearse. */
  readonly verifyByReload: boolean;
}

/** Fase creada e inscripción aceptada (o fase sin composición). */
export function stageSaveSucceeded(input: {
  readonly mode: 'create' | 'existing' | 'retry';
  readonly stageId: string;
  readonly requestedTeamIds: readonly string[];
  readonly response?: unknown;
}): StageSaveResult {
  const requested = normalizeStageTeamIds(input.requestedTeamIds);
  const normalized = normalizeAssignmentResponse(input.response);
  const accepted = normalized
    ? new Set([...normalized.assigned, ...normalized.already_assigned])
    : new Set(requested);
  const pending = requested.filter((teamId) => !accepted.has(teamId));
  const status: StageSaveStatus = pending.length
    ? 'partial'
    : (input.mode === 'create' ? 'created' : 'existing');
  let messageKey: string;
  if (pending.length) messageKey = 'stage.wizard.partial';
  else if (input.mode === 'create') {
    messageKey = requested.length
      ? 'stage.wizard.createdAndAssigned'
      : 'stage.wizard.createdWithoutTeams';
  } else {
    messageKey = 'stage.wizard.existingAssigned';
  }

  return {
    status,
    stageId: input.stageId,
    pendingTeamIds: pending,
    messageKey,
    canRetry: pending.length > 0,
    verifyByReload: false,
  };
}

/**
 * La fase existe pero la inscripción falló (RF-010): guardado parcial, la fase
 * queda visible sin esos equipos y la selección se conserva para reintentar.
 */
export function stageSaveFailed(input: {
  readonly stageId: string;
  readonly requestedTeamIds: readonly string[];
  readonly cause?: unknown;
}): StageSaveResult {
  return {
    status: 'partial',
    stageId: input.stageId,
    pendingTeamIds: normalizeStageTeamIds(input.requestedTeamIds),
    messageKey: 'stage.wizard.partial',
    canRetry: true,
    verifyByReload: false,
  };
}

/** Fallo al crear la fase: rechazo con respuesta o resultado desconocido. */
export interface StageCreateFailure {
  readonly kind: 'rejected' | 'ambiguous';
  readonly messageKey: string;
  /** `false` cuando no se sabe si la fase se creó: no se invita a crear otra. */
  readonly retryCreate: boolean;
  /** Recargar la lista de fases para verificar antes de seguir. */
  readonly reloadStages: boolean;
}

/**
 * Clasifica el fallo de `POST /stages`. Sin código HTTP (timeout, respuesta
 * perdida) el resultado es ambiguo: la fase pudo crearse, así que no se ofrece
 * crear otra, sino revisar la lista y, si está, inscribir sobre ella.
 */
export function stageCreateFailure(cause: unknown): StageCreateFailure {
  if (getApiStatus(cause) > 0) {
    return {
      kind: 'rejected',
      messageKey: 'stage.wizard.createRejected',
      retryCreate: true,
      reloadStages: false,
    };
  }
  return {
    kind: 'ambiguous',
    messageKey: 'stage.wizard.createAmbiguous',
    retryCreate: false,
    reloadStages: true,
  };
}

/** Fases ordenadas por `stage_order` y, en empate, por id (orden estable). */
export function sortStagesByOrder<T extends StageOptionLike>(stages: readonly T[]): T[] {
  return [...stages].sort((left, right) => (
    (left.stage_order - right.stage_order) || left.id.localeCompare(right.id)
  ));
}

/** Primera fase por orden, o `null` sin fases. */
export function firstStageByOrder<T extends StageOptionLike>(stages: readonly T[]): T | null {
  return sortStagesByOrder(stages)[0] ?? null;
}

/** Siguiente orden libre para una fase nueva. */
export function nextStageOrder(stages: readonly StageOptionLike[]): number {
  return stages.reduce((highest, stage) => Math.max(highest, stage.stage_order || 0), 0) + 1;
}

/** Fase existente abierta para componer su inscripción (RF-002). */
export interface ExistingStageContext {
  readonly stageId: string;
  readonly identity: StageIdentity;
  /** La identificación de una fase existente no se edita. */
  readonly readOnly: true;
  readonly startStep: 'phases.composition';
}

/**
 * Contexto de una fase existente: la elegida o, sin selección, la primera por
 * orden. El asistente abre directamente la composición (RF-002).
 */
export function openExistingStage<T extends StageOptionLike>(
  stages: readonly T[],
  selectedId?: string | null,
): ExistingStageContext | null {
  const chosen = stages.find((stage) => stage.id === selectedId) ?? firstStageByOrder(stages);
  if (!chosen) return null;
  return {
    stageId: chosen.id,
    identity: {
      name: chosen.name,
      stageOrder: chosen.stage_order,
      stageType: chosen.stage_type,
    },
    readOnly: true,
    startStep: 'phases.composition',
  };
}

/** Resumen del paso de revisión. */
export interface StageReview {
  readonly mode: 'create' | 'existing';
  readonly stageId: string | null;
  readonly name: string;
  readonly stageOrder: number | null;
  readonly stageType: string | null;
  readonly stageTypeLabelKey: string;
  readonly teamCount: number;
  readonly teamIds: string[];
  /** Claves i18n de los avisos que acompañan a la revisión. */
  readonly warningKeys: readonly string[];
}

export function reviewStage(input: {
  readonly mode: 'create' | 'existing';
  readonly stageId?: string | null;
  readonly values: StageWizardValues;
}): StageReview {
  const teamIds = normalizeStageTeamIds(input.values.teamIds);
  const stageType = normalizeStageType(input.values.stageType);
  const warningKeys = [
    // RF-010: el calendario no se regenera ni al inscribir ni al retirar.
    'stage.wizard.calendarNotice',
  ];
  if (!teamIds.length) warningKeys.push('stage.wizard.optionalComposition');

  return {
    mode: input.mode,
    stageId: input.stageId ?? null,
    name: normalizeStageName(input.values.name),
    stageOrder: normalizeStageOrder(input.values.stageOrder),
    stageType: stageType ?? (normalizeStageName(input.values.stageType) || null),
    stageTypeLabelKey: STAGE_FORMATS.find((format) => format.value === stageType)?.labelKey
      ?? 'stage.roundRobin',
    teamCount: teamIds.length,
    teamIds,
    warningKeys,
  };
}
