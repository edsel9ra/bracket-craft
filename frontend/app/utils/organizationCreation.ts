/**
 * Mensaje del alta de organización (RF-24, RF-25).
 *
 * El backend distingue el identificador ocupado con el código aditivo
 * `ORGANIZATION_SLUG_TAKEN`; el 409 de una cuenta que ya tiene organización no
 * lleva código. Esta función traduce ambos a una clave del catálogo y deja
 * cualquier otro fallo en el mensaje genérico.
 */

export type OrganizationCreationErrorKey =
  | 'organization.slugTaken'
  | 'organization.alreadyExists'
  | 'organization.error';

export function organizationCreationErrorKey(
  code: unknown,
  status: unknown,
): OrganizationCreationErrorKey {
  if (code === 'ORGANIZATION_SLUG_TAKEN') return 'organization.slugTaken';
  if (typeof status === 'number' && status === 409) return 'organization.alreadyExists';
  return 'organization.error';
}
