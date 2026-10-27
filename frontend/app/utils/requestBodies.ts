/**
 * Constructores puros de los cuatro cuerpos JSON del cliente (spec 019, plan
 * §9, tarea T7).
 *
 * El servidor pasa a rechazar con **422** cualquier clave que su modelo no
 * declare, así que el cliente se blinda en el único punto donde compone el
 * cuerpo: cada constructor recibe el estado del formulario y devuelve
 * **exactamente** las claves declaradas del DTO. El estado de interfaz nunca
 * viaja (RF-005 «el cliente solo envía campos declarados» y RNF-004(b) «el
 * cliente se blinda», que es lo que cita el bloque T7 de `tasks.md`).
 *
 * El patrón es el de `buildCloseReportBody` (`matchClose.ts`), que **no** se
 * toca: aquí se replica. Este módulo es puro (sin `vue`, sin `#app`, sin
 * `request`, sin reloj, sin almacenamiento y sin efectos), así que corre con el
 * ejecutor de Node (`node --test`).
 *
 * Dos decisiones (plan §9 y uso actual de cada página):
 *
 * 1. **Opcionales del DTO que el formulario no maneja.** `CreateRosterPlayerRequest`
 *    declara 10 claves; el formulario de altas solo maneja 7 (`team_id` + los
 *    seis campos del form) y así se construye hoy. `document_type` e
 *    `issuing_country` conservan el default del servidor y `photo_url` el
 *    validador exige nulo, así que el constructor **no** las emite: subconjunto
 *    declarado y válido, con el comportamiento idéntico al actual (mínimo
 *    movimiento). `CreateTournamentRequest` no recibe `rules_config` porque el
 *    servidor le pone su default (decisión explícita del plan §9). Los otros dos
 *    DTO no tienen opcionales.
 * 2. **Entradas estructurales.** Los formularios ya hablan el idioma del DTO
 *    (snake_case), así que el constructor solo **selecciona** campos declarados;
 *    la firma de índice admite las claves de más que un formulario pueda
 *    arrastrar —que es justo lo que hay que probar que se ignoran— y las
 *    declara cada DTO en su tipo de salida.
 */

import type { AssignableRoleCode } from './labels.ts';

// ---------------------------------------------------------------------------
// Alta de jugador en plantilla — CreateRosterPlayerRequest + team_id
// (backend/app/modules/tournaments/schemas.py)
// ---------------------------------------------------------------------------

/** Estado del formulario de alta de plantillas más el equipo seleccionado. */
export interface RosterPlayerBodyInput {
  readonly team_id: string;
  readonly first_name: string;
  readonly last_name: string;
  readonly national_id: string;
  readonly birth_date: string;
  readonly dorsal_number: number;
  readonly photo_consent: boolean;
  /** Claves de UI que el formulario pueda arrastrar: se ignoran. */
  readonly [key: string]: unknown;
}

/**
 * Cuerpo exacto de `POST /tournaments/{id}/rosters`.
 *
 * Subconjunto declarado de `CreateRosterPlayerRequest`: no emite
 * `document_type` ni `issuing_country` (default del servidor) ni `photo_url`
 * (el modelo rechaza cualquier valor no nulo). Ver la decisión 1 de este
 * módulo.
 */
export interface RosterPlayerBody {
  team_id: string;
  first_name: string;
  last_name: string;
  national_id: string;
  birth_date: string;
  dorsal_number: number;
  photo_consent: boolean;
}

/** Construye el cuerpo del alta de un jugador sin arrastrar estado de UI. */
export function buildRosterPlayerBody(input: RosterPlayerBodyInput): RosterPlayerBody {
  return {
    team_id: input.team_id,
    first_name: input.first_name,
    last_name: input.last_name,
    national_id: input.national_id,
    birth_date: input.birth_date,
    dorsal_number: input.dorsal_number,
    photo_consent: input.photo_consent,
  };
}

