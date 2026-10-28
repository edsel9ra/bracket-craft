import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import test from 'node:test';

import { extractUsedKeys } from '../app/utils/i18nCatalog.ts';
import {
  EVENT_FIELDS,
  EVENT_TYPES,
  assistCandidates,
  buildDraftEvent,
  dropLegacyClientEventIds,
  eventFields,
  eventSummary,
  eventTypeAnnouncement,
  isEventFieldRequired,
  isUuid,
  newClientEventId,
  validateAssist,
  validateEventValues,
  validateSegmentMinute,
  visibleEventFields,
  type EventField,
  type EventFormValues,
  type EventType,
  type UuidSource,
} from '../app/utils/matchEvents.ts';

// Spec 015, T8 (RF-001, RF-004, RF-005, RF-006, RF-015). Funciones puras del
// formulario por tipo: el catálogo de campos, la construcción del payload que
// solo lleva lo que el tipo declara, el subconjunto exacto de validación de
// cliente (RF-006), el identificador UUID (RF-015) y el descarte de los
// identificadores antiguos de un borrador (D-9). Nada aquí lee el reloj, la red
// ni el almacenamiento: la fuente de UUID entra por parámetro.
//
// Spec 015, T9: además del formulario dinámico, se comprueba contra la propia
// pantalla que el alta usa estas utilidades (identificador, payload y resumen)
// y que los textos nuevos existen en los dos catálogos.

const matchPageSource = readFileSync(
  new URL('../app/pages/workspace/matches/[id].vue', import.meta.url),
  'utf8',
);
const translationsSource = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);

const PLAYERS = [
  { player_id: 'p1', team_id: 'home', is_active: true },
  { player_id: 'p2', team_id: 'home', is_active: true },
  { player_id: 'p3', team_id: 'away', is_active: true },
  { player_id: 'p4', team_id: 'away', is_active: true },
];

const ALL_FIELDS: readonly EventField[] = [
  'player',
  'player_out',
  'player_in',
  'assist',
  'beneficiary',
  'red_card_type',
];

const UUID = '9f1c1e2a-3b4c-4d5e-8f60-718293a4b5c6';

function form(overrides: Partial<EventFormValues> = {}): EventFormValues {
  return {
    event_type: 'goal',
    team_id: 'home',
    player_id: 'p1',
    assist_player_id: '',
    beneficiary_team_id: '',
    player_out_id: '',
    player_in_id: '',
    red_card_type: 'direct_red',
    minute: 45,
    added_minute: 2,
    ...overrides,
  };
}

function fixedUuid(): string {
  return UUID;
}

/** Formulario válido del tipo, con lo mínimo que cada uno exige. */
function validForm(type: EventType): EventFormValues {
  const substitution = type === 'substitution';
  return form({
    event_type: type,
    player_id: substitution ? '' : 'p1',
    player_out_id: substitution ? 'p1' : '',
    player_in_id: substitution ? 'p2' : '',
    beneficiary_team_id: type === 'own_goal' ? 'away' : '',
  });
}

// ---------------------------------------------------------------------------
// Catálogo por tipo (RF-001, RF-004)
// ---------------------------------------------------------------------------

test('declares the seven closed event types in order', () => {
  assert.deepEqual([...EVENT_TYPES], [
    'goal',
    'own_goal',
    'penalty_goal',
    'yellow_card',
    'red_card',
    'substitution',
    'foul',
  ]);
});

test('every type partitions the six own fields into required, optional and forbidden', () => {
  for (const type of EVENT_TYPES) {
    const fields = eventFields(type);
    assert.ok(fields, `eventFields('${type}') returned null`);
    const union = [...fields.required, ...fields.optional, ...fields.forbidden].sort();
    assert.deepEqual(union, [...ALL_FIELDS].sort(), `${type} does not partition the fields`);
    assert.equal(
      new Set(union).size,
      ALL_FIELDS.length,
      `${type} lists a field twice`,
    );
    assert.equal(fields.type, type);
  }
});

test('the catalog of fields per type matches the server contract', () => {
  // Tabla de la spec 015, apéndice A: propios por tipo. `foul` solo añade el
  // jugador (RF-004) y la asistencia solo existe en `goal` (RF-007/RF-009).
  assert.deepEqual(eventFields('goal')?.required, ['player']);
  assert.deepEqual(eventFields('goal')?.optional, ['assist']);
  assert.deepEqual(eventFields('goal')?.forbidden, [
    'beneficiary',
    'player_out',
    'player_in',
    'red_card_type',
  ]);

  assert.deepEqual(eventFields('penalty_goal')?.required, ['player']);
  assert.deepEqual(eventFields('penalty_goal')?.optional, []);
  assert.deepEqual(eventFields('penalty_goal')?.forbidden, [
    'assist',
    'beneficiary',
    'player_out',
    'player_in',
    'red_card_type',
  ]);

  assert.deepEqual(eventFields('own_goal')?.required, ['player', 'beneficiary']);
  assert.deepEqual(eventFields('own_goal')?.optional, []);
  assert.deepEqual(eventFields('own_goal')?.forbidden, [
    'assist',
    'player_out',
    'player_in',
    'red_card_type',
  ]);

  assert.deepEqual(eventFields('yellow_card')?.required, ['player']);
  assert.deepEqual(eventFields('yellow_card')?.forbidden, [
    'assist',
    'beneficiary',
    'player_out',
    'player_in',
    'red_card_type',
  ]);

  assert.deepEqual(eventFields('red_card')?.required, ['player', 'red_card_type']);
  assert.deepEqual(eventFields('red_card')?.forbidden, [
    'assist',
    'beneficiary',
    'player_out',
    'player_in',
  ]);

  assert.deepEqual(eventFields('substitution')?.required, ['player_out', 'player_in']);
  assert.deepEqual(eventFields('substitution')?.forbidden, [
    'player',
    'assist',
    'beneficiary',
    'red_card_type',
  ]);

  // Falta informativa: solo pide el jugador; añadido y segmento son compartidos.
  assert.deepEqual(eventFields('foul')?.required, ['player']);
  assert.deepEqual(eventFields('foul')?.forbidden, [
    'assist',
    'beneficiary',
    'player_out',
    'player_in',
    'red_card_type',
  ]);
});

