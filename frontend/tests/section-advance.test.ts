import assert from 'node:assert/strict';
import test from 'node:test';

import {
  advanceAfterSave,
  advanceTarget,
  clearsPendingAdvance,
  resolveNotice,
  type AdvanceDecision,
  type AdvanceTarget,
  type ConfigurationSection,
} from '../app/utils/sectionAdvance.ts';
import { phasesAssistantHref } from '../app/utils/teamsWizard.ts';

const TOURNAMENT_ID = '8f2b7c40-2a5e-4a53-9f5c-6d0f1a2b3c4d';
const OTHER_TOURNAMENT_ID = '1d9e3a75-6c48-4b02-8e7f-05a4c2b19d3e';

/** La cadena completa, con el calendario como final (ORD-4, RF-001, RF-003). */
const SECTIONS: readonly ConfigurationSection[] = ['rules', 'teams', 'stages', 'calendar'];

function targetOf(section: ConfigurationSection, tournamentId = TOURNAMENT_ID): AdvanceTarget {
  const target = advanceTarget(section, tournamentId);
  if (target === null) {
    assert.fail(`the ${section} section must have a destination`);
  }
  return target;
}

function expectNavigate(decision: AdvanceDecision): AdvanceTarget {
  if (decision.kind !== 'navigate') {
    assert.fail(`expected a navigation, got ${decision.kind}`);
  }
  return decision.target;
}

function expectWait(decision: AdvanceDecision): Extract<AdvanceDecision, { kind: 'wait' }> {
  if (decision.kind !== 'wait') {
    assert.fail(`expected an armed jump waiting for the notice, got ${decision.kind}`);
  }
  return decision;
}

/** Dirección completa de un destino, tal como la compone la página (RF-007). */
function hrefOf(target: AdvanceTarget): string {
  return `${target.path}${target.hash ?? ''}`;
}

// RF-001, RF-007: Reglas → Equipos, con el ancla existente y la consulta conservada.
test('sends rules to the teams section keeping the current query', () => {
  const target = targetOf('rules');

  assert.equal(target.path, `/workspace/tournaments/${TOURNAMENT_ID}`);
  assert.equal(target.hash, '#equipos');
  // RF-007: la página compone el destino con la consulta actual, así que el
  // `?step=` presente no se añade ni se retira.
  assert.equal(target.keepQuery, true);
  assert.equal(hrefOf(target).includes('?'), false);
});

// RF-002, RF-007, ORD-13: Equipos → Fases es el mismo destino que el enlace de la 025.
test('sends teams to the phases block and matches the cross link of spec 025', () => {
  const target = targetOf('teams');

  assert.equal(target.path, `/workspace/tournaments/${TOURNAMENT_ID}`);
  assert.equal(target.hash, '#fases');
  assert.equal(target.keepQuery, true);

  // Una sola definición del destino: el salto y el enlace cruzado no divergen.
  assert.equal(phasesAssistantHref(TOURNAMENT_ID), `/workspace/tournaments/${TOURNAMENT_ID}#fases`);
  assert.equal(hrefOf(target), phasesAssistantHref(TOURNAMENT_ID));

  // ORD-13: el salto no escribe paso en la dirección ni añade consulta.
  assert.equal(hrefOf(target).includes('?'), false);
  assert.equal(hrefOf(target).includes('step='), false);

  // El destino se construye con el torneo recibido, no con un literal fijo.
  assert.equal(hrefOf(targetOf('teams', OTHER_TOURNAMENT_ID)), phasesAssistantHref(OTHER_TOURNAMENT_ID));
});

// RF-003, RF-007: Fases → Calendario, en su propia ruta y sin consulta ni fragmento.
test('sends stages to the calendar route without query or fragment', () => {
  const target = targetOf('stages');

  assert.equal(target.path, `/workspace/tournaments/${TOURNAMENT_ID}/calendar`);
  assert.equal(target.hash, null);
  assert.equal(target.keepQuery, false);
  assert.equal(target.path.includes('?'), false);
  assert.equal(hrefOf(target).includes('?'), false);

  assert.equal(
    targetOf('stages', OTHER_TOURNAMENT_ID).path,
    `/workspace/tournaments/${OTHER_TOURNAMENT_ID}/calendar`,
  );
});

// RF-003: el calendario es el final de la cadena y no abre otra sección.
test('leaves the calendar without a destination because it ends the chain', () => {
  assert.equal(advanceTarget('calendar', TOURNAMENT_ID), null);
  assert.equal(advanceTarget('calendar', OTHER_TOURNAMENT_ID), null);
});

// RF-001, RF-002, RF-003: un destino por sección y ninguno en el calendario.
test('declares one destination per section and none for the calendar', () => {
  assert.equal(SECTIONS.length, 4);
  assert.deepEqual(
    SECTIONS.map((section) => advanceTarget(section, TOURNAMENT_ID) === null),
    [false, false, false, true],
  );
});

// RF-007: el destino es determinista para la misma sección y el mismo torneo.
test('is deterministic for the same section and tournament', () => {
  for (const section of SECTIONS) {
    assert.deepEqual(
      advanceTarget(section, TOURNAMENT_ID),
      advanceTarget(section, TOURNAMENT_ID),
    );
  }
});

