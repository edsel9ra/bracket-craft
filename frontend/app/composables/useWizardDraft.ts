import type { WizardKind } from '~/utils/wizardModel';
import {
  createWizardDraftStore,
  type WizardDraft,
  type WizardDraftContext,
  type WizardStorage,
} from '~/utils/wizardDraft';

export interface UseWizardDraftOptions {
  wizard: WizardKind;
  /** Usuario de la sesión; sin él no se persiste nada. */
  userId: () => string | null | undefined;
  /** Organización activa; un borrador de otra organización no se aplica. */
  organizationId: () => string | null | undefined;
  tournamentId: () => string | null | undefined;
  versionId: () => string | null | undefined;
}

function sessionStorageOrNull(): WizardStorage | null {
  if (!import.meta.client) return null;
  try {
    return window.sessionStorage;
  } catch {
    // Almacenamiento deshabilitado o bloqueado: el asistente sigue funcionando
    // sin borrador de pestaña, sin errores en pantalla.
    return null;
  }
}

/**
 * Borrador de un asistente en el almacenamiento de sesión de la pestaña
 * (spec 012, RF-014, WP-1). La clave asocia usuario, organización, torneo,
 * versión y asistente; sin todos los identificadores no se persiste nada y
 * `available` queda en `false`. Nunca se usa almacenamiento persistente:
 * cerrar la pestaña o la sesión descarta el borrador.
 */
export function useWizardDraft(options: UseWizardDraftOptions) {
  const storage = sessionStorageOrNull();
  const context = computed<WizardDraftContext>(() => ({
    wizard: options.wizard,
    userId: options.userId(),
    organizationId: options.organizationId(),
    tournamentId: options.tournamentId(),
    versionId: options.versionId(),
  }));
  const store = computed(() => createWizardDraftStore(context.value, storage));
  const key = computed(() => store.value.key);
  const available = computed(() => store.value.available);

  function read(): WizardDraft | null {
    return store.value.read();
  }

  function save(draft: WizardDraft): boolean {
    return store.value.save(draft);
  }

  function clear(): boolean {
    return store.value.clear();
  }

  /**
   * Aplica el borrador después de montar (plan §11): el primer render usa los
   * valores del servidor y la hidratación no se desajusta. En servidor no hace
   * nada, así que ningún acceso al almacenamiento ocurre fuera del cliente.
   */
  function applyAfterMount(apply: (draft: WizardDraft | null) => void): void {
    if (!import.meta.client) return;
    onMounted(() => apply(read()));
  }

  return { key, available, read, save, clear, applyAfterMount };
}
