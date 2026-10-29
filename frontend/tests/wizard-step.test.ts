import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  createWizardDraftStore,
  draftForStep,
  draftKey,
  parseDraft,
  serializeDraft,
  type WizardDraftContext,
  type WizardStorage,
} from '../app/utils/wizardDraft.ts';
import {
  NAVIGATION_RULES,
  defaultStepId,
  entryStepWrite,
  namesWizardStep,
  requestedStep,
  resolveNavigation,
  shouldConfirmNavigation,
  stepBlock,
  stepChangeWrite,
  stepFromAddress,
  stepFromLocation,
  stepUrl,
  type NavigationKind,
} from '../app/utils/wizardStep.ts';
import { wizardSteps, type WizardKind, type WizardStepId, type WizardValues } from '../app/utils/wizardModel.ts';

const LOCATION = '/workspace/tournaments/t1#configuracion';
const CONTEXT: WizardDraftContext = {
  wizard: 'rules',
  userId: 'user-1',
  organizationId: 'org-1',
  tournamentId: 'tournament-1',
  versionId: 'version-1',
};

function stepIds(wizard: WizardKind): WizardStepId[] {
  return wizardSteps(wizard, (key) => key).map((step) => step.id);
}

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
  return { data, storage: storage satisfies WizardStorage };
}

// RF-013: sin `?step=` el asistente abre en su primer paso.
test('opens the first step when the address has no step', () => {
  assert.equal(defaultStepId('rules'), 'rules.scoring');
  assert.equal(defaultStepId('phases'), 'phases.identity');
  assert.equal(defaultStepId('teams'), 'teams.entry');

  for (const location of [
    LOCATION,
    '/workspace/tournaments/t1',
    '/workspace/tournaments/t1?step=',
    '/workspace/tournaments/t1?step=%20%20',
  ]) {
    assert.equal(stepFromAddress('rules', location), 'rules.scoring', location);
    assert.equal(stepFromAddress('phases', location), 'phases.identity', location);
    assert.equal(stepFromAddress('teams', location), 'teams.entry', location);
  }

  assert.equal(requestedStep('rules', null), null);
  assert.equal(stepFromLocation(LOCATION), null);
});

// RF-013/RF-015: un paso desconocido o de otro asistente no se acepta; se vuelve
// al paso por defecto y nunca se inventa otro.
test('ignores an unknown, empty or foreign step', () => {
  for (const raw of ['nope', 'rules.unknown', 'phases.identity', 'wizard.rules.scoring', '0']) {
    assert.equal(requestedStep('rules', raw), null, raw);
    assert.equal(stepFromAddress('rules', `/workspace/tournaments/t1?step=${raw}`), 'rules.scoring', raw);
  }
  assert.equal(stepFromAddress('phases', '/workspace/tournaments/t1?step=rules.scoring'), 'phases.identity');
  assert.equal(requestedStep('teams', 'teams.unknown'), null);
});

// RF-013: el valor llega de la dirección con espacios accidentales y sigue siendo el mismo paso.
test('trims the step read from the address', () => {
  assert.equal(requestedStep('rules', ' rules.scoring '), 'rules.scoring');
  assert.equal(stepFromAddress('rules', '/workspace/tournaments/t1?step=%20rules.scoring%20'), 'rules.scoring');
  assert.equal(stepFromLocation('/workspace/tournaments/t1?step=teams.review'), 'teams.review');
});

// RF-013: el paso válido de un enlace compartido se respeta (sin redirección silenciosa).
test('keeps every valid step of its own assistant', () => {
  for (const wizard of ['rules', 'phases', 'teams'] satisfies WizardKind[]) {
    for (const id of stepIds(wizard)) {
      assert.equal(stepFromAddress(wizard, `/workspace/tournaments/t1?step=${id}`), id, id);
    }
  }

  assert.equal(stepFromLocation('/workspace/tournaments/t1?step=rules.format#configuracion'), 'rules.format');
});

