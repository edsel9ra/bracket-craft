/**
 * Paso en la dirección, bloqueo de un paso sin datos y política de navegación
 * de los asistentes (spec 012, RF-004, RF-008, RF-013, RF-014, RF-015).
 *
 * Módulo puro: no lee el reloj, el entorno global, el almacenamiento ni la red.
 * La dirección, el borrador y los efectos (escribir la dirección, guardar el
 * borrador) entran como parámetro, de modo que la navegación entre pasos sea
 * comprobable sin DOM y sin emitir peticiones.
 */

import {
  WIZARD_KINDS,
  wizardSteps,
  type WizardKind,
  type WizardStepId,
  type WizardValues,
} from './wizardModel.ts';
import type { WizardDraft } from './wizardDraft.ts';

/** Parámetro de la dirección que lleva el paso actual (RF-013). */
export const STEP_PARAM = 'step';

/** Primer paso declarado por el asistente. */
export function defaultStepId(wizard: WizardKind): WizardStepId {
  const first = wizardSteps(wizard)[0]?.id;
  if (!first) throw new Error(`wizard ${wizard} declares no steps`);
  return first;
}

/** Si el valor es un paso declarado por ese asistente. */
export function isWizardStep(
  wizard: WizardKind,
  value: string | null | undefined,
): value is WizardStepId {
  if (typeof value !== 'string') return false;
  const candidate = value.trim();
  if (!candidate) return false;
  return wizardSteps(wizard).some((step) => step.id === candidate);
}

/**
 * Paso pedido explícitamente por la dirección, o `null` cuando falta o no
 * pertenece al asistente. Un valor desconocido nunca se convierte en otro paso
 * pedido: solo devuelve `null` para que el llamador use el paso por defecto.
 */
export function requestedStep(
  wizard: WizardKind,
  raw: string | null | undefined,
): WizardStepId | null {
  if (!isWizardStep(wizard, raw)) return null;
  return raw.trim() as WizardStepId;
}

/**
 * Paso que se muestra al abrir la dirección (RF-013, RF-015): el pedido si es
 * válido y, si no, el primero del asistente. Nunca redirige en silencio a otro
 * paso distinto del pedido.
 */
export function parseStep(wizard: WizardKind, raw: string | null | undefined): WizardStepId {
  return requestedStep(wizard, raw) ?? defaultStepId(wizard);
}

/** Valor de `?step=` de una dirección completa o parcial, o `null`. */
export function stepFromLocation(location: string): string | null {
  const queryIndex = location.indexOf('?');
  if (queryIndex < 0) return null;
  const hashIndex = location.indexOf('#', queryIndex);
  const search = hashIndex < 0 ? location.slice(queryIndex + 1) : location.slice(queryIndex + 1, hashIndex);
  return new URLSearchParams(search).get(STEP_PARAM);
}

/**
 * Dirección con el paso indicado (RF-013): conserva el resto de parámetros y el
 * fragmento, y no añade ningún valor del formulario. Con `null` retira el paso.
 */
export function stepUrl(location: string, step: WizardStepId | null): string {
  const hashIndex = location.indexOf('#');
  const hash = hashIndex < 0 ? '' : location.slice(hashIndex);
  const withoutHash = hashIndex < 0 ? location : location.slice(0, hashIndex);
  const queryIndex = withoutHash.indexOf('?');
  const path = queryIndex < 0 ? withoutHash : withoutHash.slice(0, queryIndex);
  const params = new URLSearchParams(queryIndex < 0 ? '' : withoutHash.slice(queryIndex + 1));

  if (step) params.set(STEP_PARAM, step);
  else params.delete(STEP_PARAM);

  const search = params.toString();
  return `${path}${search ? `?${search}` : ''}${hash}`;
}

/**
 * Si la dirección nombra un paso de **cualquiera** de los asistentes de la
 * página (RF-013). Los tres comparten un único `?step=`, así que un valor válido
 * para otro asistente no se normaliza ni se descarta: solo no nombra a este.
 */
