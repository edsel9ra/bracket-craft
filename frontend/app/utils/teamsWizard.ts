/**
 * Asistente de equipos: datos (nombre y código), dos vías de alta excluyentes
 * —individual o carga masiva— y revisión (spec 012, RF-003, RF-006, RF-011,
 * RF-021; IN-1).
 *
 * El alta de equipos **no inscribe en ninguna fase**: ningún cuerpo que este
 * módulo construye lleva `stage_id`. La inscripción vive solo en el asistente de
 * fases. El módulo es puro: no lee el reloj, el entorno, el almacenamiento ni la
 * red; la validación de la carga masiva es la que ya tenía la página de
 * configuración, extraída aquí para no duplicarla.
 */

import type {
  ConfirmResult,
  TeamsStepId,
  WizardErrors,
  WizardStepStatus,
  WizardTranslate,
  WizardValues,
} from './wizardModel.ts';
import { canConfirm, wizardStepStates } from './wizardModel.ts';

/** Tope del contrato de carga masiva (`BulkTournamentTeamRequest`). */
export const MAX_BULK_TEAMS = 200;
export const TEAM_NAME_MIN_LENGTH = 2;
export const TEAM_NAME_MAX_LENGTH = 100;
export const TEAM_CODE_PATTERN = /^[A-Za-z0-9_-]{2,10}$/;

const DETAILS_STEP: TeamsStepId = 'teams.details';
const BULK_STEP: TeamsStepId = 'teams.bulk';

/** Vías de alta excluyentes del asistente (RF-011). */
export type TeamEntryPath = 'individual' | 'bulk';

export type TeamCsvColumn = 'name' | 'short_code' | 'logo_url' | 'file';

/** Valores editables del asistente, tal como llegan del formulario. */
export interface TeamWizardValues {
  readonly name?: unknown;
  readonly shortCode?: unknown;
  /** Vía elegida; `null` mientras no se elige ninguna. */
  readonly entryPath?: unknown;
  /** Texto pegado o leído del archivo, conservado íntegro. */
  readonly bulkCsv?: unknown;
  readonly bulkFileName?: unknown;
}

/** Un equipo listo para registrar. */
export interface TeamCsvRow {
  readonly name: string;
  readonly short_code: string;
  readonly logo_url: string | null;
}

/** Un problema de la carga masiva, ubicado por fila y columna. */
export interface TeamCsvIssue {
  /** Fila de datos (1..n); `0` en los problemas del archivo completo. */
  readonly row: number;
  readonly column: TeamCsvColumn;
  readonly messageKey: string;
  readonly params: Record<string, string | number>;
}

export interface TeamCsvParse {
  readonly rows: TeamCsvRow[];
  readonly issues: TeamCsvIssue[];
  readonly headerDetected: boolean;
  readonly dataRowCount: number;
}

/** Un problema del asistente, ubicado en su paso y en su campo. */
export interface TeamIssue {
  readonly stepId: TeamsStepId;
  readonly field: 'name' | 'shortCode' | 'bulkCsv';
  readonly row?: number;
  readonly column?: TeamCsvColumn;
  readonly messageKey: string;
  readonly params?: Record<string, string | number>;
}

const identity: WizardTranslate = (key) => key;

const COLUMN_KEYS: Readonly<Record<TeamCsvColumn, string>> = {
  name: 'teams.wizard.column.name',
  short_code: 'teams.wizard.column.code',
  logo_url: 'teams.wizard.column.logo',
  file: 'teams.wizard.column.file',
};

/** Clave i18n de la etiqueta de una columna del CSV. */
export function columnLabelKey(column: TeamCsvColumn): string {
  return COLUMN_KEYS[column];
}