// RF-013: la dirección identifica el paso y nunca contiene valores del formulario.
test('writes the step in the address without touching the rest', () => {
  assert.equal(
    stepUrl('/workspace/tournaments/t1#configuracion', 'rules.format'),
    '/workspace/tournaments/t1?step=rules.format#configuracion',
  );
  assert.equal(
    stepUrl('/workspace/tournaments/t1?step=rules.scoring&stage=s1', 'rules.format'),
    '/workspace/tournaments/t1?step=rules.format&stage=s1',
  );
  assert.equal(
    stepUrl('/workspace/tournaments/t1?stage=s1', 'phases.identity'),
    '/workspace/tournaments/t1?stage=s1&step=phases.identity',
  );
  assert.equal(stepUrl('/workspace/tournaments/t1?step=rules.format', null), '/workspace/tournaments/t1');
  assert.equal(stepUrl('/workspace/tournaments/t1?step=rules.format#x', null), '/workspace/tournaments/t1#x');

  const url = stepUrl('/workspace/tournaments/t1', 'rules.format');
  assert.doesNotMatch(url, /win|gameFormat|scoring/);
});

// RF-013/RF-015: un enlace directo a un paso válido se respeta, también sin
// borrador, y un borrador con solo paso no aporta valores: mandan los del
// servidor.
test('respects a shared step and takes the values from the server', () => {
  assert.equal(stepFromAddress('rules', '/workspace/tournaments/t1?step=rules.format'), 'rules.format');
  assert.equal(stepFromAddress('teams', '/workspace/tournaments/t1?step=teams.review'), 'teams.review');

  const { storage } = memoryStorage();
  createWizardDraftStore(CONTEXT, storage).save(draftForStep('rules.discipline', { gameFormat: '11v11' }, false));
  const draft = createWizardDraftStore(CONTEXT, storage).read();

  // La dirección pedida manda sobre el paso del borrador.
  assert.equal(
    stepFromAddress('rules', '/workspace/tournaments/t1?step=rules.format', draft?.step ?? defaultStepId('rules')),
    'rules.format',
  );
  // Sin dirección, el borrador solo aporta el paso; no lleva valores.
  assert.equal(stepFromAddress('rules', LOCATION, draft?.step ?? defaultStepId('rules')), 'rules.discipline');
  assert.equal(draft?.values, null);
});

// RF-015: la composición de una fase sin fase se muestra bloqueada con enlace
// al paso que aporta el dato; la dirección pedida se respeta.
test('blocks the phase composition without a phase and links to its identity', () => {
  const block = stepBlock('phases.composition', { stageId: null });
  assert.ok(block);
  assert.equal(block.missing, 'stageId');
  assert.equal(block.provider, 'phases.identity');
  assert.equal(block.messageKey, 'wizard.step.blockedPhase');
  assert.equal(block.actionKey, 'wizard.step.blockedPhaseAction');

  assert.equal(stepBlock('phases.composition', { stageId: 'stage-1' }), null);
  assert.equal(stepBlock('phases.identity', {}), null);
  assert.equal(stepBlock('rules.substitutions', {}), null);
  // El paso pedido se mantiene: el enlace se ofrece, no se aplica solo.
  assert.equal(
    stepFromAddress('phases', '/workspace/tournaments/t1?step=phases.composition'),
    'phases.composition',
  );
});

// RF-014/WP-1: la clave asocia usuario, organización, torneo, versión y asistente.
test('keys the draft by user, organization, tournament, version and assistant', () => {
  assert.equal(draftKey(CONTEXT), 'bc_wizard:rules:user-1:org-1:tournament-1:version-1');
  assert.equal(draftKey({ ...CONTEXT, wizard: 'teams' }), 'bc_wizard:teams:user-1:org-1:tournament-1:version-1');
  assert.notEqual(draftKey({ ...CONTEXT, versionId: 'version-2' }), draftKey(CONTEXT));
  assert.notEqual(draftKey({ ...CONTEXT, tournamentId: 'tournament-2' }), draftKey(CONTEXT));
  assert.notEqual(draftKey({ ...CONTEXT, organizationId: 'org-2' }), draftKey(CONTEXT));
  assert.notEqual(draftKey({ ...CONTEXT, userId: 'user-2' }), draftKey(CONTEXT));
});