test('the shared fields are the same for every type and none is an own field', () => {
  assert.deepEqual([...EVENT_FIELDS], ['event_type', 'team', 'segment', 'minute', 'added_minute']);
  for (const field of EVENT_FIELDS) {
    assert.ok(!(ALL_FIELDS as readonly string[]).includes(field), `${field} is not a shared field`);
  }
});

test('an unknown event type has no field catalog', () => {
  assert.equal(eventFields('penalty_missed'), null);
  assert.equal(eventFields(''), null);
});

// ---------------------------------------------------------------------------
// Payload por tipo (RF-002 en el cliente, RF-015)
// ---------------------------------------------------------------------------

test('a goal carries the scorer and an optional assistant', () => {
  const event = buildDraftEvent(form({ assist_player_id: 'p2' }), 'segment-1', UUID);
  assert.ok(event, 'a valid goal was not built');
  assert.equal(event.player_id, 'p1');
  assert.equal(event.assist_player_id, 'p2');
  assert.equal(event.beneficiary_team_id, null);
  assert.equal(event.player_out_id, null);
  assert.equal(event.player_in_id, null);
  assert.equal(event.metadata, undefined);
});

test('a goal without an assistant leaves the assist empty, never a placeholder', () => {
  const event = buildDraftEvent(form(), 'segment-1', UUID);
  assert.ok(event);
  assert.equal(event.assist_player_id, null);
});

test('only the own goal carries the beneficiary team', () => {
  const ownGoal = buildDraftEvent(
    form({ event_type: 'own_goal', beneficiary_team_id: 'away' }),
    'segment-1',
    UUID,
  );
  assert.ok(ownGoal);
  assert.equal(ownGoal.beneficiary_team_id, 'away');

  for (const type of EVENT_TYPES) {
    if (type === 'own_goal') continue;
    const event = buildDraftEvent(validForm(type), 'segment-1', UUID);
    assert.ok(event, `the payload of ${type} was not built`);
    assert.equal(event.beneficiary_team_id, null, `${type} must not carry a beneficiary`);
  }
});

test('only a red card carries metadata, and only with its class', () => {
  const red = buildDraftEvent(
    form({ event_type: 'red_card', red_card_type: 'double_yellow_red' }),
    'segment-1',
    UUID,
  );
  assert.ok(red);
  assert.deepEqual(red.metadata, { red_card_type: 'double_yellow_red' });

  for (const type of EVENT_TYPES) {
    if (type === 'red_card') continue;
    const event = buildDraftEvent(validForm(type), 'segment-1', UUID);
    assert.ok(event, `the payload of ${type} was not built`);
    assert.equal(event.metadata, undefined, `${type} must not carry metadata`);
  }
});

test('only a substitution carries the outgoing/incoming pair and derives player_id', () => {
  const event = buildDraftEvent(
    form({ event_type: 'substitution', player_id: '', player_out_id: 'p2', player_in_id: 'p1' }),
    'segment-1',
    UUID,
  );
  assert.ok(event);
  // El cierre exige `player_id === player_out_id`.
  assert.equal(event.player_id, 'p2');
  assert.equal(event.player_out_id, 'p2');
  assert.equal(event.player_in_id, 'p1');

  for (const type of EVENT_TYPES) {
    if (type === 'substitution') continue;
    const other = buildDraftEvent(validForm(type), 'segment-1', UUID);
    assert.ok(other, `the payload of ${type} was not built`);
    assert.equal(other.player_out_id, null, `${type} must not carry player_out_id`);
    assert.equal(other.player_in_id, null, `${type} must not carry player_in_id`);
  }
});

test('the payload of every type has exactly the keys the server declares', () => {
  // `extra="forbid"`: una clave de primer nivel no declarada es 422. Los campos
  // que el tipo no admite viajan en `null` (el servidor los admite nulos) y
  // nunca con un valor.
  const allowed = new Set([
    'client_event_id',
    'event_type',
    'team_id',
    'beneficiary_team_id',
    'player_id',
    'player_out_id',
    'player_in_id',
    'assist_player_id',
    'minute',
    'added_minute',
    'segment_id',
    'metadata',
  ]);

  for (const type of EVENT_TYPES) {
    const event = buildDraftEvent(validForm(type), 'segment-1', UUID);
    assert.ok(event, `the payload of ${type} was not built`);
    for (const key of Object.keys(event)) {
      assert.ok(allowed.has(key), `${type} carries the undeclared key ${key}`);
    }
    assert.equal(event.client_event_id, UUID);
    assert.equal(event.event_type, type);
    assert.equal(event.team_id, 'home');
    assert.equal(event.segment_id, 'segment-1');
    assert.equal(event.minute, 45);
    assert.equal(event.added_minute, 2);
  }
});

test('a payload with a forbidden value is never built', () => {
  // El servidor responde 422 a estas combinaciones; la utilidad devuelve null y
  // el evento no llega al borrador.
  const cases: Array<[string, Partial<EventFormValues>]> = [
    ['assist on a penalty goal', { event_type: 'penalty_goal', assist_player_id: 'p2' }],
    ['assist on a yellow card', { event_type: 'yellow_card', assist_player_id: 'p2' }],
    ['assist on a foul', { event_type: 'foul', assist_player_id: 'p2' }],
    ['assist equal to the scorer', { event_type: 'goal', assist_player_id: 'p1' }],
    ['own goal without a beneficiary', { event_type: 'own_goal', beneficiary_team_id: '' }],
    ['own goal with its own team as beneficiary', {
      event_type: 'own_goal',
      beneficiary_team_id: 'home',
    }],
    ['substitution without an incoming player', {
      event_type: 'substitution',
      player_out_id: 'p1',
      player_in_id: '',
    }],
    ['substitution with the same player in and out', {
      event_type: 'substitution',
      player_out_id: 'p1',
      player_in_id: 'p1',
    }],
    ['missing scorer', { event_type: 'yellow_card', player_id: '' }],
    ['unknown event type', { event_type: 'penalty_missed' }],
    ['missing team', { team_id: '' }],
    ['minute out of range', { minute: 181 }],
    ['added minute out of range', { added_minute: 31 }],
    ['negative minute', { minute: -1 }],
  ];

  for (const [label, overrides] of cases) {
    const event = buildDraftEvent(form(overrides), 'segment-1', UUID);
    assert.equal(event, null, `${label} was built`);
  }

  assert.equal(buildDraftEvent(form(), '', UUID), null, 'the segment is required');
});