// ---------------------------------------------------------------------------
// Invitación de miembro — CreateInvitationRequest
// (backend/app/modules/invitations/schemas.py)
// ---------------------------------------------------------------------------

/** Estado del formulario de invitación de `members.vue`. */
export interface InviteMemberBodyInput {
  readonly email: string;
  readonly role_code: AssignableRoleCode;
  /** Claves de UI que el formulario pueda arrastrar: se ignoran. */
  readonly [key: string]: unknown;
}

/**
 * Cuerpo exacto de `POST /organizations/invitations`: las **dos** claves
 * declaradas por `CreateInvitationRequest`, sin opcionales.
 *
 * `AssignableRoleCode` (`labels.ts`) es el mismo catálogo que el
 * `InvitationRole` del backend: `administrator`, `operator`, `referee`,
 * `viewer`.
 */
export interface InviteMemberBody {
  email: string;
  role_code: AssignableRoleCode;
}

/** Construye el cuerpo de la invitación sin arrastrar estado de UI. */
export function buildInviteMemberBody(input: InviteMemberBodyInput): InviteMemberBody {
  return {
    email: input.email,
    role_code: input.role_code,
  };
}

// ---------------------------------------------------------------------------
// Asignación de oficial — OfficialAssignmentRequest
// (backend/app/modules/matches/schemas.py)
// ---------------------------------------------------------------------------

/**
 * Roles de partido: la copia cliente del `OfficialRole` del backend (mismos
 * cinco valores que declara `matches/schemas.py`).
 */
export type OfficialAssignmentRole =
  | 'main_referee'
  | 'assistant_referee_1'
  | 'assistant_referee_2'
  | 'fourth_official'
  | 'match_commissioner';

/** Estado del formulario de asignación de oficiales de la pantalla de operación. */
export interface OfficialAssignmentBodyInput {
  readonly organization_user_id: string;
  readonly official_role: OfficialAssignmentRole;
  /** Claves de UI que el formulario pueda arrastrar: se ignoran. */
  readonly [key: string]: unknown;
}

/**
 * Cuerpo exacto de `POST /matches/{id}/officials`: las **dos** claves
 * declaradas por `OfficialAssignmentRequest`, sin opcionales.
 */
export interface OfficialAssignmentBody {
  organization_user_id: string;
  official_role: OfficialAssignmentRole;
}

/** Construye el cuerpo de la asignación de un oficial sin arrastrar estado de UI. */
export function buildOfficialAssignmentBody(
  input: OfficialAssignmentBodyInput,
): OfficialAssignmentBody {
  return {
    organization_user_id: input.organization_user_id,
    official_role: input.official_role,
  };
}

// ---------------------------------------------------------------------------
// Creación de torneo desde el Workspace — CreateTournamentRequest
// (backend/app/modules/rules_engine/schemas.py)
// ---------------------------------------------------------------------------

/**
 * Estado del formulario de creación de `workspace/index.vue`. Puede contener
 * propiedades de UI, que este constructor descarta.
 */
export interface TournamentDraftBodyInput {
  readonly name: string;
  readonly season: string;
  readonly start_date: string;
  /** Claves de UI que el formulario pueda arrastrar: se ignoran. */
  readonly [key: string]: unknown;
}

/**
 * Cuerpo exacto de `POST /tournaments`.
 *
 * Subconjunto declarado de `CreateTournamentRequest`: **no** envía
 * `rules_config`, cuyo default lo pone el servidor (plan §9). Ver la decisión 1
 * de este módulo.
 */
export interface TournamentDraftBody {
  name: string;
  season: string;
  start_date: string;
}

/** Construye el cuerpo de creación de torneo sin arrastrar estado de UI. */
export function buildTournamentDraftBody(input: TournamentDraftBodyInput): TournamentDraftBody {
  return {
    name: input.name,
    season: input.season,
    start_date: input.start_date,
  };
}