// RF-014: sin algún identificador no se persiste nada.
test('keeps no draft without every identifier', () => {
  const missing: Array<keyof WizardDraftContext> = ['userId', 'organizationId', 'tournamentId', 'versionId'];

  for (const field of missing) {
    assert.equal(draftKey({ ...CONTEXT, [field]: null }), null, field);
    assert.equal(draftKey({ ...CONTEXT, [field]: undefined }), null, field);
    assert.equal(draftKey({ ...CONTEXT, [field]: '   ' }), null, field);
  }

  const { storage, data } = memoryStorage();
  const store = createWizardDraftStore({ ...CONTEXT, versionId: null }, storage);
  assert.equal(store.key, null);
  assert.equal(store.available, false);
  assert.equal(store.save({ step: 'rules.scoring', values: { scoring: {} } }), false);
  assert.equal(store.read(), null);
  assert.equal(data.size, 0);
});

// RF-014: los identificadores no pueden colisionar entre contextos.
test('never mixes two contexts through the separator or blank space', () => {
  assert.equal(draftKey({ ...CONTEXT, userId: 'user:1' }), null);
  assert.equal(draftKey({ ...CONTEXT, tournamentId: 'tournament 1' }), null);
});

// RF-004/RF-014: recargar conserva el paso y todos los valores, también los inválidos.
test('a reload restores the step and every value, invalid ones included', () => {
  const { storage } = memoryStorage();
  const values: WizardValues = {
    scoring: { win: 3, loss: 'not-a-number' },
    tiebreakers: [],
    gameFormat: '7v7',
  };

  createWizardDraftStore(CONTEXT, storage).save(draftForStep('rules.discipline', values, true));

  const draft = createWizardDraftStore(CONTEXT, storage).read();
  assert.deepEqual(draft, { step: 'rules.discipline', values });
  assert.equal(
    stepFromAddress('rules', LOCATION, draft?.step ?? defaultStepId('rules')),
    'rules.discipline',
  );
  assert.deepEqual(draft?.values, values);
});

// RF-013: la dirección manda sobre el paso guardado; el borrador sigue aportando los valores.
test('the address wins over the stored step and the draft keeps the values', () => {
  const { storage } = memoryStorage();
  const values = { scoring: { win: 3 } };
  createWizardDraftStore(CONTEXT, storage).save(draftForStep('rules.discipline', values, true));

  const draft = createWizardDraftStore(CONTEXT, storage).read();
  assert.equal(
    stepFromAddress('rules', '/workspace/tournaments/t1?step=rules.scoring', draft?.step ?? defaultStepId('rules')),
    'rules.scoring',
  );
  assert.deepEqual(draft?.values, values);
});

// RF-014: otra pestaña no comparte el borrador; la versión y el torneo tampoco.
test('another tab, version or tournament never applies the draft', () => {
  const tabA = memoryStorage();
  createWizardDraftStore(CONTEXT, tabA.storage).save(draftForStep('rules.format', { gameFormat: '7v7' }, true));

  const otherTab = memoryStorage();
  assert.equal(createWizardDraftStore(CONTEXT, otherTab.storage).read(), null);

  assert.equal(createWizardDraftStore({ ...CONTEXT, versionId: 'version-2' }, tabA.storage).read(), null);
  assert.equal(createWizardDraftStore({ ...CONTEXT, tournamentId: 'tournament-2' }, tabA.storage).read(), null);
  assert.equal(createWizardDraftStore({ ...CONTEXT, organizationId: 'org-2' }, tabA.storage).read(), null);

  // Sin borrador aplicable se abre en el primer paso, no en el de la otra pestaña.
  assert.equal(stepFromAddress('rules', LOCATION), 'rules.scoring');
});

