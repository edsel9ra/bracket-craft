/**
 * Código estable del 409 de invitaciones → clave i18n (RF-007).
 *
 * El servidor conserva `detail` como texto en español y añade `code` con uno de
 * los cuatro identificadores estables. Este módulo solo lee `code` del cuerpo
 * del error y lo traduce contra el catálogo del idioma activo. Sin reloj, sin
 * red y sin DOM.
 */

export const INVITATION_CONFLICT_CODES = [
  'INVITATION_NOT_REVOKED',
  'INVITATION_OTHER_PENDING',
  'INVITATION_ALREADY_ACCEPTED',
  'INVITATION_REVOKED_RESEND',
] as const;

export type InvitationConflictCode = (typeof INVITATION_CONFLICT_CODES)[number];

export const INVITATION_CONFLICT_MESSAGE_KEYS: Record<InvitationConflictCode, string> = {
  INVITATION_NOT_REVOKED: 'members.conflictNotRevoked',
  INVITATION_OTHER_PENDING: 'members.conflictOtherPending',
  INVITATION_ALREADY_ACCEPTED: 'members.conflictAccepted',
  INVITATION_REVOKED_RESEND: 'members.conflictRevokedResend',
};

function isConflictCode(value: unknown): value is InvitationConflictCode {
  return typeof value === 'string' && (INVITATION_CONFLICT_CODES as readonly string[]).includes(value);
}

/**
 * Lee `cause.data.code` (forma del error de `$fetch`). Devuelve `null` cuando el
 * cuerpo no trae código: el llamador cae al `errorMessage` de siempre.
 */
export function invitationConflictCode(cause: unknown): InvitationConflictCode | null {
  if (typeof cause !== 'object' || cause === null) return null;
  const data = (cause as { data?: unknown }).data;
  if (typeof data !== 'object' || data === null) return null;
  const code = (data as { code?: unknown }).code;
  return isConflictCode(code) ? code : null;
}

/** Clave i18n del motivo; `null` si falta el código o no es uno conocido. */
export function invitationConflictMessageKey(code: string | null | undefined): string | null {
  return isConflictCode(code) ? INVITATION_CONFLICT_MESSAGE_KEYS[code] : null;
}
