import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  CLOSE_CONFLICT_MESSAGE_LABEL_KEYS,
  SEGMENT_PROPOSAL_HINT_LABEL_KEYS,
  applySegmentProposal,
  classifyCloseConflict,
  closeConflictMessageKey,
  forceMinuteOnRefresh,
  parseSegmentProposal,
  segmentProposalHint,
  shouldPrefillMinute,
  type SegmentFormState,
} from '../app/utils/matchSegments.ts';
import {
  ASSIST_PLAYER_INVALID_CODE,
  DOUBLE_YELLOW_INCONSISTENT_CODE,
  RESOLUTION_NOT_ENABLED_CODE,
  ROSTER_SIZE_OUT_OF_RANGE_CODE,
  classifyMatchConflict,
} from '../app/utils/matchResolution.ts';

// Spec 017, T6 (RF-015, RF-006). La propuesta del siguiente segmento la calcula
// el servidor (`next_segment` en la operación) y el cliente solo la **consume**:
// aquí se valida su forma y se decide qué campos del formulario se prerrellenan.
// El servidor sigue siendo la autoridad al crear el segmento (RF-013/RF-014).
//
// Todo es puro: no hay reloj, red, almacenamiento ni estado de módulo, así que
// las mismas entradas producen siempre el mismo resultado (RNF-008).

const UTILS_SOURCE = readFileSync(
  new URL('../app/utils/matchSegments.ts', import.meta.url),
  'utf8',
);

const CLEAN_FORM: SegmentFormState = { segment_number: 1, minute_start: 0, minuteDirty: false };
const EDITED_FORM: SegmentFormState = { segment_number: 1, minute_start: 55, minuteDirty: true };

// ---------------------------------------------------------------------------
// La propuesta del servidor: forma declarada
// ---------------------------------------------------------------------------

test('reads the proposal returned by the operation and applies its number and minute', () => {
  const proposal = { segment_number: 3, minute_start: 37, derived: true };

  assert.deepEqual(parseSegmentProposal(proposal), {
    segment_number: 3,
    minute_start: 37,
    derived: true,
  });

  const next = applySegmentProposal(CLEAN_FORM, proposal);
  assert.deepEqual(next, { segment_number: 3, minute_start: 37, minuteDirty: false });
});

test('ignores a null proposal without blocking the segment form', () => {
  assert.equal(parseSegmentProposal(null), null);
  assert.equal(segmentProposalHint(null), null);

  // Un partido terminal (o una versión no publicada) no propone nada: el
  // formulario conserva lo que tenía y sigue utilizable, no queda bloqueado.
  const untouched = applySegmentProposal(EDITED_FORM, null);
  assert.deepEqual(untouched, EDITED_FORM);
  assert.deepEqual(applySegmentProposal(CLEAN_FORM, undefined), CLEAN_FORM);
  assert.equal(shouldPrefillMinute(EDITED_FORM, null), false);
});

test('discards a proposal whose shape does not match the contract', () => {
  const invalid: unknown[] = [
    undefined,
    'next',
    7,
    true,
    [],
    {},
    // Número del segmento: entero >= 1.
    { segment_number: 0, minute_start: 0, derived: true },
    { segment_number: -1, minute_start: 0, derived: true },
    { segment_number: 1.5, minute_start: 0, derived: true },
    { segment_number: '3', minute_start: 0, derived: true },
    { minute_start: 0, derived: true },
    // `derived` es un booleano obligatorio.
    { segment_number: 3, minute_start: 37 },
    { segment_number: 3, minute_start: 37, derived: 'yes' },
    // Derivada: el minuto es un entero >= 0 informado.
    { segment_number: 3, minute_start: null, derived: true },
    { segment_number: 3, metadata: {}, derived: true },
    { segment_number: 3, minute_start: -1, derived: true },
    { segment_number: 3, minute_start: 37.5, derived: true },
    { segment_number: 3, minute_start: '37', derived: true },
    // No derivada: el minuto debe venir nulo (el operador lo indica).
    { segment_number: 3, minute_start: 37, derived: false },
    { segment_number: 3, minute_start: '0', derived: false },
  ];

  for (const value of invalid) {
    assert.equal(parseSegmentProposal(value), null, `must reject ${JSON.stringify(value)}`);
    assert.equal(segmentProposalHint(value), null, `must not hint ${JSON.stringify(value)}`);
    // Sin propuesta válida no se toca el formulario ni se rompe.
    assert.deepEqual(applySegmentProposal(EDITED_FORM, value), EDITED_FORM);
  }
});