test('a client event id that is not a UUID is never built', () => {
  assert.equal(buildDraftEvent(form(), 'segment-1', 'event-1700000000-0'), null);
  assert.equal(buildDraftEvent(form(), 'segment-1', ''), null);
});

// ---------------------------------------------------------------------------
// Validación de cliente (RF-006)
// ---------------------------------------------------------------------------

test('the client validation accepts the required fields of every type', () => {
  assert.deepEqual(validateEventValues(form()), { ok: true, issues: [] });
  assert.deepEqual(
    validateEventValues(form({ event_type: 'own_goal', beneficiary_team_id: 'away' })),
    { ok: true, issues: [] },
  );
  assert.deepEqual(
    validateEventValues(form({
      event_type: 'substitution',
      player_id: '',
      player_out_id: 'p2',
      player_in_id: 'p1',
    })),
    { ok: true, issues: [] },
  );
  assert.deepEqual(validateEventValues(form({ event_type: 'foul' })), { ok: true, issues: [] });
});

test('the client validation reports the missing required field of each type', () => {
  const missingScorer = validateEventValues(form({ event_type: 'yellow_card', player_id: '' }));
  assert.equal(missingScorer.ok, false);
  assert.deepEqual(missingScorer.issues, [{ field: 'player', code: 'missing_player' }]);

  const missingBeneficiary = validateEventValues(form({ event_type: 'own_goal' }));
  assert.equal(missingBeneficiary.ok, false);
  assert.deepEqual(missingBeneficiary.issues, [
    { field: 'beneficiary', code: 'missing_beneficiary' },
  ]);

  const sameBeneficiary = validateEventValues(
    form({ event_type: 'own_goal', beneficiary_team_id: 'home' }),
  );
  assert.deepEqual(sameBeneficiary.issues, [
    { field: 'beneficiary', code: 'beneficiary_same_team' },
  ]);

  const missingPair = validateEventValues(
    form({ event_type: 'substitution', player_id: '', player_out_id: 'p1', player_in_id: '' }),
  );
  assert.deepEqual(missingPair.issues, [{ field: 'player_in', code: 'missing_player_in' }]);

  const samePair = validateEventValues(
    form({ event_type: 'substitution', player_id: '', player_out_id: 'p1', player_in_id: 'p1' }),
  );
  assert.deepEqual(samePair.issues, [{ field: 'player_in', code: 'same_substitution_player' }]);

  const assistOnCard = validateEventValues(
    form({ event_type: 'yellow_card', assist_player_id: 'p2' }),
  );
  assert.deepEqual(assistOnCard.issues, [
    { field: 'assist', code: 'assist_not_in_goal' },
  ]);
});

test('the client validation rejects an assistant equal to the scorer only in a goal', () => {
  const issue = validateEventValues(form({ assist_player_id: 'p1' }));
  assert.deepEqual(issue.issues, [{ field: 'assist', code: 'assist_same_as_scorer' }]);
});

test('the client validation does not judge what belongs to the server', () => {
  // Ni plantilla del partido, ni sanciones, ni versión, ni marcador: solo la
  // estructura del formulario (RF-006). Un jugador desconocido o no inscrito
  // pasa la validación del cliente.
  assert.deepEqual(validateEventValues(form({ player_id: 'not-in-any-roster' })), {
    ok: true,
    issues: [],
  });
});

test('the minute must fall inside the selected segment when it has an end', () => {
  // RF-006, viñeta 2: el servidor compara solo el minuto con el intervalo.
  const open = { minute_start: 0, minute_end: null };
  assert.equal(validateSegmentMinute(0, open).ok, true);
  assert.equal(validateSegmentMinute(90, open).ok, true);

  const closed = { minute_start: 46, minute_end: 90 };
  assert.equal(validateSegmentMinute(46, closed).ok, true);
  assert.equal(validateSegmentMinute(90, closed).ok, true);

  const before = validateSegmentMinute(45, closed);
  assert.equal(before.ok, false);
  assert.equal(before.issue, 'before_segment');
  assert.equal(before.start, 46);

  const after = validateSegmentMinute(91, { minute_start: 46, minute_end: 90 });
  assert.equal(after.ok, false);
  assert.equal(after.issue, 'after_segment');
  assert.equal(after.end, 90);

  // Sin segmento no se inventa un intervalo y el resto de la validación decide.
  assert.equal(validateSegmentMinute(45, null).ok, true);
});

// ---------------------------------------------------------------------------
// Asistente (RF-008, subconjunto del cliente)
// ---------------------------------------------------------------------------

test('an empty assistant is always valid', () => {
  assert.deepEqual(validateAssist('', 'p1', PLAYERS), {
    ok: true,
    issue: null,
    assist_player_id: null,
  });
  assert.deepEqual(validateAssist(null, 'p1', PLAYERS), {
    ok: true,
    issue: null,
    assist_player_id: null,
  });
});

test('the assistant cannot be the scorer', () => {
  assert.deepEqual(validateAssist('p1', 'p1', PLAYERS), {
    ok: false,
    issue: 'same_as_scorer',
    assist_player_id: 'p1',
  });
});