// RF-001 a RF-003: con guardado efectivo y sin aviso, la cadena es inmediata.
test('navigates after an effective save without notice', () => {
  for (const section of ['rules', 'teams', 'stages'] as const) {
    const decision = advanceAfterSave({
      section,
      effective: true,
      notice: false,
      tournamentId: TOURNAMENT_ID,
    });

    assert.deepEqual(expectNavigate(decision), advanceTarget(section, TOURNAMENT_ID));
  }
});

// RF-001, RF-015, ORD-6: con el aviso de minutos la pantalla se queda en Reglas
// y el salto a Equipos queda armado, sin ejecutarse.
test('waits in rules while the minutes notice is visible', () => {
  const decision = advanceAfterSave({
    section: 'rules',
    effective: true,
    notice: true,
    tournamentId: TOURNAMENT_ID,
  });

  assert.equal(decision.kind, 'wait');
  const armed = expectWait(decision);
  assert.deepEqual(armed, { kind: 'wait', target: targetOf('rules') });
  assert.equal(hrefOf(armed.target), `/workspace/tournaments/${TOURNAMENT_ID}#equipos`);
});

// RF-004, ORD-4: el guardado parcial de una fase —fase creada, inscripción
// fallida— no es efectivo y no abre el calendario.
test('stays when the save is partial', () => {
  assert.deepEqual(
    advanceAfterSave({
      section: 'stages',
      effective: false,
      notice: false,
      tournamentId: TOURNAMENT_ID,
    }),
    { kind: 'stay' },
  );
});

// RF-004, RF-016: un guardado fallido no navega y no deja salida armada, ni
// siquiera cuando el cambio de minutos habría dejado aviso.
test('stays when the save fails and leaves no armed jump', () => {
  for (const section of ['rules', 'teams', 'stages'] as const) {
    for (const notice of [false, true]) {
      assert.deepEqual(
        advanceAfterSave({ section, effective: false, notice, tournamentId: TOURNAMENT_ID }),
        { kind: 'stay' },
      );
    }
  }
});

// RF-015, ORD-9: «Continuar» reanuda el salto ya armado sin guardar ni cambiar
// la decisión pendiente (idempotente).
test('resumes the armed jump with continue', () => {
  const decision = advanceAfterSave({
    section: 'rules',
    effective: true,
    notice: true,
    tournamentId: TOURNAMENT_ID,
  });
  const armed = expectWait(decision);

  const continued = resolveNotice(armed, 'continue');

  assert.equal(continued.kind, 'navigate');
  assert.deepEqual(expectNavigate(continued), advanceTarget('rules', TOURNAMENT_ID));
  // La decisión armada no se consume ni se reescribe al resolverla.
  assert.equal(decision.kind, 'wait');
  assert.deepEqual(decision, { kind: 'wait', target: armed.target });
  assert.deepEqual(armed, { kind: 'wait', target: targetOf('rules') });
});

// RF-015, ORD-9: «Quedarme» cancela el salto y deja al usuario en Reglas.
test('cancels the armed jump with stay', () => {
  const decision = advanceAfterSave({
    section: 'rules',
    effective: true,
    notice: true,
    tournamentId: TOURNAMENT_ID,
  });
  const armed = expectWait(decision);

  assert.deepEqual(resolveNotice(armed, 'stay'), { kind: 'stay' });
  assert.deepEqual(decision, { kind: 'wait', target: armed.target });
});

interface PendingAdvanceCase {
  readonly event: Parameters<typeof clearsPendingAdvance>[0];
  readonly clears: boolean;
  readonly reason: string;
}

/**
 * Tabla única de invalidación de RF-016. Ninguno de estos seis sucesos conserva
 * el salto pendiente: los cuatro últimos además lo descartan **sin ejecutarlo**,
 * y la edición y el guardado nuevo lo descartan porque el aviso se recalcula.
 * La pulsación de «Continuar» o «Quedarme» no está en la tabla: su efecto lo
 * decide `resolveNotice`.
 */
const PENDING_ADVANCE_TABLE: readonly PendingAdvanceCase[] = [
  { event: 'edit', clears: true, reason: 'editar una regla oculta el aviso y cancela el salto' },
  { event: 'save', clears: true, reason: 'un guardado nuevo recalcula el aviso desde cero' },
  { event: 'save-failed', clears: true, reason: 'un guardado fallido no deja aviso ni salida armada' },
  { event: 'navigation', clears: true, reason: 'navegar dentro de la página o a otra descarta el salto' },
  { event: 'version-change', clears: true, reason: 'cambiar de versión o de torneo descarta el salto' },
  { event: 'reload', clears: true, reason: 'recargar descarta el salto sin ejecutarlo' },
];

// RF-016: la tabla de invalidación del aviso y de su salto pendiente.
test('discards the pending advance on edit, save, failed save, navigation, version change and reload', () => {
  assert.equal(PENDING_ADVANCE_TABLE.length, 6);
  assert.equal(new Set(PENDING_ADVANCE_TABLE.map((entry) => entry.event)).size, 6);

  for (const { event, clears, reason } of PENDING_ADVANCE_TABLE) {
    assert.equal(clearsPendingAdvance(event), clears, `${event}: ${reason}`);
  }
});

// RF-016: la tabla es determinista y no depende de llamadas previas.
test('answers the invalidation table deterministically', () => {
  for (const { event, clears } of PENDING_ADVANCE_TABLE) {
    assert.equal(clearsPendingAdvance(event), clearsPendingAdvance(event));
  }
});