// ---------------------------------------------------------------------------
// Cuándo se prerrellena el minuto (D-5)
//
//   propuesta válida y derivada │ minuto editado │ forceMinute │ resultado
//   ────────────────────────────┼────────────────┼─────────────┼──────────
//   no                          │ —              │ —           │ no pisa
//   sí                          │ no             │ no          │ pisa
//   sí                          │ no             │ sí          │ pisa
//   sí                          │ sí             │ no          │ no pisa
//   sí                          │ sí             │ sí          │ pisa
//   derivada falsa              │ —              │ sí          │ no pisa
// ---------------------------------------------------------------------------

test('does not overwrite the minute the operator edited', () => {
  const proposal = { segment_number: 2, minute_start: 45, derived: true };

  assert.equal(shouldPrefillMinute(EDITED_FORM, proposal), false);

  const next = applySegmentProposal(EDITED_FORM, proposal);
  // El número sí es siempre del servidor; el minuto escrito se conserva.
  assert.deepEqual(next, { segment_number: 2, minute_start: 55, minuteDirty: true });
});

test('forces the proposed minute after creating or interrupting a segment', () => {
  const proposal = { segment_number: 2, minute_start: 45, derived: true };

  assert.equal(forceMinuteOnRefresh('mount'), true);
  assert.equal(forceMinuteOnRefresh('segment-changed'), true);
  // Un refresco (incluido el que provoca el socket) no pisa lo que se escribe.
  assert.equal(forceMinuteOnRefresh('refresh'), false);

  assert.equal(shouldPrefillMinute(EDITED_FORM, proposal, { forceMinute: true }), true);

  const next = applySegmentProposal(EDITED_FORM, proposal, { forceMinute: true });
  // Al escribir el minuto propuesto, el campo deja de estar editado a mano.
  assert.deepEqual(next, { segment_number: 2, minute_start: 45, minuteDirty: false });

  // Tras crear o interrumpir, el refresco se aplica con la propuesta forzada.
  const afterInterruption = applySegmentProposal(EDITED_FORM, proposal, {
    forceMinute: forceMinuteOnRefresh('segment-changed'),
  });
  assert.deepEqual(afterInterruption, { segment_number: 2, minute_start: 45, minuteDirty: false });
});

test('only pre-fills the minute when the proposal is derived', () => {
  const manual = { segment_number: 4, minute_start: null, derived: false };

  assert.equal(segmentProposalHint(manual), 'manual');
  assert.equal(SEGMENT_PROPOSAL_HINT_LABEL_KEYS.manual, 'match.segmentProposalManual');

  // El operador lo indica: ni con forceMinute se inventa un minuto.
  assert.equal(shouldPrefillMinute(EDITED_FORM, manual, { forceMinute: true }), false);
  assert.deepEqual(applySegmentProposal(EDITED_FORM, manual, { forceMinute: true }), {
    segment_number: 4,
    minute_start: 55,
    minuteDirty: true,
  });
  assert.deepEqual(applySegmentProposal(CLEAN_FORM, manual, { forceMinute: true }), {
    segment_number: 4,
    minute_start: 0,
    minuteDirty: false,
  });

  // La propuesta derivada se anuncia con su propia clave.
  const derived = { segment_number: 5, minute_start: 62, derived: true };
  assert.equal(segmentProposalHint(derived), 'derived');
  assert.equal(SEGMENT_PROPOSAL_HINT_LABEL_KEYS.derived, 'match.segmentProposalDerived');
  assert.equal(segmentProposalHint(null), null);
});

// ---------------------------------------------------------------------------
// Cierre del acta: códigos aditivos (RF-006)
// ---------------------------------------------------------------------------

