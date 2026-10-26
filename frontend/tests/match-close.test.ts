import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  WALKOVER_REASONS,
  WALKOVER_REASON_LABEL_KEYS,
  buildCloseReportBody,
  closePreflight,
  walkoverReasonLabelKey,
  walkoverScoreFrom,
  type ClosePreflightInput,
} from '../app/utils/matchClose.ts';
import {
  WALKOVER_CONFIG_INCONSISTENT_CODE,
  WALKOVER_SCORE_MISMATCH_CODE,
  WALKOVER_STATE_NOT_ALLOWED_CODE,
  classifyMatchConflict,
  type OperationLimits,
} from '../app/utils/matchResolution.ts';
import {
  classifyCloseConflict,
  closeConflictMessageKey,
} from '../app/utils/matchSegments.ts';

// Spec 016, T9 (RF-012, RF-005, RNF-007). El cierre por resolución vive en
// utilidades puras: el cuerpo que se envía, la validación previa, el catálogo
// de motivos del walkover y la clasificación de sus tres códigos. La pantalla
// (T10) solo cablea estas funciones.
//
// El catálogo de motivos tiene una sola fuente en el cliente y esta prueba la
// contrasta con `WALKOVER_REASONS` del backend, que es la autoridad (RF-007).
// Esa fuente no siempre es alcanzable: `web` monta solo `frontend`, así que
// dentro del contenedor `../../backend` no existe. Cuando no se puede leer, la
// prueba de paridad se **omite** con el motivo a la vista; cuando se puede (el
// runner de CI con el repositorio completo, o el árbol montado en `/repo`), se
// compara de verdad.

/**
 * Fuente del backend, o `null` si la ruta no es alcanzable desde el directorio
 * de pruebas. No se convierte en un fallo: la paridad es una comprobación extra
 * y su ausencia se informa como omisión, no como rojo.
 */
function readBackendSchemas(): string | null {
  try {
    return readFileSync(
      new URL('../../backend/app/modules/matches/schemas.py', import.meta.url),
      'utf8',
    );
  } catch {
    return null;
  }
}

const BACKEND_SCHEMAS = readBackendSchemas();
const BACKEND_REASONS_SKIP = BACKEND_SCHEMAS
  ? false
  : 'backend/app/modules/matches/schemas.py is not reachable from the test directory '
    + '(only `frontend` is mounted in the `web` container); run the suite from the '
    + 'repository root to compare the catalogues';

const TRANSLATIONS = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);

const FULL: OperationLimits = {
  max_minute_regular: 90,
  max_minute_extra: 120,
  max_minute: 120,
  extra_time_enabled: true,
  penalties_enabled: true,
  added_minute_max: 30,
  walkover_score: { winner: 3, loser: 0 },
};

const SCORE_KEYS = [
  'home_score_regular',
  'away_score_regular',
  'home_score',
  'away_score',
  'home_penalties',
  'away_penalties',
] as const;

/** Motivos declarados por el backend, leídos de su única fuente. */
function backendWalkoverReasons(source: string): string[] {
  const block = source.match(/WALKOVER_REASONS[^=\n]*=\s*\(([\s\S]*?)\)/);
  assert.ok(block, 'the backend declares WALKOVER_REASONS');
  return Array.from(block[1]!.matchAll(/"([^"\\]+)"/g), (match) => match[1]!);
}

function catalogSlices(): { spanish: string; english: string } {
  const englishStart = TRANSLATIONS.indexOf('\n  en: {');
  assert.ok(englishStart > 0, 'the English catalog is missing');
  return {
    spanish: TRANSLATIONS.slice(0, englishStart),
    english: TRANSLATIONS.slice(englishStart),
  };
}

