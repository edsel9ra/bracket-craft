import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import test from 'node:test';

import {
  buildInviteMemberBody,
  buildOfficialAssignmentBody,
  buildRosterPlayerBody,
  buildTournamentDraftBody,
} from '../app/utils/requestBodies.ts';

// Spec 019, T7 (plan §9; RF-005 «el cliente solo envía campos declarados» y
// RNF-004(b) «el cliente se blinda», como cita tasks.md): los cuatro cuerpos
// que el cliente enviaba expandiendo un formulario reactivo pasan a
// constructores puros de `app/utils/requestBodies.ts`.
//
// Cada constructor se comprueba con las mismas cuatro propiedades:
//
// 1. devuelve **exactamente** las claves que declara su DTO del backend
//    (`Object.keys(...).sort()`);
// 2. **ignora** las claves de UI que el formulario pueda arrastrar (se añade
//    una bandera de interfaz al input y no puede aparecer en el cuerpo);
// 3. **no muta** su argumento (el formulario sigue siendo la fuente);
// 4. produce el cuerpo que hoy se envía en un caso real (mismo valor).
//
// El patrón es el de `buildCloseReportBody` (`app/utils/matchClose.ts`), que
// esta prueba no toca. Sin `vue`, ni `#app`, ni `request`, ni efectos: todo es
// puro y corre con el ejecutor de Node (`node --test`).
//
// Claves esperadas y decisión sobre los opcionales del DTO (plan §9):
//
// - `CreateRosterPlayerRequest` (`backend/app/modules/tournaments/schemas.py`):
//   declara 10 claves; el formulario solo maneja 7 (`team_id` + los seis del
//   form). `document_type` e `issuing_country` tienen default en el servidor y
//   `photo_url` el modelo exige nulo, así que el constructor **no** las emite:
//   subconjunto declarado y válido, con el comportamiento idéntico al actual.
// - `CreateInvitationRequest` (`invitations/schemas.py`): `email`, `role_code`.
// - `OfficialAssignmentRequest` (`matches/schemas.py`): `organization_user_id`,
//   `official_role`.
// - `CreateTournamentRequest` (`rules_engine/schemas.py`): `name`, `season`,
//   `start_date`; `rules_config` **no** viaja porque el servidor le pone su
//   default (plan §9).

test('buildRosterPlayerBody sends exactly the declared roster player keys', () => {
  const form = {
    team_id: 'team-0001',
    first_name: 'Ada',
    last_name: 'Lovelace',
    national_id: 'CC-100200300',
    birth_date: '1990-12-10',
    dorsal_number: 10,
    photo_consent: true,
    // Bandera de interfaz: el formulario puede arrastrar estado de UI (RF-005).
    wizard_step: 'jugadores',
    submitting: true,
  } as const;
  const snapshot = structuredClone(form);

  const body = buildRosterPlayerBody(form);

  // 1. Exactamente las claves declaradas (subconjunto que maneja el form).
  assert.deepEqual(Object.keys(body).sort(), [
    'birth_date',
    'dorsal_number',
    'first_name',
    'last_name',
    'national_id',
    'photo_consent',
    'team_id',
  ]);
  // 2. Las claves ajenas del formulario no viajan.
  assert.ok(!('wizard_step' in body), 'the UI flag must not travel');
  assert.ok(!('submitting' in body), 'the UI flag must not travel');
  // 4. Caso real: el mismo cuerpo que hoy se envía, valor a valor.
  assert.deepEqual(body, {
    team_id: 'team-0001',
    first_name: 'Ada',
    last_name: 'Lovelace',
    national_id: 'CC-100200300',
    birth_date: '1990-12-10',
    dorsal_number: 10,
    photo_consent: true,
  });
  // 3. No muta su argumento.
  assert.deepEqual(form, snapshot, 'the builder must not mutate its input');
});

test('buildInviteMemberBody sends exactly the declared invitation keys', () => {
  const form = {
    email: 'new.member@example.test',
    role_code: 'operator',
    // Bandera de interfaz.
    dialog_open: true,
    returnTo: '/workspace',
  } as const;
  const snapshot = structuredClone(form);

  const body = buildInviteMemberBody(form);

  assert.deepEqual(Object.keys(body).sort(), ['email', 'role_code']);
  assert.ok(!('dialog_open' in body), 'the UI flag must not travel');
  assert.ok(!('returnTo' in body), 'the UI flag must not travel');
  assert.deepEqual(body, {
    email: 'new.member@example.test',
    role_code: 'operator',
  });
  assert.deepEqual(form, snapshot, 'the builder must not mutate its input');
});

test('buildOfficialAssignmentBody sends exactly the declared official keys', () => {
  const form = {
    organization_user_id: 'user-0001',
    official_role: 'main_referee',
    // Bandera de interfaz.
    picker_open: true,
    eligible_officials: ['user-0002'],
  } as const;
  const snapshot = structuredClone(form);

  const body = buildOfficialAssignmentBody(form);

  assert.deepEqual(Object.keys(body).sort(), ['official_role', 'organization_user_id']);
  assert.ok(!('picker_open' in body), 'the UI flag must not travel');
  assert.ok(!('eligible_officials' in body), 'the UI flag must not travel');
  assert.deepEqual(body, {
    organization_user_id: 'user-0001',
    official_role: 'main_referee',
  });
  assert.deepEqual(form, snapshot, 'the builder must not mutate its input');
});

