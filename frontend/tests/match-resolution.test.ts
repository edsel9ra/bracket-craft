import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  ASSIST_PLAYER_INVALID_CODE,
  DEFAULT_RESOLUTION,
  DOUBLE_YELLOW_INCONSISTENT_CODE,
  MAXIMUM_SOURCE_LABEL_KEYS,
  RESOLUTION_LABEL_KEYS,
  RESOLUTION_NOT_ENABLED_CODE,
  ROSTER_SIZE_OUT_OF_RANGE_CODE,
  WALKOVER_CONFIG_INCONSISTENT_CODE,
  WALKOVER_SCORE_MISMATCH_CODE,
  WALKOVER_STATE_NOT_ALLOWED_CODE,
  classifyMatchConflict,
  closeResolutionDecision,
  createResolutionStore,
  enabledResolutions,
  findDraftMinuteViolations,
  matchConflictDetail,
  matchLimitsFor,
  maximumMinuteFor,
  maximumMinuteSource,
  normalizeResolution,
  parseStoredResolution,
  resolutionChangeOutcome,
  resolutionEnabled,
  resolutionKey,
  resolutionPayload,
  serializeResolution,
  validateEventMinute,
  type OperationLimits,
  type ResolutionDraftEventInput,
  type ResolutionScope,
  type ResolutionSegmentInput,
  type ResolutionStorage,
  type ResolutionType,
} from '../app/utils/matchResolution.ts';
import {
  MATCH_DRAFT_VERSION,
  createMatchDraftStore,
  matchDraftKey,
  parseStoredMatchDraft,
  sanitizeMatchDraft,
  serializeMatchDraft,
  type MatchDraft,
  type MatchDraftResult,
  type MatchDraftScope,
  type MatchDraftStorage,
} from '../app/utils/matchDraft.ts';
import { closeConflictMessageKey } from '../app/utils/matchSegments.ts';

// Spec 012, H3-T04 (RF-033, RF-034). La resolución prevista se elige con un
// único control en la operación, el máximo se lee de `limits` (el cliente no
// recalcula reglas) y se envía al crear o interrumpir segmentos y al cerrar.
// Vive solo en el almacenamiento de sesión de la pestaña (P3).

const FULL: OperationLimits = {
  max_minute_regular: 90,
  max_minute_extra: 120,
  max_minute: 120,
  extra_time_enabled: true,
  penalties_enabled: true,
  added_minute_max: 25,
};

const SCOPE: ResolutionScope = {
  userId: 'user-1',
  organizationId: 'org-1',
  matchId: 'match-1',
};

const PAGE_SOURCE = readFileSync(
  new URL('../app/pages/workspace/matches/[id].vue', import.meta.url),
  'utf8',
);
const COMPOSABLE_SOURCE = readFileSync(
  new URL('../app/composables/useMatchResolution.ts', import.meta.url),
  'utf8',
);
const UTILS_SOURCE = readFileSync(
  new URL('../app/utils/matchResolution.ts', import.meta.url),
  'utf8',
);
const DRAFT_UTILS_SOURCE = readFileSync(
  new URL('../app/utils/matchDraft.ts', import.meta.url),
  'utf8',
);
const TRANSLATIONS_SOURCE = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  const storage = {
    getItem: (key: string): string | null => (data.has(key) ? data.get(key) ?? null : null),
    setItem: (key: string, value: string): void => {
      data.set(key, value);
    },
    removeItem: (key: string): void => {
      data.delete(key);
    },
  };
  return { data, storage: storage satisfies ResolutionStorage };
}

// RF-033: por defecto, tiempo reglamentario.
test('defaults the planned resolution to regular time', () => {
  assert.equal(DEFAULT_RESOLUTION, 'regular');
  assert.equal(normalizeResolution(FULL, null), 'regular');
  assert.equal(normalizeResolution(FULL, undefined), 'regular');
  assert.equal(normalizeResolution(FULL, 'not-a-resolution'), 'regular');
  assert.equal(normalizeResolution(null, null), 'regular');
  assert.equal(enabledResolutions(null)[0], 'regular');
});

// RF-033: solo se ofrecen las resoluciones habilitadas por la fase; una
// resolución no habilitada no se puede seleccionar ni se restaura al recargar.
test('offers only the resolutions enabled by the effective stage configuration', () => {
  assert.deepEqual(
    enabledResolutions({ extra_time_enabled: false, penalties_enabled: false }),
    ['regular', 'walkover', 'administrative'],
  );
  assert.deepEqual(
    enabledResolutions({ extra_time_enabled: true, penalties_enabled: false }),
    ['regular', 'extra_time', 'walkover', 'administrative'],
  );
  assert.deepEqual(
    enabledResolutions({ extra_time_enabled: false, penalties_enabled: true }),
    ['regular', 'penalties', 'walkover', 'administrative'],
  );
  assert.deepEqual(
    enabledResolutions(FULL),
    ['regular', 'extra_time', 'penalties', 'walkover', 'administrative'],
  );

  assert.equal(resolutionEnabled(FULL, 'extra_time'), true);
  assert.equal(resolutionEnabled({ extra_time_enabled: false }, 'extra_time'), false);
  assert.equal(resolutionEnabled({ penalties_enabled: false }, 'penalties'), false);
  assert.equal(resolutionEnabled(FULL, 'walkover'), true);
  assert.equal(resolutionEnabled(FULL, 'administrative'), true);

  assert.equal(normalizeResolution({ extra_time_enabled: false }, 'extra_time'), 'regular');
  assert.equal(normalizeResolution({ penalties_enabled: false }, 'penalties'), 'regular');
  assert.equal(normalizeResolution({ extra_time_enabled: true }, 'extra_time'), 'extra_time');
});

// RF-033: el máximo mostrado es el del servidor para la resolución prevista y
// la pantalla sabe si procede del tiempo reglamentario o de la prórroga.
test('shows the server maximum that applies to the selected resolution', () => {
  assert.equal(maximumMinuteFor(FULL, 'regular'), 90);
  assert.equal(maximumMinuteFor(FULL, 'extra_time'), 120);
  assert.equal(maximumMinuteFor(FULL, 'penalties'), 120);
  assert.equal(maximumMinuteFor(FULL, 'walkover'), 90);
  assert.equal(maximumMinuteFor(FULL, 'administrative'), 90);

  assert.equal(maximumMinuteSource(FULL, 'regular'), 'regular');
  assert.equal(maximumMinuteSource(FULL, 'extra_time'), 'extra_time');
  assert.equal(maximumMinuteSource(FULL, 'penalties'), 'extra_time');
  assert.equal(maximumMinuteSource(FULL, 'walkover'), 'regular');

  assert.deepEqual(matchLimitsFor(FULL, 'penalties'), { maxMinute: 120, addedMax: 25 });
  assert.deepEqual(matchLimitsFor(FULL, 'regular'), { maxMinute: 90, addedMax: 25 });

  // La prórroga deshabilitada en la fase no eleva el máximo aunque exista el
  // valor; el servidor la envía como `null`.
  const regularOnly: OperationLimits = {
    max_minute_regular: 90,
    max_minute_extra: null,
    max_minute: 90,
    extra_time_enabled: false,
    penalties_enabled: false,
    added_minute_max: 30,
  };
  assert.equal(maximumMinuteFor(regularOnly, 'extra_time'), 90);
  assert.equal(maximumMinuteFor(regularOnly, 'penalties'), 90);
  assert.equal(maximumMinuteSource(regularOnly, 'penalties'), 'regular');
});