// RF-014/RF-008: descartar borra el borrador de la pestaña y vuelve a lo guardado.
test('clearing the draft removes only its own key', () => {
  const { storage, data } = memoryStorage();
  createWizardDraftStore(CONTEXT, storage).save({ step: 'rules.format', values: { gameFormat: '7v7' } });
  createWizardDraftStore({ ...CONTEXT, wizard: 'teams' }, storage).save({ step: 'teams.details', values: {} });

  const store = createWizardDraftStore(CONTEXT, storage);
  assert.equal(store.clear(), true);
  assert.equal(store.read(), null);
  assert.equal(data.size, 1);
  assert.deepEqual(createWizardDraftStore({ ...CONTEXT, wizard: 'teams' }, storage).read(), {
    step: 'teams.details',
    values: {},
  });
});

// RF-014: un borrador ilegible o de otro formato nunca se aplica.
test('ignores a corrupt, foreign or unknown-version draft', () => {
  assert.equal(parseDraft('rules', null), null);
  assert.equal(parseDraft('rules', ''), null);
  assert.equal(parseDraft('rules', '{'), null);
  assert.equal(parseDraft('rules', '[]'), null);
  assert.equal(parseDraft('rules', '{"v":2,"step":"rules.scoring","values":{}}'), null);
  assert.equal(parseDraft('rules', '{"v":1,"step":"rules.scoring","values":"nope"}'), null);

  const unknownStep = parseDraft('rules', serializeDraft({ step: 'phases.review' as WizardStepId, values: { scoring: {} } }));
  assert.deepEqual(unknownStep, { step: null, values: { scoring: {} } });
});

// RF-008: solo el descarte explícito y el cambio de versión o torneo piden confirmación.
test('only an explicit discard or a version or tournament change asks for confirmation', () => {
  for (const kind of ['step', 'section', 'back', 'reload', 'close'] satisfies NavigationKind[]) {
    assert.equal(shouldConfirmNavigation(kind, true), false, kind);
    assert.equal(shouldConfirmNavigation(kind, false), false, kind);
  }
  for (const kind of ['discard', 'version', 'tournament'] satisfies NavigationKind[]) {
    assert.equal(shouldConfirmNavigation(kind, true), true, kind);
    assert.equal(shouldConfirmNavigation(kind, false), false, kind);
  }
});

// RF-008: cambiar de versión o de torneo descarta el borrador solo si el
// usuario acepta la confirmación; cancelar no toca nada.
test('a version or tournament change discards the draft only when accepted', () => {
  for (const kind of ['version', 'tournament'] satisfies NavigationKind[]) {
    assert.deepEqual(resolveNavigation(kind, true, false), {
      proceed: false,
      discardDraft: false,
    }, `${kind} without acceptance must keep the assistant as it is`);

    assert.deepEqual(resolveNavigation(kind, true, true), {
      proceed: true,
      discardDraft: true,
    }, `${kind} accepted must drop the draft of the old version`);

    assert.deepEqual(resolveNavigation(kind, false, false), {
      proceed: true,
      discardDraft: true,
    }, `${kind} without changes asks nothing`);
  }
});

// RF-008: recargar, cambiar de paso, de sección o usar atrás no piden
// confirmación y conservan el borrador; el descarte explícito sí pregunta.
test('navigations that keep the draft never ask, and the explicit discard asks', () => {
  for (const kind of ['step', 'section', 'back', 'reload'] satisfies NavigationKind[]) {
    assert.deepEqual(resolveNavigation(kind, true, false), {
      proceed: true,
      discardDraft: false,
    }, kind);
  }

  assert.deepEqual(resolveNavigation('discard', true, false), {
    proceed: false,
    discardDraft: false,
  });
  assert.deepEqual(resolveNavigation('discard', true, true), {
    proceed: true,
    discardDraft: true,
  });
  assert.deepEqual(resolveNavigation('discard', false, false), {
    proceed: true,
    discardDraft: true,
  });
});

test('declares the navigation table of the spec in one place', () => {
  assert.deepEqual(
    NAVIGATION_RULES.map((rule) => [rule.kind, rule.confirms, rule.keepsDraft]),
    [
      ['step', false, true],
      ['section', false, true],
      ['back', false, true],
      ['reload', false, true],
      ['close', false, false],
      ['discard', true, false],
      ['version', true, false],
      ['tournament', true, false],
    ],
  );
});