test('the assistant must belong to the same team as the scorer', () => {
  assert.equal(validateAssist('p2', 'p1', PLAYERS).ok, true);
  const otherTeam = validateAssist('p3', 'p1', PLAYERS);
  assert.equal(otherTeam.ok, false);
  assert.equal(otherTeam.issue, 'not_in_team');
  const notInRoster = validateAssist('p9', 'p1', PLAYERS);
  assert.equal(notInRoster.ok, false);
  assert.equal(notInRoster.issue, 'not_in_team');
});

test('the assistant is judged against the scorer, so a scorer is required', () => {
  const result = validateAssist('p2', '', PLAYERS);
  assert.equal(result.ok, false);
  assert.equal(result.issue, 'missing_scorer');
});

test('the assistant candidates are the same team minus the scorer', () => {
  const candidates = assistCandidates(PLAYERS, 'home', 'p1');
  assert.deepEqual(candidates.map((player) => player.player_id), ['p2']);

  const all = assistCandidates(PLAYERS, 'away', '');
  assert.deepEqual(all.map((player) => player.player_id), ['p3', 'p4']);

  const none = assistCandidates(PLAYERS, 'home', 'p1');
  assert.equal(none.some((player) => player.player_id === 'p1'), false);
});

test('the assistant candidates ignore malformed roster rows', () => {
  const candidates = assistCandidates(
    [
      { player_id: 'p2', team_id: 'home' },
      { player_id: '', team_id: 'home' },
      { team_id: 'home' },
      { player_id: 'p1', team_id: 'home' },
      { player_id: 'p5', team_id: null },
    ],
    'home',
    'p1',
  );
  assert.deepEqual(candidates.map((player) => player.player_id), ['p2']);
});

// ---------------------------------------------------------------------------
// Identificador de cliente (RF-015)
// ---------------------------------------------------------------------------

test('recognizes the canonical UUID shape, in either case', () => {
  assert.equal(isUuid(UUID), true);
  assert.equal(isUuid(UUID.toUpperCase()), true);
  assert.equal(isUuid('event-1700000000-0'), false);
  assert.equal(isUuid('9f1c1e2a3b4c4d5e8f60718293a4b5c6'), false);
  assert.equal(isUuid(`{${UUID}}`), false);
  assert.equal(isUuid(`urn:uuid:${UUID}`), false);
  assert.equal(isUuid(`${UUID}\n`), false);
  assert.equal(isUuid(''), false);
  assert.equal(isUuid(null), false);
  assert.equal(isUuid(42), false);
  assert.equal(isUuid({ randomUUID: fixedUuid }), false);
});

test('a new client event id comes from the injected crypto source', () => {
  const source: UuidSource = { randomUUID: fixedUuid };
  assert.equal(newClientEventId(source), UUID);
});

test('without randomUUID the client does not invent an identifier', () => {
  assert.equal(newClientEventId({}), null);
  assert.equal(newClientEventId({ randomUUID: 'not-a-function' }), null);
  assert.equal(newClientEventId(null), null);
  assert.equal(newClientEventId(undefined), null);
});

test('a crypto source that fails or returns a non-UUID also yields nothing', () => {
  assert.equal(newClientEventId({ randomUUID: () => { throw new Error('unavailable'); } }), null);
  assert.equal(newClientEventId({ randomUUID: () => 'event-1700000000-0' }), null);
  assert.equal(newClientEventId({ randomUUID: () => '' }), null);
  assert.equal(newClientEventId({ randomUUID: () => 42 }), null);
});

// ---------------------------------------------------------------------------
// Descarte de identificadores antiguos (D-9)
// ---------------------------------------------------------------------------

test('drops the draft events whose identifier is not a UUID, keeping the rest in order', () => {
  const events = [
    { client_event_id: UUID, event_type: 'goal' },
    { client_event_id: 'event-1700000000-0', event_type: 'goal' },
    { client_event_id: UUID.toUpperCase(), event_type: 'yellow_card' },
    { client_event_id: '', event_type: 'foul' },
    { event_type: 'foul' },
    { client_event_id: 'event-1700000000-1', event_type: 'foul' },
  ];
  const result = dropLegacyClientEventIds(events);
  assert.equal(result.dropped, 4);
  assert.deepEqual(
    result.events.map((event) => event.client_event_id),
    [UUID, UUID.toUpperCase()],
  );
});

test('a draft with no legacy identifier drops nothing', () => {
  assert.deepEqual(dropLegacyClientEventIds([]), { events: [], dropped: 0 });
  assert.deepEqual(dropLegacyClientEventIds(null), { events: [], dropped: 0 });
  const clean = [{ client_event_id: UUID }, { client_event_id: UUID.toUpperCase() }];
  const result = dropLegacyClientEventIds(clean);
  assert.equal(result.dropped, 0);
  assert.equal(result.events.length, 2);
});

// ---------------------------------------------------------------------------
// Resumen del acta (RF-005)
// ---------------------------------------------------------------------------

const NAMES: Record<string, string> = { p1: 'Ana', p2: 'Bea', p3: 'Carla', p4: 'Dani' };
const resolveName = (playerId: string): string | null => NAMES[playerId] ?? null;

test('a goal reads with its scorer and, when there is one, its assistant', () => {
  assert.equal(eventSummary({ event_type: 'goal', player_id: 'p1' }, resolveName), 'Ana');
  assert.equal(
    eventSummary({ event_type: 'goal', player_id: 'p1', assist_player_id: 'p2' }, resolveName),
    'Ana → Bea',
  );
  // La palabra del catálogo entra por parámetro: aquí no se escribe texto.
  assert.equal(
    eventSummary(
      { event_type: 'goal', player_id: 'p1', assist_player_id: 'p2' },
      resolveName,
      { assist: 'asist.' },
    ),
    'Ana (asist. Bea)',
  );
});

