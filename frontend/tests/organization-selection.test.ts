import assert from 'node:assert/strict';
import test from 'node:test';

import {
  organizationHistoryEntry,
  selectActiveOrganization,
} from '../app/utils/organizationSelection.ts';

interface Organization {
  id: string;
  name: string;
}

const ALPHA = '11111111-1111-4111-8111-111111111111';
const BETA = '22222222-2222-4222-8222-222222222222';
const GAMMA = '33333333-3333-4333-8333-333333333333';
const ALIEN = '99999999-9999-4999-8999-999999999999';

// El servidor entrega la lista ya ordenada por nombre y, en empate, por id.
// La función no reordena: elegir la primera del orden estable significa
// elegir el primer elemento recibido.
const organizations: Organization[] = [
  { id: ALPHA, name: 'Alpha' },
  { id: BETA, name: 'Beta' },
  { id: GAMMA, name: 'Gamma' },
];

test('restaura la organización recordada cuando está en la lista', () => {
  assert.deepEqual(selectActiveOrganization(organizations, BETA), organizations[1]);
});

test('descarta una organización recordada que no está en la lista', () => {
  // Organización eliminada, inactiva, sin membresía o de otra persona: el
  // identificador guardado no aparece en la respuesta y se cae al orden estable.
  assert.deepEqual(selectActiveOrganization(organizations, ALIEN), organizations[0]);
});

test('sin historial activa la primera del orden estable', () => {
  assert.deepEqual(selectActiveOrganization(organizations, null), organizations[0]);
  assert.deepEqual(selectActiveOrganization(organizations, undefined), organizations[0]);
  assert.deepEqual(selectActiveOrganization(organizations, ''), organizations[0]);
});

test('una lista vacía no activa ninguna organización', () => {
  assert.equal(selectActiveOrganization([], BETA), null);
  assert.equal(selectActiveOrganization([], null), null);
  assert.equal(selectActiveOrganization(null, BETA), null);
  assert.equal(selectActiveOrganization(undefined, BETA), null);
});

test('una lista de un solo elemento se activa con o sin historial', () => {
  const single = [{ id: GAMMA, name: 'Gamma' }];
  assert.deepEqual(selectActiveOrganization(single, GAMMA), single[0]);
  assert.deepEqual(selectActiveOrganization(single, ALIEN), single[0]);
  assert.deepEqual(selectActiveOrganization(single, null), single[0]);
});

test('respeta el orden estable del servidor y no reordena la lista', () => {
  const byServer = [organizations[2] as Organization, organizations[0] as Organization, organizations[1] as Organization];
  assert.deepEqual(selectActiveOrganization(byServer, null), byServer[0]);
  assert.deepEqual(selectActiveOrganization(byServer, ALPHA), byServer[1]);
  assert.deepEqual(selectActiveOrganization(byServer, GAMMA), byServer[0]);
});

test('nunca devuelve una organización ajena a la lista', () => {
  for (const remembered of [null, ALIEN, ...organizations.map((organization) => organization.id)]) {
    const selected = selectActiveOrganization(organizations, remembered);
    assert.ok(selected !== null);
    assert.ok(organizations.includes(selected), 'la organización activa debe salir de la lista devuelta');
  }
});

test('no modifica la lista recibida', () => {
  const snapshot = organizations.map((organization) => ({ ...organization }));
  selectActiveOrganization(organizations, GAMMA);
  assert.deepEqual(organizations, snapshot);
});

test('el historial solo registra una organización presente en la lista', () => {
  assert.equal(organizationHistoryEntry(organizations, BETA), BETA);
  assert.equal(organizationHistoryEntry(organizations, ALIEN), null);
  assert.equal(organizationHistoryEntry(organizations, null), null);
  assert.equal(organizationHistoryEntry([], ALPHA), null);
});