test('classifies the four close codes and keeps a generic message for an unknown one', () => {
  assert.equal(DOUBLE_YELLOW_INCONSISTENT_CODE, 'DOUBLE_YELLOW_INCONSISTENT');
  assert.equal(ASSIST_PLAYER_INVALID_CODE, 'ASSIST_PLAYER_INVALID');

  const causes = {
    'double_yellow_inconsistent': {
      status: 409,
      data: { detail: 'Roja por doble amarilla incoherente en el minuto 61.', code: DOUBLE_YELLOW_INCONSISTENT_CODE },
    },
    'assist_player_invalid': {
      status: 409,
      data: { detail: 'El asistente no está en la plantilla del partido.', code: ASSIST_PLAYER_INVALID_CODE },
    },
    'resolution_not_enabled': {
      status: 409,
      data: { detail: 'La resolución no está habilitada.', code: RESOLUTION_NOT_ENABLED_CODE },
    },
    'roster_size_out_of_range': {
      status: 409,
      data: { detail: 'Plantilla fuera de rango.', code: ROSTER_SIZE_OUT_OF_RANGE_CODE },
    },
  } as const;

  for (const [kind, cause] of Object.entries(causes)) {
    assert.equal(classifyCloseConflict(cause), kind);
    // El clasificador es el mismo que usa el resto de la operación.
    assert.equal(classifyMatchConflict(cause), kind);
  }

  // Mensaje de producto por código: la doble amarilla y la resolución tienen
  // texto propio; el asistente y la plantilla conservan el `detail` del
  // servidor, que es más específico que cualquier texto genérico.
  assert.equal(closeConflictMessageKey('double_yellow_inconsistent'), 'match.doubleYellowInconsistent');
  assert.equal(closeConflictMessageKey('resolution_not_enabled'), 'match.resolutionNotEnabled');
  assert.equal(closeConflictMessageKey('assist_player_invalid'), null);
  assert.equal(closeConflictMessageKey('roster_size_out_of_range'), null);
  assert.equal(closeConflictMessageKey('other'), 'match.noClose');

  // Un 409 sin `code`, con otro código o en otro estado no se confunde.
  assert.equal(classifyCloseConflict({ status: 409, data: { detail: 'Conflicto' } }), 'other');
  assert.equal(classifyCloseConflict({ status: 409, data: { code: 'OTRO' } }), 'other');
  assert.equal(classifyCloseConflict({ status: 409, data: { code: 12 } }), 'other');
  assert.equal(classifyCloseConflict(null), 'other');
  assert.equal(classifyCloseConflict(undefined), 'other');

  // Las claves de producto son las del catálogo, no literales del mensaje.
  assert.equal(CLOSE_CONFLICT_MESSAGE_LABEL_KEYS.double_yellow_inconsistent, 'match.doubleYellowInconsistent');
  assert.equal(CLOSE_CONFLICT_MESSAGE_LABEL_KEYS.other, 'match.noClose');
});

// ---------------------------------------------------------------------------
// Pureza y determinismo
// ---------------------------------------------------------------------------

test('is deterministic and does not mutate its inputs', () => {
  const current: SegmentFormState = Object.freeze({
    segment_number: 2,
    minute_start: 41,
    minuteDirty: false,
  });
  const proposal = Object.freeze({ segment_number: 3, minute_start: 41, derived: true });

  const first = applySegmentProposal(current, proposal);
  const second = applySegmentProposal(current, proposal);
  assert.deepEqual(first, second);
  assert.deepEqual(first, { segment_number: 3, minute_start: 41, minuteDirty: false });
  assert.deepEqual(proposal, { segment_number: 3, minute_start: 41, derived: true });
  assert.deepEqual(current, { segment_number: 2, minute_start: 41, minuteDirty: false });

  // La misma causa desconocida se clasifica igual en cada llamada.
  assert.equal(classifyCloseConflict({ status: 409, data: { code: 'X' } }), classifyCloseConflict({ status: 409, data: { code: 'X' } }));
});

test('does not read the clock, the network or the storage', () => {
  for (const pattern of [
    /Date\.now/,
    /new Date\(/,
    /Math\.random/,
    /\$fetch/,
    /useApi/,
    /localStorage/,
    /sessionStorage/,
  ]) {
    assert.doesNotMatch(UTILS_SOURCE, pattern);
  }

  for (const exported of [
    'parseSegmentProposal',
    'applySegmentProposal',
    'segmentProposalHint',
    'shouldPrefillMinute',
    'forceMinuteOnRefresh',
    'classifyCloseConflict',
    'closeConflictMessageKey',
  ]) {
    assert.match(UTILS_SOURCE, new RegExp(`export function ${exported}\\(`));
  }
});