test('an own goal and a foul never read an assistant', () => {
  // RF-005: el autogol no tiene asistente; el resumen no lo inventa.
  assert.equal(
    eventSummary(
      { event_type: 'own_goal', player_id: 'p1', assist_player_id: 'p2' },
      resolveName,
    ),
    'Ana',
  );
  assert.equal(eventSummary({ event_type: 'foul', player_id: 'p3' }, resolveName), 'Carla');
});

test('an own goal reads with its author and the beneficiary team', () => {
  // RF-005: `team_id` es el equipo del autor; el acreditado es el beneficiario.
  const teams: Record<string, string> = { home: 'Local', away: 'Visitante' };
  const resolveTeam = (teamId: string): string | null => teams[teamId] ?? null;

  assert.equal(
    eventSummary(
      {
        event_type: 'own_goal',
        team_id: 'home',
        player_id: 'p1',
        beneficiary_team_id: 'away',
      },
      resolveName,
      { ownGoal: 'beneficia a' },
      resolveTeam,
    ),
    'Ana (beneficia a Visitante)',
  );

  // Sin el texto del catálogo, el equipo sigue viéndose y no se escribe copia.
  assert.equal(
    eventSummary(
      { event_type: 'own_goal', team_id: 'home', player_id: 'p1', beneficiary_team_id: 'away' },
      resolveName,
      {},
      resolveTeam,
    ),
    'Ana (Visitante)',
  );

  // Sin equipo resolutor no se inventa el beneficiario.
  assert.equal(
    eventSummary({ event_type: 'own_goal', player_id: 'p1', beneficiary_team_id: 'away' }, resolveName),
    'Ana',
  );
});

test('a red card reads its class and distinguishes a direct red from a second yellow', () => {
  const labels = { redCardDirect: 'roja directa', redCardDouble: 'doble amarilla' };

  const direct = eventSummary(
    { event_type: 'red_card', player_id: 'p1', metadata: { red_card_type: 'direct_red' } },
    resolveName,
    labels,
  );
  const double = eventSummary(
    { event_type: 'red_card', player_id: 'p1', metadata: { red_card_type: 'double_yellow_red' } },
    resolveName,
    labels,
  );

  assert.equal(direct, 'Ana (roja directa)');
  assert.equal(double, 'Ana (doble amarilla)');
  assert.notEqual(direct, double);

  // El servidor aplica `direct_red` por defecto.
  assert.equal(
    eventSummary({ event_type: 'red_card', player_id: 'p1' }, resolveName, labels),
    'Ana (roja directa)',
  );
});

test('a substitution reads as outgoing then incoming', () => {
  assert.equal(
    eventSummary(
      { event_type: 'substitution', player_id: 'p1', player_out_id: 'p1', player_in_id: 'p2' },
      resolveName,
    ),
    'Ana → Bea',
  );
});

test('an unresolved player leaves no invented name', () => {
  assert.equal(eventSummary({ event_type: 'goal', player_id: 'p9' }, resolveName), '');
  assert.equal(
    eventSummary({ event_type: 'goal', player_id: 'p1', assist_player_id: 'p9' }, resolveName),
    'Ana',
  );
  assert.equal(
    eventSummary({ event_type: 'goal', player_id: 'p9', assist_player_id: 'p2' }, resolveName),
    'Bea',
  );
});

test('the summary never shows an assistant outside a goal', () => {
  assert.equal(
    eventSummary({ event_type: 'yellow_card', player_id: 'p1', assist_player_id: 'p2' }, resolveName),
    'Ana',
  );
});

// ---------------------------------------------------------------------------
// Formulario dinámico por tipo (spec 015, T9; RF-001, RF-004, RF-007)
// ---------------------------------------------------------------------------

test('the form of each type renders only its own fields, in catalog order', () => {
  // RF-001: el formulario pide solo lo que el tipo admite y los campos no
  // aplicables están ausentes, no deshabilitados.
  const expected: Record<EventType, EventField[]> = {
    goal: ['player', 'assist'],
    own_goal: ['player', 'beneficiary'],
    penalty_goal: ['player'],
    yellow_card: ['player'],
    red_card: ['player', 'red_card_type'],
    substitution: ['player_out', 'player_in'],
    foul: ['player'],
  };

  for (const type of EVENT_TYPES) {
    const visible = visibleEventFields(type);
    assert.deepEqual([...visible], expected[type], `${type} does not render its own fields`);
    for (const field of visible) {
      assert.ok(
        !eventFields(type)?.forbidden.includes(field),
        `${type} renders the forbidden field ${field}`,
      );
    }
  }

  assert.deepEqual(visibleEventFields('penalty_missed'), []);
  assert.deepEqual(visibleEventFields(''), []);
});

test('every own field is either rendered or forbidden, never both', () => {
  for (const type of EVENT_TYPES) {
    const visible = visibleEventFields(type);
    const forbidden = eventFields(type)?.forbidden ?? [];
    assert.deepEqual(
      [...visible, ...forbidden].sort(),
      [...ALL_FIELDS].sort(),
      `${type} loses or repeats a field`,
    );
    assert.equal(
      visible.some((field) => (forbidden as readonly EventField[]).includes(field)),
      false,
      `${type} renders and forbids the same field`,
    );
  }
});

test('only a goal offers the assistant, and it stays optional', () => {
  // RF-007: la interfaz no ofrece el campo en ningún tipo distinto de `goal`.
  for (const type of EVENT_TYPES) {
    assert.equal(
      visibleEventFields(type).includes('assist'),
      type === 'goal',
      `${type} offers or hides the assistant incorrectly`,
    );
  }

  // Opcional siempre: el gol se construye igual sin asistente (DU-2).
  const withoutAssist = buildDraftEvent(form(), 'segment-1', UUID);
  assert.ok(withoutAssist);
  assert.equal(withoutAssist.assist_player_id, null);
});

