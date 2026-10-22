/**
 * Vocabulario del producto que se pinta en pantalla (R29): roles, estados de
 * invitación y estados de miembro.
 *
 * Las funciones devuelven la **clave i18n** de un valor conocido. Para un valor
 * desconocido (o vacío) devuelven el propio valor, de modo que `t(key)` lo
 * muestre tal cual: `t()` devuelve la clave recibida cuando no existe en el
 * catálogo, así que nunca se inventa una traducción.
 */

export const ROLE_LABEL_KEYS = {
  owner: 'role.owner',
  administrator: 'role.administrator',
  operator: 'role.operator',
  referee: 'role.referee',
  viewer: 'role.viewer',
} as const;

export const INVITATION_STATUS_LABEL_KEYS = {
  pending: 'invitationStatus.pending',
  accepted: 'invitationStatus.accepted',
  expired: 'invitationStatus.expired',
  revoked: 'invitationStatus.revoked',
} as const;

export const MEMBER_STATUS_LABEL_KEYS = {
  active: 'memberStatus.active',
  inactive: 'memberStatus.inactive',
} as const;

function labelKey(
  catalog: Record<string, string>,
  value: string | null | undefined,
): string {
  if (typeof value !== 'string') return '';
  const code = value.trim();
  if (!code) return '';
  return Object.prototype.hasOwnProperty.call(catalog, code) ? catalog[code]! : value;
}

export function roleLabelKey(code: string | null | undefined): string {
  return labelKey(ROLE_LABEL_KEYS, code);
}

export function invitationStatusLabelKey(status: string | null | undefined): string {
  return labelKey(INVITATION_STATUS_LABEL_KEYS, status);
}

export function memberStatusLabelKey(status: string | null | undefined): string {
  return labelKey(MEMBER_STATUS_LABEL_KEYS, status);
}
