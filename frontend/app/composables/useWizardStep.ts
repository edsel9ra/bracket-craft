import { nextStepId, previousStepId, type WizardKind, type WizardStepId } from '~/utils/wizardModel';
import {
  defaultStepId,
  entryStepWrite,
  stepBlock,
  stepFromAddress,
  stepUrl,
  stepChangeWrite,
  type WizardStepBlock,
  type WizardStepData,
  type WizardStepWrite,
} from '~/utils/wizardStep';

export interface UseWizardStepOptions {
  wizard: WizardKind;
  /** Datos de los que depende un paso (RF-015); se recalculan al crearse la fase. */
  data?: () => WizardStepData;
  /** Guarda el borrador al cambiar de paso (RF-014). */
  onStepChange?: (step: WizardStepId) => void;
  /**
   * Paso de entrada del asistente cuando la dirección no lo nombra (RF-002:
   * una fase existente abre su composición). Por defecto, el primero declarado.
   */
  entryStep?: () => WizardStepId;
  /**
   * Paso guardado por el borrador de la pestaña (RF-014). Solo se consulta una
   * vez, al montar, para normalizar la dirección; nunca compite con ella.
   */
  draftStep?: () => WizardStepId | null;
}

/**
 * La página monta los tres asistentes y todos comparten un único `?step=`. Solo
 * el primero que monta (orden del documento) normaliza la entrada inicial: la
 * dirección resultante es determinista y no se pisan entre ellos.
 */
let initialNormalization: symbol | null = null;

function claimInitialNormalization(): boolean {
  if (initialNormalization) return false;
  const claim = Symbol('wizard-entry');
  initialNormalization = claim;
  queueMicrotask(() => {
    if (initialNormalization === claim) initialNormalization = null;
  });
  return true;
}

/**
 * Paso actual de un asistente en la dirección (spec 012, RF-013, RF-019).
 *
 * La dirección es la **única** fuente del paso: se deriva de `?step=` en
 * servidor y en cliente, de modo que la dirección compartida abre el paso pedido
 * sin desajuste de hidratación, recargar lo conserva y el botón atrás devuelve
 * al paso que la entrada anterior nombra. Una dirección que no nombra este
 * asistente —sin `?step=`, con un paso desconocido o con el paso de otro
 * asistente— muestra su paso de entrada (el del borrador de la pestaña o el
 * primero), y al montar se normaliza con `replace` para que la dirección lo
 * nombre, sin añadir historial.
 *
 * Cada cambio de paso del usuario apila **una** entrada con `push` (nunca con
 * `history.replaceState`, que el router re-sincroniza): un movimiento produce un
 * solo paso atrás, la vuelta conserva los valores y el segundo atrás sale del
 * asistente. La navegación usa el router, así que no recarga, no escribe en el
 * servidor y conserva el resto de la dirección.
 *
 * `location` y `href()` son la dirección vigente con el paso incluido: la página
 * construye con ellos sus enlaces y sus cambios de parámetros para no perder el
 * paso vigente.
 */
export function useWizardStep(options: UseWizardStepOptions) {
  const route = useRoute();
  const router = useRouter();

  // Paso de entrada: el del borrador se aplica después de montar para no
  // desajustar la hidratación (plan §11). Nunca sustituye a la dirección.
  const restoredStep = ref<WizardStepId | null>(null);
  const entry = computed<WizardStepId>(() => (
    restoredStep.value ?? options.entryStep?.() ?? defaultStepId(options.wizard)
  ));
  const step = computed<WizardStepId>(() => stepFromAddress(options.wizard, route.fullPath, entry.value));
  const location = computed(() => stepUrl(route.fullPath, step.value));
  const data = computed<WizardStepData>(() => options.data?.() ?? {});
  const blocked = computed<WizardStepBlock | null>(() => stepBlock(step.value, data.value));
  const previous = computed(() => previousStepId(options.wizard, step.value));
  const next = computed(() => nextStepId(options.wizard, step.value));

  /** Dirección con otro paso, conservando el resto de parámetros y el fragmento. */
  function href(stepId: WizardStepId): string {
    return stepUrl(location.value, stepId);
  }

  /** Aplica una escritura de historial decidida por el modelo puro. */
  async function apply(decision: WizardStepWrite | null): Promise<void> {
    if (!decision || !import.meta.client) return;
    // Una navegación cancelada no deja el asistente en un estado inconsistente:
    // la dirección sigue siendo la fuente y el cambio simplemente no ocurrió.
    const navigation = decision.mode === 'replace'
      ? router.replace(decision.url)
      : router.push(decision.url);
    await navigation.catch(() => undefined);
  }

  async function goTo(nextStep: WizardStepId): Promise<void> {
    const decision = stepChangeWrite(route.fullPath, step.value, nextStep);
    await apply(decision);
    if (decision?.mode === 'push') options.onStepChange?.(nextStep);
  }

  if (import.meta.client) {
    onMounted(async () => {
      const stored = options.draftStep?.() ?? null;
      if (stored) restoredStep.value = stored;
      // Normalización de la entrada: `replace` con el paso que se muestra, solo
      // si la dirección no nombra a ningún asistente y solo desde el asistente
      // que monta primero. Nunca con `history.replaceState`.
      const decision = entryStepWrite(route.fullPath, step.value);
      if (decision && claimInitialNormalization()) await apply(decision);
    });
  }

  return { step, blocked, previous, next, location, href, goTo };
}
