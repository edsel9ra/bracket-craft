/**
 * Borrador de los asistentes en el almacenamiento de sesión de la pestaña
 * (spec 012, RF-014, WP-1).
 *
 * La clave asocia usuario, organización, torneo, versión y asistente: un
 * borrador de otra pestaña, otro torneo u otra organización no se aplica nunca.
 * Sin todos los identificadores no se persiste nada. Nunca se usa
 * almacenamiento persistente: cerrar la pestaña o la sesión descarta el
 * borrador. El módulo no lee el reloj ni escribe en la red; el almacenamiento
 * y los valores entran como parámetro.
 */

import { isWizardStep } from './wizardStep.ts';
import type { WizardKind, WizardStepId, WizardValues } from './wizardModel.ts';

/** Versión del formato guardado; un borrador de otra versión se ignora. */
export const DRAFT_VERSION = 1;

/** Contexto que identifica un borrador (RF-014). */
export interface WizardDraftContext {
  readonly wizard: WizardKind;
  readonly userId?: string | null;
  readonly organizationId?: string | null;
  readonly tournamentId?: string | null;
  readonly versionId?: string | null;
}

/** Borrador de un asistente: paso y, si hay cambios, valores introducidos. */
export interface WizardDraft {
  /**
   * Paso guardado, o `null` si el guardado no era un paso de este asistente:
   * los valores se conservan y el paso se resuelve con la dirección o el
   * primero del asistente.
   */
  readonly step: WizardStepId | null;
  /**
   * Valores introducidos, o `null` cuando no hay cambios: el borrador solo
   * recuerda el paso y los valores mostrados siguen siendo los del servidor
   * (RF-014). Un objeto de valores vacío nunca se guarda.
   */
  readonly values: WizardValues | null;
}

/**
 * Borrador que corresponde a un paso (RF-014). Con cambios guarda paso y
 * valores; sin cambios guarda **solo el paso**. Los valores vacíos se tratan
 * como «sin cambios»: persistirlos sustituiría los del servidor por un objeto
 * vacío al restaurar la pestaña.
 */
export function draftForStep(
  step: WizardStepId,
  values: WizardValues | null | undefined,
  hasChanges: boolean,
): WizardDraft {
  const stored = hasChanges && values && Object.keys(values).length > 0 ? values : null;
  return { step, values: stored };
}

/** Parte de `Storage` que el borrador necesita. */
export type WizardStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function draftPart(value: string | null | undefined): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  // Un identificador con separadores o espacios podría hacer que dos contextos
  // compartieran clave; en ese caso no se persiste nada.
  if (/[:\s]/.test(trimmed)) return null;
  return trimmed;
}

/**
 * Clave del borrador (plan §6): `bc_wizard:{wizard}:{userId}:{orgId}:{torneo}:{versión}`.
 * Devuelve `null` si falta algún identificador, y entonces no se persiste.
 */
export function draftKey(context: WizardDraftContext): string | null {
  const wizard = draftPart(context.wizard);
  const userId = draftPart(context.userId);
  const organizationId = draftPart(context.organizationId);
  const tournamentId = draftPart(context.tournamentId);
  const versionId = draftPart(context.versionId);
  if (!wizard || !userId || !organizationId || !tournamentId || !versionId) return null;
  return ['bc_wizard', wizard, userId, organizationId, tournamentId, versionId].join(':');
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Formato guardado del borrador; sin valores, el objeto solo lleva el paso. */
export function serializeDraft(draft: WizardDraft): string {
  const payload = draft.values === null
    ? { v: DRAFT_VERSION, step: draft.step }
    : { v: DRAFT_VERSION, step: draft.step, values: draft.values };
  return JSON.stringify(payload);
}

/**
 * Lee un borrador guardado (RF-014). Un contenido ilegible, de otra versión o
 * con valores que no son un objeto se ignora; un paso desconocido para el
 * asistente conserva los valores y deja que la dirección decida el paso. Un
 * borrador sin valores solo recuerda el paso.
 */
export function parseDraft(
  wizard: WizardKind,
  raw: string | null | undefined,
): WizardDraft | null {
  if (typeof raw !== 'string' || !raw.trim()) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }

  if (!isRecord(parsed) || parsed.v !== DRAFT_VERSION) return null;
  const candidate = typeof parsed.step === 'string' ? parsed.step : null;
  const step = isWizardStep(wizard, candidate) ? candidate : null;

  const rawValues = parsed.values;
  if (rawValues === undefined || rawValues === null) return { step, values: null };
  if (!isRecord(rawValues)) return null;

  return { step, values: rawValues as WizardValues };
}

export interface WizardDraftStore {
  /** Clave efectiva, o `null` si falta un identificador y no se persiste. */
  readonly key: string | null;
  readonly available: boolean;
  read(): WizardDraft | null;
  save(draft: WizardDraft): boolean;
  clear(): boolean;
}

/**
 * Acceso al borrador de un contexto sobre el almacenamiento recibido (la
 * sesión de la pestaña en el composable, un doble en las pruebas). Cualquier
 * fallo del almacenamiento (cuota, modo privado, almacenamiento deshabilitado)
 * se comporta como «no hay borrador» y nunca rompe el asistente.
 */
export function createWizardDraftStore(
  context: WizardDraftContext,
  storage: WizardStorage | null,
): WizardDraftStore {
  const key = draftKey(context);
  const available = Boolean(key && storage);

  return {
    key,
    available,
    read(): WizardDraft | null {
      if (!key || !storage) return null;
      try {
        return parseDraft(context.wizard, storage.getItem(key));
      } catch {
        return null;
      }
    },
    save(draft: WizardDraft): boolean {
      if (!key || !storage) return false;
      try {
        storage.setItem(key, serializeDraft(draft));
        return true;
      } catch {
        return false;
      }
    },
    clear(): boolean {
      if (!key || !storage) return false;
      try {
        storage.removeItem(key);
        return true;
      } catch {
        return false;
      }
    },
  };
}
