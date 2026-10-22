/**
 * Textos visibles que el arnés E2E usa como localizadores accesibles.
 *
 * La corrida fija el idioma con la cookie `bc_locale` y busca por texto, rol y
 * nombre accesible (RNF-005); nunca por clases ni atributos de maquetación.
 * Los textos se copian del catálogo `useI18n.ts` y `tests/e2e-observations.test.ts`
 * comprueba que no derivan: si una traducción cambia, la prueba unitaria falla
 * antes de que el navegador busque un texto que ya no existe.
 */

import { realtimeStatusLabelKey, type RealtimeLabelNamespace } from '../app/utils/realtimeStatusLabel.ts';

export type E2ELocale = 'es' | 'en';

/** Idioma fijo de la corrida: el del contexto del navegador y el de la interfaz. */
export const E2E_LOCALE: E2ELocale = 'es';

/** Cookie de idioma del cliente (`useI18n`), fijada antes de navegar. */
export const E2E_LOCALE_COOKIE = 'bc_locale';

export interface LocalizedText {
  /** Clave i18n de la que procede el texto. */
  readonly key: string;
  readonly es: string;
  readonly en: string;
}

export interface LocaleCookie {
  readonly name: string;
  readonly value: string;
  readonly path: string;
}

/** Cookie de idioma lista para `context.addCookies`. */
export function localeCookie(locale: E2ELocale = E2E_LOCALE): LocaleCookie {
  return { name: E2E_LOCALE_COOKIE, value: locale, path: '/' };
}

/** Texto del idioma fijado; el contraste es/en lo verifica la prueba unitaria. */
export function labelText(text: LocalizedText, locale: E2ELocale = E2E_LOCALE): string {
  return text[locale];
}

function statusText(
  namespace: RealtimeLabelNamespace,
  status: VisibleRealtimeStatus,
  es: string,
  en: string,
): LocalizedText {
  const key = realtimeStatusLabelKey(status, namespace);
  if (key === null) throw new Error(`the visible status ${status} must have a label key`);
  return { key, es, en };
}

/** Estados visibles: los únicos que una vista anuncia con texto. */
export type VisibleRealtimeStatus = 'connected' | 'reconnecting' | 'retrying' | 'error';

/**
 * Etiquetas de estado por namespace. `retrying` (reintento manual) nunca es
 * igual a `reconnecting` (reconexión automática) en ninguno de los dos idiomas.
 */
export const REALTIME_STATUS_TEXT: Readonly<
  Record<RealtimeLabelNamespace, Readonly<Record<VisibleRealtimeStatus, LocalizedText>>>
> = {
  public: {
    connected: statusText('public', 'connected', 'Actualización en vivo conectada', 'Live updates connected'),
    reconnecting: statusText(
      'public',
      'reconnecting',
      'Reconectando actualización en vivo',
      'Reconnecting live updates',
    ),
    retrying: statusText('public', 'retrying', 'Reintentando…', 'Retrying…'),
    error: statusText(
      'public',
      'error',
      'La actualización en vivo no está disponible',
      'Live updates are unavailable',
    ),
  },
  workspace: {
    connected: statusText(
      'workspace',
      'connected',
      'Actualización en vivo conectada',
      'Live updates connected',
    ),
    reconnecting: statusText(
      'workspace',
      'reconnecting',
      'Reconectando actualización en vivo',
      'Reconnecting live updates',
    ),
    retrying: statusText('workspace', 'retrying', 'Reintentando…', 'Retrying…'),
    error: statusText(
      'workspace',
      'error',
      'La actualización en vivo no está disponible',
      'Live updates are unavailable',
    ),
  },
  match: {
    connected: statusText(
      'match',
      'connected',
      'Actualización del partido conectada',
      'Match live updates connected',
    ),
    reconnecting: statusText(
      'match',
      'reconnecting',
      'Reconectando actualización del partido',
      'Reconnecting match live updates',
    ),
    retrying: statusText('match', 'retrying', 'Reintentando…', 'Retrying…'),
    error: statusText(
      'match',
      'error',
      'La actualización del partido no está disponible',
      'Match live updates are unavailable',
    ),
  },
};

/**
 * Controles y datos de la preparación (sesión del Workspace y control de
 * reintento) y anclas accesibles de cada vista: encabezados y etiquetas con los
 * que se acota el localizador y se comprueba que la vista está cargada.
 */
export const E2E_LABELS = {
  retry: { key: 'common.retry', es: 'Reintentar', en: 'Retry' },
  loginEmail: { key: 'auth.email', es: 'Email', en: 'Email' },
  loginPassword: { key: 'auth.password', es: 'Contraseña', en: 'Password' },
  loginSubmit: { key: 'auth.login', es: 'Entrar', en: 'Log in' },
  workspaceReady: { key: 'workspace.private', es: 'Workspace privado', en: 'Private workspace' },
  workspaceTournaments: {
    key: 'workspace.yourTournaments',
    es: 'Tus torneos',
    en: 'Your tournaments',
  },
  workspaceConfigure: {
    key: 'workspace.configure',
    es: 'Configurar torneo',
    en: 'Configure tournament',
  },
  operationReportHeading: { key: 'match.buildReport', es: 'Construye el acta', en: 'Build the report' },
  operationEventType: { key: 'match.eventType', es: 'Tipo', en: 'Type' },
  operationEventMinute: { key: 'match.minute', es: 'Minuto', en: 'Minute' },
  operationSubstitutionPreview: {
    key: 'match.substitutionPreview',
    es: 'Vista previa de sustituciones',
    en: 'Substitution preview',
  },
} as const satisfies Record<string, LocalizedText>;

export type E2ELabelName = keyof typeof E2E_LABELS;
