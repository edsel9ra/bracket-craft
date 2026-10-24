/**
 * Textos visibles que el arnés E2E usa como localizadores accesibles.
 *
 * La corrida fija el idioma con la cookie `bc_locale` y busca por texto, rol y
 * nombre accesible (RNF-005); nunca por clases ni atributos de maquetación.
 * Los textos se copian del catálogo `useI18n.ts` y `tests/e2e-observations.test.ts`
 * comprueba que no derivan: si una traducción cambia, la prueba unitaria falla
 * antes de que el navegador busque un texto que ya no existe.
 */

import { realtimeStatusLabelKey, type RealtimeLabelNamespace } from '../app/utils/realtimeStatusLabel.ts';

export type E2ELocale = 'es' | 'en';

/** Idioma fijo de la corrida: el del contexto del navegador y el de la interfaz. */
export const E2E_LOCALE: E2ELocale = 'es';

/** Cookie de idioma del cliente (`useI18n`), fijada antes de navegar. */
export const E2E_LOCALE_COOKIE = 'bc_locale';

export interface LocalizedText {
  /** Clave i18n de la que procede el texto. */
  readonly key: string;
  readonly es: string;
  readonly en: string;
}

export interface LocaleCookie {
  readonly name: string;
  readonly value: string;
  readonly path: string;
}

/** Cookie de idioma lista para `context.addCookies`. */
export function localeCookie(locale: E2ELocale = E2E_LOCALE): LocaleCookie {
  return { name: E2E_LOCALE_COOKIE, value: locale, path: '/' };
}

/** Texto del idioma fijado; el contraste es/en lo verifica la prueba unitaria. */
export function labelText(text: LocalizedText, locale: E2ELocale = E2E_LOCALE): string {
  return text[locale];
}

function statusText(
  namespace: RealtimeLabelNamespace,
  status: VisibleRealtimeStatus,
  es: string,
  en: string,
): LocalizedText {
  const key = realtimeStatusLabelKey(status, namespace);
  if (key === null) throw new Error(`the visible status ${status} must have a label key`);
  return { key, es, en };
}

/** Estados visibles: los únicos que una vista anuncia con texto. */
export type VisibleRealtimeStatus = 'connected' | 'reconnecting' | 'retrying' | 'error';

/**
 * Etiquetas de estado por namespace. `retrying` (reintento manual) nunca es
 * igual a `reconnecting` (reconexión automática) en ninguno de los dos idiomas.
 */
export const REALTIME_STATUS_TEXT: Readonly<
  Record<RealtimeLabelNamespace, Readonly<Record<VisibleRealtimeStatus, LocalizedText>>>
> = {
  public: {
    connected: statusText('public', 'connected', 'Actualización en vivo conectada', 'Live updates connected'),
    reconnecting: statusText(
      'public',
      'reconnecting',
      'Reconectando actualización en vivo',
      'Reconnecting live updates',
    ),
    retrying: statusText('public', 'retrying', 'Reintentando…', 'Retrying…'),
    error: statusText(
      'public',
      'error',
      'La actualización en vivo no está disponible',
      'Live updates are unavailable',
    ),
  },
  workspace: {
    connected: statusText(
      'workspace',
      'connected',
      'Actualización en vivo conectada',
      'Live updates connected',
    ),
    reconnecting: statusText(
      'workspace',
      'reconnecting',
      'Reconectando actualización en vivo',
      'Reconnecting live updates',
    ),
    retrying: statusText('workspace', 'retrying', 'Reintentando…', 'Retrying…'),
    error: statusText(
      'workspace',
      'error',
      'La actualización en vivo no está disponible',
      'Live updates are unavailable',
    ),
  },
  match: {
    connected: statusText(
      'match',
      'connected',
      'Actualización del partido conectada',
      'Match live updates connected',
    ),
    reconnecting: statusText(
      'match',
      'reconnecting',
      'Reconectando actualización del partido',
      'Reconnecting match live updates',
    ),
    retrying: statusText('match', 'retrying', 'Reintentando…', 'Retrying…'),
    error: statusText(
      'match',
      'error',
      'La actualización del partido no está disponible',
      'Match live updates are unavailable',
    ),
  },
};

/**
 * Controles y datos de la preparación (sesión del Workspace y control de
 * reintento) y anclas accesibles de cada vista: encabezados y etiquetas con los
 * que se acota el localizador y se comprueba que la vista está cargada.
 */
