/**
 * Pure step model of the three Workspace assistants (rules, phases, teams).
 *
 * This module is the single source of the step order, the obligation of each
 * step (`required`, `optional`, `alternative`), the group of exclusive
 * alternatives and the five index states of RF-006. It reads no clock, keeps no
 * global state and performs no network or storage access: the caller passes the
 * step values and the recorded errors explicitly.
 */

export type WizardKind = 'rules' | 'phases' | 'teams';

/**
 * The three assistants, in the order of the page that hosts them. The page
 * shares a single `?step=`, so this order also decides which one normalizes the
 * initial entry (spec 012, RF-013, RF-019).
 */
export const WIZARD_KINDS: readonly WizardKind[] = ['rules', 'phases', 'teams'];

export type RulesStepId =
  | 'rules.scoring'
  | 'rules.tiebreakers'
  | 'rules.discipline'
  | 'rules.resolution'
  | 'rules.format'
  | 'rules.substitutions'
  | 'rules.registration'
  | 'rules.overrides';

export type PhasesStepId =
  | 'phases.identity'
  | 'phases.composition'
  | 'phases.review';

export type TeamsStepId =
  | 'teams.details'
  | 'teams.individual'
  | 'teams.bulk'
  | 'teams.review';

export type WizardStepId = RulesStepId | PhasesStepId | TeamsStepId;

/** Obligation of a step inside the assistant (RF-006). */
export type StepObligation = 'required' | 'optional' | 'alternative';

/** State shown by the step index (RF-006). */
export type StepState = 'complete' | 'incomplete' | 'error' | 'omitted' | 'alternative';

/** Obligation of a field inside a step; optional fields never block a step. */
export type StepFieldObligation = 'required' | 'optional';

export type WizardTranslate = (key: string) => string;

/** Values of the assistant keyed by field id (see `StepDefinition.fields`). */
export type WizardValues = Readonly<Record<string, unknown>>;

/** Errors recorded for a step, keyed by step id; an empty list means no error. */
export type WizardErrors = Readonly<
  Record<string, readonly string[] | string | null | undefined>
>;

export interface StepFieldDefinition {
  readonly id: string;
  readonly obligation: StepFieldObligation;
}

export interface StepDefinition {
  readonly id: WizardStepId;
  readonly obligation: StepObligation;
  readonly labelKey: string;
  readonly label: string;
  /** Only for `alternative` steps: steps of the same group exclude each other. */
  readonly group?: string;
  readonly fields: readonly StepFieldDefinition[];
}

export interface WizardStepStatus {
  readonly id: WizardStepId;
  readonly obligation: StepObligation;
  readonly labelKey: string;
  readonly label: string;
  readonly group?: string;
  readonly state: StepState;
}

export interface ConfirmResult {
  readonly ok: boolean;
  readonly blockedBy: WizardStepId[];
}

/** Group of the two exclusive entry paths of the teams assistant (RF-011). */
export const TEAM_ENTRY_GROUP = 'teams.entry';

const requiredField = (id: string): StepFieldDefinition => ({ id, obligation: 'required' });
const optionalField = (id: string): StepFieldDefinition => ({ id, obligation: 'optional' });

interface StepDeclaration {
  readonly id: WizardStepId;
  readonly labelKey: string;
  readonly obligation: StepObligation;
  readonly group?: string;
  readonly fields: readonly StepFieldDefinition[];
}

const RULES_STEPS: readonly StepDeclaration[] = [
  { id: 'rules.scoring', labelKey: 'wizard.rules.scoring', obligation: 'required', fields: [requiredField('scoring')] },
  { id: 'rules.tiebreakers', labelKey: 'wizard.rules.tiebreakers', obligation: 'required', fields: [requiredField('tiebreakers')] },
  { id: 'rules.discipline', labelKey: 'wizard.rules.discipline', obligation: 'required', fields: [requiredField('discipline')] },
  { id: 'rules.resolution', labelKey: 'wizard.rules.resolution', obligation: 'required', fields: [requiredField('resolution')] },
  {
    id: 'rules.format',
    labelKey: 'wizard.rules.format',
    obligation: 'required',
    fields: [requiredField('gameFormat'), optionalField('minPlayers'), optionalField('maxPlayers')],
  },
  { id: 'rules.substitutions', labelKey: 'wizard.rules.substitutions', obligation: 'optional', fields: [optionalField('substitutions')] },
  { id: 'rules.registration', labelKey: 'wizard.rules.registration', obligation: 'optional', fields: [optionalField('registration')] },
  { id: 'rules.overrides', labelKey: 'wizard.rules.overrides', obligation: 'optional', fields: [optionalField('overrides')] },
];