export function namesWizardStep(location: string): boolean {
  const raw = stepFromLocation(location);
  return WIZARD_KINDS.some((kind) => requestedStep(kind, raw) !== null);
}

/** Paso que muestra un asistente cuya dirección no lo nombra (RF-014, RF-015). */
export function stepFromAddress(
  wizard: WizardKind,
  location: string,
  entryStep: WizardStepId = defaultStepId(wizard),
): WizardStepId {
  return requestedStep(wizard, stepFromLocation(location)) ?? entryStep;
}

/**
 * Escritura de historial que produce una navegación de un asistente (RF-013,
 * RF-019). `push` apila una entrada por paso del usuario; `replace` solo corrige
 * la entrada vigente, sin añadir ninguna.
 */
export interface WizardStepWrite {
  readonly mode: 'replace' | 'push';
  readonly url: string;
}

/**
 * Escritura de la **entrada** del asistente: `replace` de la entrada vigente con
 * el paso de entrada, sin añadir historial. Devuelve `null` cuando la dirección
 * ya nombra un paso de algún asistente: no se pisa lo que el usuario abrió.
 */
export function entryStepWrite(location: string, step: WizardStepId): WizardStepWrite | null {
  if (namesWizardStep(location)) return null;
  return { mode: 'replace', url: stepUrl(location, step) };
}

/**
 * Escritura de un cambio de paso del usuario: siempre `push`, de modo que un
 * movimiento produzca un solo paso atrás y el botón atrás devuelva al paso
 * anterior con sus valores (RF-019, criterio 14). Si el paso pedido ya es el
 * vigente, solo se corrige la entrada —sin apilar— cuando la dirección nombraba
 * a otro asistente; si ya lo nombraba, no se escribe nada.
 */
export function stepChangeWrite(
  location: string,
  currentStep: WizardStepId,
  nextStep: WizardStepId,
): WizardStepWrite | null {
  if (nextStep !== currentStep) {
    return { mode: 'push', url: stepUrl(location, nextStep) };
  }
  if (stepFromLocation(location) === nextStep) return null;
  return { mode: 'replace', url: stepUrl(location, nextStep) };
}

/** Datos de los que puede depender un paso (RF-015). */
export interface WizardStepData {
  /** Fase a la que se aplica la composición; ausente mientras no exista. */
  readonly stageId?: string | null;
}

/** Paso bloqueado por un dato que aún no existe, con el enlace que lo aporta. */
export interface WizardStepBlock {
  readonly missing: 'stageId';
  readonly provider: WizardStepId;
  /** Clave i18n de la explicación. */
  readonly messageKey: string;
  /** Clave i18n del enlace al paso que aporta el dato. */
  readonly actionKey: string;
}

/**
 * Bloqueo de un paso por un dato ausente (RF-015). Con la fase ya creada la
 * composición deja de estar bloqueada; el resto de pasos no depende de nada.
 */
export function stepBlock(step: WizardStepId, data: WizardStepData = {}): WizardStepBlock | null {
  if (step !== 'phases.composition') return null;
  if (typeof data.stageId === 'string' && data.stageId.trim().length > 0) return null;
  return {
    missing: 'stageId',
    provider: 'phases.identity',
    messageKey: 'wizard.step.blockedPhase',
    actionKey: 'wizard.step.blockedPhaseAction',
  };
}

/**
 * Dirección del paso que aporta el dato que falta (RF-015). El paso pedido se
 * mantiene: el enlace se ofrece, no se aplica solo.
 */
export function blockedStepHref(location: string, block: WizardStepBlock | null): string | null {
  return block ? stepUrl(location, block.provider) : null;
}

/**
 * Navegaciones que pueden ocurrir con un asistente abierto. Solo el descarte
 * explícito y el cambio de versión o de torneo piden confirmación (RF-008).
 */
export type NavigationKind =
  | 'step'
  | 'section'
  | 'back'
  | 'reload'
  | 'close'
  | 'discard'
  | 'version'
  | 'tournament';