test('the catalog marks the required fields and never the optional assistant', () => {
  // RF-001: la marca visual sale del mismo catálogo que pinta el formulario.
  for (const type of EVENT_TYPES) {
    const fields = eventFields(type);
    assert.ok(fields);
    for (const field of fields.required) {
      assert.equal(isEventFieldRequired(type, field), true, `${type}.${field} is not marked`);
    }
    for (const field of fields.optional) {
      assert.equal(isEventFieldRequired(type, field), false, `${type}.${field} is marked`);
    }
    assert.equal(isEventFieldRequired(type, 'assist'), false, `${type} marks the assistant`);
  }

  // El asistente es opcional y el formulario no lo marca ni lo exige.
  assert.doesNotMatch(
    matchPageSource,
    /isEventFieldRequired\(eventForm\.event_type, 'assist'\)/,
    'the assistant is marked as required',
  );
  assert.match(
    matchPageSource,
    /isEventFieldRequired\(eventForm\.event_type, 'player'\)/,
    'the player is not marked as required',
  );
  assert.match(matchPageSource, /t\('match\.requiredField'\)/);
});

test('a payload built for each type never carries a forbidden value', () => {
  // RF-002: los campos prohibidos no viajan con valor; el servidor responde 422.
  const keyOf: Record<EventField, string> = {
    player: 'player_id',
    player_out: 'player_out_id',
    player_in: 'player_in_id',
    assist: 'assist_player_id',
    beneficiary: 'beneficiary_team_id',
    red_card_type: 'metadata',
  };

  for (const type of EVENT_TYPES) {
    const event = buildDraftEvent(validForm(type), 'segment-1', UUID);
    assert.ok(event, `the payload of ${type} was not built`);
    for (const field of eventFields(type)?.forbidden ?? []) {
      const value = (event as unknown as Record<string, unknown>)[keyOf[field]];
      if (field === 'player') {
        // La sustitución no envía un `player` propio: `player_id` se deriva de
        // `player_out_id`, como exige el cierre.
        assert.equal(event.player_id, event.player_out_id);
        continue;
      }
      assert.ok(
        value === null || value === undefined,
        `${type} carries a value for the forbidden field ${field}`,
      );
    }
    for (const field of visibleEventFields(type)) {
      if (field === 'assist' || field === 'beneficiary') continue;
      if (field === 'red_card_type') {
        assert.ok(event.metadata, `${type} lost its red card class`);
        continue;
      }
      const value = (event as unknown as Record<string, unknown>)[keyOf[field]];
      assert.equal(typeof value, 'string', `${type} did not build ${field}`);
    }
  }
});