const PHASES_STEPS: readonly StepDeclaration[] = [
  {
    id: 'phases.identity',
    labelKey: 'wizard.phases.identity',
    obligation: 'required',
    fields: [requiredField('name'), requiredField('stageOrder'), requiredField('stageType')],
  },
  { id: 'phases.composition', labelKey: 'wizard.phases.composition', obligation: 'optional', fields: [requiredField('teamIds')] },
  { id: 'phases.review', labelKey: 'wizard.phases.review', obligation: 'required', fields: [] },
];

const TEAMS_STEPS: readonly StepDeclaration[] = [
  {
    id: 'teams.details',
    labelKey: 'wizard.teams.details',
    obligation: 'required',
    fields: [requiredField('name'), requiredField('code')],
  },
  {
    id: 'teams.individual',
    labelKey: 'wizard.teams.individual',
    obligation: 'alternative',
    group: TEAM_ENTRY_GROUP,
    fields: [requiredField('individualRows')],
  },
  {
    id: 'teams.bulk',
    labelKey: 'wizard.teams.bulk',
    obligation: 'alternative',
    group: TEAM_ENTRY_GROUP,
    fields: [requiredField('bulkCsv')],
  },
  { id: 'teams.review', labelKey: 'wizard.teams.review', obligation: 'required', fields: [] },
];

const WIZARDS: Readonly<Record<WizardKind, readonly StepDeclaration[]>> = {
  rules: RULES_STEPS,
  phases: PHASES_STEPS,
  teams: TEAMS_STEPS,
};

const STATE_KEYS: Readonly<Record<StepState, string>> = {
  complete: 'wizard.state.complete',
  incomplete: 'wizard.state.incomplete',
  error: 'wizard.state.error',
  omitted: 'wizard.state.omitted',
  alternative: 'wizard.state.alternative',
};

const OBLIGATION_KEYS: Readonly<Record<StepObligation, string>> = {
  required: 'wizard.obligation.required',
  optional: 'wizard.obligation.optional',
  alternative: 'wizard.obligation.alternative',
};

const identity: WizardTranslate = (key) => key;

function declarations(wizard: WizardKind): readonly StepDeclaration[] {
  return WIZARDS[wizard] ?? [];
}

/** Step declarations of an assistant, with their labels resolved through `t`. */
export function wizardSteps(wizard: WizardKind, t: WizardTranslate = identity): StepDefinition[] {
  return declarations(wizard).map((step) => {
    const label = t(step.labelKey);
    const base = {
      id: step.id,
      obligation: step.obligation,
      labelKey: step.labelKey,
      label,
      fields: step.fields,
    };
    return step.group ? { ...base, group: step.group } : base;
  });
}

/**
 * Whether a value counts as configured. Blank strings, empty lists, `null`,
 * `undefined` and `false` mean "not configured"; `0` is a configured number.
 */
export function isStepValueSet(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === 'string') return value.trim().length > 0;
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value === 'boolean') return value;
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

function hasRecordedError(stepId: string, errors: WizardErrors): boolean {
  const entry = errors[stepId];
  if (entry === null || entry === undefined) return false;
  if (Array.isArray(entry)) {
    return entry.some((item) => typeof item === 'string' && item.trim().length > 0);
  }
  return typeof entry === 'string' && entry.trim().length > 0;
}

/**
 * State of a step (RF-006). Errors win over every other state; a required step
 * is `complete` only when all its required fields are set; an optional step
 * without values is `omitted` and a non-chosen alternative is `alternative`.
 */
