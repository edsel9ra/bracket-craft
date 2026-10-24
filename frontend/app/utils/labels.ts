/**
 * Vocabulario del producto que se pinta en pantalla (R29 / RF-025, RF-026):
 * roles de la organización, estados de invitación y estados de miembro.
 *
 * Los **códigos** son el valor contractual: son lo que viaja a la API y a la
 * base de datos, y son lo que se compara para decidir permisos. Nunca se
 * comparan etiquetas. Solo se localiza lo que se muestra, y este archivo es la
 * **única fuente** del vocabulario de roles: declara la clave i18n estable de
 * cada código conocido, igual que `positions.ts` hace con las posiciones. Aquí
 * no hay ningún texto traducible; los catálogos es/en viven solo en
 * `composables/useI18n.ts`.
 *
 * `owner` (dueño) es un rol conocido pero **no editable**: se muestra traducido
 * donde aparece, incluida la tabla de miembros, pero no se ofrece para invitar
 * ni para cambiar el rol de un integrante.
 *
 * Las funciones devuelven la **clave i18n** de un valor conocido. Para un valor
 * desconocido (o vacío) devuelven el propio valor, de modo que `t(key)` lo
 * muestre tal cual: `t()` devuelve la clave recibida cuando no existe en el
 * catálogo, así que nunca se inventa una traducción (RF-026).
 */

export const ROLE_CODES = [
  'owner',
  'administrator',
  'operator',
  'referee',
  'viewer',
] as const;

export type RoleCode = (typeof ROLE_CODES)[number];

export interface RoleDefinition {
  readonly key: string;
  /** `owner` es conocido pero no editable: no se ofrece para invitar ni asignar. */
  readonly assignable: boolean;
}

/** Los cinco roles conocidos, en el orden de precedencia del producto. */
export const ROLE_DEFINITIONS: Record<RoleCode, RoleDefinition> = {
  owner: { key: 'roles.owner', assignable: false },
  administrator: { key: 'roles.administrator', assignable: true },
  operator: { key: 'roles.operator', assignable: true },
  referee: { key: 'roles.referee', assignable: true },
  viewer: { key: 'roles.viewer', assignable: true },
};

/** Roles que se pueden ofrecer en una invitación o en el cambio de rol. */
export type AssignableRoleCode = Exclude<RoleCode, 'owner'>;

export const ASSIGNABLE_ROLE_CODES: readonly AssignableRoleCode[] = ROLE_CODES.filter(
  (code): code is AssignableRoleCode => ROLE_DEFINITIONS[code].assignable,
);

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

function definitionOf(code: string | null | undefined): RoleDefinition | null {
  if (typeof code !== 'string') return null;
  const candidate = code.trim();
  if (!candidate) return null;
  return Object.prototype.hasOwnProperty.call(ROLE_DEFINITIONS, candidate)
    ? ROLE_DEFINITIONS[candidate as RoleCode]
    : null;
}

/**
 * Clave i18n de un rol conocido; el propio código si es desconocido y una
 * cadena vacía si no hay código. Así `t(roleKey(code))` nunca inventa texto.
 */
export function roleKey(code: string | null | undefined): string {
  if (typeof code !== 'string') return '';
  return definitionOf(code)?.key ?? (code.trim() ? code : '');
}

/** Indica si el código es un rol editable (todo rol conocido salvo `owner`). */
export function isAssignableRole(code: string | null | undefined): boolean {
  return definitionOf(code)?.assignable ?? false;
}

export function invitationStatusLabelKey(status: string | null | undefined): string {
  return labelKey(INVITATION_STATUS_LABEL_KEYS, status);
}

export function memberStatusLabelKey(status: string | null | undefined): string {
  return labelKey(MEMBER_STATUS_LABEL_KEYS, status);
}
