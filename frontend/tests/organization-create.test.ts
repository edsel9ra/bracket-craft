import assert from 'node:assert/strict';
import test from 'node:test';

import { organizationCreationErrorKey } from '../app/utils/organizationCreation.ts';

// RF-24 / RF-25: el alta opcional distingue el identificador ocupado (código
// aditivo), la cuenta que ya tiene organización (409 sin código) y cualquier
// otro fallo. La página usa la clave para mostrar el mensaje del catálogo.

test('a taken slug keeps its own message inside the step', () => {
  assert.equal(
    organizationCreationErrorKey('ORGANIZATION_SLUG_TAKEN', 409),
    'organization.slugTaken',
  );
  assert.equal(
    organizationCreationErrorKey('ORGANIZATION_SLUG_TAKEN', null),
    'organization.slugTaken',
  );
});

test('the uncoded 409 means the account already has an organization', () => {
  assert.equal(organizationCreationErrorKey(null, 409), 'organization.alreadyExists');
  assert.equal(organizationCreationErrorKey(undefined, 409), 'organization.alreadyExists');
  assert.equal(organizationCreationErrorKey('OTHER_CODE', 409), 'organization.alreadyExists');
});

test('any other failure falls back to the generic organization error', () => {
  assert.equal(organizationCreationErrorKey(null, null), 'organization.error');
  assert.equal(organizationCreationErrorKey(undefined, undefined), 'organization.error');
  assert.equal(organizationCreationErrorKey('SOMETHING_ELSE', 422), 'organization.error');
  assert.equal(organizationCreationErrorKey(undefined, 500), 'organization.error');
});