export function stepState(
  step: StepDefinition,
  values: WizardValues,
  errors: WizardErrors = {},
): StepState {
  if (hasRecordedError(step.id, errors)) return 'error';

  const required = step.fields.filter((field) => field.obligation === 'required');
  const requiredComplete = required.every((field) => isStepValueSet(values[field.id]));
  const anyFieldSet = step.fields.some((field) => isStepValueSet(values[field.id]));

  switch (step.obligation) {
    case 'alternative':
      return requiredComplete ? 'complete' : 'alternative';
    case 'optional':
      if (!anyFieldSet) return 'omitted';
      return requiredComplete ? 'complete' : 'incomplete';
    default:
      return requiredComplete ? 'complete' : 'incomplete';
  }
}

/** State of every step of an assistant, in declaration order. */
export function wizardStepStates(
  wizard: WizardKind,
  t: WizardTranslate,
  values: WizardValues,
  errors: WizardErrors = {},
): WizardStepStatus[] {
  return wizardSteps(wizard, t).map((step) => {
    const base = {
      id: step.id,
      obligation: step.obligation,
      labelKey: step.labelKey,
      label: step.label,
      state: stepState(step, values, errors),
    };
    return step.group ? { ...base, group: step.group } : base;
  });
}

/**
 * Whether the assistant can be confirmed (RF-006): every required step is
 * complete, no step records an error and each alternative group has exactly one
 * chosen step. Optional steps never block, whether configured or omitted.
 * `blockedBy` lists the steps that prevent the confirmation in declaration order.
 */
export function canConfirm(
  wizard: WizardKind,
  states: readonly WizardStepStatus[],
): ConfirmResult {
  const byId = new Map(states.map((entry) => [entry.id, entry.state] as const));
  const stateOfStep = (id: WizardStepId): StepState => byId.get(id) ?? 'incomplete';
  const blocked = new Set<WizardStepId>();

  for (const step of declarations(wizard)) {
    const state = stateOfStep(step.id);
    if (state === 'error') {
      blocked.add(step.id);
    } else if (step.obligation === 'required' && state !== 'complete') {
      blocked.add(step.id);
    }
  }

  const groups = new Map<string, WizardStepId[]>();
  for (const step of declarations(wizard)) {
    if (!step.group) continue;
    const members = groups.get(step.group) ?? [];
    members.push(step.id);
    groups.set(step.group, members);
  }
  for (const members of groups.values()) {
    const chosen = members.filter((id) => stateOfStep(id) === 'complete');
    if (chosen.length !== 1) {
      for (const id of members) blocked.add(id);
    }
  }

  const blockedBy = declarations(wizard)
    .map((step) => step.id)
    .filter((id) => blocked.has(id));
  return { ok: blockedBy.length === 0, blockedBy };
}

/** First step of an assistant, or `null` when it declares none. */
export function firstStepId(wizard: WizardKind): WizardStepId | null {
  return declarations(wizard)[0]?.id ?? null;
}

/** Next step in declaration order, or `null` on the last one or an unknown id. */
export function nextStepId(wizard: WizardKind, stepId: string): WizardStepId | null {
  const steps = declarations(wizard);
  const index = steps.findIndex((step) => step.id === stepId);
  if (index < 0) return null;
  return steps[index + 1]?.id ?? null;
}

/** Previous step in declaration order, or `null` on the first one or an unknown id. */
export function previousStepId(wizard: WizardKind, stepId: string): WizardStepId | null {
  const steps = declarations(wizard);
  const index = steps.findIndex((step) => step.id === stepId);
  if (index <= 0) return null;
  return steps[index - 1]?.id ?? null;
}

/** i18n key of the visible label of a step state. */
export function stepStateLabelKey(state: StepState): string {
  return STATE_KEYS[state];
}

/** i18n key of the visible label of a step obligation. */
export function obligationLabelKey(obligation: StepObligation): string {
  return OBLIGATION_KEYS[obligation];
}