test('the report screen builds the draft event with the pure utilities', () => {
  // La pantalla no reimplementa el catálogo ni el payload: consume T8.
  assert.match(matchPageSource, /visibleEventFields\(/);
  assert.match(matchPageSource, /assistCandidates\(/);
  assert.match(matchPageSource, /newClientEventId\(/);
  assert.match(matchPageSource, /buildDraftEvent\(/);
  assert.match(matchPageSource, /eventSummary\(/);
  // RNF-007: se conservan las anclas del arnés.
  assert.match(matchPageSource, /match\.eventType/);
  assert.match(matchPageSource, /match\.minute/);
});

test('the report screen offers a control that adds the event', () => {
  // B1: el alta existe de verdad. No basta con que `addEvent` esté declarada:
  // tiene que haber un control visible que la invoque y que no esté siempre
  // deshabilitado.
  const button = matchPageSource.match(/<button[^>]*@click="addEvent"[^>]*>[\s\S]*?<\/button>/);
  assert.ok(button, 'no control calls addEvent');
  const tag = button[0];
  assert.match(tag, /t\('match\.addEvent'\)/, 'the add control has no label');
  assert.doesNotMatch(tag, /:disabled="true"/, 'the add control is permanently disabled');
  // Solo se bloquea en el caso declarado: partido cerrado, segmento inactivo y
  // una sustitución sin disponibilidad o sin cupo.
  assert.match(tag, /:disabled="/);
  assert.match(tag, /eventForm\.event_type === 'substitution'/);
  assert.match(tag, /eventSubstitutionAvailability\.disabled/);
  assert.match(tag, /eventSubstitutionCounters\.can_register/);
});

test('the assistant selector uses the match lineup, like the player selector', () => {
  // M4: la plantilla del torneo ofrece jugadores que el cierre rechazará con
  // 409; el asistente elige de la misma alineación que el goleador.
  assert.match(matchPageSource, /assistCandidates\(\s*eventPlayers\.value/);
  assert.doesNotMatch(matchPageSource, /assistCandidates\(\s*eventRosterPlayers\.value/);
});

test('without randomUUID the report blocks the registration instead of inventing an id', () => {
  // RF-015: el cliente no fabrica un texto alternativo; avisa y no añade.
  assert.doesNotMatch(
    matchPageSource,
    /event-\$\{Date\.now\(\)\}/,
    'the legacy timestamp id is still generated',
  );
  assert.match(matchPageSource, /match\.eventIdUnavailable/);
  assert.equal(newClientEventId({}), null);
  assert.equal(newClientEventId(undefined), null);
});

test('the summary of the report shows the assistant in the draft and in the report', () => {
  // RF-005: el resumen del borrador y el del acta persistida comparten
  // `eventSummary`; el asistente se resuelve desde la plantilla del partido.
  const roster = [
    { roster_id: 'r1', player_id: 'p1', team_id: 'home', first_name: 'Ana', last_name: 'Uno' },
    { roster_id: 'r2', player_id: 'p2', team_id: 'home', first_name: 'Bea', last_name: 'Dos' },
  ];
  const nameOf = (playerId: string): string | null =>
    roster.find((row) => row.player_id === playerId)?.last_name ?? null;

  // T11: el resumen usa la forma corta (`match.assistShort`), no la etiqueta del
  // campo: «Uno (asistencia de Dos)» se lee, «Uno (Asistente Dos)» no.
  assert.equal(
    eventSummary(
      { event_type: 'goal', player_id: 'p1', assist_player_id: 'p2' },
      nameOf,
      { assist: 'asistencia de' },
    ),
    'Uno (asistencia de Dos)',
  );

  // La pantalla resuelve los nombres con la plantilla de la operación, también
  // para el acta persistida.
  assert.match(matchPageSource, /function draftEventSummary/);
  assert.match(matchPageSource, /function persistedEventSummary/);
  assert.match(matchPageSource, /assist_player_id/);
});

// T11 (RF-001, RF-004, RF-005, RNF-009): las siete claves de esta
// funcionalidad, con su texto, en los dos idiomas. La lista es la del
// catálogo de la pantalla: si alguien deja una clave sin uso, sobra.
const REPORT_TEXT_KEYS = [
  'match.assist',
  'match.assistShort',
  'match.assistNone',
  'match.assistHint',
  'match.eventIdUnavailable',
  'match.draftEventsDropped',
  'match.foulInformative',
  'match.addEvent',
  'match.requiredField',
  'match.ownGoalBeneficiaryShort',
  'match.redCardDirectShort',
  'match.redCardDoubleShort',
  'match.eventMissingPlayer',
  'match.eventMissingTeam',
  'match.eventBeneficiarySameTeam',
  'match.eventAssistSameAsScorer',
  'match.eventAssistNotAllowed',
  'match.eventAssistOtherTeam',
  'match.eventUnknownType',
  'match.eventMinuteBeforeSegment',
  'match.eventMinuteAfterSegment',
  // Spec 017, T7: el aviso de acta cerrada, el 409 de la doble amarilla y el
  // origen del minuto propuesto. Entran en la misma lista para que la paridad
  // es/en y el uso real se comprueben con el mismo mecanismo.
  'match.reportLocked',
  'match.doubleYellowInconsistent',
  'match.segmentProposalDerived',
  'match.segmentProposalManual',
] as const;

function catalogSlices(): { spanish: string; english: string } {
  const englishStart = translationsSource.indexOf('\n  en: {');
  assert.ok(englishStart > 0, 'the English catalog is missing');
  return {
    spanish: translationsSource.slice(0, englishStart),
    english: translationsSource.slice(englishStart),
  };
}

function catalogMap(slice: string): Map<string, string> {
  const map = new Map<string, string>();
  const pattern = /'((?:[^'\\]|\\.)*)':\s*'((?:[^'\\]|\\.)*)'/g;
  for (const match of slice.matchAll(pattern)) {
    map.set(match[1]!, match[2]!.replaceAll("\\'", "'"));
  }
  return map;
}

function appFiles(): { name: string; source: string }[] {
  const appDir = new URL('../app/', import.meta.url);
  return (readdirSync(appDir, { recursive: true }) as string[])
    .filter((file) => file.endsWith('.ts') || file.endsWith('.vue'))
    .map((file) => ({
      name: file.replaceAll('\\', '/'),
      source: readFileSync(new URL(file.replaceAll('\\', '/'), appDir), 'utf8'),
    }));
}

test('the new report texts exist once in each catalog and are all used', () => {
  const { spanish, english } = catalogSlices();
  const used = extractUsedKeys(appFiles());

  for (const key of REPORT_TEXT_KEYS) {
    const pattern = new RegExp(`'${key.replace(/\./g, '\\.')}':`);
    assert.match(spanish, pattern, `${key} is missing in Spanish`);
    assert.match(english, pattern, `${key} is missing in English`);
    assert.equal(
      spanish.split(`'${key}':`).length - 1,
      1,
      `${key} is not declared exactly once in Spanish`,
    );
    assert.equal(
      english.split(`'${key}':`).length - 1,
      1,
      `${key} is not declared exactly once in English`,
    );
    assert.ok(used.has(key), `${key} is declared but no screen uses it`);
  }
});

test('the report texts are product copy and never engineering wording', () => {
  const { spanish, english } = catalogSlices();
  const catalogs = [
    ['Spanish', catalogMap(spanish)],
    ['English', catalogMap(english)],
  ] as const;
  // Ni el mecanismo interno ni el nombre de un contrato llegan a la pantalla.
  const internal = /\b(?:crypto|randomUUID|uuid|metadata|client_event_id|payload|contrato|contract|backend)\b/i;

  for (const [locale, catalog] of catalogs) {
    for (const key of REPORT_TEXT_KEYS) {
      const value = catalog.get(key);
      assert.ok(value, `${locale} catalog has no value for ${key}`);
      assert.doesNotMatch(value, internal, `${locale} ${key} leaks engineering wording`);

      // Lo que el lector necesita saber, en cada caso.
      if (key === 'match.eventIdUnavailable') {
        assert.match(value, /no se ha añadido|not added/i, `${locale} ${key} does not say the event was not added`);
        assert.match(value, /navegador|browser/i, `${locale} ${key} does not mention the browser`);
      }
      if (key === 'match.foulInformative') {
        assert.match(value, /informativa|information only/i, `${locale} ${key} does not say the foul is informative`);
        assert.match(value, /no sanciona|does not sanction/i, `${locale} ${key} does not say the foul sanctions nobody`);
      }
      if (key === 'match.draftEventsDropped') {
        assert.match(value, /\{count\}/, `${locale} ${key} does not report the number`);
      }
    }
  }
});

test('the field label and the summary word of the assist are separate keys', () => {
  const { spanish, english } = catalogSlices();
  // El resumen del gol necesita una palabra que encaje en la frase; la etiqueta
  // del campo, un sustantivo. Una sola clave no sirve bien a los dos usos.
  for (const [locale, catalog] of [
    ['Spanish', catalogMap(spanish)],
    ['English', catalogMap(english)],
  ] as const) {
    const label = catalog.get('match.assist');
    const summary = catalog.get('match.assistShort');
    assert.ok(label, `${locale} catalog has no value for match.assist`);
    assert.ok(summary, `${locale} catalog has no value for match.assistShort`);
    assert.notEqual(label, summary, `${locale} reuses the same text for both uses`);
  }

  // La pantalla no duplica la palabra del resumen: la recibe por parámetro.
  const functionBody = (name: string): string => {
    const match = matchPageSource.match(new RegExp(`function ${name}\\([\\s\\S]*?\\n\\}`));
    assert.ok(match, `${name} is missing`);
    return match[0];
  };

  for (const name of ['draftEventSummary', 'persistedEventSummary']) {
    const body = functionBody(name);
    assert.match(body, /eventSummary\(/, `${name} does not use the shared summary`);
    assert.match(body, /eventSummaryLabels\(\)/, `${name} does not use the shared labels`);
  }

  // La forma corta y las clases se resuelven en un único lugar, por i18n.
  const labels = functionBody('eventSummaryLabels');
  assert.match(labels, /t\('match\.assistShort'\)/, 'the short form is missing');
  assert.match(labels, /t\('match\.ownGoalBeneficiaryShort'\)/, 'the own goal word is missing');
  assert.match(labels, /t\('match\.redCardDirectShort'\)/, 'the direct red word is missing');
  assert.match(labels, /t\('match\.redCardDoubleShort'\)/, 'the second yellow word is missing');
  assert.doesNotMatch(
    labels,
    /t\('match\.assist'\)/,
    'the summary reuses the field label as the summary word',
  );
});

test('the new report notices are announced to the screen reader', () => {
  // RNF-007: la pantalla ya anuncia con `role="status"`; los avisos nuevos
  // siguen ese patrón y no estrenan otro.
  for (const key of ['match.draftEventsDropped', 'match.assistHint', 'match.foulInformative']) {
    const pattern = new RegExp(`role="status">\\{\\{ t\\('${key.replace(/\./g, '\\.')}'`);
    assert.match(matchPageSource, pattern, `${key} is not announced with role="status"`);
  }
  assert.match(matchPageSource, /v-if="eventIdError"[^>]*role="alert"/, 'the event id failure is not announced');
});

test('a change of event type is announced with the fields it shows', () => {
  // RNF-007: un `<select>` nativo anuncia su valor, no que el formulario cambie
  // sus campos. Los siete tipos cambian el formulario (el autogol estrena el
  // beneficiario, la roja la clase, la sustitución el par salida/entrada), así
  // que el anuncio cubre los siete y no solo los que ya tenían un aviso.
  const fieldNames: Record<string, string> = {
    'match.player': 'Jugador',
    'match.playerOut': 'Sale',
    'match.playerIn': 'Entra',
    'match.assist': 'Asistente',
    'match.beneficiary': 'Beneficia',
    'match.redCardType': 'Clase de roja',
  };
  const translate = (key: string, params: Record<string, string | number> = {}): string =>
    key === 'match.eventTypeChanged'
      ? `Tipo de evento: ${params.type}. El formulario muestra: ${params.fields}.`
      : fieldNames[key] ?? key;

  const announcements = EVENT_TYPES.map((type) => {
    const text = eventTypeAnnouncement(type, type, translate);
    assert.ok(text, `${type} is not announced`);
    for (const field of visibleEventFields(type)) {
      assert.match(text, new RegExp(fieldNames[field]!), `${type} does not announce its ${field} field`);
    }
    return text;
  });

  // El texto cambia con el tipo: los campos aparecen y desaparecen.
  assert.equal(new Set(announcements).size, EVENT_TYPES.length);
  const announced = (type: EventType): string => announcements[EVENT_TYPES.indexOf(type)]!;
  assert.match(announced('own_goal'), /Beneficia/);
  assert.doesNotMatch(announced('goal'), /Beneficia/);
  assert.match(announced('red_card'), /Clase de roja/);
  assert.match(announced('substitution'), /Sale, Entra/);
  assert.equal(eventTypeAnnouncement('not_in_the_catalog', 'Otro', translate), null);

  // La pantalla lo escribe en una región `role="status"` que ya está montada:
  // una región que nace con el cambio no se anuncia.
  assert.match(
    matchPageSource,
    /role="status">\{\{ eventTypeNotice \}\}/,
    'the change of event type is not announced',
  );
  assert.doesNotMatch(
    matchPageSource,
    /v-if="[^"]*"[^>]*role="status"[^>]*>\{\{ eventTypeNotice \}\}/,
    'the announcement region is mounted with the change, so it is never read',
  );

  // El texto es producto, por i18n, y nombra los dos datos del anuncio.
  const { spanish, english } = catalogSlices();
  for (const [locale, catalog] of [
    ['Spanish', catalogMap(spanish)],
    ['English', catalogMap(english)],
  ] as const) {
    const value = catalog.get('match.eventTypeChanged');
    assert.ok(value, `${locale} catalog has no value for match.eventTypeChanged`);
    assert.match(value, /\{type\}/, `${locale} does not name the type`);
    assert.match(value, /\{fields\}/, `${locale} does not name the fields`);
  }
});

test('every registration error is associated with its field', () => {
  // RNF-007: el error se queda junto al control afectado, con su etiqueta
  // `aria-describedby` y `aria-invalid`, y no en un aviso suelto de la página.
  // Se recorre también el tipo, la clase de roja y el minuto añadido, que
  // quedaban fuera del barrido de asociación.
  for (const field of [
    'event_type',
    'segment',
    'team',
    'player',
    'player_out',
    'player_in',
    'assist',
    'beneficiary',
    'red_card_type',
    'minute',
  ]) {
    const invalid = new RegExp(`:aria-invalid="Boolean\\(eventFieldError\\('${field}'\\)\\)"`);
    const described = new RegExp(`:aria-describedby="eventFieldDescribedBy\\('${field}'\\)"`);
    const message = new RegExp(`:id="eventFieldErrorId\\('${field}'\\)"`);
    assert.match(matchPageSource, invalid, `${field} has no aria-invalid`);
    assert.match(matchPageSource, described, `${field} has no aria-describedby`);
    assert.match(matchPageSource, message, `${field} has no associated error message`);
  }
});