function preflightInput(overrides: Partial<ClosePreflightInput> = {}): ClosePreflightInput {
  return {
    resolution: 'walkover',
    limits: FULL,
    homeTeamId: 'home',
    awayTeamId: 'away',
    segmentActive: false,
    lineupComplete: false,
    scores: {},
    winnerTeamId: 'home',
    reason: 'no_show',
    draftEvents: [],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// RF-012: la validación previa depende de la resolución.
// ---------------------------------------------------------------------------

// RF-012/RF-003: el walkover no exige segmento activo ni planilla completa; es
// el caso típico (un equipo no se presenta).
test('accepts a walkover without an active segment or a complete lineup', () => {
  assert.equal(closePreflight(preflightInput()), null);
  assert.equal(
    closePreflight(preflightInput({ segmentActive: false, lineupComplete: false })),
    null,
  );
});

// RF-012: el resto de resoluciones conserva la exigencia de segmento y planilla.
test('still requires an active segment and both lineups for the other resolutions', () => {
  const missingSegment = closePreflight(
    preflightInput({ resolution: 'regular', segmentActive: false, lineupComplete: true }),
  );
  assert.equal(missingSegment?.key, 'match.needSegmentLineup');

  const missingLineup = closePreflight(
    preflightInput({ resolution: 'extra_time', segmentActive: true, lineupComplete: false }),
  );
  assert.equal(missingLineup?.key, 'match.needSegmentLineup');

  const ready = closePreflight(
    preflightInput({
      resolution: 'regular',
      segmentActive: true,
      lineupComplete: true,
      winnerTeamId: null,
      reason: null,
      scores: { home_score_regular: 0, away_score_regular: 0 },
    }),
  );
  assert.equal(ready, null);
});

// RF-007: el motivo es obligatorio y de catálogo cerrado; ausente o fuera del
// catálogo se informa con su propia clave (nunca como un error genérico).
test('requires a walkover reason from the closed catalogue', () => {
  for (const reason of [null, undefined, '']) {
    const issue = closePreflight(preflightInput({ reason }));
    assert.equal(issue?.key, 'match.walkoverReasonRequired', `reason ${String(reason)}`);
  }

  const unknown = closePreflight(preflightInput({ reason: 'home_win' }));
  assert.equal(unknown?.key, 'match.walkoverReasonRequired');

  for (const reason of WALKOVER_REASONS) {
    assert.equal(closePreflight(preflightInput({ reason })), null, `reason ${reason}`);
  }
});

// RF-006/D-13: el walkover no admite ningún evento, con un mensaje concreto
// (no el genérico del cierre).
test('rejects a walkover with draft events', () => {
  const issue = closePreflight(
    preflightInput({ draftEvents: [{ event_type: 'goal', team_id: 'home' }] }),
  );
  assert.equal(issue?.key, 'match.walkoverEventsNotAllowed');
});

// RF-001/RNF-007: el walkover exige un ganador que sea uno de los participantes.
// Sin ganador el error es del campo (su propia clave); un ganador que no
// participa sigue siendo el rechazo genérico del cierre.
test('rejects a walkover without a participating winner', () => {
  assert.equal(
    closePreflight(preflightInput({ winnerTeamId: null }))?.key,
    'match.walkoverWinnerRequired',
  );
  assert.equal(
    closePreflight(preflightInput({ winnerTeamId: '' }))?.key,
    'match.walkoverWinnerRequired',
  );
  assert.equal(
    closePreflight(preflightInput({ winnerTeamId: 'other-team' }))?.key,
    'match.closeValidation',
  );
});

// RF-007: la resolución administrativa conserva su texto libre y sus reglas;
// `reason` sigue prohibido en las demás resoluciones.
test('keeps the administrative free-text reason and forbids it elsewhere', () => {
  const administrative = {
    resolution: 'administrative',
    segmentActive: true,
    lineupComplete: true,
    winnerTeamId: 'home',
    scores: { home_score_regular: 1, away_score_regular: 0, home_score: 1, away_score: 0 },
  } as const;

  assert.equal(closePreflight(preflightInput({ ...administrative, reason: 'Cambio de horario' })), null);
  assert.equal(
    closePreflight(preflightInput({ ...administrative, reason: '' }))?.key,
    'match.administrativeReasonRequired',
  );

  assert.equal(
    closePreflight(
      preflightInput({
        resolution: 'regular',
        segmentActive: true,
        lineupComplete: true,
        winnerTeamId: null,
        reason: 'no_show',
        scores: { home_score_regular: 0, away_score_regular: 0 },
      }),
    )?.key,
    'match.closeValidation',
  );
});

// RF-032 (spec 012): el problema de minuto ya resuelto por la pantalla sigue
// bloqueando el cierre normal, pero no un walkover, que no valida segmentos.
test('keeps the draft minute issue for the normal close and ignores it for a walkover', () => {
  const minuteIssue = { key: 'match.minuteOutOfRange', params: { max: 90 } };

  assert.equal(
    closePreflight(
      preflightInput({
        resolution: 'regular',
        segmentActive: true,
        lineupComplete: true,
        winnerTeamId: null,
        reason: null,
        scores: { home_score_regular: 0, away_score_regular: 0 },
        minuteIssue,
      }),
    )?.key,
    'match.minuteOutOfRange',
  );
  assert.equal(closePreflight(preflightInput({ minuteIssue })), null);
});

// ---------------------------------------------------------------------------
// RF-005: el cuerpo del cierre por resolución.
// ---------------------------------------------------------------------------

// RF-005/RF-012: el walkover no envía ninguno de los seis marcadores; el
// servidor deriva el marcador de las reglas de la fase.
test('builds a walkover body without any score field', () => {
  const body = buildCloseReportBody({
    resolution: 'walkover',
    limits: FULL,
    scores: { home_score_regular: 0, away_score_regular: 0, home_score: 0, away_score: 0 },
    winnerTeamId: 'away',
    reason: 'sanction',
    events: [],
  });

  for (const key of SCORE_KEYS) {
    assert.ok(!(key in body), `the walkover body must not send ${key}`);
  }

  assert.deepEqual(Object.keys(body).sort(), [
    'events',
    'reason',
    'resolution_type',
    'winner_team_id',
  ]);
  assert.equal(body.resolution_type, 'walkover');
  assert.equal(body.winner_team_id, 'away');
  assert.equal(body.reason, 'sanction');
  assert.deepEqual(body.events, []);
});

// RF-012: el resto de resoluciones conserva exactamente su cuerpo actual.
test('keeps the current body for the other resolutions', () => {
  const scores = {
    home_score_regular: 2,
    away_score_regular: 1,
    home_score: 3,
    away_score: 1,
    home_penalties: 4,
    away_penalties: 3,
  };

  assert.deepEqual(
    buildCloseReportBody({ resolution: 'regular', limits: FULL, scores, winnerTeamId: 'away', reason: 'x' }),
    {
      resolution_type: 'regular',
      home_score_regular: 2,
      away_score_regular: 1,
      home_score: null,
      away_score: null,
      home_penalties: null,
      away_penalties: null,
      winner_team_id: null,
      reason: null,
      events: [],
    },
  );

  assert.deepEqual(
    buildCloseReportBody({ resolution: 'extra_time', limits: FULL, scores, winnerTeamId: 'home', reason: 'x' }),
    {
      resolution_type: 'extra_time',
      home_score_regular: 2,
      away_score_regular: 1,
      home_score: 3,
      away_score: 1,
      home_penalties: null,
      away_penalties: null,
      winner_team_id: 'home',
      reason: null,
      events: [],
    },
  );

  assert.deepEqual(
    buildCloseReportBody({ resolution: 'penalties', limits: FULL, scores, winnerTeamId: 'home', reason: 'x' }),
    {
      resolution_type: 'penalties',
      home_score_regular: 2,
      away_score_regular: 1,
      home_score: 3,
      away_score: 1,
      home_penalties: 4,
      away_penalties: 3,
      winner_team_id: 'home',
      reason: null,
      events: [],
    },
  );

  assert.deepEqual(
    buildCloseReportBody({
      resolution: 'administrative',
      limits: FULL,
      scores,
      winnerTeamId: 'home',
      reason: '  Cambio de horario  ',
    }),
    {
      resolution_type: 'administrative',
      home_score_regular: 2,
      away_score_regular: 1,
      home_score: 3,
      away_score: 1,
      home_penalties: null,
      away_penalties: null,
      winner_team_id: 'home',
      reason: 'Cambio de horario',
      events: [],
    },
  );
});

// RF-005: el marcador efectivo del walkover se lee del bloque `limits`; un
// servidor anterior (clave ausente) no rompe la pantalla.
test('reads the effective walkover score from the operation limits', () => {
  assert.deepEqual(walkoverScoreFrom(FULL), { winner: 3, loser: 0 });
  assert.deepEqual(walkoverScoreFrom({ walkover_score: { winner: 5, loser: 1 } }), {
    winner: 5,
    loser: 1,
  });
  assert.equal(walkoverScoreFrom({}), null);
  assert.equal(walkoverScoreFrom(null), null);
  assert.equal(walkoverScoreFrom(undefined), null);
  assert.equal(walkoverScoreFrom({ walkover_score: null }), null);
  assert.equal(walkoverScoreFrom({ walkover_score: { winner: '3', loser: 0 } }), null);
  assert.equal(walkoverScoreFrom({ walkover_score: { winner: 3 } }), null);
  assert.equal(walkoverScoreFrom({ walkover_score: { winner: -1, loser: 0 } }), null);
});

// ---------------------------------------------------------------------------
// RF-007: una sola fuente del catálogo de motivos.
// ---------------------------------------------------------------------------

// RF-007: el catálogo del cliente coincide con `WALKOVER_REASONS` del backend,
// en el mismo orden, y cada motivo tiene su clave i18n (sin literales). Se omite
// —con el motivo visible— cuando la fuente del backend no es alcanzable.
test('matches the backend walkover reason catalogue', { skip: BACKEND_REASONS_SKIP }, () => {
  const backend = backendWalkoverReasons(BACKEND_SCHEMAS as string);

  assert.equal(backend.length, 4, 'the backend catalogue declares four reasons');
  assert.deepEqual([...WALKOVER_REASONS], backend);

  for (const reason of WALKOVER_REASONS) {
    const key = WALKOVER_REASON_LABEL_KEYS[reason];
    assert.ok(key, `missing label key for ${reason}`);
    assert.equal(walkoverReasonLabelKey(reason), key);
    assert.match(key, /^match\./);
  }
});

// ---------------------------------------------------------------------------
// RNF-003/RF-005: los tres códigos del walkover se clasifican con el
// clasificador existente (no hay un segundo clasificador).
// ---------------------------------------------------------------------------

test('classifies the three walkover codes with their own message', () => {
  assert.equal(WALKOVER_STATE_NOT_ALLOWED_CODE, 'WALKOVER_STATE_NOT_ALLOWED');
  assert.equal(WALKOVER_SCORE_MISMATCH_CODE, 'WALKOVER_SCORE_MISMATCH');
  assert.equal(WALKOVER_CONFIG_INCONSISTENT_CODE, 'WALKOVER_CONFIG_INCONSISTENT');

  const causes = {
    walkover_state_not_allowed: {
      status: 409,
      data: { detail: 'El partido no admite walkover.', code: WALKOVER_STATE_NOT_ALLOWED_CODE },
    },
    walkover_score_mismatch: {
      status: 409,
      data: { detail: 'El marcador no coincide.', code: WALKOVER_SCORE_MISMATCH_CODE },
    },
    walkover_config_inconsistent: {
      status: 409,
      data: { detail: 'El marcador no da la victoria.', code: WALKOVER_CONFIG_INCONSISTENT_CODE },
    },
  } as const;

  const expectedKeys = {
    walkover_state_not_allowed: 'match.walkoverStateNotAllowed',
    walkover_score_mismatch: 'match.walkoverScoreMismatch',
    walkover_config_inconsistent: 'match.walkoverConfigInconsistent',
  } as const;

  for (const [kind, cause] of Object.entries(causes)) {
    // El clasificador es el mismo que usa el resto de la operación.
    assert.equal(classifyMatchConflict(cause), kind);
    assert.equal(classifyCloseConflict(cause), kind);
    assert.equal(
      closeConflictMessageKey(kind as keyof typeof expectedKeys),
      expectedKeys[kind as keyof typeof expectedKeys],
    );
  }

  // Un código desconocido cae en el mensaje genérico del cierre.
  assert.equal(classifyMatchConflict({ status: 409, data: { code: 'OTRO' } }), 'other');
  assert.equal(closeConflictMessageKey('other'), 'match.noClose');
});

// RNF-007/RF-012: los textos de los motivos y de los tres códigos existen en
// español e inglés.
test('declares the walkover texts in both catalogues', () => {
  const { spanish, english } = catalogSlices();
  const keys = [
    'match.walkoverReason',
    'match.walkoverReasonRequired',
    'match.walkoverWinnerRequired',
    'match.walkoverEventsNotAllowed',
    'match.walkoverScore',
    'match.walkoverNoSegment',
    'match.walkoverStateNotAllowed',
    'match.walkoverScoreMismatch',
    'match.walkoverConfigInconsistent',
    ...Object.values(WALKOVER_REASON_LABEL_KEYS),
  ];

  for (const key of keys) {
    const pattern = new RegExp(`'${key.replace(/\./g, '\\.')}':`);
    assert.match(spanish, pattern, `missing Spanish key ${key}`);
    assert.match(english, pattern, `missing English key ${key}`);
  }
});
