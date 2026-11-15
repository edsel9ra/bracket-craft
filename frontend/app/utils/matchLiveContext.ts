import { isForbidden, isNotFound, isUnauthorized } from './api.ts';
import {
  createReloadCoordinator,
  createRequestGeneration,
} from './realtimeReload.ts';

/** Contrato cerrado de `GET /matches/{id}/live/access` (spec 036, C3). */
export interface LiveCapabilities {
  can_view: boolean;
  can_operate: boolean;
  can_close: boolean;
  available: boolean;
}

/**
 * Normaliza las capacidades efectivas: solo cuatro booleanos estrictos;
 * cualquier forma distinta se descarta como respuesta inválida.
 */
export function normalizeLiveCapabilities(value: unknown): LiveCapabilities | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const candidate = value as Record<string, unknown>;
  for (const key of ['can_view', 'can_operate', 'can_close', 'available'] as const) {
    if (typeof candidate[key] !== 'boolean') return null;
  }
  return {
    can_view: candidate.can_view as boolean,
    can_operate: candidate.can_operate as boolean,
    can_close: candidate.can_close as boolean,
    available: candidate.available as boolean,
  };
}

export function isAccessDenied(cause: unknown): boolean {
  return isUnauthorized(cause) || isForbidden(cause) || isNotFound(cause);
}

export interface LiveContextCallbacks {
  /** Capacidades vigentes aplicadas al contexto actual. */
  applyAccess(capabilities: LiveCapabilities): void;
  /** Borrador autorizado aplicado al contexto actual. */
  applyLive(snapshot: unknown): void;
  /** La lectura dejó de estar autorizada: capacidades y borrador se limpian. */
  denyAccess(): void;
  /** Solo el borrador se limpia; el historial 033 autorizado se conserva. */
  denyLive(): void;
}

export interface LiveContextSource {
  fetchAccess(): Promise<unknown>;
  fetchLive(): Promise<unknown>;
}

export interface LiveContextCoordinatorOptions {
  /** Guarda de contexto/generación: una respuesta tardía nunca se aplica. */
  isCurrent(): boolean;
  /** La acción en curso aplaza la aplicación, no la descarta. */
  isBusy(): boolean;
  onBusy(): void;
  source: LiveContextSource;
  callbacks: LiveContextCallbacks;
}

export interface LiveContextCoordinator {
  /** Reconstruye capacidades y borrador con una sola corrida más una trailing. */
  request(): Promise<void>;
  readonly inFlight: boolean;
}

/**
 * Reconstrucción coordinada de capacidades y borrador live (RF-012–018).
 *
 * Una corrida consulta `live/access` y, solo si `can_view`, el borrador.
 * Cada lectura tiene su propia guarda: una denegación del borrador limpia ese
 * recurso sin tocar las capacidades aplicadas ni el historial 033; una
 * denegación de acceso limpia ambos. Un fallo no denegación conserva el estado
 * vigente —el consumidor decide el mensaje— y nunca bloquea la lectura de
 * operation, que viaja por su propio coordinador con el mismo disparador.
 */
export function createLiveContextCoordinator(
  options: LiveContextCoordinatorOptions,
): LiveContextCoordinator {
  const { isCurrent, isBusy, onBusy, source, callbacks } = options;
  const generation = createRequestGeneration();

  async function run() {
    const runGeneration = generation.next();
    const current = () => isCurrent() && generation.isCurrent(runGeneration);

    let rawAccess: unknown;
    try {
      rawAccess = await source.fetchAccess();
    } catch (cause) {
      if (current() && isAccessDenied(cause)) callbacks.denyAccess();
      return;
    }
    if (!current()) return;
    const capabilities = normalizeLiveCapabilities(rawAccess);
    if (capabilities === null || !capabilities.can_view) {
      // Respuesta inválida o sin lectura: nada del borrador queda vigente.
      callbacks.denyAccess();
      if (capabilities !== null) callbacks.applyAccess(capabilities);
      return;
    }
    callbacks.applyAccess(capabilities);

    if (!current()) return;
    if (isBusy()) {
      onBusy();
      return;
    }
    try {
      const snapshot = await source.fetchLive();
      if (!current()) return;
      callbacks.applyLive(snapshot);
    } catch (cause) {
      if (!current()) return;
      if (isAccessDenied(cause)) callbacks.denyLive();
    }
  }

  const coordinator = createReloadCoordinator(async () => {
    if (isBusy()) {
      onBusy();
      return;
    }
    await run();
  });

  return {
    request: () => coordinator.request(),
    get inFlight() {
      return coordinator.inFlight;
    },
  };
}