// RF-034: sin `limits` (o con la resolución ya no habilitada) se cae a tiempo
// reglamentario sin romper la operación.
test('falls back to regular time without the limits block', () => {
  assert.equal(maximumMinuteFor(null, 'regular'), 180);
  assert.equal(maximumMinuteFor(undefined, 'extra_time'), 180);
  assert.deepEqual(matchLimitsFor(null, 'extra_time'), { maxMinute: 180, addedMax: 30 });
  assert.equal(maximumMinuteSource(null, 'extra_time'), 'regular');
  assert.equal(normalizeResolution(null, 'penalties'), 'regular');
});

// RF-033: el mismo cálculo alimenta el envío al crear o interrumpir segmentos
// y al cerrar; nunca se envía otra resolución que la mostrada.
test('sends the shown resolution to segments, interruptions and the close', () => {
  assert.deepEqual(resolutionPayload(FULL, 'regular'), { resolution_type: 'regular' });
  assert.deepEqual(resolutionPayload(FULL, 'extra_time'), { resolution_type: 'extra_time' });
  assert.deepEqual(resolutionPayload(FULL, 'penalties'), { resolution_type: 'penalties' });
  assert.deepEqual(resolutionPayload(FULL, 'walkover'), { resolution_type: 'walkover' });
  assert.deepEqual(resolutionPayload(FULL, 'administrative'), { resolution_type: 'administrative' });

  // Una resolución deshabilitada se envía como la que se muestra: regular.
  assert.deepEqual(resolutionPayload({ extra_time_enabled: false }, 'extra_time'), { resolution_type: 'regular' });
  assert.deepEqual(resolutionPayload(null, 'penalties'), { resolution_type: 'regular' });
});

// RF-034/P3: la clave asocia usuario, organización y partido; sin alguno de
// ellos no se persiste nada y ninguna otra pestaña ni partido la comparte.
test('keys the planned resolution by user, organization and match', () => {
  assert.equal(resolutionKey(SCOPE), 'bc_match_resolution:user-1:org-1:match-1');
  assert.notEqual(resolutionKey({ ...SCOPE, matchId: 'match-2' }), resolutionKey(SCOPE));
  assert.notEqual(resolutionKey({ ...SCOPE, organizationId: 'org-2' }), resolutionKey(SCOPE));
  assert.notEqual(resolutionKey({ ...SCOPE, userId: 'user-2' }), resolutionKey(SCOPE));

  assert.equal(resolutionKey({ ...SCOPE, userId: null }), null);
  assert.equal(resolutionKey({ ...SCOPE, organizationId: undefined }), null);
  assert.equal(resolutionKey({ ...SCOPE, matchId: '   ' }), null);
  assert.equal(resolutionKey({ ...SCOPE, userId: 'user:1' }), null);
  assert.equal(resolutionKey({ ...SCOPE, matchId: 'match 1' }), null);
});

// RF-034: recargar la pestaña restaura la resolución guardada.
test('restores the planned resolution after a simulated reload', () => {
  const tab = memoryStorage();

  createResolutionStore(SCOPE, tab.storage).save('extra_time');

  const reloaded = createResolutionStore(SCOPE, tab.storage).read();
  assert.equal(reloaded, 'extra_time');
  assert.equal(normalizeResolution(FULL, reloaded), 'extra_time');

  // La misma resolución en una fase que ya no la habilita cae a regular.
  assert.equal(normalizeResolution({ extra_time_enabled: false }, reloaded), 'regular');

  // Otra pestaña, otro partido u otro usuario no la ven.
  assert.equal(createResolutionStore(SCOPE, memoryStorage().storage).read(), null);
  assert.equal(createResolutionStore({ ...SCOPE, matchId: 'match-2' }, tab.storage).read(), null);
  assert.equal(createResolutionStore({ ...SCOPE, userId: 'user-2' }, tab.storage).read(), null);
});

// RF-034: un valor ilegible, de otra versión o desconocido nunca se aplica.
test('ignores a corrupt or unknown stored resolution', () => {
  assert.equal(parseStoredResolution(null), null);
  assert.equal(parseStoredResolution(''), null);
  assert.equal(parseStoredResolution('{'), null);
  assert.equal(parseStoredResolution('[]'), null);
  assert.equal(parseStoredResolution('{"version":2,"resolution_type":"regular"}'), null);
  assert.equal(parseStoredResolution('{"version":1,"resolution_type":"bogus"}'), null);
  assert.equal(parseStoredResolution(serializeResolution('penalties')), 'penalties');

  const tab = memoryStorage({ [resolutionKey(SCOPE)!]: '{' });
  assert.equal(createResolutionStore(SCOPE, tab.storage).read(), null);
});

// RF-034: sin identificadores no se escribe nada y limpiar solo borra la clave
// propia.
test('keeps no value without every identifier and clears only its own key', () => {
  const tab = memoryStorage();
  const missing = createResolutionStore({ ...SCOPE, matchId: null }, tab.storage);
  assert.equal(missing.key, null);
  assert.equal(missing.available, false);
  assert.equal(missing.save('regular'), false);
  assert.equal(missing.read(), null);
  assert.equal(tab.data.size, 0);

  createResolutionStore(SCOPE, tab.storage).save('penalties');
  createResolutionStore({ ...SCOPE, matchId: 'match-2' }, tab.storage).save('extra_time');
  assert.equal(createResolutionStore(SCOPE, tab.storage).clear(), true);
  assert.equal(createResolutionStore(SCOPE, tab.storage).read(), null);
  assert.equal(createResolutionStore({ ...SCOPE, matchId: 'match-2' }, tab.storage).read(), 'extra_time');
});