export function normalizeTeamName(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

/** Código del equipo: el mismo patrón del contrato del servidor. */
export function normalizeTeamCode(value: unknown): string {
  if (typeof value !== 'string') return '';
  const code = value.trim();
  return TEAM_CODE_PATTERN.test(code) ? code : '';
}

export function normalizeTeamEntryPath(value: unknown): TeamEntryPath | null {
  return value === 'individual' || value === 'bulk' ? value : null;
}

/**
 * Si el paso de una vía debe mostrar sus campos (RF-011). La vía no elegida
 * queda oculta —conservando lo escrito— y solo reaparece al elegirla de nuevo.
 * El paso de datos y el de revisión no son vías alternativas.
 */
export function showsEntryPathStep(step: TeamsStepId, entryPath: unknown): boolean {
  const path = normalizeTeamEntryPath(entryPath);
  if (step === 'teams.individual') return path !== 'bulk';
  if (step === 'teams.bulk') return path !== 'individual';
  return true;
}

function isNameValid(name: string): boolean {
  return name.length >= TEAM_NAME_MIN_LENGTH && name.length <= TEAM_NAME_MAX_LENGTH;
}

function isLogoValid(logoUrl: string): boolean {
  return !logoUrl || /^https?:\/\//i.test(logoUrl);
}

/** Divide una línea CSV respetando las comillas dobles escapadas (`""`). */
export function splitCsvLine(line: string): string[] {
  const values: string[] = [];
  let value = '';
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"') {
      if (quoted && line[index + 1] === '"') {
        value += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (character === ',' && !quoted) {
      values.push(value.trim());
      value = '';
    } else {
      value += character;
    }
  }
  values.push(value.trim());
  return values;
}

function fileIssue(row: number, messageKey: string): TeamCsvIssue {
  return { row, column: 'file', messageKey, params: {} };
}

/**
 * Parsea y valida la carga masiva con las reglas que ya aplicaba la página:
 * columnas `name,short_code[,logo_url]`, encabezado opcional, hasta 200 filas,
 * nombre de 2 a 100 caracteres, código de 2 a 10 con el patrón del contrato,
 * código no repetido en la carga y logo con `http`/`https`. Devuelve **todas**
 * las filas válidas y **todos** los problemas, cada uno con su fila y columna.
 */
export function parseTeamCsv(text: unknown): TeamCsvParse {
  const raw = typeof text === 'string' ? text : '';
  const lines = raw
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  if (!lines.length) {
    return { rows: [], issues: [fileIssue(0, 'setup.csvEmpty')], headerDetected: false, dataRowCount: 0 };
  }

  const firstColumns = splitCsvLine(lines[0] ?? '').map((column) => column.toLowerCase());
  const headerDetected = firstColumns[0] === 'name' && firstColumns[1] === 'short_code';
  const dataLines = headerDetected ? lines.slice(1) : lines;
  const dataRowCount = dataLines.length;

  if (!dataRowCount) {
    return {
      rows: [],
      issues: [fileIssue(0, 'setup.csvHeaderOnly')],
      headerDetected,
      dataRowCount,
    };
  }
  if (dataRowCount > MAX_BULK_TEAMS) {
    return {
      rows: [],
      issues: [{ row: 0, column: 'file', messageKey: 'setup.csvLimit', params: { max: MAX_BULK_TEAMS } }],
      headerDetected,
      dataRowCount,
    };
  }

  const rows: TeamCsvRow[] = [];
  const issues: TeamCsvIssue[] = [];
  const codes = new Set<string>();

  dataLines.forEach((line, index) => {
    const row = index + 1;
    const [name = '', shortCode = '', logoUrl = ''] = splitCsvLine(line);

    const nameValid = isNameValid(name);
    if (!nameValid) {
      issues.push({ row, column: 'name', messageKey: 'setup.csvName', params: { row } });
    }

    const codeValid = TEAM_CODE_PATTERN.test(shortCode);
    const normalizedCode = shortCode.toLowerCase();
    const duplicated = codeValid && codes.has(normalizedCode);
    if (!codeValid) {
      issues.push({ row, column: 'short_code', messageKey: 'setup.csvCode', params: { row } });
    } else if (duplicated) {
      issues.push({
        row,
        column: 'short_code',
        messageKey: 'setup.csvDuplicate',
        params: { row, code: shortCode },
      });
    }

    const logoValid = isLogoValid(logoUrl);
    if (!logoValid) {
      issues.push({ row, column: 'logo_url', messageKey: 'setup.csvLogo', params: { row } });
    }

    if (!nameValid || !codeValid || duplicated || !logoValid) return;
    codes.add(normalizedCode);
    rows.push({ name, short_code: shortCode, logo_url: logoUrl || null });
  });

  return { rows, issues, headerDetected, dataRowCount };
}

/** Todos los problemas del asistente, en el orden de los pasos. */
export function validateTeamValues(values: TeamWizardValues): TeamIssue[] {
  const issues: TeamIssue[] = [];

  const path = normalizeTeamEntryPath(values.entryPath);
  const individual = path === 'individual';

  const nameTrimmed = normalizeTeamName(values.name);
  if (individual) {
    if (!isNameValid(nameTrimmed)) {
      issues.push({ stepId: DETAILS_STEP, field: 'name', messageKey: 'teams.wizard.error.name' });
    }
  } else if (nameTrimmed !== '' && !isNameValid(nameTrimmed)) {
    issues.push({ stepId: DETAILS_STEP, field: 'name', messageKey: 'teams.wizard.error.name' });
  }

  const codeRaw = typeof values.shortCode === 'string' ? values.shortCode : '';
  const codeTrimmed = codeRaw.trim();
  if (individual) {
    if (!normalizeTeamCode(codeRaw)) {
      issues.push({ stepId: DETAILS_STEP, field: 'shortCode', messageKey: 'teams.wizard.error.code' });
    }
  } else if (codeTrimmed !== '' && !TEAM_CODE_PATTERN.test(codeTrimmed)) {
    issues.push({ stepId: DETAILS_STEP, field: 'shortCode', messageKey: 'teams.wizard.error.code' });
  }

  // Solo la vía elegida valida: lo escrito en la otra se conserva sin bloquear.
  if (path === 'bulk') {
    for (const issue of parseTeamCsv(values.bulkCsv).issues) {
      issues.push({
        stepId: BULK_STEP,
        field: 'bulkCsv',
        row: issue.row,
        column: issue.column,
        messageKey: issue.messageKey,
        params: issue.params,
      });
    }
  }

  return issues;
}

/**
 * Valores del modelo de pasos (RF-011): solo la vía elegida cuenta como
 * completa, de modo que conservar lo escrito en la otra nunca elija dos.
 */
export function teamWizardValues(values: TeamWizardValues): WizardValues {
  const name = normalizeTeamName(values.name);
  const code = normalizeTeamCode(values.shortCode);
  const path = normalizeTeamEntryPath(values.entryPath);
  const bulkText = typeof values.bulkCsv === 'string' ? values.bulkCsv : '';

  return {
    entryPath: path ?? undefined,
    name: name || undefined,
    code: code || undefined,
    individualRows: path === 'individual' && name && code
      ? [{ name, short_code: code }]
      : undefined,
    bulkCsv: path === 'bulk' && bulkText.trim() ? bulkText : undefined,
  };
}

/** Errores por paso en el formato que consume el índice (`stepState`). */
export function teamWizardErrors(issues: readonly TeamIssue[]): WizardErrors {
  const errors: Record<string, readonly string[]> = {};
  for (const issue of issues) {
    errors[issue.stepId] = [...(errors[issue.stepId] ?? []), issue.messageKey];
  }
  return errors;
}

/** Estado de cada paso del asistente para el índice (RF-006). */
export function teamWizardStatuses(
  values: TeamWizardValues,
  issues: readonly TeamIssue[] = [],
  t: WizardTranslate = identity,
): WizardStepStatus[] {
  const path = normalizeTeamEntryPath(values.entryPath);
  const statuses = wizardStepStates('teams', t, teamWizardValues(values), teamWizardErrors(issues));

  // RF-004: en vía masiva, el estado de `teams.details` se clasifica a partir
  // de los campos `name`/`shortCode` (vacío/válido/inválido por formato), sin
  // bloquear la confirmación.
  if (path !== 'individual') {
    return statuses.map((status) => {
      if (status.id !== 'teams.details') return status;
      const name = normalizeTeamName(values.name);
      const codeRaw = typeof values.shortCode === 'string' ? values.shortCode : '';
      const codeTrimmed = codeRaw.trim();
      const nameFilled = name !== '';
      const codeFilled = codeTrimmed !== '';
      const nameError = issues.some((issue) => issue.stepId === 'teams.details' && issue.field === 'name');
      const codeError = issues.some((issue) => issue.stepId === 'teams.details' && issue.field === 'shortCode');
      let state: typeof status.state;
      if (nameError || codeError) {
        state = nameFilled || codeFilled ? 'error' : status.state;
      } else if (nameFilled && codeFilled) {
        state = 'complete';
      } else if (nameFilled || codeFilled) {
        state = 'incomplete';
      } else {
        state = 'omitted';
      }
      return { ...status, state };
    });
  }

  return statuses;
}

/** Confirmación: datos y revisión completos y exactamente una vía elegida. */
export function teamConfirmation(
  values: TeamWizardValues,
  issues: readonly TeamIssue[] = [],
  t: WizardTranslate = identity,
): ConfirmResult {
  const result = canConfirm('teams', teamWizardStatuses(values, issues, t));
  // En vía masiva, `teams.details` no bloquea la confirmación (RF-007).
  const path = normalizeTeamEntryPath(values.entryPath);
  if (path !== 'individual') {
    const blockedBy = result.blockedBy.filter((id) => id !== 'teams.details');
    return { ok: blockedBy.length === 0, blockedBy };
  }
  return result;
}

/** Resumen del paso de revisión. */
export interface TeamReview {
  readonly path: TeamEntryPath | null;
  readonly pathLabelKey: string;
  /** Equipos que se registrarán, ya normalizados. */
  readonly teams: TeamCsvRow[];
  readonly count: number;
  /** Claves i18n de los avisos que acompañan a la revisión. */
  readonly warningKeys: readonly string[];
}

/** Alias corto de `reviewTeams` (T006): genera el resumen de revisión. */
export function review(state: TeamWizardValues | { readonly values?: TeamWizardValues } | null | undefined): TeamReview {
  const values =
    state && typeof state === 'object' && 'values' in state
      ? ((state as { values?: TeamWizardValues }).values ?? {})
      : (state ?? {});
  return reviewTeams(values as TeamWizardValues);
}

export function reviewTeams(values: TeamWizardValues): TeamReview {
  const path = normalizeTeamEntryPath(values.entryPath);
  const teams: TeamCsvRow[] = [];
  if (path === 'individual') {
    const name = normalizeTeamName(values.name);
    const code = normalizeTeamCode(values.shortCode);
    if (name && code) teams.push({ name, short_code: code, logo_url: null });
  } else if (path === 'bulk') {
    teams.push(...parseTeamCsv(values.bulkCsv).rows);
  }

  return {
    path,
    pathLabelKey: path === 'bulk' ? 'teams.wizard.pathBulk' : 'teams.wizard.pathIndividual',
    teams,
    count: teams.length,
    // RF-003 / IN-1: el alta no inscribe; para inscribir se usa el asistente de fases.
    warningKeys: ['teams.wizard.noStage'],
  };
}

/** Cuerpo de `POST /teams`: nombre y código, **sin** fase destino (IN-1). */
export function buildTeamBody(values: TeamWizardValues): Record<string, unknown> | null {
  const name = normalizeTeamName(values.name);
  const shortCode = normalizeTeamCode(values.shortCode);
  if (!isNameValid(name) || !shortCode) return null;
  return { name, short_code: shortCode };
}

/** Cuerpo de `POST /teams/bulk`: las filas válidas, **sin** fase destino (IN-1). */
export function buildBulkTeamsBody(values: TeamWizardValues): Record<string, unknown> | null {
  const parsed = parseTeamCsv(values.bulkCsv);
  if (parsed.issues.length || !parsed.rows.length) return null;
  return { teams: parsed.rows };
}

export function teamsPath(tournamentId: string): string {
  return `/tournaments/${tournamentId}/teams`;
}

export function bulkTeamsPath(tournamentId: string): string {
  return `/tournaments/${tournamentId}/teams/bulk`;
}

/**
 * Dirección del asistente de fases, para inscribir después del alta (RF-003,
 * spec 025 RF-013): apunta al ancla `#fases` y **no escribe ningún paso** en la
 * dirección; el propio asistente resuelve su paso de entrada al montar.
 */
export function phasesAssistantHref(tournamentId: string): string {
  return `/workspace/tournaments/${tournamentId}#fases`;
}

/** Un paso del plan de alta: un equipo o la carga masiva. */
export type TeamPlanStep =
  | {
    readonly kind: 'create_team';
    readonly path: string;
    readonly body: Record<string, unknown>;
  }
  | {
    readonly kind: 'create_teams_bulk';
    readonly path: string;
    readonly body: Record<string, unknown>;
  };

export interface TeamCreationPlan {
  readonly mode: TeamEntryPath | null;
  readonly steps: readonly TeamPlanStep[];
}

/**
 * Plan de alta (RF-011): una sola llamada, la de la vía elegida. Sin vía, con
 * datos inválidos o con filas inválidas no hay ninguna llamada que hacer.
 */
export function planTeamCreation(input: {
  readonly tournamentId: string;
  readonly values: TeamWizardValues;
}): TeamCreationPlan {
  const mode = normalizeTeamEntryPath(input.values.entryPath);
  if (mode === 'individual') {
    const body = buildTeamBody(input.values);
    return body
      ? { mode, steps: [{ kind: 'create_team', path: teamsPath(input.tournamentId), body }] }
      : { mode, steps: [] };
  }
  if (mode === 'bulk') {
    const body = buildBulkTeamsBody(input.values);
    return body
      ? { mode, steps: [{ kind: 'create_teams_bulk', path: bulkTeamsPath(input.tournamentId), body }] }
      : { mode, steps: [] };
  }
  return { mode: null, steps: [] };
}

/**
 * Valores que se guardan en el borrador de la pestaña (RF-011, RF-014): el
 * texto del CSV, el archivo elegido y lo escrito en la otra vía, sin recortes.
 */
export function teamDraftValues(values: TeamWizardValues): Record<string, unknown> {
  return {
    name: typeof values.name === 'string' ? values.name : '',
    shortCode: typeof values.shortCode === 'string' ? values.shortCode : '',
    entryPath: normalizeTeamEntryPath(values.entryPath),
    bulkCsv: typeof values.bulkCsv === 'string' ? values.bulkCsv : '',
    bulkFileName: typeof values.bulkFileName === 'string' ? values.bulkFileName : '',
  };
}

/**
 * Restaura el borrador de la pestaña. Las filas y sus errores se recalculan con
 * `parseTeamCsv` (determinista), así que el CSV vuelve con su texto, sus filas
 * y sus mensajes. Un borrador ilegible deja el asistente vacío.
 */
/**
 * Infiere la vía de alta de un borrador legacy que no declara `entryPath`
 * válido (RF-006, spec 027). Las señales se calculan sobre los valores
 * presentes, sin validar su formato.
 */
export function inferTeamEntryPath(source: Record<string, unknown>): TeamEntryPath {
  const individualSignal =
    (typeof source.name === 'string' && source.name.trim() !== '') ||
    (typeof source.shortCode === 'string' && source.shortCode.trim() !== '');
  const bulkSignal =
    (typeof source.bulkCsv === 'string' && source.bulkCsv.trim() !== '') ||
    (typeof source.bulkFileName === 'string' && source.bulkFileName.trim() !== '');

  if (individualSignal && !bulkSignal) return 'individual';
  if (bulkSignal && !individualSignal) return 'bulk';
  // Ambas señales o ninguna: prioridad a la vía individual.
  return 'individual';
}

/** Alias de compatibilidad para la normalización legacy (T005). */
export const normalizeLegacyTeamValues = restoreTeamValues;
export const normalizeLegacyTeams = restoreTeamValues;

export function restoreTeamValues(saved: Record<string, unknown> | null | undefined): TeamWizardValues {
  const source = saved ?? {};
  const declared = normalizeTeamEntryPath(source.entryPath);
  const entryPath = declared ?? inferTeamEntryPath(source);
  return {
    name: typeof source.name === 'string' ? source.name : '',
    shortCode: typeof source.shortCode === 'string' ? source.shortCode : '',
    entryPath,
    bulkCsv: typeof source.bulkCsv === 'string' ? source.bulkCsv : '',
    bulkFileName: typeof source.bulkFileName === 'string' ? source.bulkFileName : '',
  };
}