export interface NavigationRule {
  readonly kind: NavigationKind;
  /** Si pide confirmación cuando hay cambios sin guardar. */
  readonly confirms: boolean;
  /** Si conserva el borrador de la pestaña. */
  readonly keepsDraft: boolean;
}

/** Tabla de navegaciones de la spec (RF-008, plan §3.1). */
export const NAVIGATION_RULES: readonly NavigationRule[] = [
  { kind: 'step', confirms: false, keepsDraft: true },
  { kind: 'section', confirms: false, keepsDraft: true },
  { kind: 'back', confirms: false, keepsDraft: true },
  { kind: 'reload', confirms: false, keepsDraft: true },
  { kind: 'close', confirms: false, keepsDraft: false },
  { kind: 'discard', confirms: true, keepsDraft: false },
  { kind: 'version', confirms: true, keepsDraft: false },
  { kind: 'tournament', confirms: true, keepsDraft: false },
];

/** Regla declarada para una navegación. */
export function navigationRule(kind: NavigationKind): NavigationRule {
  return NAVIGATION_RULES.find((rule) => rule.kind === kind)
    ?? { kind, confirms: false, keepsDraft: true };
}

/**
 * Si una navegación debe pedir confirmación antes de descartar (RF-008). Sin
 * cambios sin guardar no se pregunta nunca.
 */
export function shouldConfirmNavigation(kind: NavigationKind, hasChanges: boolean): boolean {
  return navigationRule(kind).confirms && hasChanges;
}

/** Efecto decidido de una navegación con un asistente abierto (RF-008). */
export interface NavigationEffect {
  /** `true` si la navegación sigue adelante. */
  readonly proceed: boolean;
  /** `true` si hay que descartar el borrador de la pestaña. */
  readonly discardDraft: boolean;
}

/**
 * Resuelve una navegación con `NAVIGATION_RULES` como **única** fuente
 * (RF-008). Las que no piden confirmación siguen siempre y conservan el
 * borrador, salvo el cierre de la pestaña. Las que piden confirmación no
 * siguen sin aceptación (`accepted = false`); con aceptación siguen y
 * descartan el borrador, porque pertenece a la versión o al torneo anterior.
 *
 * Cancelar deja intactos el asistente, la versión y el borrador: la función no
 * tiene efectos, solo informa de lo que el llamador debe hacer.
 */
export function resolveNavigation(
  kind: NavigationKind,
  hasChanges: boolean,
  accepted = false,
): NavigationEffect {
  if (shouldConfirmNavigation(kind, hasChanges) && !accepted) {
    return { proceed: false, discardDraft: false };
  }
  return { proceed: true, discardDraft: !navigationRule(kind).keepsDraft };
}

/** Estado de apertura de un asistente (RF-013, RF-014, RF-015). */
export interface WizardStart {
  readonly step: WizardStepId;
  readonly values: WizardValues;
  readonly blocked: WizardStepBlock | null;
  /** De dónde salen los valores: del borrador de la pestaña o del servidor. */
  readonly source: 'draft' | 'server';
}

export interface WizardStartOptions {
  readonly wizard: WizardKind;
  /** Dirección completa (`/ruta?step=…&…`). */
  readonly location: string;
  /** Valores de partida del servidor. */
  readonly serverValues?: WizardValues;
  /** Borrador ya leído del almacenamiento de sesión, si existe. */
  readonly draft?: WizardDraft | null;
  readonly data?: WizardStepData;
}

/**
 * Estado con el que se abre un asistente. El paso sale de la dirección (también
 * en servidor) y el borrador de la pestaña solo aporta el paso cuando la
 * dirección no lo trae, más los valores introducidos (RF-004, RF-013, RF-014).
 */
