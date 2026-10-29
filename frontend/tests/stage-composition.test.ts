import assert from 'node:assert/strict';
import test from 'node:test';

import { compositionMessage, stageComposition } from '../app/utils/stageComposition.ts';
import { MAX_STAGE_TEAMS } from '../app/utils/stageWizard.ts';

function teamIds(count: number, prefix = 'team'): string[] {
  return Array.from({ length: count }, (_, index) => `${prefix}-${index}`);
}

// RF-010: un solo total de equipos distintos entre inscritos y seleccionados.
test('merges assigned and selected team ids without duplicates', () => {
  const composition = stageComposition({
    mode: 'existing',
    assignedTeamIds: ['team-a', 'team-b'],
    selectedTeamIds: ['team-b', 'team-c'],
    loading: false,
  });

  assert.equal(composition.count, 3);
  assert.deepEqual(composition.teamIds, ['team-a', 'team-b', 'team-c']);
  assert.equal(composition.overflows, false);
  assert.equal(composition.visible, true);
});

// RF-010: un equipo ya inscrito vuelve a marcarse y la cifra no lo suma dos veces.
test('counts an already assigned team selected again only once', () => {
  const composition = stageComposition({
    mode: 'existing',
    assignedTeamIds: ['team-a', 'team-b'],
    selectedTeamIds: ['team-a'],
    loading: false,
  });

  assert.equal(composition.count, 2);
  assert.deepEqual(composition.teamIds, ['team-a', 'team-b']);
  assert.equal(composition.overflows, false);
});

// RF-010, RF-014: «5 de 64» con la clave y los parámetros de la cifra normal.
test('shows five of sixty-four teams without overflowing', () => {
  const composition = stageComposition({
    mode: 'create',
    assignedTeamIds: [],
    selectedTeamIds: teamIds(5),
    loading: false,
  });
  const message = compositionMessage(composition);

  assert.equal(MAX_STAGE_TEAMS, 64);
  assert.equal(composition.count, 5);
  assert.equal(composition.overflows, false);
  assert.equal(message.key, 'stage.wizard.teamCount');
  assert.deepEqual(message.params, { count: 5, max: MAX_STAGE_TEAMS });
});

// RF-011: por encima de 64 se muestra el total real, sin recortar la cifra.
test('keeps the real total above sixty-four teams without truncating it', () => {
  const assignedTeamIds = teamIds(60, 'assigned');
  const selectedTeamIds = teamIds(10, 'selected');
  const composition = stageComposition({
    mode: 'existing',
    assignedTeamIds,
    selectedTeamIds,
    loading: false,
  });
  const message = compositionMessage(composition);

  assert.equal(composition.count, 70);
  assert.equal(composition.overflows, true);
  assert.equal(composition.teamIds.length, 70);
  assert.equal(message.key, 'stage.wizard.teamCountOverflow');
  assert.equal(message.params.count, 70);
  assert.equal(message.params.max, undefined);
});

// RF-010, RF-014, ORD-14: en «fase existente» no hay cifra mientras carga la lista.
test('hides the figure in existing mode while the assigned list is loading', () => {
  const composition = stageComposition({
    mode: 'existing',
    assignedTeamIds: ['team-a'],
    selectedTeamIds: ['team-b'],
    loading: true,
  });

  assert.equal(composition.visible, false);
});

// RF-010, RF-014: en el alta no hay inscritos que cargar, así que la cifra se ve.
test('shows the figure in create mode while loading', () => {
  const composition = stageComposition({
    mode: 'create',
    assignedTeamIds: [],
    selectedTeamIds: ['team-a', 'team-b'],
    loading: true,
  });

  assert.equal(composition.visible, true);
  assert.equal(composition.count, 2);
  assert.deepEqual(compositionMessage(composition).params, {
    count: 2,
    max: MAX_STAGE_TEAMS,
  });
});

// RF-014: «0 de 64» en los dos modos cuando no hay inscritos ni seleccionados.
test('shows zero of sixty-four teams with no teams loaded in both modes', () => {
  const existing = stageComposition({
    mode: 'existing',
    assignedTeamIds: [],
    selectedTeamIds: [],
    loading: false,
  });
  const create = stageComposition({
    mode: 'create',
    assignedTeamIds: [],
    selectedTeamIds: [],
    loading: true,
  });

  for (const composition of [existing, create]) {
    assert.equal(composition.visible, true);
    assert.equal(composition.count, 0);
    assert.equal(composition.overflows, false);
    assert.deepEqual(composition.teamIds, []);

    const message = compositionMessage(composition);
    assert.equal(message.key, 'stage.wizard.teamCount');
    assert.deepEqual(message.params, { count: 0, max: MAX_STAGE_TEAMS });
  }
});

// RF-011, ORD-8: 64 conserva el «de 64» y 65 cambia la clave del mensaje.
test('switches the message key above sixty-four teams', () => {
  const atLimit = stageComposition({
    mode: 'existing',
    assignedTeamIds: teamIds(MAX_STAGE_TEAMS),
    selectedTeamIds: [],
    loading: false,
  });
  const aboveLimit = stageComposition({
    mode: 'existing',
    assignedTeamIds: teamIds(MAX_STAGE_TEAMS + 1),
    selectedTeamIds: [],
    loading: false,
  });
  const atLimitMessage = compositionMessage(atLimit);
  const aboveLimitMessage = compositionMessage(aboveLimit);

  assert.equal(atLimit.count, MAX_STAGE_TEAMS);
  assert.equal(atLimit.overflows, false);
  assert.equal(atLimitMessage.key, 'stage.wizard.teamCount');
  assert.equal(atLimitMessage.params.max, MAX_STAGE_TEAMS);

  assert.equal(aboveLimit.count, MAX_STAGE_TEAMS + 1);
  assert.equal(aboveLimit.overflows, true);
  assert.equal(aboveLimitMessage.key, 'stage.wizard.teamCountOverflow');
  assert.equal(aboveLimitMessage.params.count, MAX_STAGE_TEAMS + 1);
  assert.equal(aboveLimitMessage.params.max, undefined);
});

// RNF-006: mismas entradas, mismo resultado, sin efectos sobre la entrada.
test('is deterministic for the same input and leaves it untouched', () => {
  const assignedTeamIds = ['team-a', 'team-b'];
  const selectedTeamIds = ['team-b', 'team-c'];
  const input = {
    mode: 'existing' as const,
    assignedTeamIds,
    selectedTeamIds,
    loading: false,
  };

  const first = stageComposition(input);
  const second = stageComposition(input);

  assert.deepEqual(second, first);
  assert.deepEqual(compositionMessage(second), compositionMessage(first));
  assert.deepEqual(assignedTeamIds, ['team-a', 'team-b']);
  assert.deepEqual(selectedTeamIds, ['team-b', 'team-c']);
});
