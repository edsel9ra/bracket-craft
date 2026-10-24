import {
  DEFAULT_RESOLUTION,
  createResolutionStore,
  normalizeResolution,
  type OperationLimits,
  type ResolutionScope,
  type ResolutionStorage,
  type ResolutionType,
} from '~/utils/matchResolution';

export interface UseMatchResolutionOptions {
  /** Usuario de la sesión; sin él no se persiste nada. */
  userId: () => string | null | undefined;
  /** Organización activa; una selección de otra organización no se aplica. */
  organizationId: () => string | null | undefined;
  matchId: () => string | null | undefined;
}

/** Resultado de restaurar al montar: si se descartó un valor no habilitado. */
export interface RestoredResolution {
  readonly resolution: ResolutionType;
  readonly fellBack: boolean;
}

function sessionStorageOrNull(): ResolutionStorage | null {
  if (!import.meta.client) return null;
  try {
    return window.sessionStorage;
  } catch {
    // Almacenamiento deshabilitado o bloqueado: la operación sigue funcionando
    // sin persistencia de pestaña, sin errores en pantalla.
    return null;
  }
}

/**
 * Resolución prevista de la operación (spec 012, RF-033, RF-034, P3).
 *
 * Vive **solo** en el almacenamiento de sesión de la pestaña, asociada a
 * usuario, organización y partido; no se escribe en el servidor ni en el
 * borrador local. La restauración se aplica después de montar para no
 * desajustar la hidratación: el primer render usa el valor por defecto.
 */
export function useMatchResolution(options: UseMatchResolutionOptions) {
  const storage = sessionStorageOrNull();
  const scope = computed<ResolutionScope>(() => ({
    userId: options.userId(),
    organizationId: options.organizationId(),
    matchId: options.matchId(),
  }));
  const store = computed(() => createResolutionStore(scope.value, storage));
  const key = computed(() => store.value.key);
  const available = computed(() => store.value.available);
  const resolution = ref<ResolutionType>(DEFAULT_RESOLUTION);
  /**
   * Resolución prevista anunciada al empezar la operación (la que se restauró).
   * `select` mueve la selección vigente pero no esta base: al cerrar se compara
   * con ella para exigir confirmación explícita si se elige otra (RF-034).
   */
  const planned = ref<ResolutionType>(DEFAULT_RESOLUTION);

  /**
   * Selecciona la resolución mostrada. Si la configuración no la habilita, cae
   * a tiempo reglamentario y el valor efectivo es el que se persiste: nunca se
   * restaura una resolución que la fase no admite.
   */
  function select(next: ResolutionType, limits: OperationLimits | null | undefined): ResolutionType {
    const effective = normalizeResolution(limits, next);
    resolution.value = effective;
    store.value.save(effective);
    return effective;
  }

  /**
   * Restaura el valor de la pestaña al montar (RF-034). Un valor ausente deja
   * el tiempo reglamentario; uno que la fase ya no habilita se sustituye por
   * regular y se informa para que la pantalla pueda avisar.
   */
  function restore(limits: OperationLimits | null | undefined): RestoredResolution {
    const stored = store.value.read();
    const effective = normalizeResolution(limits, stored);
    resolution.value = effective;
    planned.value = effective;
    const fellBack = stored !== null && stored !== effective;
    if (fellBack) store.value.save(effective);
    return { resolution: effective, fellBack };
  }

  function clear(): boolean {
    return store.value.clear();
  }

  /**
   * Instantánea de la resolución vigente al abrir el cierre (RF-034, RP-1).
   *
   * La resolución prevista que el cierre compara es la que está en vigor en ese
   * momento: si el operador cambió durante la operación, el cierre no le avisa
   * de un cambio que no ha hecho. Solo un cambio **posterior** a esta
   * instantánea exige confirmación. La resolución sigue arrastrándose y
   * persistiendo en la sesión de la pestaña.
   */
  function snapshot(): ResolutionType {
    planned.value = resolution.value;
    return planned.value;
  }

  return { key, available, resolution, planned, select, restore, snapshot, clear };
}