// RF-004/RF-014: recorrer todos los pasos de ida y vuelta conserva cada valor,
// válido o no: el borrador guarda los mismos valores con el paso nuevo.
test('walking every step forward and back keeps every value', () => {
  const values: WizardValues = {
    scoring: { win: 3, loss: 'not-a-number' },
    tiebreakers: ['goal_difference', ''],
    discipline: {},
    resolution: { allow_extra_time: true },
    gameFormat: '11v11',
    substitutions: { max_per_team: 99 },
  };
  const { storage } = memoryStorage();
  const store = createWizardDraftStore(CONTEXT, storage);

  const ids = stepIds('rules');
  for (const id of ids) {
    assert.equal(store.save(draftForStep(id, values, true)), true);
    const draft = store.read();
    assert.equal(draft?.step, id);
    assert.deepEqual(draft?.values, values);
  }
  for (const id of [...ids].reverse()) {
    assert.equal(store.save(draftForStep(id, values, true)), true);
    assert.deepEqual(store.read()?.values, values);
  }
});

// RF-013/RF-019: cada cambio de paso apila una sola entrada de historial con el
// paso pedido y nunca con valores del formulario; atrás recorre los pasos.
test('every step change pushes one address without form values', () => {
  const { router, apply } = createRouterDouble(['/workspace', LOCATION]);
  apply(entryStepWrite(router.current, stepFromAddress('rules', router.current)));

  const ids = stepIds('rules');
  let current = stepFromAddress('rules', router.current);
  for (const id of ids.slice(1)) {
    apply(stepChangeWrite(router.current, current, id));
    assert.equal(stepFromLocation(router.current), id);
    assert.equal(router.stack.length, 2 + ids.indexOf(id));
    assert.doesNotMatch(router.current, /win=|gameFormat=|scoring=/);
    current = id;
  }

  for (let index = ids.length - 2; index >= 0; index -= 1) {
    const previousLocation = router.back();
    assert.ok(previousLocation, `step ${index} must be reachable with back`);
    assert.equal(stepFromLocation(previousLocation), ids[index]);
  }
  assert.equal(router.back(), '/workspace');
});

// RF-014: sin cambios se recuerda solo el paso y no se guardan valores.
test('remembers the last visited step without changes and stores only the step', () => {
  const { storage, data } = memoryStorage();
  const store = createWizardDraftStore(CONTEXT, storage);

  const stepOnly = draftForStep('rules.discipline', { gameFormat: '11v11' }, false);
  assert.deepEqual(stepOnly, { step: 'rules.discipline', values: null });
  assert.equal(store.save(stepOnly), true);
  assert.deepEqual(store.read(), { step: 'rules.discipline', values: null });

  // Volver de otra sección sin `?step=`: el último paso visitado.
  const draft = store.read();
  assert.equal(stepFromAddress('rules', LOCATION, draft?.step ?? defaultStepId('rules')), 'rules.discipline');
  // Recargar (misma pestaña, mismo borrador) lo conserva.
  const reloaded = createWizardDraftStore(CONTEXT, storage).read();
  assert.equal(stepFromAddress('rules', LOCATION, reloaded?.step ?? defaultStepId('rules')), 'rules.discipline');

  // No se persiste ningún valor, ni vacío.
  assert.equal(data.size, 1);
  assert.equal(storage.getItem(store.key ?? '')?.includes('values'), false);
  assert.deepEqual(draftForStep('rules.discipline', {}, true), { step: 'rules.discipline', values: null });
});

// RF-014: con cambios se guardan el paso y todos los valores.
test('keeps the step and the values when there are changes', () => {
  const values: WizardValues = { scoring: { win: 3 }, gameFormat: '7v7' };
  const withChanges = draftForStep('rules.format', values, true);
  assert.deepEqual(withChanges, { step: 'rules.format', values });

  const { storage } = memoryStorage();
  createWizardDraftStore(CONTEXT, storage).save(withChanges);
  const draft = createWizardDraftStore(CONTEXT, storage).read();
  assert.deepEqual(draft, { step: 'rules.format', values });
  assert.equal(stepFromAddress('rules', LOCATION, draft?.step ?? defaultStepId('rules')), 'rules.format');
});