export function resolveWizardStart(options: WizardStartOptions): WizardStart {
  const fromUrl = requestedStep(options.wizard, stepFromLocation(options.location));
  const draft = options.draft ?? null;
  const step = fromUrl ?? draft?.step ?? defaultStepId(options.wizard);
  return {
    step,
    values: draft ? draft.values : (options.serverValues ?? {}),
    blocked: stepBlock(step, options.data),
    source: draft ? 'draft' : 'server',
  };
}

/** Igualdad estructural de valores de formulario (RF-004, RF-007). */
export function sameValues(left: WizardValues, right: WizardValues): boolean {
  return sameValue(left, right);
}

function sameValue(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (typeof left !== typeof right || left === null || right === null) return false;
  if (typeof left !== 'object') return false;

  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) return false;
    return left.every((item, index) => sameValue(item, right[index]));
  }

  const leftRecord = left as Record<string, unknown>;
  const rightRecord = right as Record<string, unknown>;
  const keys = Object.keys(leftRecord);
  if (keys.length !== Object.keys(rightRecord).length) return false;
  return keys.every(
    (key) => Object.hasOwn(rightRecord, key) && sameValue(leftRecord[key], rightRecord[key]),
  );
}

/**
 * Contrato mínimo de `useApi()` que un asistente puede llegar a necesitar al
 * guardar. La navegación entre pasos nunca lo usa: H1-T04 no escribe en la red.
 */
export interface WizardApi {
  readonly request: (path: string, options?: unknown) => Promise<unknown>;
}

export interface CreateWizardSessionOptions extends WizardStartOptions {
  /** Doble o instancia real de `useApi()`; reservado para guardar (H1-T05…T07). */
  readonly api: WizardApi;
  /** Escritura de la dirección: una entrada de historial por cambio de paso. */
  readonly writeLocation?: (url: string) => void;
  /** Guarda el borrador de la pestaña cuando hay cambios sin guardar. */
  readonly persist?: (draft: WizardDraft) => void;
  /** Elimina el borrador de la pestaña al descartar. */
  readonly clearDraft?: () => void;
}

export interface WizardSession {
  readonly wizard: WizardKind;
  readonly api: WizardApi;
  readonly step: WizardStepId;
  readonly blocked: WizardStepBlock | null;
  readonly values: WizardValues;
  readonly dirty: boolean;
  goTo(step: WizardStepId): void;
  setValues(values: WizardValues): void;
  setData(data: WizardStepData): void;
  /** Descarte explícito: vuelve a los valores del servidor y borra el borrador. */
  discard(): void;
}

/**
 * Estado de la pestaña de un asistente (RF-004, RF-008, RF-013, RF-014, RF-015).
 * El estado vive en el cierre de esta función: ni global ni compartido entre
 * pestañas, y sin reloj. Cambiar de paso escribe la dirección y el borrador,
 * nunca la red.
 */
export function createWizardSession(options: CreateWizardSessionOptions): WizardSession {
  const { wizard } = options;
  const serverValues = options.serverValues ?? {};
  const start = resolveWizardStart(options);

  let location = options.location;
  let step = start.step;
  let values = start.values;
  let data = options.data ?? {};
  let blocked = start.blocked;

  const isDirty = (): boolean => !sameValues(values, serverValues);

  function saveDraft(): void {
    if (!options.persist || !isDirty()) return;
    options.persist({ step, values });
  }

  return {
    wizard,
    api: options.api,
    get step() {
      return step;
    },
    get blocked() {
      return blocked;
    },
    get values() {
      return values;
    },
    get dirty() {
      return isDirty();
    },
    goTo(next: WizardStepId) {
      if (!isWizardStep(wizard, next) || next === step) return;
      step = next;
      location = stepUrl(location, next);
      options.writeLocation?.(location);
      blocked = stepBlock(step, data);
      saveDraft();
    },
    setValues(next: WizardValues) {
      values = next;
      saveDraft();
    },
    setData(next: WizardStepData) {
      data = next;
      blocked = stepBlock(step, data);
    },
    discard() {
      values = serverValues;
      options.clearDraft?.();
    },
  };
}