// RF-033: un único control en la operación; el cierre reutiliza ese valor y no
// añade un segundo selector.
test('renders a single planned-resolution control in the operation', () => {
  assert.equal(
    PAGE_SOURCE.split('v-model="selectedResolution"').length - 1,
    1,
    'the operation must have exactly one resolution control',
  );
  assert.doesNotMatch(PAGE_SOURCE, /v-model="closeForm\.resolution_type"/, 'the close must not offer a second selector');
  assert.match(PAGE_SOURCE, /useMatchResolution\(/);
  assert.match(PAGE_SOURCE, /restoreResolution\(/);
  assert.match(PAGE_SOURCE, /t\('match\.plannedResolution'\)/);
  assert.match(PAGE_SOURCE, /t\('match\.closeUsesResolution'/);
});

// RF-033: las tres llamadas envían la resolución mostrada a través del mismo
// cálculo; ninguna usa un segundo valor.
test('sends the shown resolution on segment, interruption and close', () => {
  // Crear e interrumpir la envían con el cálculo directo…
  assert.equal(
    PAGE_SOURCE.split('resolutionPayload(').length - 1,
    2,
    'create and interrupt must send the resolution',
  );
  assert.match(PAGE_SOURCE, /\/matches\/\$\{matchId\}\/segments`/);
  assert.match(PAGE_SOURCE, /\/segments\/\$\{activeSegment\.value!\.id\}\/interrupt`/);
  assert.match(PAGE_SOURCE, /\/matches\/\$\{matchId\}\/close`/);

  // …y el cierre dentro del cuerpo de la utilidad pura (spec 016, RF-005), que
  // recibe la misma resolución mostrada.
  assert.match(
    PAGE_SOURCE,
    /buildCloseReportBody\(\{[\s\S]{0,200}resolution: resolution\.value/,
    'the close body does not carry the shown resolution',
  );

  assert.match(PAGE_SOURCE, /const \{ request \} = useApi\(\)/);
  assert.doesNotMatch(PAGE_SOURCE, /\$fetch\(/);
});

// RF-033: el máximo mostrado sale de `limits` del servidor; el cliente solo
// elige la resolución.
test('shows the maximum reported by the server for the resolution', () => {
  assert.match(PAGE_SOURCE, /:max="resolutionLimits\.maxMinute"/);
  assert.match(PAGE_SOURCE, /:max="resolutionLimits\.addedMax"/);
  assert.match(UTILS_SOURCE, /max_minute_regular/);
  assert.match(UTILS_SOURCE, /max_minute_extra/);
  assert.match(UTILS_SOURCE, /added_minute_max/);
  assert.match(UTILS_SOURCE, /maximumMinuteFor/);
});

// P3/RNF-011: la selección vive solo en la sesión de la pestaña, nunca en el
// almacenamiento persistente ni en el servidor.
test('keeps the planned resolution in the tab session only', () => {
  for (const source of [COMPOSABLE_SOURCE, UTILS_SOURCE]) {
    assert.doesNotMatch(source, /localStorage/);
    assert.doesNotMatch(source, /\$fetch|useApi/);
  }
  assert.match(COMPOSABLE_SOURCE, /sessionStorage/);
  assert.match(COMPOSABLE_SOURCE, /import\.meta\.client/);
  assert.match(COMPOSABLE_SOURCE, /createResolutionStore\(/);
});

// RF-029: los textos nuevos existen en español e inglés, una sola vez por
// idioma.
test('declares the resolution texts in both catalogs', () => {
  const keys = [
    'match.plannedResolution',
    'match.plannedResolutionHint',
    'match.resolutionMaximum',
    'match.resolutionAddedMaximum',
    'match.resolutionFallenBack',
    'match.closeUsesResolution',
    ...Object.values(RESOLUTION_LABEL_KEYS),
    ...Object.values(MAXIMUM_SOURCE_LABEL_KEYS),
  ];

  for (const key of keys) {
    assert.equal(
      TRANSLATIONS_SOURCE.split(`'${key}':`).length - 1,
      2,
      `${key} must be declared once per language`,
    );
  }

  const offered = enabledResolutions(FULL) as ResolutionType[];
  for (const code of offered) {
    assert.ok(RESOLUTION_LABEL_KEYS[code], `missing label key for ${code}`);
  }
});

// ---------------------------------------------------------------------------
// Spec 012, H3-T05 (RF-033, RF-034, P2).
//
// El cambio de resolución tiene tres resultados puros. `ok`: nada queda fuera
// del nuevo máximo. `confirm`: solo hay eventos del borrador fuera del máximo;
// se avisa y no se borra ni se envía nada. `blocked`: hay **segmentos ya
// persistidos** (datos del servidor) fuera del máximo; el cambio no se permite
// y no existe contrato de corrección de segmentos.
//
// Al cerrar, una resolución distinta de la prevista y compatible exige
// confirmación explícita: sin ella no se envía el cierre. Con segmentos fuera
// del máximo no hay confirmación posible.
// ---------------------------------------------------------------------------

const PERSISTED_SEGMENTS: ResolutionSegmentInput[] = [
  { id: 'seg-1', segment_number: 1, minute_start: 0, minute_end: 45, status: 'completed' },
  { id: 'seg-2', segment_number: 2, minute_start: 45, minute_end: 90, status: 'active' },
];

function copy<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

// RF-033: nada fuera de límite → el cambio se aplica sin avisos.
test('allows the change when every persisted segment and draft event fits the new maximum', () => {
  const segments = copy(PERSISTED_SEGMENTS);
  const events: ResolutionDraftEventInput[] = [
    { client_event_id: 'ev-1', event_type: 'goal', minute: 88, added_minute: 2 },
  ];

  const result = resolutionChangeOutcome(segments, events, 90);

  assert.equal(result.outcome, 'ok');
  assert.equal(result.maxMinute, 90);
  assert.deepEqual(result.segments, []);
  assert.deepEqual(result.events, []);
  assert.equal(result.messageKey, 'match.resolutionChangeOk');

  // Puro: ni los segmentos del servidor ni el borrador se tocan.
  assert.deepEqual(segments, PERSISTED_SEGMENTS);
  assert.equal(events.length, 1);
});

// RF-033: solo eventos del borrador fuera de límite → se avisa sin borrar.
test('warns without deleting when only draft events exceed the new maximum', () => {
  const events: ResolutionDraftEventInput[] = [
    { client_event_id: 'ev-1', event_type: 'goal', minute: 110, added_minute: 0 },
    { client_event_id: 'ev-2', event_type: 'yellow_card', minute: 95, added_minute: 0 },
  ];
  const before = copy(events);

  const result = resolutionChangeOutcome(PERSISTED_SEGMENTS, events, 90);

  assert.equal(result.outcome, 'confirm');
  assert.deepEqual(result.segments, [], 'no persisted segment is over the maximum');
  assert.deepEqual(
    result.events.map((event) => event.client_event_id),
    ['ev-1', 'ev-2'],
    'the affected draft events are reported in their order',
  );
  assert.equal(result.messageKey, 'match.resolutionChangeNeedsConfirmation');
  assert.equal(result.messageParams.count, 2);
  assert.equal(result.messageParams.minute, 110, 'the warning names the affected minute');
  assert.equal(result.messageParams.max, 90);

  // Avisar no borra ni envía: los eventos siguen intactos en el borrador.
  assert.deepEqual(events, before);
});

// RF-033/P2: segmentos persistidos fuera de límite → el cambio se bloquea.
test('blocks the change when a persisted segment exceeds the new maximum', () => {
  const segments: ResolutionSegmentInput[] = [
    ...PERSISTED_SEGMENTS,
    { id: 'seg-3', segment_number: 3, minute_start: 95, minute_end: 115, status: 'completed' },
  ];
  const events: ResolutionDraftEventInput[] = [
    { client_event_id: 'ev-1', event_type: 'goal', minute: 100, added_minute: 0 },
  ];

  const result = resolutionChangeOutcome(segments, events, 90);

  assert.equal(result.outcome, 'blocked');
  assert.deepEqual(result.segments.map((segment) => segment.segment_number), [3]);
  assert.equal(result.segments[0]!.minute, 115);
  assert.equal(result.messageKey, 'match.resolutionChangeBlocked');
  assert.equal(result.messageParams.segment, 3, 'the message names the segment');
  assert.equal(result.messageParams.minute, 115, 'the message names the minute');
  assert.equal(result.messageParams.max, 90);
});

// Un segmento abierto no tiene fin: cuenta su minuto de inicio.
test('uses the start minute of a segment that is still open', () => {
  const open: ResolutionSegmentInput[] = [
    { id: 'seg-open', segment_number: 2, minute_start: 100, minute_end: null, status: 'active' },
  ];

  const result = resolutionChangeOutcome(open, [], 90);

  assert.equal(result.outcome, 'blocked');
  assert.equal(result.segments[0]!.minute, 100);
  assert.equal(result.messageParams.segment, 2);
});

// RF-032: antes del minuto final la suma con el añadido no puede pasar el
// máximo; en el minuto final se admite el añadido dentro del tope estructural.
test('keeps the added-minute rule when judging the draft events', () => {
  const events: ResolutionDraftEventInput[] = [
    { client_event_id: 'final-minute', minute: 90, added_minute: 5 },
    { client_event_id: 'before-final', minute: 89, added_minute: 5 },
  ];

  const result = resolutionChangeOutcome([], events, 90);

  assert.equal(result.outcome, 'confirm');
  assert.deepEqual(result.events.map((event) => event.client_event_id), ['before-final']);
  assert.equal(result.events[0]!.over, 4);
});

// RF-034/RP-1: cerrar con otra resolución compatible exige confirmación
// explícita; sin ella no se envía el cierre.
test('requires explicit confirmation to close with another compatible resolution', () => {
  const base = {
    planned: 'extra_time' as ResolutionType,
    chosen: 'regular' as ResolutionType,
    limits: FULL,
    segments: PERSISTED_SEGMENTS,
    draftEvents: [{ client_event_id: 'ev-1', minute: 85, added_minute: 0 }],
    confirmed: false,
  };

  const pending = closeResolutionDecision(base);

  assert.equal(pending.outcome, 'confirm');
  assert.equal(pending.changed, true);
  assert.equal(pending.needsConfirmation, true);
  assert.equal(pending.send, false, 'without confirmation the report is not closed');
  assert.equal(pending.messageKey, 'match.closeResolutionConfirm');
  assert.equal(pending.messageParams.resolution, 'regular');
  assert.equal(pending.messageParams.planned, 'extra_time');
  assert.equal(pending.messageParams.max, 90);

  const confirmed = closeResolutionDecision({ ...base, confirmed: true });

  assert.equal(confirmed.outcome, 'confirm');
  assert.equal(confirmed.needsConfirmation, true);
  assert.equal(confirmed.send, true, 'the explicit confirmation lets the close through');
});

// RF-034: la confirmación nombra los eventos del borrador que quedan fuera.
test('names the draft events that fall outside the resolution chosen at close', () => {
  const decision = closeResolutionDecision({
    planned: 'extra_time',
    chosen: 'regular',
    limits: FULL,
    segments: PERSISTED_SEGMENTS,
    draftEvents: [
      { client_event_id: 'ev-1', minute: 95, added_minute: 0 },
      { client_event_id: 'ev-2', minute: 108, added_minute: 0 },
    ],
    confirmed: false,
  });

  assert.equal(decision.outcome, 'confirm');
  assert.equal(decision.needsConfirmation, true);
  assert.equal(decision.messageKey, 'match.closeResolutionWithAffectedDraft');
  assert.equal(decision.messageParams.count, 2);
  assert.equal(decision.messageParams.minute, 108);
  assert.equal(decision.messageParams.max, 90);
});

// RF-034: con la resolución prevista no hay confirmación adicional.
test('closes without an extra confirmation with the planned resolution', () => {
  const decision = closeResolutionDecision({
    planned: 'regular',
    chosen: 'regular',
    limits: FULL,
    segments: PERSISTED_SEGMENTS,
    draftEvents: [],
    confirmed: false,
  });

  assert.equal(decision.outcome, 'ok');
  assert.equal(decision.needsConfirmation, false);
  assert.equal(decision.send, true);
  assert.equal(decision.messageKey, 'match.resolutionChangeOk');
});

// RF-034/RP-1: la resolución prevista es la vigente al abrir el cierre. Si el
// operador la cambió durante la operación, el cierre no le avisa de un cambio
// que no ha hecho; solo se confirma lo que cambie después de ese momento.
test('takes the resolution in force when the close opens as the planned one', () => {
  const duringOperation = closeResolutionDecision({
    planned: 'extra_time',
    chosen: 'extra_time',
    limits: FULL,
    segments: PERSISTED_SEGMENTS,
    draftEvents: [],
    confirmed: false,
  });
  assert.equal(duringOperation.changed, false);
  assert.equal(duringOperation.outcome, 'ok');
  assert.equal(duringOperation.needsConfirmation, false);
  assert.equal(duringOperation.send, true);

  const afterSnapshot = closeResolutionDecision({
    planned: 'extra_time',
    chosen: 'penalties',
    limits: FULL,
    segments: PERSISTED_SEGMENTS,
    draftEvents: [],
    confirmed: false,
  });
  assert.equal(afterSnapshot.changed, true);
  assert.equal(afterSnapshot.outcome, 'confirm');
  assert.equal(afterSnapshot.needsConfirmation, true);
  assert.equal(afterSnapshot.send, false);
});

// RF-034: el composable expone la instantánea del cierre y la operación la
// toma al abrir el panel, sin dejar de arrastrar y persistir la resolución.
test('snapshots the planned resolution when the close panel opens', () => {
  assert.match(COMPOSABLE_SOURCE, /function snapshot\(/);
  assert.match(COMPOSABLE_SOURCE, /planned\.value = resolution\.value/);
  assert.match(COMPOSABLE_SOURCE, /snapshot/);
  assert.match(COMPOSABLE_SOURCE, /store\.value\.save\(/);

  assert.match(PAGE_SOURCE, /snapshot: snapshotResolution/);
  assert.match(PAGE_SOURCE, /@focusin="beginClose"/);
  assert.match(PAGE_SOURCE, /function beginClose\(/);
  const beginCloseAt = PAGE_SOURCE.indexOf('function beginClose(');
  const beginCloseBody = PAGE_SOURCE.slice(beginCloseAt, PAGE_SOURCE.indexOf('\n}', beginCloseAt));
  assert.match(beginCloseBody, /snapshotResolution\(/);
  assert.match(PAGE_SOURCE, /restoreResolution\(operation\.value\?\.limits \?\? null\)/);
});

// RF-034/P2: con segmentos fuera del máximo no hay confirmación posible; el
// acta sigue abierta aunque el operador diga que sí.
test('never closes an incompatible resolution even when confirmed', () => {
  const segments: ResolutionSegmentInput[] = [
    ...PERSISTED_SEGMENTS,
    { id: 'seg-3', segment_number: 3, minute_start: 91, minute_end: 100, status: 'completed' },
  ];

  const decision = closeResolutionDecision({
    planned: 'extra_time',
    chosen: 'regular',
    limits: FULL,
    segments,
    draftEvents: [],
    confirmed: true,
  });

  assert.equal(decision.outcome, 'blocked');
  assert.equal(decision.needsConfirmation, false);
  assert.equal(decision.send, false);
  assert.equal(decision.messageParams.segment, 3);
  assert.equal(decision.messageParams.minute, 100);
});

// RNF-003: el tope del cierre sale del bloque `limits` del servidor, con la
// misma regla que la operación.
test('resolves the close maximum from the server limits', () => {
  const plannedOnly: OperationLimits = {
    max_minute_regular: 80,
    max_minute_extra: 110,
    max_minute: 80,
    extra_time_enabled: false,
    penalties_enabled: false,
    added_minute_max: 30,
  };

  const decision = closeResolutionDecision({
    planned: 'extra_time',
    chosen: 'regular',
    limits: plannedOnly,
    segments: [{ id: 'seg-1', segment_number: 1, minute_start: 0, minute_end: 85, status: 'completed' }],
    draftEvents: [],
    confirmed: true,
  });

  // `extra_time` no está habilitada: la prevista se normaliza a regular y el
  // máximo es el reglamentario del servidor (80); el segmento que acaba en 85
  // bloquea el cierre.
  assert.equal(decision.maxMinute, 80);
  assert.equal(decision.outcome, 'blocked');
  assert.equal(decision.send, false);
});

// RF-033/RF-034: la operación valida el cambio antes de aplicarlo y el cierre
// no se envía sin la confirmación explícita.
test('gates the change and the close on the pure decisions', () => {
  const changeStart = PAGE_SOURCE.indexOf('function changeResolution(');
  const changeBody = PAGE_SOURCE.slice(changeStart, PAGE_SOURCE.indexOf('const selectedResolution'));
  assert.ok(changeStart > 0, 'the operation needs a resolution change handler');
  assert.match(changeBody, /resolutionChangeOutcome\(/);
  assert.match(changeBody, /outcome\.outcome === 'blocked'/);
  assert.ok(
    changeBody.indexOf("outcome.outcome === 'blocked'") < changeBody.indexOf('selectResolution('),
    'a blocked change must return before the selection is applied',
  );
  assert.doesNotMatch(changeBody, /draftEvents\.value\s*=/, 'the change never deletes draft events');

  assert.match(PAGE_SOURCE, /closeResolutionDecision\(/);
  const decisionAt = PAGE_SOURCE.indexOf('closeResolutionDecision(');
  const closeRequestAt = PAGE_SOURCE.indexOf('/matches/${matchId}/close');
  assert.ok(decisionAt > 0, 'the close must evaluate the decision');
  assert.ok(decisionAt < closeRequestAt, 'the decision must come before sending the close');
  assert.match(PAGE_SOURCE, /needsConfirmation/);
  assert.match(PAGE_SOURCE, /window\.confirm\(t\(decision\.messageKey/);
});

// RF-033/RNF-011: las funciones son puras: sin reloj, sin red y sin
// almacenamiento.
test('computes the change without a clock or the network', () => {
  for (const pattern of [/Date\.now/, /new Date\(/, /\$fetch/, /useApi/]) {
    assert.doesNotMatch(UTILS_SOURCE, pattern);
  }
  assert.match(UTILS_SOURCE, /resolutionChangeOutcome/);
  assert.match(UTILS_SOURCE, /closeResolutionDecision/);
});

// RF-029: los textos nuevos existen en español e inglés, una sola vez por
// idioma, y nombran el segmento, el minuto y el máximo.
test('declares the change and close texts in both catalogs', () => {
  const keys = [
    'match.resolutionChangeOk',
    'match.resolutionChangeNeedsConfirmation',
    'match.resolutionChangeBlocked',
    'match.closeResolutionConfirm',
    'match.closeResolutionWithAffectedDraft',
  ];

  for (const key of keys) {
    assert.equal(
      TRANSLATIONS_SOURCE.split(`'${key}':`).length - 1,
      2,
      `${key} must be declared once per language`,
    );
  }

  assert.match(
    TRANSLATIONS_SOURCE,
    /'match\.resolutionChangeBlocked': '[^']*\{segment\}[^']*\{minute\}[^']*\{max\}/,
    'the blocked message names the segment, the minute and the maximum',
  );
  assert.match(
    TRANSLATIONS_SOURCE,
    /'match\.resolutionChangeNeedsConfirmation': '[^']*\{count\}[^']*\{max\}[^']*\{minute\}/,
    'the draft warning names the number of events, the maximum and the minute',
  );
});

// ---------------------------------------------------------------------------
// Spec 012, H3-T06 (RF-022, RF-034, RNF-011).
//
// El borrador local del partido (eventos y formulario de cierre) deja de
// escribir la resolución prevista. Un borrador antiguo que la contenga la
// ignora al restaurar, la elimina del guardado sin tocar eventos ni marcador y
// nunca la usa como resolución de la pestaña: sin selección de sesión, la
// prevista es tiempo reglamentario.
// ---------------------------------------------------------------------------

const DRAFT_SCOPE: MatchDraftScope = {
  userId: 'user-1',
  organizationId: 'org-1',
  matchId: 'match-1',
};

const DRAFT_EVENTS = [
  {
    client_event_id: 'ev-1',
    event_type: 'goal',
    team_id: 'team-1',
    beneficiary_team_id: null,
    player_id: 'player-1',
    minute: 12,
    added_minute: 0,
    segment_id: 'segment-1',
    player_out_id: null,
    player_in_id: null,
  },
  {
    client_event_id: 'ev-2',
    event_type: 'yellow_card',
    team_id: 'team-2',
    beneficiary_team_id: null,
    player_id: 'player-2',
    minute: 44,
    added_minute: 2,
    segment_id: 'segment-1',
    player_out_id: null,
    player_in_id: null,
  },
];

const DRAFT_RESULT: MatchDraftResult = {
  home_score_regular: 2,
  away_score_regular: 1,
  home_score: 3,
  away_score: 1,
  home_penalties: null,
  away_penalties: null,
  winner_team_id: 'team-1',
  reason: '',
};

const DRAFT_SAVED_AT = '2026-10-20T10:00:00.000Z';

function legacyDraft(overrides: Record<string, unknown> = {}) {
  return {
    version: MATCH_DRAFT_VERSION,
    match_id: 'match-1',
    events: DRAFT_EVENTS,
    result: { ...DRAFT_RESULT, resolution_type: 'extra_time' },
    saved_at: DRAFT_SAVED_AT,
    ...overrides,
  };
}

// RF-022/RF-034: un borrador antiguo se restaura sin su resolución y el campo
// heredado desaparece del guardado; los eventos y el marcador quedan idénticos.
test('ignores and removes the resolution of a legacy local draft without losing events or score', () => {
  const key = matchDraftKey(DRAFT_SCOPE)!;
  const local = memoryStorage({ [key]: JSON.stringify(legacyDraft()) });

  const read = createMatchDraftStore(DRAFT_SCOPE, local.storage).read();

  assert.ok(read.draft, 'the legacy draft is still restored');
  assert.equal(read.cleaned, true, 'the legacy field is removed');
  assert.equal(read.discard, false, 'the rest of the draft is valid');
  assert.equal(Object.hasOwn(read.draft, 'resolution_type'), false);
  assert.equal(Object.hasOwn(read.draft.result, 'resolution_type'), false);
  assert.deepEqual(read.draft.events, DRAFT_EVENTS, 'every event survives intact');
  assert.deepEqual(read.draft.result, DRAFT_RESULT, 'the score and the rest of the close form survive');
  assert.equal(read.draft.match_id, 'match-1');
  assert.equal(read.draft.saved_at, DRAFT_SAVED_AT);
  assert.equal(read.draft.version, MATCH_DRAFT_VERSION);

  const rewritten = JSON.parse(local.data.get(key)!) as Record<string, unknown>;
  const rewrittenResult = rewritten.result as Record<string, unknown>;
  assert.equal(Object.hasOwn(rewritten, 'resolution_type'), false, 'the stored draft is clean');
  assert.equal(Object.hasOwn(rewrittenResult, 'resolution_type'), false);
  assert.deepEqual(rewritten.events, DRAFT_EVENTS);
  assert.deepEqual(rewrittenResult, DRAFT_RESULT);
});

// RF-022: una forma inválida del campo heredado no rompe la restauración.
test('restores a legacy draft when the resolution field has an invalid shape', () => {
  const shapes: unknown[] = [42, null, 'extra_time', { nested: true }, ['penalties']];

  for (const shape of shapes) {
    const key = matchDraftKey(DRAFT_SCOPE)!;
    const inResult = memoryStorage({
      [key]: JSON.stringify({ ...legacyDraft(), result: { ...DRAFT_RESULT, resolution_type: shape } }),
    });
    const resultRead = createMatchDraftStore(DRAFT_SCOPE, inResult.storage).read();
    assert.ok(resultRead.draft, `restores the draft with result.resolution_type = ${JSON.stringify(shape)}`);
    assert.equal(resultRead.cleaned, true);
    assert.deepEqual(resultRead.draft.events, DRAFT_EVENTS);
    assert.deepEqual(resultRead.draft.result, DRAFT_RESULT);
    assert.doesNotMatch(inResult.data.get(key)!, /resolution_type/);

    const topLevel = memoryStorage({
      [key]: JSON.stringify({ ...legacyDraft(), resolution_type: shape }),
    });
    const topRead = createMatchDraftStore(DRAFT_SCOPE, topLevel.storage).read();
    assert.ok(topRead.draft, `restores the draft with top-level resolution_type = ${JSON.stringify(shape)}`);
    assert.equal(topRead.cleaned, true);
    assert.deepEqual(topRead.draft.events, DRAFT_EVENTS);
    assert.deepEqual(topRead.draft.result, DRAFT_RESULT);
    assert.doesNotMatch(topLevel.data.get(key)!, /resolution_type/);
  }
});

// RF-022/RNF-011: un borrador ya limpio no se reescribe y conserva su formato.
test('keeps a draft without the resolution field untouched', () => {
  const key = matchDraftKey(DRAFT_SCOPE)!;
  const clean: MatchDraft = {
    version: MATCH_DRAFT_VERSION,
    match_id: 'match-1',
    events: DRAFT_EVENTS,
    result: DRAFT_RESULT,
    saved_at: DRAFT_SAVED_AT,
  };
  const raw = JSON.stringify(clean);
  const local = memoryStorage({ [key]: raw });

  const read = createMatchDraftStore(DRAFT_SCOPE, local.storage).read();

  assert.ok(read.draft);
  assert.equal(read.cleaned, false, 'there is no legacy field to remove');
  assert.equal(local.data.get(key), raw, 'a clean draft is not rewritten');
  assert.deepEqual(read.draft.events, DRAFT_EVENTS);
  assert.deepEqual(read.draft.result, DRAFT_RESULT);
  assert.equal(read.draft.saved_at, DRAFT_SAVED_AT);
});

// RF-022/RF-034: ninguna ruta del borrador (guardar, restaurar, limpiar)
// escribe la resolución prevista, ni siquiera si el formulario la trae.
test('never writes the planned resolution on any draft path', () => {
  const key = matchDraftKey(DRAFT_SCOPE)!;
  const local = memoryStorage();
  const store = createMatchDraftStore(DRAFT_SCOPE, local.storage);
  const tainted: MatchDraftResult & { resolution_type: string } = {
    ...DRAFT_RESULT,
    resolution_type: 'penalties',
  };

  const serialized = serializeMatchDraft({
    version: MATCH_DRAFT_VERSION,
    match_id: 'match-1',
    events: DRAFT_EVENTS,
    result: tainted,
    saved_at: DRAFT_SAVED_AT,
  });
  assert.doesNotMatch(serialized, /resolution_type/, 'serialization never writes the field');

  assert.equal(store.save({ events: DRAFT_EVENTS, result: tainted, saved_at: DRAFT_SAVED_AT }), true);
  assert.doesNotMatch(local.data.get(key)!, /resolution_type/, 'the initial save never writes the field');

  // El autoguardado y el guardado tras restaurar tampoco la escriben.
  assert.equal(store.save({ events: DRAFT_EVENTS, result: DRAFT_RESULT, saved_at: DRAFT_SAVED_AT }), true);
  assert.doesNotMatch(local.data.get(key)!, /resolution_type/);

  assert.equal(store.clear(), true);
  assert.equal(local.data.has(key), false, 'discarding removes only its own draft');
});

// RF-034/P3: sin selección de sesión, la prevista cae a regular y nunca toma
// el valor del borrador legacy.
test('falls back to regular time when the legacy draft is the only source', () => {
  assert.equal(matchDraftKey(DRAFT_SCOPE), 'bc_match_draft:user-1:org-1:match-1');
  assert.notEqual(matchDraftKey({ ...DRAFT_SCOPE, matchId: 'match-2' }), matchDraftKey(DRAFT_SCOPE));
  assert.equal(matchDraftKey({ ...DRAFT_SCOPE, matchId: '   ' }), null);
  assert.equal(matchDraftKey({ ...DRAFT_SCOPE, userId: null }), 'bc_match_draft:anonymous:org-1:match-1');

  const key = matchDraftKey(DRAFT_SCOPE)!;
  const local = memoryStorage({ [key]: JSON.stringify(legacyDraft()) });
  const session = memoryStorage();

  const restoredDraft = createMatchDraftStore(DRAFT_SCOPE, local.storage).read();
  const tabResolution = createResolutionStore(SCOPE, session.storage).read();

  assert.equal(tabResolution, null, 'the draft never seeds the tab selection');
  assert.equal(normalizeResolution(FULL, tabResolution), 'regular');
  assert.equal(tabResolution, null);
  assert.ok(restoredDraft.draft);
  assert.equal(Object.hasOwn(restoredDraft.draft.result, 'resolution_type'), false);
  assert.equal(Object.hasOwn(restoredDraft.draft, 'resolution_type'), false);
  assert.equal(session.data.size, 0, 'reading the draft writes nothing in the tab session');
});

// RF-022: un guardado ilegible se descarta sin romper la operación.
test('discards an unreadable local draft without breaking the operation', () => {
  assert.equal(sanitizeMatchDraft(null), null);
  assert.equal(sanitizeMatchDraft('not-a-draft'), null);
  assert.equal(sanitizeMatchDraft([]), null);
  assert.equal(parseStoredMatchDraft(null), null);
  assert.equal(parseStoredMatchDraft('{'), null);
  assert.equal(parseStoredMatchDraft('[]'), null);

  const key = matchDraftKey(DRAFT_SCOPE)!;
  const local = memoryStorage({ [key]: '{' });
  const read = createMatchDraftStore(DRAFT_SCOPE, local.storage).read();

  assert.equal(read.draft, null);
  assert.equal(read.discard, true);
});

// RF-022/RNF-011: la página guarda, restaura y descarta solo a través del
// módulo saneado; el módulo es puro y no toca la red ni el reloj.
test('writes the local draft only through the sanitized store', () => {
  assert.match(PAGE_SOURCE, /createMatchDraftStore\(/);
  assert.match(PAGE_SOURCE, /draftStore\.value\.read\(\)/);
  assert.match(PAGE_SOURCE, /draftStore\.value\.save\(/);
  assert.match(PAGE_SOURCE, /draftStore\.value\.clear\(\)/);
  assert.doesNotMatch(PAGE_SOURCE, /localStorage\.setItem/, 'no write bypasses the sanitizer');
  assert.doesNotMatch(PAGE_SOURCE, /localStorage\.removeItem/);
  assert.doesNotMatch(PAGE_SOURCE, /closeForm\.resolution_type|result\.resolution_type/);
  assert.match(
    PAGE_SOURCE,
    /restoreResolution\(operation\.value\?\.limits \?\? null\)/,
    'the planned resolution is restored only from the tab session',
  );

  for (const pattern of [/Date\.now/, /new Date\(/, /\$fetch/, /useApi/, /localStorage/, /sessionStorage/]) {
    assert.doesNotMatch(DRAFT_UTILS_SOURCE, pattern);
  }
  assert.match(DRAFT_UTILS_SOURCE, /createMatchDraftStore/);
  assert.match(DRAFT_UTILS_SOURCE, /sanitizeMatchDraft/);
});

// ---------------------------------------------------------------------------
// Spec 012, H4-T09 (RF-050, RF-046).
//
// La apertura del partido es el **primer** segmento. El servidor es la
// autoridad del tamaño de plantilla: el cliente no adelanta un bloqueo. Si la
// respuesta es **409** con `code: ROSTER_SIZE_OUT_OF_RANGE`, la operación
// muestra el detalle —equipo, mínimo, máximo y cantidad—, deja claro que el
// partido no se ha abierto, no crea el segmento en la interfaz y ofrece un
// enlace a la plantilla del equipo y un reintento. El 409 de resolución
// (`RESOLUTION_NOT_ENABLED`) se distingue por el mismo campo aditivo `code`, y
// un 409 antiguo que solo trae `detail` conserva el comportamiento actual.
// ---------------------------------------------------------------------------

const OPENING_DETAIL =
  'Plantilla fuera de rango: Leones: 9 jugadores activos (mínimo 11, máximo 25).';

test('distinguishes the opening size 409 from the resolution 409 by the additive code', () => {
  assert.equal(RESOLUTION_NOT_ENABLED_CODE, 'RESOLUTION_NOT_ENABLED');
  assert.equal(ROSTER_SIZE_OUT_OF_RANGE_CODE, 'ROSTER_SIZE_OUT_OF_RANGE');

  const sizeConflict = {
    status: 409,
    data: { detail: OPENING_DETAIL, code: ROSTER_SIZE_OUT_OF_RANGE_CODE },
  };
  assert.equal(classifyMatchConflict(sizeConflict), 'roster_size_out_of_range');
  assert.equal(matchConflictDetail(sizeConflict), OPENING_DETAIL);

  const resolutionConflict = {
    status: 409,
    data: { detail: 'La resolución no está habilitada.', code: RESOLUTION_NOT_ENABLED_CODE },
  };
  assert.equal(classifyMatchConflict(resolutionConflict), 'resolution_not_enabled');

  // Compatibilidad: un 409 que solo trae `detail` (cliente anterior) sigue
  // siendo un conflicto genérico y su detalle no se pierde.
  const legacy = { status: 409, data: { detail: 'Conflicto de estado' } };
  assert.equal(classifyMatchConflict(legacy), 'other');
  assert.equal(matchConflictDetail(legacy), 'Conflicto de estado');

  // Otros códigos, otros estados y cuerpos vacíos no se confunden.
  assert.equal(classifyMatchConflict({ status: 409, data: { code: 'OTRO' } }), 'other');
  assert.equal(classifyMatchConflict({ status: 422, data: { detail: 'x' } }), 'other');
  assert.equal(classifyMatchConflict(null), 'other');
  assert.equal(classifyMatchConflict(undefined), 'other');
  assert.equal(matchConflictDetail({ data: { detail: 7 } }), null);
  assert.equal(matchConflictDetail(null), null);
});

// Spec 017, T6 (RF-006): el cierre rechazado por una doble amarilla incoherente
// llega con su propio `code` aditivo. El clasificador lo distingue sin mirar el
// texto, igual que el asistente inválido de la 015, y un 409 anterior sin `code`
// sigue cayendo en `other` para no cambiar el comportamiento del cliente.
test('classifies the double yellow and the assist codes additively', () => {
  assert.equal(DOUBLE_YELLOW_INCONSISTENT_CODE, 'DOUBLE_YELLOW_INCONSISTENT');
  assert.equal(ASSIST_PLAYER_INVALID_CODE, 'ASSIST_PLAYER_INVALID');

  const doubleYellow = {
    status: 409,
    data: {
      detail: 'La roja por doble amarilla del minuto 61 no tiene exactamente dos amarillas previas.',
      code: DOUBLE_YELLOW_INCONSISTENT_CODE,
    },
  };
  assert.equal(classifyMatchConflict(doubleYellow), 'double_yellow_inconsistent');
  assert.equal(matchConflictDetail(doubleYellow), doubleYellow.data.detail);

  const assist = {
    status: 409,
    data: { detail: 'El asistente no está en la plantilla del partido.', code: ASSIST_PLAYER_INVALID_CODE },
  };
  assert.equal(classifyMatchConflict(assist), 'assist_player_invalid');

  // Los códigos de la 012 siguen clasificándose igual.
  assert.equal(
    classifyMatchConflict({ status: 409, data: { code: RESOLUTION_NOT_ENABLED_CODE } }),
    'resolution_not_enabled',
  );
  assert.equal(
    classifyMatchConflict({ status: 409, data: { code: ROSTER_SIZE_OUT_OF_RANGE_CODE } }),
    'roster_size_out_of_range',
  );

  // Compatibilidad: sin `code` el detalle sigue mandando y no se inventa causa.
  assert.equal(classifyMatchConflict({ status: 409, data: { detail: 'Doble amarilla' } }), 'other');
});

test('keeps the match unopened and allows a retry after the opening size 409', () => {
  assert.match(PAGE_SOURCE, /classifyMatchConflict\(cause\) === 'roster_size_out_of_range'/);
  assert.match(PAGE_SOURCE, /openingBlocked\.value = describeOpeningBlocked\(/);

  const start = PAGE_SOURCE.indexOf('async function createSegment(');
  const end = PAGE_SOURCE.indexOf('async function interruptSegment(');
  assert.ok(start > 0 && end > start, 'the segment creation handler is missing');
  const body = PAGE_SOURCE.slice(start, end);

  const requestAt = body.indexOf('/matches/${matchId}/segments`');
  const responseAt = body.indexOf('showOpeningBlocked(cause)');
  // Spec 017 (RF-015): el formulario ya no avanza sumando uno en el cliente; el
  // número y el minuto los fija la propuesta del servidor en el refresco que
  // sigue a la creación, que también ocurre solo si el servidor aceptó.
  const incrementAt = body.indexOf("refreshOperation('segment-changed')");
  assert.ok(requestAt > 0, 'the creation request is missing');
  assert.ok(responseAt > requestAt, 'the opening block is only decided by the server response');
  assert.ok(incrementAt > requestAt, 'the interface only advances after a successful creation');
  assert.doesNotMatch(body, /segmentForm\.segment_number \+= 1/, 'the client advances the number by hand');

  // El intento no se bloquea antes de llamar al servidor: no hay comprobación
  // local del tamaño en la ruta de creación.
  const attempt = body.slice(0, requestAt);
  assert.doesNotMatch(attempt, /openingBlocked|rosterSizeState|hasRosterLimits|effectiveRosterLimits/);

  // La rama del 409 no crea el segmento, no avanza el formulario ni recarga
  // un estado que ya es correcto: el partido sigue sin abrir.
  const blockedBranch = body.slice(responseAt);
  assert.match(blockedBranch, /return true/);
  assert.doesNotMatch(blockedBranch, /refreshOperation\(/);
  assert.doesNotMatch(blockedBranch, /segmentForm\.segment_number/);

  // El aviso se construye a partir de la respuesta, sin tocar la red.
  const noticeStart = PAGE_SOURCE.indexOf('function showOpeningBlocked(');
  const noticeEnd = PAGE_SOURCE.indexOf('async function createSegment(');
  assert.ok(noticeStart > 0 && noticeEnd > noticeStart, 'the opening notice builder is missing');
  const notice = PAGE_SOURCE.slice(noticeStart, noticeEnd);
  assert.match(notice, /openingBlocked\.value = describeOpeningBlocked\(/);
  assert.doesNotMatch(notice, /request\(|\$fetch|refreshOperation\(|segmentForm\./);
});

test('shows the opening 409 with the team, the range, the count and a roster link', () => {
  assert.match(PAGE_SOURCE, /v-if="openingBlocked"/);
  assert.match(PAGE_SOURCE, /OPENING_BLOCKED_LABEL_KEYS\.title/);
  assert.match(PAGE_SOURCE, /OPENING_BLOCKED_LABEL_KEYS\.reason/);
  assert.match(PAGE_SOURCE, /openingBlocked\.teams/);
  assert.match(PAGE_SOURCE, /team\.message/);
  assert.match(PAGE_SOURCE, /OPENING_BLOCKED_LABEL_KEYS\.serverDetail/);
  assert.match(PAGE_SOURCE, /OPENING_BLOCKED_LABEL_KEYS\.openRoster/);
  assert.match(PAGE_SOURCE, /teamRosterLink\(team\.teamId\)/);
  assert.match(PAGE_SOURCE, /OPENING_BLOCKED_LABEL_KEYS\.retryAction/);
  assert.match(PAGE_SOURCE, /@click="createSegment"/);
  assert.match(PAGE_SOURCE, /role="alert"/);

  // El aviso de resolución no se pinta como bloqueo de apertura.
  assert.match(PAGE_SOURCE, /t\('match\.resolutionNotEnabled'\)/);
});

test('declares the opening texts in both catalogs', () => {
  const keys = [
    'rosterLimits.opening.title',
    'rosterLimits.opening.reason',
    'rosterLimits.opening.team',
    'rosterLimits.opening.serverDetail',
    'rosterLimits.opening.retry',
    'rosterLimits.opening.retryAction',
    'rosterLimits.opening.openRoster',
    'match.resolutionNotEnabled',
  ];

  for (const key of keys) {
    assert.equal(
      TRANSLATIONS_SOURCE.split(`'${key}':`).length - 1,
      2,
      `${key} must be declared once per language`,
    );
  }

  assert.match(
    TRANSLATIONS_SOURCE,
    /'rosterLimits\.opening\.team': '[^']*\{team\}[^']*\{count\}[^']*\{min\}[^']*\{max\}/,
    'the opening message names the team, the count, the minimum and the maximum',
  );
  assert.match(
    TRANSLATIONS_SOURCE,
    /'rosterLimits\.opening\.title': 'El partido no se ha abierto'/,
  );
  assert.match(
    TRANSLATIONS_SOURCE,
    /'rosterLimits\.opening\.title': 'The match was not opened'/,
  );
});

// ---------------------------------------------------------------------------
// Tope combinado de minuto (spec 012, RF-032 / criterio 20)
//
// El cierre del servidor aplica una sola regla sobre `minute + added_minute`:
// antes del minuto final la suma no puede pasar el máximo; en el minuto final
// se admite el añadido dentro del tope estructural. El cliente tiene que
// validar exactamente lo mismo al añadir eventos y al restaurar el borrador.
// ---------------------------------------------------------------------------

test('the combined event minute matches the server rule at the exact boundary', () => {
  const max = 90;
  const addedMax = 30;

  // Borde exacto: 90 + 0 y 89 + 1 son válidos; el final admite el añadido.
  assert.equal(validateEventMinute(90, 0, max, addedMax).ok, true);
  assert.equal(validateEventMinute(89, 1, max, addedMax).ok, true);
  assert.equal(validateEventMinute(90, 5, max, addedMax).ok, true, 'the final minute opens the added window');
  assert.equal(validateEventMinute(0, 30, max, addedMax).ok, true);

  // 89 + 5 supera el máximo antes del minuto final: el cierre lo rechazaría.
  const overCombined = validateEventMinute(89, 5, max, addedMax);
  assert.equal(overCombined.ok, false);
  assert.equal(overCombined.reason, 'combined');
  assert.deepEqual(
    { minute: overCombined.minute, added: overCombined.added, max: overCombined.max },
    { minute: 89, added: 5, max: 90 },
  );

  assert.equal(validateEventMinute(91, 0, max, addedMax).reason, 'minute');
  assert.equal(validateEventMinute(45, 46, max, addedMax).reason, 'combined');
  assert.equal(validateEventMinute(0, 31, max, addedMax).reason, 'added');
  assert.equal(validateEventMinute(Number.NaN, 0, max, addedMax).reason, 'minute');
});

test('restoring a draft finds the stored events the closure would reject', () => {
  const max = 90;
  const addedMax = 30;
  const events = [
    { client_event_id: 'a', minute: 45, added_minute: 0 },
    { client_event_id: 'b', minute: 89, added_minute: 5 },
    { client_event_id: 'c', minute: 90, added_minute: 5 },
    { client_event_id: 'd', minute: 91, added_minute: 0 },
  ];

  const violations = findDraftMinuteViolations(events, max, addedMax);
  assert.deepEqual(
    violations.map((violation) => [violation.index, violation.event.client_event_id, violation.validation.reason]),
    [
      [1, 'b', 'combined'],
      [3, 'd', 'minute'],
    ],
  );
});

test('the operation uses the combined validator when adding and when restoring a draft', () => {
  assert.match(PAGE_SOURCE, /validateEventMinute\(/);
  assert.match(PAGE_SOURCE, /findDraftMinuteViolations\(/);
  assert.match(PAGE_SOURCE, /draftMinuteViolations/);
  // El mensaje nombra minuto, añadido y máximo, y el evento inválido no se añade.
  assert.match(PAGE_SOURCE, /match\.eventMinuteExceedsMaximum/);
  assert.match(
    TRANSLATIONS_SOURCE,
    /'match\.eventMinuteExceedsMaximum': '[^']*\{minute\}[^']*\{added\}[^']*\{max\}/,
  );
  // El cierre no puede ignorar los eventos restaurados fuera del tope: el
  // problema de minuto entra en la validación previa como `minuteIssue`.
  const closeValidation = PAGE_SOURCE.slice(
    PAGE_SOURCE.indexOf('function closeValidationIssue('),
    PAGE_SOURCE.indexOf('function failureMessage('),
  );
  assert.match(closeValidation, /draftMinuteViolations\.value/);
});

// ---------------------------------------------------------------------------
// Spec 016, T9 (RF-005, RF-012, RNF-003). El walkover añade tres códigos de
// dominio a la misma clasificación de conflictos de la operación y deja de
// bloquearse por segmentos persistidos fuera del máximo: el servidor no valida
// segmentos en el W.O. (D-13).
// ---------------------------------------------------------------------------

test('classifies the three walkover codes with the shared classifier', () => {
  assert.equal(WALKOVER_STATE_NOT_ALLOWED_CODE, 'WALKOVER_STATE_NOT_ALLOWED');
  assert.equal(WALKOVER_SCORE_MISMATCH_CODE, 'WALKOVER_SCORE_MISMATCH');
  assert.equal(WALKOVER_CONFIG_INCONSISTENT_CODE, 'WALKOVER_CONFIG_INCONSISTENT');

  const cases = [
    ['walkover_state_not_allowed', WALKOVER_STATE_NOT_ALLOWED_CODE],
    ['walkover_score_mismatch', WALKOVER_SCORE_MISMATCH_CODE],
    ['walkover_config_inconsistent', WALKOVER_CONFIG_INCONSISTENT_CODE],
  ] as const;

  for (const [kind, code] of cases) {
    assert.equal(classifyMatchConflict({ status: 409, data: { detail: 'x', code } }), kind);
    assert.ok(closeConflictMessageKey(kind), `${kind} needs its own message`);
  }

  assert.equal(classifyMatchConflict({ status: 409, data: { code: 'OTRO' } }), 'other');
});

// D-13/RF-012: con walkover el servidor no valida segmentos, así que un
// segmento persistido por encima del máximo no bloquea el cambio; el aviso por
// eventos del borrador se conserva. Con las demás resoluciones sigue bloqueando.
test('does not block a walkover because of persisted segments beyond the maximum', () => {
  const segments: ResolutionSegmentInput[] = [
    ...PERSISTED_SEGMENTS,
    { id: 'seg-3', segment_number: 3, minute_start: 91, minute_end: 100, status: 'completed' },
  ];
  const events: ResolutionDraftEventInput[] = [
    { client_event_id: 'ev-1', event_type: 'goal', minute: 95, added_minute: 0 },
  ];

  assert.equal(resolutionChangeOutcome(segments, [], 90).outcome, 'blocked');

  const walkoverChange = resolutionChangeOutcome(segments, [], 90, { resolution: 'walkover' });
  assert.equal(walkoverChange.outcome, 'ok');

  const walkoverWithDraft = resolutionChangeOutcome(segments, events, 90, {
    resolution: 'walkover',
  });
  assert.equal(walkoverWithDraft.outcome, 'confirm');
  assert.equal(walkoverWithDraft.events.length, 1);

  const decision = closeResolutionDecision({
    planned: 'regular',
    chosen: 'walkover',
    limits: FULL,
    segments,
    draftEvents: [],
    confirmed: true,
  });
  assert.equal(decision.outcome, 'confirm');
  assert.equal(decision.send, true);
  assert.equal(decision.needsConfirmation, true);
});