// RF-013/RF-019: la dirección es la **única** fuente del paso. Una dirección
// sin `?step=`, con un valor desconocido o con el paso de otro asistente se
// resuelve con el paso de entrada; el paso del propio asistente se respeta.
test('derives the step of the assistant from the address only', () => {
  // Lo que la dirección nombra: cualquier paso de los tres asistentes.
  assert.equal(namesWizardStep(LOCATION), false);
  assert.equal(namesWizardStep('/workspace/tournaments/t1?step=rules.format'), true);
  assert.equal(namesWizardStep('/workspace/tournaments/t1?step=teams.review'), true);
  assert.equal(namesWizardStep('/workspace/tournaments/t1?step=nope'), false);
  assert.equal(namesWizardStep('/workspace/tournaments/t1?step='), false);

  // Sin paso, con un paso inválido o con el de otro asistente: paso de entrada.
  for (const location of [
    LOCATION,
    '/workspace/tournaments/t1?step=nope',
    '/workspace/tournaments/t1?step=teams.review',
    '/workspace/tournaments/t1?step=phases.identity#configuracion',
  ]) {
    assert.equal(stepFromAddress('rules', location), 'rules.scoring', location);
  }
  // El paso de entrada de una fase existente es su composición (RF-002).
  assert.equal(stepFromAddress('phases', LOCATION), 'phases.identity');
  assert.equal(stepFromAddress('phases', LOCATION, 'phases.composition'), 'phases.composition');
  assert.equal(stepFromAddress('phases', `${LOCATION}?step=rules.scoring`, 'phases.composition'), 'phases.composition');

  // Un enlace directo manda: el paso pedido se respeta.
  assert.equal(
    stepFromAddress('rules', '/workspace/tournaments/t1?step=rules.discipline#configuracion'),
    'rules.discipline',
  );
  assert.equal(
    stepFromAddress('phases', '/workspace/tournaments/t1?step=phases.composition'),
    'phases.composition',
  );
});

/**
 * Doble del router sobre una pila de historial: `replace` corrige la entrada
 * vigente y `push` apila una nueva. Modela lo que hace el navegador con atrás.
 */
function createRouterDouble(initialStack: readonly string[]) {
  const stack = [...initialStack];
  let position = stack.length - 1;
  const router = {
    get current(): string {
      return stack[position] ?? '';
    },
    get stack(): readonly string[] {
      return [...stack];
    },
    replace(url: string): void {
      stack[position] = url;
    },
    push(url: string): void {
      stack.splice(position + 1);
      stack.push(url);
      position = stack.length - 1;
    },
    back(): string | null {
      if (position === 0) return null;
      position -= 1;
      return stack[position] ?? null;
    },
  };
  function apply(write: ReturnType<typeof entryStepWrite>): void {
    if (!write) return;
    if (write.mode === 'replace') router.replace(write.url);
    else router.push(write.url);
  }
  return { router, apply };
}

// RF-013/RF-019: la entrada se normaliza con el router (`replace`, sin añadir
// historial) y cada cambio de paso del usuario apila una entrada con `push`.
// Consecuencia: un atrás vuelve al paso anterior —la dirección lo nombra— y el
// segundo atrás sale del asistente.
test('normalizes the entry with the router and pushes one entry per step change', () => {
  const { router, apply } = createRouterDouble(['/workspace', LOCATION]);

  // Entrada del asistente: la dirección no nombra ningún paso.
  apply(entryStepWrite(router.current, stepFromAddress('rules', router.current)));
  assert.deepEqual(router.stack, [
    '/workspace',
    '/workspace/tournaments/t1?step=rules.scoring#configuracion',
  ]);

  // Un movimiento del usuario: una sola entrada nueva.
  apply(stepChangeWrite(router.current, 'rules.scoring', 'rules.tiebreakers'));
  assert.deepEqual(router.stack, [
    '/workspace',
    '/workspace/tournaments/t1?step=rules.scoring#configuracion',
    '/workspace/tournaments/t1?step=rules.tiebreakers#configuracion',
  ]);

  // Atrás: la entrada anterior nombra el paso anterior, así que se muestra.
  const previousLocation = router.back();
  assert.ok(previousLocation);
  assert.equal(stepFromAddress('rules', previousLocation), 'rules.scoring');

  // Segundo atrás: se sale del asistente, no a otro paso intermedio.
  assert.equal(router.back(), '/workspace');
});