test('buildTournamentDraftBody sends exactly the declared tournament keys', () => {
  const form = {
    name: 'Copa Primavera',
    season: '2026',
    start_date: '2026-03-01',
    // Bandera de interfaz: `createForm` puede contener propiedades de UI.
    showCreateForm: true,
    creating: false,
  } as const;
  const snapshot = structuredClone(form);

  const body = buildTournamentDraftBody(form);

  // `rules_config` no viaja: el servidor le pone su default (plan §9).
  assert.deepEqual(Object.keys(body).sort(), ['name', 'season', 'start_date']);
  assert.ok(!('showCreateForm' in body), 'the UI flag must not travel');
  assert.ok(!('creating' in body), 'the UI flag must not travel');
  assert.ok(!('rules_config' in body), 'the server default must not travel');
  assert.deepEqual(body, {
    name: 'Copa Primavera',
    season: '2026',
    start_date: '2026-03-01',
  });
  assert.deepEqual(form, snapshot, 'the builder must not mutate its input');
});

// ---------------------------------------------------------------------------
// T8 — cableado de las cuatro páginas (plan §9 y §12.5; RF-005, RNF-004(b)).
//
// T7 probó los constructores; aquí se garantiza que las cuatro páginas del
// Workspace los **consumen** y que ninguna queda expandiendo un formulario
// reactivo en el `body` de los cuatro patrones endurecidos (con el servidor
// rechazando claves no declaradas con 422, ese spread sería un 422 en vivo).
//
// El patrón es el barrido de fuente que ya usa el repositorio
// (`tests/match-operation-screen.test.ts`, `tests/crest-surfaces.test.ts`): no
// hay arnés de componentes, así que se lee la fuente de cada página y se
// comprueba la llamada exacta al constructor y la ausencia del spread
// anterior. El grep de verificación de `tasks.md` (`body: { \.\.\.`) solo
// alcanza dos de los cuatro patrones históricos; estas pruebas cubren los
// cuatro.
// ---------------------------------------------------------------------------

const ROSTERS_PAGE = readFileSync(
  new URL('../app/pages/workspace/tournaments/[id]/rosters.vue', import.meta.url),
  'utf8',
);
const MEMBERS_PAGE = readFileSync(
  new URL('../app/pages/workspace/members.vue', import.meta.url),
  'utf8',
);
const MATCH_PAGE = readFileSync(
  new URL('../app/pages/workspace/matches/[id].vue', import.meta.url),
  'utf8',
);
const WORKSPACE_PAGE = readFileSync(
  new URL('../app/pages/workspace/index.vue', import.meta.url),
  'utf8',
);

test('the four workspace pages import their request body builders', () => {
  assert.match(
    ROSTERS_PAGE,
    /import \{ buildRosterPlayerBody \} from '~\/utils\/requestBodies'/,
    'rosters.vue must import buildRosterPlayerBody',
  );
  assert.match(
    MEMBERS_PAGE,
    /import \{ buildInviteMemberBody \} from '~\/utils\/requestBodies'/,
    'members.vue must import buildInviteMemberBody',
  );
  assert.match(
    MATCH_PAGE,
    /import \{ buildOfficialAssignmentBody \} from '~\/utils\/requestBodies'/,
    'matches/[id].vue must import buildOfficialAssignmentBody',
  );
  assert.match(
    WORKSPACE_PAGE,
    /import \{ buildTournamentDraftBody \} from '~\/utils\/requestBodies'/,
    'workspace/index.vue must import buildTournamentDraftBody',
  );
});

test('each page serializes the hardened body through its builder', () => {
  // createPlayer: el cuerpo exacto del alta (team_id + los campos del form).
  assert.match(
    ROSTERS_PAGE,
    /body: buildRosterPlayerBody\(\{ team_id: selectedTeamId\.value, \.\.\.playerForm \}\)/,
    'rosters.vue must build the roster player body',
  );
  // inviteMember: solo email y role_code del formulario reactivo.
  assert.match(
    MEMBERS_PAGE,
    /body: buildInviteMemberBody\(inviteForm\)/,
    'members.vue must build the invitation body',
  );
  // assignOfficial: solo organization_user_id y official_role.
  assert.match(
    MATCH_PAGE,
    /body: buildOfficialAssignmentBody\(officialForm\)/,
    'matches/[id].vue must build the official assignment body',
  );
  // createTournament: solo name, season y start_date (sin reglas ni UI).
  assert.match(
    WORKSPACE_PAGE,
    /body: buildTournamentDraftBody\(createForm\)/,
    'workspace/index.vue must build the tournament draft body',
  );
});

test('no hardened page keeps the legacy reactive spread in the body', () => {
  assert.ok(
    !/body: \{ team_id: [^}]*\.\.\.playerForm/.test(ROSTERS_PAGE),
    'rosters.vue must not spread playerForm into the body',
  );
  assert.ok(
    !MEMBERS_PAGE.includes('body: { ...inviteForm }'),
    'members.vue must not spread inviteForm into the body',
  );
  assert.ok(
    !MATCH_PAGE.includes('body: { ...officialForm }'),
    'matches/[id].vue must not spread officialForm into the body',
  );
  assert.ok(
    !/body: createForm\b/.test(WORKSPACE_PAGE),
    'workspace/index.vue must not send the reactive createForm as-is',
  );
});

test('no page under app/pages spreads a reactive form into a request body', () => {
  const pagesDir = new URL('../app/pages/', import.meta.url);
  const offenders = (readdirSync(pagesDir, { recursive: true }) as string[])
    .map((file) => file.replaceAll('\\', '/'))
    .filter((file) => file.endsWith('.vue'))
    .filter((file) => readFileSync(new URL(file, pagesDir), 'utf8').includes('body: { ...'));
  assert.deepEqual(offenders, [], 'no workspace page may expand a reactive form in a body');
});