export const E2E_LABELS = {
  retry: { key: 'common.retry', es: 'Reintentar', en: 'Retry' },
  loginEmail: { key: 'auth.email', es: 'Email', en: 'Email' },
  loginPassword: { key: 'auth.password', es: 'Contraseña', en: 'Password' },
  loginSubmit: { key: 'auth.login', es: 'Entrar', en: 'Log in' },
  workspaceReady: { key: 'workspace.private', es: 'Workspace privado', en: 'Private workspace' },
  workspaceTournaments: {
    key: 'workspace.yourTournaments',
    es: 'Tus torneos',
    en: 'Your tournaments',
  },
  workspaceConfigure: {
    key: 'workspace.configure',
    es: 'Configurar torneo',
    en: 'Configure tournament',
  },
  operationReportHeading: { key: 'match.buildReport', es: 'Construye el acta', en: 'Build the report' },
  operationEventType: { key: 'match.eventType', es: 'Tipo', en: 'Type' },
  operationEventMinute: { key: 'match.minute', es: 'Minuto', en: 'Minute' },
  operationSubstitutionPreview: {
    key: 'match.substitutionPreview',
    es: 'Vista previa de sustituciones',
    en: 'Substitution preview',
  },
  // Escenario propio de operación y cierre (H4-T10). Solo se añaden anclas:
  // ninguna etiqueta del escenario de reintento cambia (RNF-008).
  wizardIndex: { key: 'wizard.indexLabel', es: 'Pasos del asistente', en: 'Wizard steps' },
  wizardNext: { key: 'wizard.next', es: 'Siguiente', en: 'Next' },
  wizardStateComplete: { key: 'wizard.state.complete', es: 'Completo', en: 'Complete' },
  wizardStateError: { key: 'wizard.state.error', es: 'Con error', en: 'With errors' },
  workspaceName: { key: 'workspace.name', es: 'Nombre', en: 'Name' },
  wizardReadOnly: {
    key: 'wizard.readOnly',
    es: 'Solo lectura: los valores se muestran sin acciones de escritura.',
    en: 'Read-only: values are shown without write actions.',
  },
  rulesWizard: { key: 'rules.wizardTitle', es: 'Asistente de reglas', en: 'Rules assistant' },
  phasesWizard: { key: 'stage.wizard.title', es: 'Fases del torneo', en: 'Tournament stages' },
  teamsWizard: { key: 'teams.wizard.title', es: 'Equipos del torneo', en: 'Tournament teams' },
  rulesStepScoring: { key: 'wizard.rules.scoring', es: 'Puntuación', en: 'Scoring' },
  rulesStepFormat: { key: 'wizard.rules.format', es: 'Formato y límites', en: 'Format and limits' },
  rulesStepTiebreakers: {
    key: 'wizard.rules.tiebreakers',
    es: 'Orden de desempates',
    en: 'Tiebreaker order',
  },
  rulesStepDiscipline: { key: 'wizard.rules.discipline', es: 'Disciplina', en: 'Discipline' },
  rulesStepResolution: { key: 'wizard.rules.resolution', es: 'Resolución', en: 'Resolution' },
  rulesStepSubstitutions: {
    key: 'wizard.rules.substitutions',
    es: 'Sustituciones',
    en: 'Substitutions',
  },
  rulesStepRegistration: {
    key: 'wizard.rules.registration',
    es: 'Inscripción',
    en: 'Registration',
  },
  rulesStepOverrides: {
    key: 'wizard.rules.overrides',
    es: 'Excepciones por fase',
    en: 'Per-stage exceptions',
  },
  teamsStepDetails: { key: 'wizard.teams.details', es: 'Datos del equipo', en: 'Team details' },
  teamsStepIndividual: {
    key: 'wizard.teams.individual',
    es: 'Alta individual',
    en: 'Single entry',
  },
  teamsStepReview: { key: 'wizard.teams.review', es: 'Revisión', en: 'Review' },
  phasesStepIdentity: {
    key: 'wizard.phases.identity',
    es: 'Identificación de la fase',
    en: 'Stage identification',
  },
  phasesStepComposition: {
    key: 'wizard.phases.composition',
    es: 'Composición de equipos',
    en: 'Team composition',
  },
  phasesStepReview: { key: 'wizard.phases.review', es: 'Revisión', en: 'Review' },
  teamsStepBulk: { key: 'wizard.teams.bulk', es: 'Carga masiva', en: 'Bulk upload' },
  stageOrderField: { key: 'setup.order', es: 'Orden', en: 'Order' },
  versionField: { key: 'setup.version', es: 'Versión', en: 'Version' },
  stageField: { key: 'setup.stage', es: 'Fase', en: 'Stage' },
  primaryNav: {
    key: 'shell.primaryNavigation',
    es: 'Navegación principal',
    en: 'Primary navigation',
  },
  tournamentsNav: { key: 'shell.tournaments', es: 'Torneos', en: 'Tournaments' },
  tournamentNav: {
    key: 'shell.tournamentNavigation',
    es: 'Navegación del torneo',
    en: 'Tournament navigation',
  },
  navCalendar: { key: 'shell.calendar', es: 'Calendario', en: 'Schedule' },
  navRosters: { key: 'shell.rosters', es: 'Plantillas', en: 'Rosters' },
  calendarTitle: {
    key: 'tournament.calendar.title',
    es: 'Calendario del torneo',
    en: 'Tournament schedule',
  },
  newTournament: {
    key: 'workspace.newTournament',
    es: 'Nuevo torneo',
    en: 'New tournament',
  },
  seasonField: { key: 'workspace.season', es: 'Temporada', en: 'Season' },
  startField: { key: 'workspace.start', es: 'Inicio', en: 'Start' },
  createDraftTournament: {
    key: 'workspace.createDraft',
    es: 'Crear borrador',
    en: 'Create draft',
  },
  teamCodeField: { key: 'setup.code', es: 'Código', en: 'Code' },
  teamPathBulk: { key: 'teams.wizard.pathBulk', es: 'Carga masiva', en: 'Bulk upload' },
  teamCsvField: {
    key: 'teams.wizard.pasteCsv',
    es: 'Equipos en CSV o TXT',
    en: 'Teams in CSV or TXT',
  },
  teamsConfirm: {
    key: 'teams.wizard.confirm',
    es: 'Registrar equipos',
    en: 'Register teams',
  },
  teamsCreatedBulk: {
    key: 'teams.wizard.createdBulk',
    es: 'Equipos registrados: {count}.',
    en: 'Teams registered: {count}.',
  },
  stageCreatedAndAssigned: {
    key: 'stage.wizard.createdAndAssigned',
    es: 'Fase creada e inscripción aplicada.',
    en: 'Stage created and enrollment applied.',
  },
  homeField: { key: 'setup.home', es: 'Local', en: 'Home' },
  awayField: { key: 'setup.away', es: 'Visitante', en: 'Away' },
  matchdayField: { key: 'setup.matchday', es: 'Jornada', en: 'Matchday' },
  matchDateField: { key: 'setup.matchDateTime', es: 'Fecha y hora', en: 'Date and time' },
  createMatch: { key: 'setup.createMatch', es: 'Crear partido', en: 'Create match' },
  saveRules: { key: 'setup.saveRules', es: 'Guardar reglas', en: 'Save rules' },
  createDraftVersion: {
    key: 'setup.createDraftVersion',
    es: 'Crear nueva versión draft',
    en: 'Create new draft version',
  },
  gameFormatField: { key: 'rules.field.gameFormat', es: 'Formato de juego', en: 'Game format' },
  minPlayersField: {
    key: 'rules.field.minPlayers',
    es: 'Mínimo de jugadores por equipo',
    en: 'Minimum players per team',
  },
  maxPlayersField: {
    key: 'rules.field.maxPlayers',
    es: 'Máximo de jugadores por equipo',
    en: 'Maximum players per team',
  },
  rosterLimitsPairError: {
    key: 'rules.error.rosterLimitsPair',
    es: 'El máximo de jugadores no puede ser menor que el mínimo.',
    en: 'The maximum number of players cannot be lower than the minimum.',
  },
  formatWarningRules: {
    key: 'format.notice.rules',
    es: 'La planilla soportada es de once jugadores. La modalidad real de la alineación llegará con la spec de formaciones; esta advertencia no bloquea el guardado.',
    en: 'The supported scoresheet is eleven-a-side. The real lineup modality will arrive with the formations spec; this warning does not block saving.',
  },
  formatWarningSummary: {
    key: 'format.notice.summary',
    es: 'El formato declarado no es 11v11: la planilla del torneo sigue siendo de once jugadores y la modalidad real de la alineación llegará con la spec de formaciones.',
    en: 'The declared format is not 11v11: the tournament scoresheet remains eleven-a-side and the real lineup modality will arrive with the formations spec.',
  },
  formatWarningOperation: {
    key: 'format.notice.operation',
    es: 'Este partido declara un formato distinto de 11v11. La operación y la planilla siguen siendo de once jugadores; la modalidad real de la alineación llegará con la spec de formaciones.',
    en: 'This match declares a format other than 11v11. The operation and the scoresheet remain eleven-a-side; the real lineup modality will arrive with the formations spec.',
  },
  stageModeField: { key: 'stage.wizard.mode', es: 'Trabajar sobre', en: 'Work on' },
  stageModeCreate: { key: 'stage.wizard.modeCreate', es: 'Una fase nueva', en: 'A new stage' },
  stageConfirmCreate: { key: 'stage.wizard.confirmCreate', es: 'Crear fase', en: 'Create stage' },
  stageEnrollmentBlocked: {
    key: 'stage.wizard.enrollmentBlocked',
    es: 'Estos equipos no se pueden inscribir todavía:',
    en: 'These teams cannot be enrolled yet:',
  },
  stagePartial: {
    key: 'stage.wizard.partial',
    es: 'La fase quedó creada, pero la inscripción no se aplicó. Los equipos seleccionados siguen marcados para reintentar.',
    en: 'The stage was created, but the enrollment did not apply. The selected teams stay marked so you can retry.',
  },
  matchSegments: {
    key: 'match.segments',
    es: '{count} segmento(s)',
    en: '{count} segment(s)',
  },
  openingBlockedTitle: {
    key: 'rosterLimits.opening.title',
    es: 'El partido no se ha abierto',
    en: 'The match was not opened',
  },
  startNextSegment: {
    key: 'match.startNextSegment',
    es: 'Iniciar siguiente segmento',
    en: 'Start next segment',
  },
  createSegment: {
    key: 'match.createSegment',
    es: 'Crear segmento',
    en: 'Create segment',
  },
  segmentStartField: {
    key: 'match.startMinute',
    es: 'Minuto inicial',
    en: 'Starting minute',
  },
  rostersTitle: {
    key: 'tournament.rosters.title',
    es: 'Plantillas del torneo',
    en: 'Tournament rosters',
  },
  rosterRetire: { key: 'tournament.rosters.retire', es: 'Retirar', en: 'Retire' },
  rosterReactivate: { key: 'tournament.rosters.reactivate', es: 'Reactivar', en: 'Reactivate' },
  rosterRetiredNotice: {
    key: 'tournament.rosters.retired',
    es: 'Jugador retirado.',
    en: 'Player retired.',
  },
  rosterReactivatedNotice: {
    key: 'tournament.rosters.reactivated',
    es: 'Jugador reactivado.',
    en: 'Player reactivated.',
  },
  rosterStateActive: { key: 'tournament.rosters.stateActive', es: 'Inscrito', en: 'Registered' },
  rosterStateRetired: { key: 'tournament.rosters.stateRetired', es: 'Retirado', en: 'Retired' },
  // Equivalencia del aviso de cierre con el 409 real (RF-039, criterio 13):
  // el aviso y el campo de la jornada de cierre.
  rosterLockNotice: {
    key: 'tournament.rosters.lockNotice',
    es: 'La inscripción de jugadores está cerrada desde la jornada {matchday}.',
    en: 'Player registration has been closed since matchday {matchday}.',
  },
  rosterLockField: {
    key: 'rules.rosterLockMatchday',
    es: 'Cerrar plantilla desde la jornada',
    en: 'Lock roster from matchday',
  },
  // Cierre del acta sin rechazo por minuto (RF-032): alta mínima de un jugador
  // por equipo, apertura del partido, evento en el límite y cierre.
  publishDraft: { key: 'setup.publishDraft', es: 'Publicar versión draft', en: 'Publish draft version' },
  statusPublished: { key: 'status.published', es: 'Publicado', en: 'Published' },
  rosterTeamField: { key: 'setup.team', es: 'Equipo', en: 'Team' },
  rosterListTitle: {
    key: 'tournament.rosters.listTitle',
    es: 'Plantilla de {team}',
    en: '{team} roster',
  },
  playerFirstName: { key: 'match.firstName', es: 'Nombre', en: 'First name' },
  playerLastName: { key: 'match.lastName', es: 'Apellido', en: 'Last name' },
  playerDocument: { key: 'match.document', es: 'Documento', en: 'Document' },
  playerBirthDate: { key: 'match.birthDate', es: 'Nacimiento', en: 'Birth date' },
  playerNumber: { key: 'match.number', es: 'Dorsal', en: 'Number' },
  addPlayer: { key: 'match.addPlayer', es: 'Agregar jugador', en: 'Add player' },
  playerCreated: {
    key: 'tournament.rosters.created',
    es: 'Jugador dado de alta.',
    en: 'Player registered.',
  },
  eventTeamField: { key: 'setup.teams', es: 'Equipos', en: 'Teams' },
  eventPlayerField: { key: 'match.player', es: 'Jugador', en: 'Player' },
  eventAddedMinuteField: { key: 'match.addedMinute', es: 'Adición', en: 'Added time' },
  eventAdd: { key: 'match.addEvent', es: 'Añadir evento', en: 'Add event' },
  saveLineup: { key: 'match.saveLineup', es: 'Guardar planilla', en: 'Save lineup' },
  lineupRole: { key: 'match.role', es: 'Rol', en: 'Role' },
  closeReport: {
    key: 'match.confirmReport',
    es: 'Cerrar y confirmar acta',
    en: 'Close and confirm report',
  },
  reportClosed: { key: 'match.closed', es: 'Acta cerrada', en: 'Report closed' },
} as const satisfies Record<string, LocalizedText>;

export type E2ELabelName = keyof typeof E2E_LABELS;