// RF-013: una dirección que ya nombra un paso no se reescribe al abrir, y
// volver al paso vigente desde el de otro asistente corrige la entrada sin
// apilar historial.
test('never rewrites an address that already names a step', () => {
  const direct = '/workspace/tournaments/t1?step=rules.format&stage=s1#configuracion';
  assert.equal(entryStepWrite(direct, 'rules.format'), null);
  // Un paso de otro asistente no se pisa al abrir.
  assert.equal(entryStepWrite('/workspace/tournaments/t1?step=teams.review', 'rules.scoring'), null);
  // Sin paso o con un paso desconocido, la entrada se normaliza.
  assert.deepEqual(entryStepWrite(LOCATION, 'rules.scoring'), {
    mode: 'replace',
    url: '/workspace/tournaments/t1?step=rules.scoring#configuracion',
  });
  assert.deepEqual(entryStepWrite('/workspace/tournaments/t1?step=nope#x', 'rules.format'), {
    mode: 'replace',
    url: '/workspace/tournaments/t1?step=rules.format#x',
  });

  // Cambiar de paso: siempre una entrada.
  assert.deepEqual(stepChangeWrite(direct, 'rules.format', 'rules.substitutions'), {
    mode: 'push',
    url: '/workspace/tournaments/t1?step=rules.substitutions&stage=s1#configuracion',
  });
  // Volver al paso vigente no escribe nada si la dirección ya lo nombra.
  assert.equal(stepChangeWrite(direct, 'rules.format', 'rules.format'), null);
  // Si la dirección nombraba otro asistente, se corrige sin apilar.
  assert.deepEqual(
    stepChangeWrite('/workspace/tournaments/t1?step=teams.review#configuracion', 'rules.format', 'rules.format'),
    { mode: 'replace', url: '/workspace/tournaments/t1?step=rules.format#configuracion' },
  );
});

const stepComposable = readFileSync(new URL('../app/composables/useWizardStep.ts', import.meta.url), 'utf8');
const draftComposable = readFileSync(new URL('../app/composables/useWizardDraft.ts', import.meta.url), 'utf8');
const draftModel = readFileSync(new URL('../app/utils/wizardDraft.ts', import.meta.url), 'utf8');

