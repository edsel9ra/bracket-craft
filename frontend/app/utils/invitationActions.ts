/**
 * Acciones disponibles por estado de invitación y guardas puras de la pantalla
 * de miembros (RF-005, RF-006).
 *
 * El servidor sigue siendo la autoridad del ciclo de vida; este módulo solo
 * decide qué controles ofrece la fila, con qué clave i18n se etiquetan y si una
 * activación debe producir una petición. Sin Nuxt, sin DOM, sin reloj y sin red.
 */

export type InvitationAction = 'resend' | 'reopen' | 'revoke';

export type InvitationOperation = 'idle' | 'creating' | 'resending' | 'reopening' | 'revoking';

/**
 * Reenviar permanece en pendientes y vencidas; reabrir solo en revocadas
 * (reenviar una revocada responde 409, cambio C-1) y revocar solo en pendientes.
 */
const INVITATION_ACTIONS_BY_STATUS: Record<string, readonly InvitationAction[]> = {
  pending: ['resend', 'revoke'],
  expired: ['resend'],
  revoked: ['reopen'],
  accepted: [],
};

const ACTION_LABEL_KEYS: Record<InvitationAction, string> = {
  resend: 'members.resend',
  reopen: 'members.reopen',
  revoke: 'members.revoke',
};

const ACTION_ERROR_KEYS: Record<InvitationAction, string> = {
  resend: 'members.noResend',
  reopen: 'members.noReopen',
  revoke: 'members.noRevoke',
};

const ACTION_ARIA_KEYS: Record<InvitationAction, string> = {
  resend: 'members.resendAria',
  reopen: 'members.reopenAria',
  revoke: 'members.revokeAria',
};

/** Devuelve una lista nueva para que la vista no mute la tabla compartida. */
export function invitationActionsFor(status: string | null | undefined): InvitationAction[] {
  if (typeof status !== 'string') return [];
  if (!Object.prototype.hasOwnProperty.call(INVITATION_ACTIONS_BY_STATUS, status)) return [];
  return [...INVITATION_ACTIONS_BY_STATUS[status]!];
}

export function invitationActionLabelKey(action: InvitationAction): string {
  return ACTION_LABEL_KEYS[action];
}

export function invitationActionErrorKey(action: InvitationAction): string {
  return ACTION_ERROR_KEYS[action];
}

export function invitationActionAriaKey(action: InvitationAction): string {
  return ACTION_ARIA_KEYS[action];
}

/** Solo reabrir exige una confirmación nueva; revocar conserva la suya. */
export function invitationActionConfirmKey(action: InvitationAction): string | null {
  return action === 'reopen' ? 'members.confirmReopen' : null;
}

/** Los controles del formulario y de las filas se bloquean con cualquier operación. */
export function invitationControlsDisabled(operation: InvitationOperation): boolean {
  return operation !== 'idle';
}

/**
 * Guarda anti doble pulsación independiente del DOM: si ya hay una operación en
 * curso devuelve `null` y el llamador no debe lanzar la petición.
 */
export function beginInvitationOperation(
  current: InvitationOperation,
  next: InvitationOperation,
): InvitationOperation | null {
  return current === 'idle' ? next : null;
}