// RF-013/RF-019: el paso se deriva de la dirección, la entrada se normaliza con
// `router.replace` y cada cambio de paso se apila con `router.push`. No hay
// estado interno del paso, ni `history.replaceState`, ni vigilante que reescriba
// el paso: una dirección sin `?step=` vuelve al paso de entrada.
test('the step composable derives the step from the address and writes with the router', () => {
  assert.match(stepComposable, /const step = computed/);
  assert.match(stepComposable, /stepFromAddress\(/);
  assert.match(stepComposable, /entryStepWrite\(/);
  assert.match(stepComposable, /stepChangeWrite\(/);
  assert.match(stepComposable, /router\.replace\(/);
  assert.match(stepComposable, /router\.push\(/);
  assert.match(stepComposable, /onMounted\(/);
  assert.doesNotMatch(stepComposable, /window\.history/);
  assert.doesNotMatch(stepComposable, /stepHistoryWrites/);
  assert.doesNotMatch(stepComposable, /useApi/);
  assert.doesNotMatch(stepComposable, /\$fetch/);
  assert.doesNotMatch(stepComposable, /sessionStorage|localStorage/);
});

const configurationPageSource = readFileSync(
  new URL('../app/pages/workspace/tournaments/[id]/index.vue', import.meta.url),
  'utf8',
);
const rulesWizardSource = readFileSync(
  new URL('../app/components/rules/RulesWizard.vue', import.meta.url),
  'utf8',
);
const phasesWizardSource = readFileSync(
  new URL('../app/components/StageTeamsWizard.vue', import.meta.url),
  'utf8',
);
const teamsWizardSource = readFileSync(
  new URL('../app/components/TeamsWizard.vue', import.meta.url),
  'utf8',
);

// RF-014: los tres asistentes guardan el borrador con `draftForStep` —sin
// cambios, solo el paso— y un borrador con solo paso nunca sustituye los
// valores del servidor.
test('the assistants remember the step and ignore a step-only draft when restoring values', () => {
  for (const [name, source] of [
    ['rules', rulesWizardSource],
    ['phases', phasesWizardSource],
    ['teams', teamsWizardSource],
  ] as const) {
    assert.match(source, /draftForStep\(/, `${name} must persist the step without changes`);
    assert.match(source, /!stored\.values/, `${name} must not apply values of a step-only draft`);
    // Sin cambios no se borra el borrador: se recuerda el paso.
    assert.doesNotMatch(source, /if \(!dirty\.value\) \{\s*draft\.clear\(\);/, name);
    assert.doesNotMatch(source, /if \(!hasChanges\(\)\) \{\s*draft\.clear\(\);/, name);
  }
});

// C-2: el modelo del paso no conserva estado de sesión ni un resolutor de
// apertura; solo las funciones puras que usan la dirección y el composable.
test('the step model has no session state left', () => {
  const source = readFileSync(new URL('../app/utils/wizardStep.ts', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /createWizardSession|resolveWizardStart|parseStep|WizardSession|WizardStart|WizardApi/);
});

// RF-008: el cambio de versión y de torneo se intercepta con la misma tabla de
// navegaciones; si el usuario cancela, la versión y el borrador no cambian.
test('the configuration page confirms version and tournament changes with the shared table', () => {
  assert.match(configurationPageSource, /resolveNavigation\('version'/);
  assert.match(configurationPageSource, /resolveNavigation\('tournament'/);
  assert.match(configurationPageSource, /wizard\.navigation\.confirmVersion/);
  assert.match(configurationPageSource, /wizard\.navigation\.confirmTournament/);
  // El selector no cambia de versión por sí solo: la navegación decide antes.
  assert.doesNotMatch(
    configurationPageSource,
    /<select v-model="selectedVersionId">/,
    'the version selector must confirm before switching',
  );
  assert.match(configurationPageSource, /discardDraft\(/);
  assert.match(configurationPageSource, /:reset-token="wizardResetToken"/);
});

// RF-008: los tres asistentes ofrecen «Descartar cambios» con confirmación y
// vuelven a los valores del servidor por la misma tabla de navegaciones.
test('every assistant offers an explicit discard that restores the server values', () => {
  for (const [name, source] of [
    ['rules', rulesWizardSource],
    ['phases', phasesWizardSource],
    ['teams', teamsWizardSource],
  ] as const) {
    assert.match(source, /resolveNavigation\('discard'/, `${name} must use the shared table`);
    assert.match(source, /wizard\.navigation\.discard/, `${name} needs the discard label`);
    assert.match(source, /wizard\.navigation\.confirmDiscard/, `${name} needs the confirmation`);
    assert.match(source, /resetToken/, `${name} must reset when the version is discarded`);
    assert.match(source, /dirty-change/, `${name} must report unsaved changes to the page`);
  }
});

// WP-1/RNF-011: el borrador de los asistentes vive solo en la sesión de la pestaña.
test('the assistant draft lives in session storage only', () => {
  for (const source of [draftComposable, draftModel]) {
    assert.doesNotMatch(source, /localStorage/);
    assert.doesNotMatch(source, /\$fetch|useApi/);
  }
  assert.match(draftComposable, /sessionStorage/);
  assert.match(draftComposable, /import\.meta\.client/);
  // Plan §11: el borrador se aplica después de montar, nunca en el primer render.
  assert.match(draftComposable, /onMounted\(/);
});
